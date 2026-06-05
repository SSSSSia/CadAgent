"""Progressive reference snippets — injected into context based on agent state.

Inspired by text-to-cad's progressive documentation pattern, adapted for
CadAgent's code-side injection approach. Instead of relying on the LLM to
load reference docs on demand, _build_context() in loop.py injects these
snippets automatically based on the current agent state (iteration, quality
results, error history).

Each snippet is kept under ~300 tokens to avoid blowing the 24K context budget.
"""

# ---------------------------------------------------------------------------
# Phase-aware references (injected by _build_context based on state)
# ---------------------------------------------------------------------------

#: Injected on first iteration — quick-start reminder of the most common
#: pitfalls that cause first-execution failures.
REF_FIRST_ITERATION = """
FIRST EXECUTION CHECKLIST:
- Use cq.Workplane("XY") to start — do NOT import cadquery.
- cylinder(H, R) — HEIGHT first, RADIUS second.
- translate((x, y, z)) takes a TUPLE, not separate arguments.
- For fuse/union: shapes MUST physically overlap by ≥0.5mm.
- cq_show(result, "Label") is required to display shapes.
"""

#: Injected when quality gate fails — specific repair guidance per failure code.
#: Each line maps a QualityIssue.code to a concrete fix.
REF_QUALITY_FAILURE = """
QUALITY REPAIR GUIDANCE (based on last failure):
- NO_SOLID: Use solid primitives (box, cylinder, sphere) not open wires/shells.
  Ensure extrude(H) has H > 0 and profile is closed.
- MULTI_SOLID: Shapes must OVERLAP physically for union to merge. Extend one
  shape INTO the other by at least 0.5mm before calling .union().
- COMPOUND_SHAPE: Extract the solid first: shape = shape.Solids[0] before
  boolean operations.
- INVALID_SHAPE: Boolean operation produced invalid geometry. Simplify or
  change the construction order. Try smaller overlap.
- NEGATIVE_VOLUME: Inside-out geometry. Reverse construction order.
- DIMENSION_SUSPICIOUS: Check for unit errors (mm assumed). Verify your
  dimensions match requirements.
"""

#: Injected when errors repeat — structured repair loop strategy.
REF_REPAIR_LOOP = """
REPAIR STRATEGY — you have repeated errors, change your approach:
1. Identify the ROOT CAUSE, not just the symptom.
2. Change ONE thing at a time (overlap distance, boolean order, geometry type).
3. If boolean fails: try increasing overlap, or use a different construction
   method (e.g., make_box_handle instead of manual torus+box positioning).
4. If 3+ failures on same shape: use undo_last and try a completely different
   construction approach.
5. Consider building a simpler version first, then adding complexity.
"""

#: Injected when approaching iteration limit — urgency nudge.
REF_ITERATION_URGENCY = """
WARNING: You are approaching the iteration limit ({max_iter} max, currently
{current}). Focus on producing a valid solid — simplify if needed. Prioritize
correct geometry over feature completeness.
"""

#: Injected when quality passed with warnings — reinforce success path.
REF_QUALITY_PASSED_WARN = """
Quality check PASSED with warnings. The model is valid but may have issues.
Review warnings above. You may continue adding features or fix warnings.
If done, respond with a summary.
"""

# ---------------------------------------------------------------------------
# Repair hint mapping — maps QualityIssue codes to terse fix instructions.
# Used by _quality_gate_block() to inject targeted repair advice.
# ---------------------------------------------------------------------------

QUALITY_FIX_MAP: dict[str, str] = {
    "NO_SOLID": (
        "Use solid primitives (box/cylinder/sphere/torus). "
        "Ensure extrude() has height > 0 and profile is closed. "
        "Do not use open wires or shells."
    ),
    "MULTI_SOLID": (
        "Shapes must physically overlap by ≥0.5mm for union/fuse to work. "
        "Translate one shape INTO the other. Example: .translate((0, 0, 2)) "
        "to extend by 2mm into the other shape."
    ),
    "COMPOUND_SHAPE": (
        "Extract the solid before operations: solid = shape.Solids[0]. "
        "Then use solid for boolean ops."
    ),
    "INVALID_SHAPE": (
        "Boolean operation produced invalid geometry. Try: "
        "(1) increase overlap distance, "
        "(2) change boolean order, "
        "(3) simplify geometry."
    ),
    "NEGATIVE_VOLUME": (
        "Inside-out geometry. Reverse construction order or check "
        "that cut subtracts from the larger body."
    ),
    "DIMENSION_SUSPICIOUS": (
        "Check for unit errors. All dimensions are in mm. "
        "Verify dimensions match the requirements."
    ),
    "NO_DOCUMENT": (
        "No active document. Create one: "
        "doc = FreeCAD.newDocument('Model')"
    ),
    "MULTIPLE_OBJECTS": (
        "Multiple shape objects in document — this is a warning, not a "
        "failure. cq_show() automatically cleans up previous objects. "
        "If objects persist, fuse all shapes into one solid using .union()."
    ),
}
