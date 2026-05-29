"""Agent controller — session and result container for the UI-driven agent loop."""
from __future__ import annotations

from core.session import ChatSession


class AgentResult:
    """Outcome of an agent run."""
    def __init__(self):
        self.success: bool = False
        self.summary: str = ""
        self.iterations: int = 0
        self.errors: list[str] = []
        self.tool_calls_log: list[dict] = []
        self.start_time: float = 0.0
        self.last_quality_passed: bool | None = None
        self.last_quality_summary: str = ""


class AgentController:
    """Container for session + result, used by the UI-driven agent loop.

    Note: the actual agent loop (state machine) lives in ui/panel.py.
    This class provides shared state (session, result, mode) that the
    panel's signal handlers read and update during the loop.
    """
    def __init__(self, session: ChatSession):
        self.session = session
        self.result = AgentResult()
        self._stopped = False
        self._mode = "auto"  # "auto" | "tool_calling" | "react"

    def stop(self):
        self._stopped = True
