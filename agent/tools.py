"""
Agent tools — the agent's interface to FreeCAD.

Each tool function takes a JSON arguments string, executes in the FreeCAD
environment, and returns a result string that becomes a role="tool" message.
"""
from __future__ import annotations

import base64
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


def _clean_stale_namespace_vars() -> list[str]:
    """Remove stale FreeCAD object references from _EXEC_NAMESPACE.

    After undo restores a snapshot, Python references to FreeCAD C++ objects
    become invalid (document was closed and reopened). This function detects
    and removes them, keeping primitive types (int, float, str, etc.) intact.
    Returns list of removed variable names.
    """
    import FreeCAD

    active_doc = FreeCAD.ActiveDocument
    stale_keys = []
    for key, val in list(_EXEC_NAMESPACE.items()):
        if isinstance(val, _PERSISTABLE_TYPES):
            continue
        try:
            doc_attr = getattr(val, "Document", None)
            if doc_attr is not None and doc_attr is not active_doc:
                stale_keys.append(key)
        except (ReferenceError, RuntimeError, AttributeError):
            stale_keys.append(key)
    for key in stale_keys:
        del _EXEC_NAMESPACE[key]
    return stale_keys


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

    # Log the code being executed
    log_info(f"execute_code [{description or 'no desc'}]:\n{code}")

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

        parts = ["OK: Code executed."]
        if auto_created_doc:
            parts.append("Auto-created document 'CadAgentModel' (none was active).")

        # Rich document state feedback — critical for LLM to verify and plan
        try:
            from core.doc_analyzer import analyze_document
            target = target_doc or FreeCAD.ActiveDocument
            if target:
                doc_state = analyze_document(target)
                if doc_state and "(No active document)" not in doc_state:
                    parts.append(f"Document state:\n{doc_state}")
        except Exception:
            pass

        stdout_text = stdout_capture.getvalue()
        if stdout_text:
            parts.append(f"Stdout:\n{stdout_text}")

        # Track parametric definitions silently
        params = _extract_parameters(code)
        if params:
            _PARAM_STORE.update(params)

        result = "\n".join(parts)
        log_info(f"execute_code result:\n{result}")
        return result

    except Exception as e:
        # Save partial namespace so variables defined before the error line
        # are available in subsequent execute_code calls
        _save_user_vars(namespace)
        tb = traceback.format_exc()
        log_error(f"execute_code FAILED: {type(e).__name__}: {e}\n{tb}")
        hint, _ = error_hint(e, code)

        parts = [f"ERROR: {type(e).__name__}: {e}"]
        parts.append(f"Traceback:\n{tb}")
        if hint:
            parts.append(hint)

        # Document state after error helps LLM understand what exists
        try:
            from core.doc_analyzer import analyze_document
            target = target_doc or FreeCAD.ActiveDocument
            if target:
                doc_state = analyze_document(target)
                if doc_state and "(No active document)" not in doc_state:
                    parts.append(f"Document state after error:\n{doc_state}")
        except Exception:
            pass

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool: undo_last
# ---------------------------------------------------------------------------

def _tool_undo_last(args_json: str) -> str:
    """Undo the last execute_code by restoring document snapshot."""
    from core.snapshot import restore_latest_snapshot
    result = restore_latest_snapshot()
    if result.startswith("SUCCESS"):
        import FreeCAD
        _EXEC_NAMESPACE["doc"] = FreeCAD.ActiveDocument
        stale = _clean_stale_namespace_vars()
        if stale:
            result += f"\nCleared stale variables: {', '.join(stale)}"
            active = FreeCAD.ActiveDocument
            if active:
                objs = [
                    o.Name for o in active.Objects
                    if hasattr(o, "Shape") and o.Shape is not None
                ]
                if objs:
                    result += (
                        f"\nObjects in restored doc: {', '.join(objs)}"
                        f" — re-reference with doc.getObject('Name')"
                    )
    return result


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
# Tool: capture_view
# ---------------------------------------------------------------------------

