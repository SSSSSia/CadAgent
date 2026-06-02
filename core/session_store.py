"""
Session store -- disk persistence for ChatSession objects.

Saves sessions as JSON files under <FreeCAD user data>/CadAgent/sessions/.
Falls back to <temp>/CadAgent/sessions/ when FreeCAD is not available (testing).
"""
from __future__ import annotations

import json
import os
import tempfile

from core.logger import log_warning


def _get_storage_dir() -> str:
    """Use project directory Mod/CadAgent/sessions for session storage."""
    # Get the CadAgent module directory
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    session_dir = os.path.join(base, "sessions")
    os.makedirs(session_dir, exist_ok=True)

    # Migrate from old FreeCAD user data directory
    try:
        import FreeCAD
        old_base = FreeCAD.getUserAppDataDir()
    except (ImportError, AttributeError):
        old_base = None

    if old_base:
        old_dir = os.path.join(old_base, "CadAgent", "sessions")
        if os.path.isdir(old_dir) and not os.listdir(session_dir):
            # New dir is empty, migrate all sessions
            try:
                import shutil
                for f in os.listdir(old_dir):
                    if f.endswith(".json"):
                        src = os.path.join(old_dir, f)
                        dst = os.path.join(session_dir, f)
                        if not os.path.isfile(dst):
                            shutil.copy2(src, dst)
                log_warning(f"Migrated sessions from {old_dir} to {session_dir}")
            except OSError as e:
                log_warning(f"Failed to migrate sessions: {e}")

    return session_dir


class SessionStore:
    """Manages disk I/O for ChatSession objects."""

    def __init__(self):
        self._dir = _get_storage_dir()

    def save(self, session) -> str:
        """Save session to {session_id}.json. Return file path or '' on failure."""
        try:
            data = session.to_dict()
            path = os.path.join(self._dir, f"{session.session_id}.json")
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            return path
        except Exception as e:
            log_warning(f"Failed to save session {getattr(session, 'session_id', '?')}: {e}")
            return ""

    def load(self, session_id: str):
        """Load session by id. Return ChatSession or None."""
        from core.session import ChatSession

        path = os.path.join(self._dir, f"{session_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ChatSession.from_dict(data)
        except Exception as e:
            log_warning(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self) -> list[dict]:
        """List all saved sessions sorted by created_at descending.

        Each dict: session_id, created_at, summary, message_count.
        """
        sessions = []
        if not os.path.isdir(self._dir):
            return sessions

        for filename in os.listdir(self._dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self._dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", ""),
                    "created_at": data.get("created_at", ""),
                    "summary": data.get("summary", ""),
                    "message_count": len(data.get("messages", [])),
                })
            except Exception as e:
                log_warning(f"Skipping corrupt session file {filename}: {e}")

        sessions.sort(key=lambda s: s["created_at"], reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Return True if deleted."""
        path = os.path.join(self._dir, f"{session_id}.json")
        try:
            if os.path.isfile(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            log_warning(f"Failed to delete session {session_id}: {e}")
            return False

    def save_current_on_close(self, session):
        """Auto-save on close, skipping sessions with no user messages."""
        if not any(m.get("role") == "user" for m in session.messages):
            return
        self.save(session)

    def save_if_not_empty(self, session) -> str:
        """Save session only if it contains at least one user message."""
        if not any(m.get("role") == "user" for m in session.messages):
            return ""
        return self.save(session)

    def cleanup_session_snapshots(self, session_id: str) -> int:
        """Remove snapshot files associated with a session from disk.

        Scans the snapshots/ directory for files whose names contain the
        session_id (format: {doc}_{counter}_{session_id}_{timestamp}.FCStd).
        Returns the number of files removed.
        """
        from core.snapshot import SnapshotManager
        snap_dir = SnapshotManager.get_snapshot_dir()
        removed = 0
        if not os.path.isdir(snap_dir):
            return removed
        for f in os.listdir(snap_dir):
            if f.endswith(".FCStd") and session_id in f:
                try:
                    os.remove(os.path.join(snap_dir, f))
                    removed += 1
                except OSError:
                    pass
        return removed
