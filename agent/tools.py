"""
Agent tools — the agent's interface to FreeCAD.

Each tool function takes a JSON arguments string, executes in the FreeCAD
environment, and returns a result string that becomes a role="tool" message.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import time
import traceback

import FreeCAD
import FreeCADGui as Gui
import Part
import math

from core.config import VALIDATE_VOLUME_THRESHOLD, VALIDATE_DIMENSION_THRESHOLD
from core.text_utils import strip_markdown
from core.doc_analyzer import analyze_document
from core.logger import log_info, log_warning, log_error
from agent.code_fixes import pre_validate_code, auto_fix_code, error_hint
from agent.tool_dispatch import register_tool, dispatch_tool  # noqa: F401


# ---------------------------------------------------------------------------
# Restricted __builtins__ for exec() sandbox (CODE-1)
# ---------------------------------------------------------------------------
SAFE_BUILTINS = {
    "__import__": __import__,
    "print": print, "range": range, "len": len, "int": int,
    "float": float, "str": str, "list": list, "dict": dict,
    "tuple": tuple, "set": set, "bool": bool, "bytes": bytes,
    "abs": abs, "min": min, "max": max, "round": round, "sum": sum,
    "sorted": sorted, "reversed": reversed, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "any": any, "all": all,
    "isinstance": isinstance, "type": type, "hasattr": hasattr,
    "getattr": getattr, "setattr": setattr, "repr": repr,
    "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError,
    "RuntimeError": RuntimeError, "Exception": Exception,
    "NotImplementedError": NotImplementedError,
    "AttributeError": AttributeError, "OSError": OSError,
}


# ---------------------------------------------------------------------------
# Post-execution shape validation
# ---------------------------------------------------------------------------

def _post_exec_validate(doc) -> list[str]:
    """Post-execution geometric validation. Returns warning strings."""
    import core.config as _config
    warnings = []
    if doc is None:
        return warnings
    for obj in doc.Objects:
        try:
            if not hasattr(obj, "Shape") or obj.Shape is None or obj.Shape.isNull():
                continue
            if not obj.Shape.isValid():
                warnings.append(f"Object '{obj.Label}' has INVALID shape — boolean operation may have failed")
            if abs(obj.Shape.Volume) < _config.VALIDATE_VOLUME_THRESHOLD:
                warnings.append(f"Object '{obj.Label}' has near-zero volume ({obj.Shape.Volume:.6f} mm³)")
            bb = obj.Shape.BoundBox
            if bb.XLength < _config.VALIDATE_DIMENSION_THRESHOLD or bb.YLength < _config.VALIDATE_DIMENSION_THRESHOLD or bb.ZLength < _config.VALIDATE_DIMENSION_THRESHOLD:
                warnings.append(f"Object '{obj.Label}' has degenerate dimensions: {bb.XLength:.3f} x {bb.YLength:.3f} x {bb.ZLength:.3f}")
        except Exception:
            continue
    return warnings


def _detect_orphan_shapes(namespace: dict, doc) -> list[str]:
    """Detect Part shapes created but not added to the document."""
    _SKIP_NAMES = {
        "FreeCAD", "Part", "math", "Gui", "doc", "Vector", "App",
        "pi", "sin", "cos", "sqrt", "__builtins__",
    }
    orphans = []
    for name, value in namespace.items():
        if name.startswith("_") or name in _SKIP_NAMES:
            continue
        try:
            if not isinstance(value, Part.Shape) or value.isNull():
                continue
            is_assigned = any(
                hasattr(obj, "Shape") and obj.Shape is not None
                and obj.Shape.isSame(value)
                for obj in doc.Objects
            ) if doc else False
            if not is_assigned:
                orphans.append(name)
        except Exception:
            continue
    return orphans


# ---------------------------------------------------------------------------
# Tool: execute_code
# ---------------------------------------------------------------------------

def _tool_execute_code(args_json: str) -> str:
    """Execute FreeCAD Python code and return stdout + error + doc state."""
    args = json.loads(args_json)
    code = args["code"].strip()
    description = args.get("description", "")

    code = strip_markdown(code)

    if not code:
        return "ERROR: Empty code block."

    # Pre-validate syntax
    ok, syntax_err = pre_validate_code(code)
    if not ok:
        return (
            f"ERROR: Code has a syntax error and cannot run.\n"
            f"{syntax_err}\n"
            f"Hint: Check for missing colons, unmatched brackets, or incorrect indentation.\n"
            f"Code that failed:\n{code}"
        )

    # Auto-fix common mistakes
    code, fixes = auto_fix_code(code)
    fix_notice = ""
    if fixes:
        fix_notice = (
            "Note: Auto-fixes applied:\n"
            + "\n".join(f"  - {f}" for f in fixes) + "\n"
        )

    stdout_capture = io.StringIO()

    namespace = {
        "FreeCAD": FreeCAD,
        "Part": Part,
        "math": math,
        "Gui": Gui,
        "doc": FreeCAD.ActiveDocument,
        "__builtins__": SAFE_BUILTINS,
        "Vector": FreeCAD.Vector,
        "App": FreeCAD,
        "pi": math.pi,
        "sin": math.sin,
        "cos": math.cos,
        "sqrt": math.sqrt,
    }

    try:
        # Snapshot before execution (so user can undo)
        try:
            from core.snapshot import take_snapshot
            take_snapshot()
        except Exception as e:
            log_warning(f"Snapshot failed, undo unavailable: {e}")

        pre_state = _safe_analyze()

        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)

        post_exec_warnings = _post_exec_validate(FreeCAD.ActiveDocument)
        orphan_names = _detect_orphan_shapes(namespace, FreeCAD.ActiveDocument)
        if orphan_names:
            post_exec_warnings.append(
                f"Orphan shapes detected: {', '.join(orphan_names)} — "
                f"these Part shapes were created but not added to the document. "
                f"Use doc.addObject('Part::Feature', 'Name') and obj.Shape = shape to register them."
            )
        post_state = _safe_analyze()
        delta = _compute_delta(pre_state, post_state)

        parts = [f"SUCCESS: Code executed without errors."]
        if fix_notice:
            parts.append(fix_notice.rstrip())
        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")
        if post_exec_warnings:
            parts.append("WARNINGS:\n" + "\n".join(f"  - {w}" for w in post_exec_warnings))
        parts.append(f"Changes: {delta}")
        parts.append(f"Document state:\n{post_state}")
        return "\n".join(parts)

    except Exception as e:
        tb = traceback.format_exc()
        post_state = _safe_analyze()
        hint, fixed_code = error_hint(e, code)

        # Auto-retry with fixed code if available
        if fixed_code:
            try:
                with contextlib.redirect_stdout(stdout_capture):
                    exec(fixed_code, namespace)
                post_exec_warnings = _post_exec_validate(FreeCAD.ActiveDocument)
                orphan_names = _detect_orphan_shapes(namespace, FreeCAD.ActiveDocument)
                if orphan_names:
                    post_exec_warnings.append(
                        f"Orphan shapes detected: {', '.join(orphan_names)} — "
                        f"these Part shapes were created but not added to the document. "
                        f"Use doc.addObject('Part::Feature', 'Name') and obj.Shape = shape to register them."
                    )
                post_state = _safe_analyze()
                delta = _compute_delta(pre_state, post_state)
                parts = [
                    f"SUCCESS (auto-corrected): Original error was {type(e).__name__}: {e}",
                    f"Auto-fix: {hint}",
                ]
                stdout_text = stdout_capture.getvalue()
                if stdout_text:
                    parts.append(f"Stdout:\n{stdout_text}")
                if post_exec_warnings:
                    parts.append("WARNINGS:\n" + "\n".join(f"  - {w}" for w in post_exec_warnings))
                parts.append(f"Changes: {delta}")
                parts.append(f"Document state:\n{post_state}")
                return "\n".join(parts)
            except Exception:
                pass  # auto-retry failed, fall through to error report

        post_state = _safe_analyze()
        delta = _compute_delta(pre_state, post_state)
        parts = [f"ERROR: {type(e).__name__}: {e}", f"Traceback:\n{tb}"]
        if fix_notice:
            parts.append(fix_notice.rstrip())
        if hint:
            parts.append(hint)
        parts.append(f"Changes: {delta}")
        parts.append(f"Document state after error:\n{post_state}")
        return "\n".join(parts)


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
        if abs(obj.Shape.Volume) < VALIDATE_VOLUME_THRESHOLD:
            issues.append(f"Object '{obj.Label}' has zero volume (empty shape).")

        # Check: valid shape
        if not obj.Shape.isValid():
            issues.append(f"Object '{obj.Label}' has invalid shape.")

        # Check: reasonable bounding box (not degenerate)
        bb = obj.Shape.BoundBox
        if bb.XLength < VALIDATE_DIMENSION_THRESHOLD or bb.YLength < VALIDATE_DIMENSION_THRESHOLD or bb.ZLength < VALIDATE_DIMENSION_THRESHOLD:
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
# Tool: undo_last
# ---------------------------------------------------------------------------

def _tool_undo_last(args_json: str) -> str:
    """Undo the last execute_code by restoring document snapshot."""
    from core.snapshot import restore_latest_snapshot
    return restore_latest_snapshot()


# ---------------------------------------------------------------------------
# Materials reference table
# ---------------------------------------------------------------------------

_MATERIALS_TABLE = [
    # (name, category, density_kg_m3, yield_strength_MPa, elastic_modulus_GPa)
    ("AISI 1045 Steel", "steel", 7850, 530, 200),
    ("AISI 304 Stainless", "steel", 8000, 215, 193),
    ("AISI 4140 Alloy Steel", "steel", 7850, 655, 205),
    ("AISI 1018 Mild Steel", "steel", 7870, 370, 205),
    ("6061-T6 Aluminum", "aluminum", 2700, 276, 68.9),
    ("7075-T6 Aluminum", "aluminum", 2810, 503, 71.7),
    ("2024-T3 Aluminum", "aluminum", 2780, 345, 73.1),
    ("Ti-6Al-4V Titanium", "titanium", 4430, 880, 114),
    ("Grade 2 Titanium", "titanium", 4510, 275, 103),
    ("C110 Copper", "copper", 8960, 220, 117),
    ("C36000 Brass", "copper", 8530, 310, 97),
    ("ABS Plastic", "plastic", 1040, 43, 2.3),
    ("Nylon 6/6", "plastic", 1140, 82, 2.9),
    ("Polycarbonate", "plastic", 1200, 62, 2.4),
    ("PEEK", "plastic", 1310, 91, 3.6),
]


# ---------------------------------------------------------------------------
# Tool: export_step
# ---------------------------------------------------------------------------

def _tool_export_step(args_json: str) -> str:
    """Export current document to STEP or IGES file."""
    args = json.loads(args_json)
    filename = args["filename"]
    fmt = args.get("format", "step")

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return "ERROR: No active document to export."

    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        filename += ".step" if fmt == "step" else ".iges"
    elif fmt == "iges" and ext not in (".iges", ".igs"):
        return "ERROR: Format is 'iges' but filename extension is not .iges/.igs"
    elif fmt == "step" and ext not in (".step", ".stp"):
        return "ERROR: Format is 'step' but filename extension is not .step/.stp"

    parent = os.path.dirname(filename)
    if parent and not os.path.isdir(parent):
        return f"ERROR: Directory does not exist: {parent}"

    try:
        import Import
        Import.export(doc.Objects, filename)
        return (
            f"SUCCESS: Exported {len(doc.Objects)} objects to {filename}\n"
            f"Format: {fmt.upper()}\n"
            f"File size: {os.path.getsize(filename)} bytes"
        )
    except Exception as e:
        try:
            shapes = [o for o in doc.Objects
                      if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
            if not shapes:
                return f"ERROR: No shape objects to export. Original error: {e}"
            Part.export(shapes, filename)
            return (
                f"SUCCESS: Exported {len(shapes)} shapes to {filename} (Part.export fallback)\n"
                f"Format: {fmt.upper()}\n"
                f"File size: {os.path.getsize(filename)} bytes"
            )
        except Exception as e2:
            return f"ERROR: Export failed: {type(e2).__name__}: {e2}"


# ---------------------------------------------------------------------------
# Tool: measure_distance
# ---------------------------------------------------------------------------

def _resolve_element(elem_str, doc):
    """Resolve element string to a Part.Shape or FreeCAD.Vector."""
    if elem_str.startswith("point:"):
        parts = elem_str[6:].split(",")
        if len(parts) != 3:
            raise ValueError(f"Invalid point format: {elem_str}. Use 'point:x,y,z'")
        return FreeCAD.Vector(float(parts[0]), float(parts[1]), float(parts[2]))
    objs = doc.getObjectsByLabel(elem_str)
    if objs and hasattr(objs[0], "Shape") and objs[0].Shape and not objs[0].Shape.isNull():
        return objs[0].Shape
    raise ValueError(f"Object not found or has no valid shape: {elem_str}")


def _tool_measure_distance(args_json: str) -> str:
    """Measure distance or angle between two geometric elements."""
    args = json.loads(args_json)
    elem1_str = args["element1"]
    elem2_str = args["element2"]
    measure_type = args.get("measure_type", "distance")

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return "ERROR: No active document."

    try:
        elem1 = _resolve_element(elem1_str, doc)
        elem2 = _resolve_element(elem2_str, doc)
    except ValueError as e:
        return f"ERROR: {e}"

    try:
        if measure_type == "distance":
            if isinstance(elem1, Part.Shape) and isinstance(elem2, Part.Shape):
                dist, pairs, _ = elem1.distToShape(elem2)
                result = f"Distance: {dist:.4f} mm"
                if pairs:
                    p1, p2 = pairs[0][0], pairs[0][1]
                    result += (
                        f"\nNearest points: ({p1.x:.2f}, {p1.y:.2f}, {p1.z:.2f}) "
                        f"<-> ({p2.x:.2f}, {p2.y:.2f}, {p2.z:.2f})"
                    )
                return result
            if isinstance(elem1, Part.Shape) and isinstance(elem2, FreeCAD.Vector):
                dist = elem1.distToShape(Part.Vertex(elem2))
                return f"Distance: {dist[0]:.4f} mm"
            if isinstance(elem1, FreeCAD.Vector) and isinstance(elem2, Part.Shape):
                dist = elem2.distToShape(Part.Vertex(elem1))
                return f"Distance: {dist[0]:.4f} mm"
            if isinstance(elem1, FreeCAD.Vector) and isinstance(elem2, FreeCAD.Vector):
                dist = (elem1 - elem2).Length
                return f"Distance: {dist:.4f} mm"

        elif measure_type == "angle":
            def _get_center(e):
                if isinstance(e, FreeCAD.Vector):
                    return e
                return e.CenterOfMass if hasattr(e, "CenterOfMass") else e.BoundBox.Center

            c1 = _get_center(elem1)
            c2 = _get_center(elem2)
            direction = c2 - c1
            if direction.Length < 1e-10:
                return "ERROR: Elements are at the same position, cannot compute angle."
            z_axis = FreeCAD.Vector(0, 0, 1)
            cos_angle = max(-1, min(1, direction.normalize().dot(z_axis)))
            angle_rad = math.acos(cos_angle)
            return f"Angle: {math.degrees(angle_rad):.2f} degrees (between connecting line and Z-axis)"

        return f"ERROR: Unknown measure_type: {measure_type}"

    except Exception as e:
        return f"ERROR: Measurement failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tool: list_materials
# ---------------------------------------------------------------------------

def _tool_list_materials(args_json: str) -> str:
    """List common engineering materials with properties."""
    args = json.loads(args_json) if args_json.strip() else {}
    category = args.get("category", "all")

    filtered = _MATERIALS_TABLE
    if category != "all":
        filtered = [m for m in _MATERIALS_TABLE if m[1] == category]

    if not filtered:
        return (
            f"No materials found for category: {category}\n"
            "Available categories: steel, aluminum, titanium, copper, plastic, all"
        )

    lines = [
        f"{'Material':<28} {'Density':>10} {'Yield':>10} {'Elastic':>10}",
        f"{'':_<28} {'kg/m3':>10} {'MPa':>10} {'GPa':>10}",
    ]
    for name, cat, density, yield_s, elastic in filtered:
        lines.append(f"{name:<28} {density:>10.0f} {yield_s:>10.0f} {elastic:>10.1f}")

    lines.append(f"\nTotal: {len(filtered)} materials")
    if category == "all":
        lines.append("Filter by category: steel, aluminum, titanium, copper, plastic")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: screenshot
# ---------------------------------------------------------------------------

def _tool_screenshot(args_json: str) -> str:
    """Capture the current FreeCAD 3D viewport as a PNG image."""
    args = json.loads(args_json) if args_json.strip() else {}
    save_path = args.get("save_path", "")
    width = max(100, min(4096, int(args.get("width", 800))))
    height = max(100, min(4096, int(args.get("height", 600))))

    if not save_path:
        temp_dir = tempfile.gettempdir()
        save_path = os.path.join(temp_dir, f"cadagent_screenshot_{int(time.time())}.png")

    if not save_path.lower().endswith(".png"):
        save_path += ".png"

    parent = os.path.dirname(save_path)
    if parent and not os.path.isdir(parent):
        return f"ERROR: Directory does not exist: {parent}"

    try:
        gui_doc = Gui.activeDocument()
        if gui_doc is None:
            return "ERROR: No active document view. Open a document first."

        view = gui_doc.activeView()
        if view is None:
            return "ERROR: No active 3D view available."

        view.saveImage(save_path, width, height)

        file_size = os.path.getsize(save_path)
        return (
            f"SUCCESS: Screenshot saved.\n"
            f"Path: {save_path}\n"
            f"Resolution: {width}x{height}\n"
            f"File size: {file_size} bytes"
        )
    except Exception as e:
        return f"ERROR: Screenshot failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool("execute_code", _tool_execute_code)
register_tool("analyze_geometry", _tool_analyze_geometry)
register_tool("validate_design", _tool_validate_design)
register_tool("undo_last", _tool_undo_last)
register_tool("export_step", _tool_export_step)
register_tool("measure_distance", _tool_measure_distance)
register_tool("list_materials", _tool_list_materials)
register_tool("screenshot", _tool_screenshot)


def _safe_analyze() -> str:
    """Safely analyze document, returning error string on failure."""
    try:
        doc = FreeCAD.ActiveDocument
        if doc:
            return analyze_document(doc)
        return "(no active document)"
    except Exception as e:
        return f"(analysis error: {e})"


def _extract_total_volume(state: str) -> float | None:
    """Sum all per-object volumes from analyze_document() output text."""
    volumes = re.findall(r"Volume:\s*([\d.]+)", state)
    if not volumes:
        return None
    return sum(float(v) for v in volumes)


def _compute_delta(pre_state: str, post_state: str) -> str:
    """Compare pre/post document states, return change summary."""
    pre_objs = set(re.findall(r"- '([^']+)'", pre_state))
    post_objs = set(re.findall(r"- '([^']+)'", post_state))

    added = sorted(post_objs - pre_objs)
    removed = sorted(pre_objs - post_objs)

    pre_vol = _extract_total_volume(pre_state)
    post_vol = _extract_total_volume(post_state)

    parts = []
    if added:
        parts.append(f"New objects: {', '.join(added)}")
    if removed:
        parts.append(f"Removed objects: {', '.join(removed)}")
    if pre_vol is not None and post_vol is not None:
        delta = post_vol - pre_vol
        pct = (delta / pre_vol * 100) if pre_vol != 0 else 0
        direction = "+" if delta >= 0 else ""
        parts.append(f"Volume: {pre_vol:.0f} -> {post_vol:.0f} mm3 ({direction}{pct:.1f}%)")

    return "; ".join(parts) if parts else "No changes detected"