def _tool_capture_view(args_json: str) -> str:
    """Capture the FreeCAD 3D viewport and analyze with vision model."""
    args = json.loads(args_json)
    prompt = args.get(
        "prompt",
        "Describe the 3D model in this FreeCAD viewport. Identify shapes, "
        "dimensions if visible, any issues with the model, and whether it "
        "looks correct."
    )

    gui_doc = Gui.activeDocument()
    if gui_doc is None:
        return "ERROR: No active 3D view to capture. Open a document first."

    view = gui_doc.activeView()
    if view is None:
        return "ERROR: No active 3D view to capture."

    try:
        view.viewIsometric()
        view.fitAll()
    except Exception:
        pass

    # Give Qt time to repaint the 3D view before capturing
    try:
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    except Exception:
        pass

    png_bytes = None
    capture_method = ""

    # Method 1: FreeCAD native saveImage (most reliable — uses Coin3D offscreen)
    import tempfile
    tmp_path = os.path.join(tempfile.gettempdir(), "cadagent_capture.png")
    try:
        view.saveImage(tmp_path, 1280, 720, "Current")
        with open(tmp_path, "rb") as f:
            png_bytes = f.read()
        capture_method = "saveImage"
    except Exception:
        png_bytes = None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Method 2: Widget grab fallback
    if png_bytes is None:
        pixmap = None
        try:
            widget = view.getWidget()
            pixmap = widget.grab()
        except (AttributeError, RuntimeError):
            pass

        if pixmap is None:
            try:
                from PySide6 import QtWidgets
                main_window = Gui.getMainWindow()
                mdi_area = main_window.findChild(QtWidgets.QMdiArea)
                if mdi_area and mdi_area.activeSubWindow():
                    widget = mdi_area.activeSubWindow().widget()
                    pixmap = widget.grab()
            except Exception:
                pass

        if pixmap is not None:
            from PySide6.QtCore import QBuffer
            buf = QBuffer()
            buf.open(QBuffer.ReadWrite)
            pixmap.save(buf, "PNG")
            png_bytes = buf.data().data()
            buf.close()
            capture_method = "widget_grab"

    if png_bytes is None:
        return "ERROR: Cannot capture 3D viewport. No accessible widget found."

    image_base64 = base64.b64encode(png_bytes).decode("ascii")

    log_info(f"Captured viewport via {capture_method}: "
             f"{len(png_bytes)} bytes PNG")

    from core.vision_client import analyze_image
    result = analyze_image(image_base64, prompt, mime_type="image/png")
    return result


# ---------------------------------------------------------------------------
# Tool: analyze_image
# ---------------------------------------------------------------------------

def _tool_analyze_image(args_json: str) -> str:
    """Analyze a user-uploaded image file with the vision model."""
    args = json.loads(args_json)
    image_path = args.get("image_path", "")
    prompt = args.get(
        "prompt",
        "Describe this image in detail. If it's a technical drawing or sketch, "
        "identify dimensions, features, and key design elements."
    )

    if not image_path:
        return "ERROR: image_path is required."

    if not os.path.isfile(image_path):
        return f"ERROR: Image file not found: {image_path}"

    from core.vision_client import image_file_to_base64, analyze_image
    try:
        image_base64, mime_type = image_file_to_base64(image_path)
    except ValueError as e:
        return f"ERROR: {e}"

    log_info(f"Analyzing image: {image_path} ({mime_type}, "
             f"{os.path.getsize(image_path)} bytes)")

    result = analyze_image(image_base64, prompt, mime_type=mime_type)
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool("execute_code", _tool_execute_code)
register_tool("undo_last", _tool_undo_last)
register_tool("export_step", _tool_export_step)
register_tool("capture_view", _tool_capture_view)
register_tool("analyze_image", _tool_analyze_image)
