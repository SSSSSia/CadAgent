"""Document snapshot management for undo support.

Saves .FCStd snapshots before each execute_code call.
Maintains a bounded stack of snapshots (max 10) with automatic cleanup.
"""
from __future__ import annotations

import os
import time
import tempfile

import core.config as _config
from core.logger import log_warning

_snapshot_counter = 0
_snapshot_stack: list[dict] = []


def _get_snapshot_dir() -> str:
    try:
        import FreeCAD
        base = FreeCAD.getUserAppDataDir()
    except (ImportError, AttributeError):
        base = tempfile.gettempdir()
    snap_dir = os.path.join(base, "CadAgent", "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    # Migrate from old AiCadAgent directory if it exists
    old_dir = os.path.join(base, "AiCadAgent", "snapshots")
    if os.path.isdir(old_dir) and not os.listdir(snap_dir):
        try:
            os.rename(old_dir, snap_dir)
        except OSError:
            pass
    return snap_dir


def take_snapshot() -> str | None:
    """Save a snapshot of the active FreeCAD document.

    Returns the snapshot file path, or None if no active document.
    """
    global _snapshot_counter

    try:
        import FreeCAD
    except ImportError:
        return None

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return None

    original_path = doc.FileName if hasattr(doc, "FileName") else ""

    _snapshot_counter += 1
    snap_dir = _get_snapshot_dir()
    snapshot_filename = f"{doc.Name}_{_snapshot_counter:04d}_{int(time.time())}.FCStd"
    snapshot_path = os.path.join(snap_dir, snapshot_filename)

    doc.saveAs(snapshot_path)

    # saveAs changes doc.FileName — restore it
    if original_path:
        doc.FileName = original_path
    else:
        doc.FileName = ""

    _snapshot_stack.append({
        "path": snapshot_path,
        "doc_name": doc.Name,
        "original_path": original_path,
        "time": time.time(),
    })

    _cleanup_old_snapshots()
    return snapshot_path


def has_snapshot() -> bool:
    return len(_snapshot_stack) > 0


def snapshot_count() -> int:
    return len(_snapshot_stack)


def pop_snapshot() -> dict | None:
    if not _snapshot_stack:
        return None
    return _snapshot_stack.pop()


def restore_latest_snapshot() -> str:
    """Restore the most recent snapshot, popping it from the stack.

    Returns a result string suitable as a tool result message.
    """
    import FreeCAD
    import FreeCADGui as Gui

    entry = pop_snapshot()
    if entry is None:
        return "ERROR: No snapshot available to restore."

    snapshot_path = entry["path"]
    doc_name = entry["doc_name"]

    if not os.path.isfile(snapshot_path):
        return f"ERROR: Snapshot file not found: {snapshot_path}"

    try:
        current_doc = FreeCAD.ActiveDocument
        if current_doc and current_doc.Name == doc_name:
            FreeCAD.closeDocument(doc_name)

        restored_doc = FreeCAD.openDocument(snapshot_path)

        original_path = entry.get("original_path", "")
        if original_path:
            restored_doc.FileName = original_path

        try:
            gui_doc = Gui.activeDocument()
            if gui_doc:
                view = gui_doc.activeView()
                if view:
                    view.viewIsometric()
                    view.fitAll()
        except Exception as e:
            log_warning(f"Failed to restore camera view: {e}")

        return (
            f"SUCCESS: Document restored from snapshot.\n"
            f"Snapshot: {snapshot_path}\n"
            f"Remaining snapshots: {snapshot_count()}"
        )

    except Exception as e:
        return f"ERROR: Failed to restore snapshot: {type(e).__name__}: {e}"


def _cleanup_old_snapshots():
    while len(_snapshot_stack) > _config.MAX_SNAPSHOTS:
        oldest = _snapshot_stack.pop(0)
        try:
            if os.path.isfile(oldest["path"]):
                os.remove(oldest["path"])
        except OSError as e:
            log_warning(f"Failed to delete old snapshot {oldest['path']}: {e}")


def cleanup_all_snapshots():
    """Remove all snapshot files and clear the stack."""
    global _snapshot_counter
    for entry in _snapshot_stack:
        try:
            if os.path.isfile(entry["path"]):
                os.remove(entry["path"])
        except OSError as e:
            log_warning(f"Failed to delete snapshot {entry['path']}: {e}")
    _snapshot_stack.clear()
    _snapshot_counter = 0
