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
# Parametric design — module-level parameter store
# ---------------------------------------------------------------------------

_PARAM_STORE: dict[str, float | int] = {}
_PARAMETRIC_CODE: str = ""

# Namespace that persists across execute_code calls so the LLM can reference
# variables (including FreeCAD shapes) defined in earlier iterations.
_EXEC_NAMESPACE: dict = {}
_BUILTIN_NAMES = frozenset({
    "FreeCAD", "Part", "math", "Gui", "doc", "Vector", "App",
    "pi", "sin", "cos", "sqrt", "__builtins__",
})

# Only these types are safe to serialize to disk for session persistence.
_PERSISTABLE_TYPES = (int, float, str, bool, type(None))

_PARAM_PATTERN = re.compile(r'^([A-Z][A-Z0-9_]*)\s*=\s*([-+]?[\d.]+)\s*$')


def _save_user_vars(namespace: dict) -> None:
    """Copy all user-defined variables from exec namespace into _EXEC_NAMESPACE.

    Keeps FreeCAD objects in memory so the next iteration can reference them.
    Disk serialization (get_persistent_vars) filters to safe types.
    """
    for name, value in namespace.items():
        if name.startswith("_") or name in _BUILTIN_NAMES:
            continue
        _EXEC_NAMESPACE[name] = value


def clear_persistent_vars() -> None:
    """Clear all persisted variables (call on new session)."""
    _EXEC_NAMESPACE.clear()


def get_persistent_vars() -> dict:
    """Return serializable subset of exec namespace (for session persistence to disk).

    FreeCAD C++ objects are excluded — they can't be serialized and would be
    stale after deserialization. Only primitive types survive disk round-trips.
    """
    return {k: v for k, v in _EXEC_NAMESPACE.items() if isinstance(v, _PERSISTABLE_TYPES)}


def set_persistent_vars(vars: dict) -> None:
    """Restore persistent vars (for session deserialization from disk)."""
    _EXEC_NAMESPACE.clear()
    _EXEC_NAMESPACE.update(vars)


def _extract_parameters(code: str) -> dict:
    """Extract parameter definitions (UPPER_NAME = value) from top of code."""
    params = {}
    for line in code.strip().split('\n'):
        m = _PARAM_PATTERN.match(line.strip())
        if m:
            val = float(m.group(2)) if '.' in m.group(2) else int(m.group(2))
            params[m.group(1)] = val
        elif line.strip() and not line.strip().startswith('#'):
            break
    return params


def _substitute_parameters(code: str, updates: dict) -> str:
    """Replace parameter assignment values in code."""
    lines = code.split('\n')
    result = []
    for line in lines:
        m = _PARAM_PATTERN.match(line.strip())
        if m and m.group(1) in updates:
            result.append(f"{m.group(1)} = {updates[m.group(1)]}")
        else:
            result.append(line)
    return '\n'.join(result)


def get_param_store() -> dict:
    """Return a copy of the current parameter store."""
    return dict(_PARAM_STORE)


def set_param_store(params: dict) -> None:
    """Replace the parameter store with given params."""
    _PARAM_STORE.clear()
    _PARAM_STORE.update(params)


# ---------------------------------------------------------------------------
# Document resolution helper
# ---------------------------------------------------------------------------

def _resolve_doc(doc_name: str | None):
    """Resolve a document name to a FreeCAD.Document.

    Returns FreeCAD.ActiveDocument if doc_name is None or empty.
    Returns None if the named document does not exist.
    """
    if not doc_name:
        return FreeCAD.ActiveDocument
    return FreeCAD.getDocument(doc_name)


def _doc_list_str() -> str:
    """Return comma-separated list of open document names."""
    try:
        return ", ".join(FreeCAD.listDocuments().keys())
    except Exception:
        return ""


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
# Tool: execute_code
# ---------------------------------------------------------------------------

