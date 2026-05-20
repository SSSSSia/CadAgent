"""
Agent tools — the agent's interface to FreeCAD.

Each tool function takes a JSON arguments string, executes in the FreeCAD
environment, and returns a result string that becomes a role="tool" message.
"""
from __future__ import annotations

import contextlib
import io
import json
import traceback

import FreeCAD
import FreeCADGui as Gui
import Part
import math

from doc_analyzer import analyze_document


# ---------------------------------------------------------------------------
# Tool: execute_code
# ---------------------------------------------------------------------------

def _tool_execute_code(args_json: str) -> str:
    """Execute FreeCAD Python code and return stdout + error + doc state."""
    args = json.loads(args_json)
    code = args["code"].strip()
    description = args.get("description", "")

    # Strip markdown fences if present
    import re
    code = re.sub(r"^```(?:python)?\s*\n?", "", code)
    code = re.sub(r"\n?```\s*$", "", code)
    code = code.strip()

    if not code:
        return "ERROR: Empty code block."

    stdout_capture = io.StringIO()

    namespace = {
        "FreeCAD": FreeCAD,
        "Part": Part,
        "math": math,
        "Gui": Gui,
        "__builtins__": __builtins__,
    }

    try:
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)

        post_state = _safe_analyze()

        parts = [f"SUCCESS: Code executed without errors."]
        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")
        parts.append(f"Document state:\n{post_state}")
        return "\n".join(parts)

    except Exception as e:
        tb = traceback.format_exc()
        post_state = _safe_analyze()
        return (
            f"ERROR: {type(e).__name__}: {e}\n"
            f"Traceback:\n{tb}\n"
            f"Document state after error:\n{post_state}"
        )


# ---------------------------------------------------------------------------
# Tool: analyze_geometry
# ---------------------------------------------------------------------------

def _tool_analyze_geometry(args_json: str) -> str:
    """Analyze current FreeCAD document geometry."""
    args = json.loads(args_json) if args_json.strip() else {}
    focus = args.get("focus", "all")

    result = analyze_document(FreeCAD.ActiveDocument)
    if not result or "(No active document)" in result:
        return "No active document. Create one first with FreeCAD.newDocument()."

    if focus == "dimensions":
        # Extract only dimension-related lines
        lines = [l for l in result.split("\n")
                 if any(k in l for k in ("Bounding", "Overall", "Volume", "R="))]
        return "\n".join(lines) if lines else result

    return result


# ---------------------------------------------------------------------------
# Tool: validate_design
# ---------------------------------------------------------------------------

def _tool_validate_design(args_json: str) -> str:
    """Validate current design against stated requirements."""
    args = json.loads(args_json)
    requirements = args.get("requirements", "")

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return "FAIL: No active document."

    issues = []

    # Check: does document have any objects?
    shape_objs = [o for o in doc.Objects
                  if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
    if not shape_objs:
        issues.append("Document has no valid shape objects.")

    for obj in shape_objs:
        # Check: non-zero volume
        if abs(obj.Shape.Volume) < 0.01:
            issues.append(f"Object '{obj.Label}' has zero volume (empty shape).")

        # Check: valid shape
        if not obj.Shape.isValid():
            issues.append(f"Object '{obj.Label}' has invalid shape.")

        # Check: reasonable bounding box (not degenerate)
        bb = obj.Shape.BoundBox
        if bb.XLength < 0.001 or bb.YLength < 0.001 or bb.ZLength < 0.001:
            issues.append(
                f"Object '{obj.Label}' has degenerate bounding box: "
                f"{bb.XLength:.1f} x {bb.YLength:.1f} x {bb.ZLength:.1f}"
            )

    if issues:
        return f"Issues found ({len(issues)}):\n" + "\n".join(f"- {i}" for i in issues)

    doc_info = analyze_document(doc)
    return (
        f"PASS: Design looks valid. {len(shape_objs)} object(s) found.\n"
        f"Requirements: {requirements}\n"
        f"Current geometry:\n{doc_info}"
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TOOL_MAP = {
    "execute_code": _tool_execute_code,
    "analyze_geometry": _tool_analyze_geometry,
    "validate_design": _tool_validate_design,
}


def dispatch_tool(name: str, args_json: str) -> str:
    """Dispatch a tool call by name. Returns result string."""
    handler = _TOOL_MAP.get(name)
    if handler is None:
        return f"ERROR: Unknown tool '{name}'. Available: {list(_TOOL_MAP.keys())}"
    try:
        return handler(args_json)
    except Exception as e:
        return f"ERROR in tool '{name}': {type(e).__name__}: {e}"


def _safe_analyze() -> str:
    """Safely analyze document, returning error string on failure."""
    try:
        doc = FreeCAD.ActiveDocument
        if doc:
            return analyze_document(doc)
        return "(no active document)"
    except Exception as e:
        return f"(analysis error: {e})"
