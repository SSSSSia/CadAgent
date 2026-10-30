"""Document snapshot management for undo support.

Saves .FCStd snapshots before each execute_code call. Snapshots are kept
in PER-DOCUMENT stacks (S4-C7) with a global cap, so undo in multi-document
workflows restores the right document instead of silently no-op'ing or
duplicating documents.

File lifecycle rule (S4-C4): a snapshot file exists on disk if and only if
its entry is in a stack — restoring deletes the file, stack-overflow
eviction deletes the file, session cleanup deletes matching files on disk.
Each snapshot is tagged with a session id for targeted cleanup.
"""
from __future__ import annotations

import os
import re
import time

import core.config as _config
from core.logger import log_warning

# Filename format: {doc.Name}_{counter:04d}_{session_id[:6]}_{timestamp}.FCStd
# (legacy: no session segment). Parsed from the END so underscores inside
# doc.Name cannot confuse the session-hash match (S4-C6).
_SESSION_FILE_RE = re.compile(r"_([0-9a-f]{6})_(\d{10})\.FCStd$")
_LEGACY_FILE_RE = re.compile(r"_\d{4}_\d{10}\.FCStd$")

# Orphan sweep runs once per PROCESS (not per manager) and only marks done
# after a successful scan so a locked directory retries later (S4-C5).
_ORPHAN_CLEANED = False