def _tool_execute_code(args_json: str) -> str:
    """Execute FreeCAD Python code and return stdout + error."""
    args = json.loads(args_json)
    code = args["code"].strip()
    description = args.get("description", "")
    doc_name = args.get("document", "")

    code = strip_markdown(code)

    if not code:
        return "ERROR: Empty code block."

    # Resolve target document
    target_doc = _resolve_doc(doc_name)
    if doc_name and target_doc is None:
        return f"ERROR: Document '{doc_name}' not found. Available: {_doc_list_str()}"

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
        # Show the LLM what was changed so it can learn
        fix_lines = ["Note: Auto-fixes applied:"]
        for f in fixes:
            fix_lines.append(f"  - {f}")
        # Include the corrected code so the LLM sees the right syntax
        fix_lines.append("Corrected code:")
        for line in code.split('\n'):
            fix_lines.append(f"  {line}")
        fix_notice = "\n".join(fix_lines) + "\n"

    # Auto-create document when none exists and code uses doc.XXX
    doc_is_none = (target_doc is None) and (FreeCAD.ActiveDocument is None)
    if doc_is_none and "doc." in code and "newDocument" not in code:
        doc_create_line = 'doc = FreeCAD.newDocument("CadAgentModel")\n'
        code = doc_create_line + code
        fixes.append("Auto-created document (no active document found)")
        if not fix_notice:
            fix_notice = (
                "Note: Auto-fixes applied:\n"
                + "\n".join(f"  - {f}" for f in fixes) + "\n"
            )
        else:
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
        "doc": target_doc if target_doc else FreeCAD.ActiveDocument,
        "__builtins__": SAFE_BUILTINS,
        "Vector": FreeCAD.Vector,
        "App": FreeCAD,
        "pi": math.pi,
        "sin": math.sin,
        "cos": math.cos,
        "sqrt": math.sqrt,
    }
    # Inject variables from previous execute_code calls (includes FreeCAD objects)
    namespace.update(_EXEC_NAMESPACE)

    try:
        # Snapshot before execution (so user can undo)
        try:
            if doc_name and target_doc:
                from core.snapshot import take_snapshot_for_doc
                take_snapshot_for_doc(target_doc)
            else:
                from core.snapshot import take_snapshot
                take_snapshot()
        except Exception as e:
            log_warning(f"Snapshot failed, undo unavailable: {e}")

        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)

        # Persist user-defined variables for subsequent execute_code calls
        _save_user_vars(namespace)

        parts = [f"SUCCESS: Code executed without errors."]
        if doc_name:
            parts.append(f"Target document: '{doc_name}'")
        if fix_notice:
            parts.append(fix_notice.rstrip())
        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")

        # Extract parametric definitions from code
        params = _extract_parameters(code)
        if params:
            _PARAM_STORE.update(params)
            _PARAMETRIC_CODE = code
            param_lines = "\n".join(f"  {k} = {v}" for k, v in params.items())
            parts.append(f"Parameters extracted:\n{param_lines}")

        return "\n".join(parts)

    except Exception as e:
        tb = traceback.format_exc()
        hint, fixed_code = error_hint(e, code)

        # Auto-retry with fixed code if available
        if fixed_code:
            try:
                with contextlib.redirect_stdout(stdout_capture):
                    exec(fixed_code, namespace)
                # Persist user-defined variables after auto-retry success
                _save_user_vars(namespace)
                parts = [
                    f"SUCCESS (auto-corrected): Original error was {type(e).__name__}: {e}",
                    f"Auto-fix: {hint}",
                    f"Corrected code:",
                ]
                for line in fixed_code.split('\n'):
                    parts.append(f"  {line}")
                if doc_name:
                    parts.append(f"Target document: '{doc_name}'")
                stdout_text = stdout_capture.getvalue()
                if stdout_text:
                    parts.append(f"Stdout:\n{stdout_text}")

                # Extract parametric definitions from code
                params = _extract_parameters(code)
                if params:
                    _PARAM_STORE.update(params)
                    _PARAMETRIC_CODE = code
                    param_lines = "\n".join(f"  {k} = {v}" for k, v in params.items())
                    parts.append(f"Parameters extracted:\n{param_lines}")

                return "\n".join(parts)
            except Exception:
                pass  # auto-retry failed, fall through to error report

        parts = [f"ERROR: {type(e).__name__}: {e}", f"Traceback:\n{tb}"]
        if fix_notice:
            parts.append(fix_notice.rstrip())
        if hint:
            parts.append(hint)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool: analyze_geometry (kept for backward compatibility, not exposed to LLM)
# ---------------------------------------------------------------------------

