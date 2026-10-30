"""Agent controller — session and result container for the UI-driven agent loop."""
from __future__ import annotations

from core.session import ChatSession


class AgentResult:
    """Outcome of an agent run (written by AgentLoop, read by the panel)."""
    def __init__(self):
        self.success: bool = False
        self.summary: str = ""
        self.errors: list[str] = []
        self.tool_calls_log: list[dict] = []


class AgentController:
    """Container for session + result, used by the UI-driven agent loop.

    Note: the actual agent loop (state machine) lives in agent/loop.py.
    This class provides shared state (session, result) that the loop and
    the panel's signal handlers read and update during the run.
    """
    def __init__(self, session: ChatSession):
        self.session = session
        self.result = AgentResult()