class SnapshotManager:
    """Manages FreeCAD document snapshots for undo support.

    Designed for single-threaded main-thread use (FreeCAD constraint).
    """

    def __init__(self, max_snapshots: int | None = None):
        self._counter: int = 0
        self._stacks: dict[str, list[dict]] = {}  # doc.Name -> entries (newest last)
        self._max_snapshots: int = max_snapshots or _config.MAX_SNAPSHOTS
        self._session_id: str | None = None

    # --- Session ID ---

    def set_session_id(self, session_id: str | None) -> None:
        """Set the current session ID for tagging new snapshots."""
        self._session_id = session_id

    # --- Snapshot directory ---

    @staticmethod
    def get_snapshot_dir() -> str:
        """Return the snapshot storage directory under the CadAgent data
        root (S4-C9), creating it if needed."""
        from core.paths import subdir
        return subdir("snapshots")

    # --- Stack views ---

    def _all_entries(self) -> list[dict]:
        """All entries across document stacks, oldest first."""
        entries = [e for stack in self._stacks.values() for e in stack]
        entries.sort(key=lambda e: e["time"])
        return entries

    def latest_entry(self) -> dict | None:
        """The globally most recent entry (or None)."""
        entries = self._all_entries()
        return entries[-1] if entries else None

    # --- Orphan cleanup ---

    def cleanup_orphans(self, max_age_seconds: int = 3600) -> None:
        """Remove orphan snapshot files older than max_age_seconds from disk.

        Defaults to 1 hour — snapshots are transient undo files. Runs at
        most once per process; a failed scan retries on the next call.
        """
        global _ORPHAN_CLEANED
        if _ORPHAN_CLEANED:
            return
        snap_dir = self.get_snapshot_dir()
        if not os.path.isdir(snap_dir):
            _ORPHAN_CLEANED = True
            return
        now = time.time()
        known_paths = {e["path"] for e in self._all_entries()}
        try:
            files = os.listdir(snap_dir)
        except OSError:
            return  # scan failed — flag stays False, retry next time
        for f in files:
            if not f.endswith(".FCStd"):
                continue
            path = os.path.join(snap_dir, f)
            if path in known_paths:
                continue
            try:
                if now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
                    log_warning(f"Cleaned orphan snapshot: {f}")
            except OSError:
                pass
        _ORPHAN_CLEANED = True

    # --- Core operations ---

    def take(self, doc=None) -> str | None:
        """Save a snapshot of the specified or active FreeCAD document.

        Returns the snapshot file path, or None when no document is
        available or FreeCAD is not importable. Does NOT raise for those
        expected conditions — callers (agent/tools.py) degrade to
        "undo unavailable"; unexpected save errors propagate to them and
        are logged there (S4-C13 contract).
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
        original_label = doc.Label if hasattr(doc, "Label") else ""

        self._counter += 1
        snap_dir = self.get_snapshot_dir()

        # Embed session_id in filename when available for targeted cleanup.
        # Only the first 6 chars keep openDocument's derived doc Name short
        # (openDocument names the restored doc after the file basename).
        if self._session_id:
            snapshot_filename = (
                f"{doc.Name}_{self._counter:04d}"
                f"_{self._session_id[:6]}_{int(time.time())}.FCStd"
            )
        else:
            snapshot_filename = (
                f"{doc.Name}_{self._counter:04d}_{int(time.time())}.FCStd"
            )
        snapshot_path = os.path.join(snap_dir, snapshot_filename)

        # saveCopy writes the snapshot without disturbing the live document
        # (FileName/Label stay untouched). Legacy fallback: saveAs rewrites
        # BOTH doc.FileName and doc.Label — restore them after saving.
        if hasattr(doc, "saveCopy"):
            doc.saveCopy(snapshot_path)
        else:
            doc.saveAs(snapshot_path)
            doc.FileName = original_path
            doc.Label = original_label

        self._stacks.setdefault(doc.Name, []).append({
            "path": snapshot_path,
            "doc_name": doc.Name,
            "original_path": original_path,
            "original_label": original_label,
            "session_id": self._session_id,
            "time": time.time(),
        })

        self._cleanup_old()
        return snapshot_path

    def has_snapshot(self) -> bool:
        return bool(self._all_entries())

    def count(self) -> int:
        return len(self._all_entries())

    def pop(self) -> dict | None:
        """Pop the globally most recent entry (raw — does not touch files)."""
        entry = self.latest_entry()
        if entry is None:
            return None
        self._remove_entry(entry)
        return entry

    def push_back(self, entry: dict) -> None:
        """Re-insert a popped entry into its document stack (time-ordered)."""
        stack = self._stacks.setdefault(entry["doc_name"], [])
        stack.append(entry)
        stack.sort(key=lambda e: e["time"])

    def _remove_entry(self, entry: dict) -> None:
        stack = self._stacks.get(entry["doc_name"], [])
        try:
            stack.remove(entry)
        except ValueError:
            pass
        if not stack:
            self._stacks.pop(entry["doc_name"], None)

    def restore_latest(self, adjust_view: bool = True) -> str:
        """Restore the most recent snapshot (across all documents).

        adjust_view=False skips the camera fit (S4-C10).
        Returns a result string suitable as a tool result message.
        """
        result, _ = self.restore_latest_with_entry(adjust_view=adjust_view)
        return result

    def restore_latest_with_entry(
        self, adjust_view: bool = True
    ) -> tuple[str, dict | None]:
        """restore_latest, also returning the popped entry.

        The entry leaves the stack ONLY on a successful restore — failures
        push it back so one broken undo never eats the whole history
        (S4-C12). A successful restore deletes the snapshot file (S4-C4).
        """
        entry = self.pop()
        if entry is None:
            return "ERROR: No snapshot available to restore.", None

        import FreeCAD

        snapshot_path = entry["path"]
        doc_name = entry["doc_name"]

        def _fail(msg: str) -> tuple[str, dict]:
            self.push_back(entry)
            return msg, entry

        if not os.path.isfile(snapshot_path):
            return _fail(f"ERROR: Snapshot file not found: {snapshot_path}")

        try:
            # Close whatever the restore would duplicate: the doc created
            # under the snapshot's Name, AND any doc whose FileName already
            # points at the snapshot (openDocument would just return that
            # same, un-restored doc — verified on FreeCAD 1.1.1).
            for name, open_doc in list(FreeCAD.listDocuments().items()):
                fname = getattr(open_doc, "FileName", "") or ""
                matches_snapshot = (
                    fname
                    and os.path.normcase(os.path.abspath(fname))
                    == os.path.normcase(os.path.abspath(snapshot_path))
                )
                if name == doc_name or matches_snapshot:
                    FreeCAD.closeDocument(name)

            restored_doc = FreeCAD.openDocument(snapshot_path)

            original_path = entry.get("original_path", "")
            if original_path:
                restored_doc.FileName = original_path
            else:
                # Untitled document: never leave FileName pointing at the
                # snapshot file — a user Ctrl+S would silently save INTO the
                # transient snapshot (which cleanup later deletes) instead
                # of opening a Save As dialog.
                restored_doc.FileName = ""

            # openDocument renames the doc after the snapshot basename —
            # restore the user-visible Label. (The internal Name cannot be
            # changed; the short filename above keeps it reasonable.)
            original_label = entry.get("original_label", "")
            if original_label:
                restored_doc.Label = original_label

            if adjust_view:
                try:
                    import FreeCADGui  # S4-C11: console-safe (inside try)
                    gui_doc = FreeCADGui.activeDocument()
                    if gui_doc:
                        view = gui_doc.activeView()
                        if view:
                            view.fitAll()  # keep zoom-to-fit, drop isometric
                except Exception as e:
                    log_warning(f"Failed to restore camera view: {e}")

            # Success: the file's purpose is served — delete it (S4-C4).
            try:
                os.remove(snapshot_path)
            except OSError as e:
                log_warning(f"Could not delete snapshot {snapshot_path}: {e}")

            return (
                f"SUCCESS: Document restored from snapshot.\n"
                f"Snapshot: {snapshot_path}\n"
                f"Restored document: Name='{restored_doc.Name}', "
                f"Label='{restored_doc.Label}'\n"
                f"Remaining snapshots: {self.count()}",
                entry,
            )

        except Exception as e:
            return _fail(f"ERROR: Failed to restore snapshot: {type(e).__name__}: {e}")

    def cleanup_all(self) -> None:
        """Remove all snapshot files and clear the stacks."""
        for entry in self._all_entries():
            try:
                if os.path.isfile(entry["path"]):
                    os.remove(entry["path"])
            except OSError as e:
                log_warning(f"Failed to delete snapshot {entry['path']}: {e}")
        self._stacks.clear()
        self._counter = 0

    def cleanup_for_session(self, session_id: str) -> int:
        """Remove snapshots associated with a session (stack entries AND
        matching files on disk, S4-C6).

        Disk matching is by the 6-hex session hash segment in the filename
        (exact match on the segment). Legacy files without a session
        segment are preserved.
        """
        if not session_id:
            return 0
        hash6 = session_id[:6]

        removed = 0
        for entry in self._all_entries():
            if entry.get("session_id") == session_id:
                try:
                    if os.path.isfile(entry["path"]):
                        os.remove(entry["path"])
                except OSError as e:
                    log_warning(f"Failed to delete snapshot {entry['path']}: {e}")
                self._remove_entry(entry)
                removed += 1

        # Disk sweep: catches files no longer in any stack (restored ones
        # are already deleted; these are crash leftovers / older runs).
        snap_dir = self.get_snapshot_dir()
        if os.path.isdir(snap_dir):
            try:
                for f in os.listdir(snap_dir):
                    if not f.endswith(".FCStd"):
                        continue
                    m = _SESSION_FILE_RE.search(f)
                    if m and m.group(1) == hash6:
                        try:
                            os.remove(os.path.join(snap_dir, f))
                            removed += 1
                        except OSError:
                            pass
            except OSError:
                pass
        return removed

    # --- Internal ---

    def _cleanup_old(self) -> None:
        """Enforce the global snapshot cap by evicting the oldest entries."""
        while self.count() > self._max_snapshots:
            entries = self._all_entries()
            oldest = entries[0]
            try:
                if os.path.isfile(oldest["path"]):
                    os.remove(oldest["path"])
            except OSError as e:
                log_warning(f"Failed to delete old snapshot {oldest['path']}: {e}")
            self._remove_entry(oldest)


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


def set_snapshot_session_id(session_id: str | None) -> None:
    """Set the current session ID on the default snapshot manager."""
    _default_manager.set_session_id(session_id)


def cleanup_session_snapshots(session_id: str) -> int:
    """Remove snapshots associated with a session from the default manager."""
    return _default_manager.cleanup_for_session(session_id)