def _tool_analyze_geometry(args_json: str) -> str:
    """Analyze current FreeCAD document geometry."""
    args = json.loads(args_json) if args_json.strip() else {}
    focus = args.get("focus", "all")
    doc_name = args.get("document", "")

    doc = _resolve_doc(doc_name)
    if doc is None:
        if doc_name:
            return f"ERROR: Document '{doc_name}' not found. Available: {_doc_list_str()}"
        return "No active document. Create one first with FreeCAD.newDocument()."

    result = analyze_document(doc)
    if not result or "(No active document)" in result:
        return "No active document. Create one first with FreeCAD.newDocument()."

    if focus == "dimensions":
        # Extract only dimension-related lines
        lines = [l for l in result.split("\n")
                 if any(k in l for k in ("Bounding", "Overall", "Volume", "R="))]
        return "\n".join(lines) if lines else result

    return result


# ---------------------------------------------------------------------------
# Tool: validate_design (kept for backward compatibility, not exposed to LLM)
# ---------------------------------------------------------------------------

def _tool_validate_design(args_json: str) -> str:
    """Validate current design against stated requirements."""
    args = json.loads(args_json)
    requirements = args.get("requirements", "")
    doc_name = args.get("document", "")

    doc = _resolve_doc(doc_name)
    if doc is None:
        if doc_name:
            return f"FAIL: Document '{doc_name}' not found. Available: {_doc_list_str()}"
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

        # Check: single manifold solid
        try:
            solid_count = len(obj.Shape.Solids)
            if solid_count == 0:
                issues.append(f"Object '{obj.Label}' has no solid components.")
            elif solid_count > 1:
                issues.append(
                    f"Object '{obj.Label}' has {solid_count} disconnected solids — "
                    f"expected single manifold. Fuse with 0.5mm overlap."
                )
            elif solid_count == 1:
                try:
                    shell_count = len(obj.Shape.Solids[0].Shells)
                    if shell_count > 1:
                        issues.append(
                            f"Object '{obj.Label}' has {shell_count} shells — "
                            f"non-manifold geometry."
                        )
                except Exception:
                    pass
        except Exception:
            pass

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
# Tool: export_step
# ---------------------------------------------------------------------------

def _tool_export_step(args_json: str) -> str:
    """Export current document to STEP or IGES file."""
    args = json.loads(args_json)
    filename = args["filename"]
    fmt = args.get("format", "step")
    doc_name = args.get("document", "")

    doc = _resolve_doc(doc_name)
    if doc is None:
        if doc_name:
            return f"ERROR: Document '{doc_name}' not found. Available: {_doc_list_str()}"
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
# Remaining tools (kept for backward compatibility, not exposed to LLM)
# ---------------------------------------------------------------------------

def _tool_measure_distance(args_json: str) -> str:
    """Measure distance or angle between two geometric elements."""
    args = json.loads(args_json)
    elem1_str = args["element1"]
    elem2_str = args["element2"]
    measure_type = args.get("measure_type", "distance")
    doc_name = args.get("document", "")

    doc = _resolve_doc(doc_name)
    if doc is None:
        if doc_name:
            return f"ERROR: Document '{doc_name}' not found. Available: {_doc_list_str()}"
        return "ERROR: No active document."

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


