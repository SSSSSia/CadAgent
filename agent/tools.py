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
import traceback

import FreeCAD
import FreeCADGui as Gui
import Part
import math

from core.text_utils import strip_markdown
from core.logger import log_info, log_warning, log_error
from agent.code_fixes import pre_validate_code, error_hint
from agent.tool_dispatch import register_tool, dispatch_tool  # noqa: F401


# ---------------------------------------------------------------------------
# Parametric design — module-level parameter store
# ---------------------------------------------------------------------------

_PARAM_STORE: dict[str, float | int] = {}

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

    # Auto-create document when none exists and code uses doc.XXX
    doc_is_none = (target_doc is None) and (FreeCAD.ActiveDocument is None)
    auto_created_doc = False
    if doc_is_none and "doc." in code and "newDocument" not in code:
        doc_create_line = 'doc = FreeCAD.newDocument("CadAgentModel")\n'
        code = doc_create_line + code
        auto_created_doc = True

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

        parts = [f"OK: Code executed."]
        if auto_created_doc:
            parts.append("Auto-created document 'CadAgentModel' (none was active).")

        # Compact geometry feedback so LLM can verify its work
        try:
            target = target_doc or FreeCAD.ActiveDocument
            if target and target.Objects:
                shape_objs = [o for o in target.Objects
                              if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
                if shape_objs:
                    geo_lines = []
                    for obj in shape_objs:
                        s = obj.Shape
                        bb = s.BoundBox
                        dims = f"{bb.XLength:.1f}x{bb.YLength:.1f}x{bb.ZLength:.1f}"
                        vol = f", V={s.Volume:.0f}" if s.Volume > 0 else ""
                        geo_lines.append(f"  {obj.Label}: {dims}mm{vol}")
                    parts.append("Geometry:\n" + "\n".join(geo_lines))
        except Exception:
            pass  # geometry feedback is optional

        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")

        # Track parametric definitions silently
        params = _extract_parameters(code)
        if params:
            _PARAM_STORE.update(params)

        return "\n".join(parts)

    except Exception as e:
        tb = traceback.format_exc()
        hint, _ = error_hint(e, code)

        parts = [f"ERROR: {type(e).__name__}: {e}"]
        # Show only last meaningful frame, not full traceback
        tb_lines = tb.strip().split('\n')
        if len(tb_lines) >= 2:
            last_frame = tb_lines[-2].strip()
            if last_frame:
                parts.append(f"At: {last_frame}")
        if hint:
            parts.append(hint)
        return "\n".join(parts)


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
# Registration
# ---------------------------------------------------------------------------

register_tool("execute_code", _tool_execute_code)
register_tool("undo_last", _tool_undo_last)
register_tool("export_step", _tool_export_step)
