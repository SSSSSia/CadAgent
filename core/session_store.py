"""
Session store -- disk persistence for ChatSession objects.

Saves sessions as JSON files under <FreeCAD user data>/AiCadAgent/sessions/.
Falls back to <temp>/AiCadAgent/sessions/ when FreeCAD is not available (testing).
"""
from __future__ import annotations

import json
import os
import tempfile


def _get_storage_dir() -> str:
    try:
        import FreeCAD
        base = FreeCAD.getUserAppDataDir()
    except (ImportError, AttributeError):
        base = tempfile.gettempdir()
    session_dir = os.path.join(base, "AiCadAgent", "sessions")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def _print_warning(msg: str):
    try:
        import FreeCAD
        FreeCAD.Console.PrintWarning(f"[SessionStore] {msg}\n")
    except (ImportError, AttributeError):
        import sys
        print(f"[SessionStore] WARNING: {msg}", file=sys.stderr)


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
            _print_warning(f"Failed to save session {getattr(session, 'session_id', '?')}: {e}")
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
            _print_warning(f"Failed to load session {session_id}: {e}")
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
                _print_warning(f"Skipping corrupt session file {filename}: {e}")

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
            _print_warning(f"Failed to delete session {session_id}: {e}")
            return False

    def save_current_on_close(self, session):
        """Auto-save on close, skipping sessions with no user messages."""
        if not any(m.get("role") == "user" for m in session.messages):
            return
        self.save(session)