def _tool_list_materials(args_json: str) -> str:
    """List common engineering materials with properties."""
    _MATERIALS_TABLE = [
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


def _tool_list_documents(args_json: str) -> str:
    """List all open FreeCAD documents."""
    args = json.loads(args_json) if args_json.strip() else {}
    include_geometry = args.get("include_geometry", False)

    docs = FreeCAD.listDocuments()
    if not docs:
        return "No documents open."

    active_name = FreeCAD.ActiveDocument.Name if FreeCAD.ActiveDocument else ""
    lines = []
    for name, doc in docs.items():
        obj_count = len(doc.Objects)
        shape_count = sum(
            1 for o in doc.Objects
            if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()
        )
        marker = " (active)" if name == active_name else ""
        lines.append(f"- '{name}'{marker}: {obj_count} objects ({shape_count} with shapes)")
        if include_geometry:
            geo = analyze_document(doc)
            for geo_line in geo.split("\n")[1:]:
                lines.append(f"  {geo_line}")

    return "\n".join(lines)


def _safe_analyze(doc=None) -> str:
    """Safely analyze document, returning error string on failure."""
    try:
        if doc is None:
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


def _tool_create_assembly(args_json: str) -> str:
    """Create a new assembly document with parts copied from other documents."""
    args = json.loads(args_json)
    name = args["name"]
    parts = args.get("parts", [])

    # Check for name conflict
    existing = FreeCAD.listDocuments()
    actual_name = name
    suffix = 1
    while actual_name in existing:
        actual_name = f"{name}_{suffix}"
        suffix += 1

    asm_doc = FreeCAD.newDocument(actual_name)

    placed = []
    errors = []

    for part_spec in parts:
        src_doc_name = part_spec.get("source_document", "")
        obj_label = part_spec.get("object_label", "")
        position = part_spec.get("position", [0, 0, 0])
        rotation = part_spec.get("rotation", None)

        src_doc = _resolve_doc(src_doc_name)
        if src_doc is None:
            errors.append(f"Source document '{src_doc_name}' not found")
            continue

        src_objs = src_doc.getObjectsByLabel(obj_label)
        if not src_objs:
            errors.append(f"Object '{obj_label}' not found in '{src_doc_name}'")
            continue
        src_obj = src_objs[0]

        new_obj = asm_doc.copyObject(src_obj, True)

        pos = FreeCAD.Vector(*position)
        if rotation:
            axis = FreeCAD.Vector(*rotation.get("axis", [0, 0, 1]))
            angle = rotation.get("angle_deg", 0)
            new_obj.Placement = FreeCAD.Placement(pos, axis, angle)
        else:
            new_obj.Placement = FreeCAD.Placement(pos, FreeCAD.Vector(0, 0, 1), 0)

        placed.append(
            f"'{obj_label}' from '{src_doc_name}' at "
            f"({position[0]:.1f}, {position[1]:.1f}, {position[2]:.1f})"
        )

    asm_doc.recompute()

    parts_line = "\n".join(f"  - {p}" for p in placed) if placed else "  (none)"
    error_line = "\n".join(f"  - {e}" for e in errors) if errors else ""

    result_parts = [
        f"SUCCESS: Assembly document '{actual_name}' created with {len(placed)} part(s).",
        f"Parts placed:\n{parts_line}",
    ]
    if errors:
        result_parts.append(f"Errors:\n{error_line}")

    result_parts.append(f"Assembly state:\n{_safe_analyze(asm_doc)}")
    return "\n".join(result_parts)


def _tool_update_parameter(args_json: str) -> str:
    """Update design parameters and re-execute the design code."""
    args = json.loads(args_json)
    updates = args["updates"]
    doc_name = args.get("document", "")

    if not _PARAMETRIC_CODE:
        return (
            "ERROR: No parameterized design found. "
            "Create a design with named constants first (e.g. OD = 200)."
        )

    # Validate parameter names
    unknown = [k for k in updates if k not in _PARAM_STORE]
    if unknown:
        available = ", ".join(sorted(_PARAM_STORE.keys()))
        return (
            f"ERROR: Unknown parameter(s): {', '.join(unknown)}. "
            f"Available: {available}"
        )

    # Substitute parameter values in stored code
    updated_code = _substitute_parameters(_PARAMETRIC_CODE, updates)

    # Undo to the state before the parametric code was executed
    undo_result = _tool_undo_last("{}")

    # Re-execute with updated parameters
    exec_args = json.dumps({
        "code": updated_code,
        "description": f"Update parameters: {updates}",
        "document": doc_name,
    })
    result = _tool_execute_code(exec_args)

    # Update parameter store with new values
    _PARAM_STORE.update(updates)

    # Append parameter table to result
    param_str = "\n".join(f"  {k} = {v}" for k, v in sorted(_PARAM_STORE.items()))
    return f"{result}\n\nUpdated parameter table:\n{param_str}"


def _tool_list_parameters(args_json: str) -> str:
    """List current design parameters and their values."""
    if not _PARAM_STORE:
        return (
            "No parameters defined yet. "
            "Use named constants (e.g. OD = 200) at the top of your code."
        )
    lines = ["Current design parameters:"]
    for name, value in sorted(_PARAM_STORE.items()):
        lines.append(f"  {name} = {value}")
    return "\n".join(lines)


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
register_tool("list_documents", _tool_list_documents)
register_tool("create_assembly", _tool_create_assembly)
register_tool("update_parameter", _tool_update_parameter)
register_tool("list_parameters", _tool_list_parameters)
