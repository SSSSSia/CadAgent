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


class SnapshotManager:
    """Manages FreeCAD document snapshots for undo support.

    Encapsulates snapshot state (counter, stack, orphan cleanup flag).
    Designed for single-threaded main-thread use (FreeCAD constraint).
    """

    def __init__(self, max_snapshots: int | None = None):
        self._counter: int = 0
        self._stack: list[dict] = []
        self._orphan_cleaned: bool = False
        self._max_snapshots: int = max_snapshots or _config.MAX_SNAPSHOTS

    # --- Snapshot directory ---

    @staticmethod
    def get_snapshot_dir() -> str:
        """Return the snapshot storage directory, creating it if needed."""
        # Use project directory Mod/CadAgent/snapshots
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        snap_dir = os.path.join(base, "snapshots")
        os.makedirs(snap_dir, exist_ok=True)

        # Migrate from old FreeCAD user data directory
        try:
            import FreeCAD
            old_base = FreeCAD.getUserAppDataDir()
        except (ImportError, AttributeError):
            old_base = None

        if old_base:
            old_dir = os.path.join(old_base, "CadAgent", "snapshots")
            if os.path.isdir(old_dir) and not os.listdir(snap_dir):
                # New dir is empty, migrate all snapshots
                try:
                    import shutil
                    for f in os.listdir(old_dir):
                        if f.endswith(".FCStd"):
                            src = os.path.join(old_dir, f)
                            dst = os.path.join(snap_dir, f)
                            if not os.path.isfile(dst):
                                shutil.copy2(src, dst)
                    log_warning(f"Migrated snapshots from {old_dir} to {snap_dir}")
                except OSError as e:
                    log_warning(f"Failed to migrate snapshots: {e}")

        return snap_dir

    # --- Orphan cleanup ---

    def cleanup_orphans(self) -> None:
        """Remove orphan snapshot files older than 24 hours from disk."""
        if self._orphan_cleaned:
            return
        self._orphan_cleaned = True
        snap_dir = self.get_snapshot_dir()
        if not os.path.isdir(snap_dir):
            return
        now = time.time()
        known_paths = {e["path"] for e in self._stack}
        for f in os.listdir(snap_dir):
            if not f.endswith(".FCStd"):
                continue
            path = os.path.join(snap_dir, f)
            if path in known_paths:
                continue
            try:
                if now - os.path.getmtime(path) > 86400:
                    os.remove(path)
                    log_warning(f"Cleaned orphan snapshot: {f}")
            except OSError:
                pass

    # --- Core operations ---

    def take(self, doc=None) -> str | None:
        """Save a snapshot of the specified or active FreeCAD document.

        Returns the snapshot file path, or None if no document available.
        """
        try:
            import FreeCAD
        except ImportError:
            return None

        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None:
            return None

        self.cleanup_orphans()

        original_path = doc.FileName if hasattr(doc, "FileName") else ""

        self._counter += 1
        snap_dir = self.get_snapshot_dir()
        snapshot_filename = f"{doc.Name}_{self._counter:04d}_{int(time.time())}.FCStd"
        snapshot_path = os.path.join(snap_dir, snapshot_filename)

        doc.saveAs(snapshot_path)

        # saveAs changes doc.FileName — restore it
        if original_path:
            doc.FileName = original_path
        else:
            doc.FileName = ""

        self._stack.append({
            "path": snapshot_path,
            "doc_name": doc.Name,
            "original_path": original_path,
            "time": time.time(),
        })

        self._cleanup_old()
        return snapshot_path

    def has_snapshot(self) -> bool:
        return len(self._stack) > 0

    def count(self) -> int:
        return len(self._stack)

    def pop(self) -> dict | None:
        if not self._stack:
            return None
        return self._stack.pop()

    def restore_latest(self) -> str:
        """Restore the most recent snapshot, popping it from the stack.

        Returns a result string suitable as a tool result message.
        """
        entry = self.pop()
        if entry is None:
            return "ERROR: No snapshot available to restore."

        import FreeCAD
        import FreeCADGui

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
                gui_doc = FreeCADGui.activeDocument()
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
                f"Remaining snapshots: {self.count()}"
            )

        except Exception as e:
            return f"ERROR: Failed to restore snapshot: {type(e).__name__}: {e}"

    def cleanup_all(self) -> None:
        """Remove all snapshot files and clear the stack."""
        for entry in self._stack:
            try:
                if os.path.isfile(entry["path"]):
                    os.remove(entry["path"])
            except OSError as e:
                log_warning(f"Failed to delete snapshot {entry['path']}: {e}")
        self._stack.clear()
        self._counter = 0

    # --- Internal ---

    def _cleanup_old(self) -> None:
        """Enforce max snapshot limit by removing oldest entries."""
        while len(self._stack) > self._max_snapshots:
            oldest = self._stack.pop(0)
            try:
                if os.path.isfile(oldest["path"]):
                    os.remove(oldest["path"])
            except OSError as e:
                log_warning(f"Failed to delete old snapshot {oldest['path']}: {e}")


# ---------------------------------------------------------------------------
# Module-level convenience API (backward compatible)
# ---------------------------------------------------------------------------

_default_manager = SnapshotManager()


def take_snapshot() -> str | None:
    return _default_manager.take()


def has_snapshot() -> bool:
    return _default_manager.has_snapshot()


def snapshot_count() -> int:
    return _default_manager.count()


def pop_snapshot() -> dict | None:
    return _default_manager.pop()


def restore_latest_snapshot() -> str:
    return _default_manager.restore_latest()


def cleanup_all_snapshots() -> None:
    _default_manager.cleanup_all()


def take_snapshot_for_doc(doc) -> str | None:
    """Take a snapshot of a specific document (not necessarily active)."""
    return _default_manager.take(doc)
