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

        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)

        post_state = _safe_analyze()

        parts = [f"SUCCESS: Code executed without errors."]
        if fix_notice:
            parts.append(fix_notice.rstrip())
        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")
        parts.append(f"Document state:\n{post_state}")
        return "\n".join(parts)

    except Exception as e:
        tb = traceback.format_exc()
        post_state = _safe_analyze()
        hint = error_hint(e, code)
        parts = [f"ERROR: {type(e).__name__}: {e}", f"Traceback:\n{tb}"]
        if fix_notice:
            parts.append(fix_notice.rstrip())
        if hint:
            parts.append(hint)
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
# Registration
# ---------------------------------------------------------------------------

register_tool("execute_code", _tool_execute_code)
register_tool("analyze_geometry", _tool_analyze_geometry)
register_tool("validate_design", _tool_validate_design)
register_tool("undo_last", _tool_undo_last)


def _safe_analyze() -> str:
    """Safely analyze document, returning error string on failure."""
    try:
        doc = FreeCAD.ActiveDocument
        if doc:
            return analyze_document(doc)
        return "(no active document)"
    except Exception as e:
        return f"(analysis error: {e})"
