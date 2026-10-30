"""
Session store -- disk persistence for ChatSession objects.

Saves sessions as JSON files under <FreeCAD user data>/CadAgent/sessions/.
Falls back to <temp>/CadAgent/sessions/ when FreeCAD is not available (testing).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import tempfile

from core.logger import log_warning

# ChatSession generates session_id as uuid4().hex[:12] — exactly 12 lowercase
# hex chars. load()/delete() reject anything else before touching the
# filesystem, so a crafted id like "../evil" cannot escape the storage dir.
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _parse_ts(ts: str) -> str:
    """Sort key for created_at: ISO strings sort correctly, but parse to a
    normalized form so mixing formats or corrupt values degrades to a stable
    "" (oldest) instead of interleaving (B13)."""
    try:
        return datetime.datetime.fromisoformat(ts).isoformat()
    except (TypeError, ValueError):
        return ""


def _get_storage_dir() -> str:
    """Sessions live under the CadAgent data root (S4-C9)."""
    from core.paths import subdir
    return subdir("sessions")


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
        """Load session by id. Return ChatSession or None.

        Rejects session ids that don't match the generated format
        (12 lowercase hex chars) before any filesystem access (B22).
        """
        if not _SESSION_ID_RE.match(session_id or ""):
            return None
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

        sessions.sort(key=lambda s: _parse_ts(s["created_at"]), reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Return True if deleted.

        Rejects session ids that don't match the generated format before
        any filesystem access (B22).
        """
        if not _SESSION_ID_RE.match(session_id or ""):
            return False
        path = os.path.join(self._dir, f"{session_id}.json")
        try:
            if os.path.isfile(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            log_warning(f"Failed to delete session {session_id}: {e}")
            return False

    def save_if_not_empty(self, session) -> str:
        """Save session only if it contains at least one user message."""
        if not any(m.get("role") == "user" for m in session.messages):
            return ""
        return self.save(session)
