"""Status bar mixin for AgentPanel — reactive state display with elapsed time."""
from __future__ import annotations

import time

from PySide6 import QtCore

import core.config as _config


class _PanelStatusMixin:
    """Centralized status bar management — reactive to actual agent state.

    Observable states:
      idle            → "Ready"
      thinking        → LLM API call in progress
      executing_tool  → a specific tool is running
      stopping        → user requested stop, waiting for thread
    Terminal states (done/failed) set the label directly and stop the timer.
    """

    _TOOL_DISPLAY = {
        "execute_code": "Running code",
        "analyze_geometry": "Analyzing geometry",
        "validate_design": "Validating design",
        "undo_last": "Undoing",
    }

    def _setup_status(self):
        """Initialize status state and timer. Call once from _setup_ui()."""
        self._status_state = "idle"
        self._status_tool_name = ""
        self._status_tool_desc = ""
        self._status_phase_start = 0.0
        self._agent_start_time = 0.0
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._status_tick)

    def _status_set(self, state, detail=""):
        """Transition to a new status state and update display immediately."""
        self._status_state = state
        self._status_phase_start = time.time()

        if state == "thinking":
            self._status_tool_name = ""
            self._status_tool_desc = ""
        elif state == "executing_tool":
            self._status_tool_name = detail
            self._status_tool_desc = ""
        elif state == "idle":
            self._status_timer.stop()
            self._status_tool_name = ""
            self._status_tool_desc = ""
            self._status_phase_start = 0.0

        if state in ("thinking", "executing_tool", "stopping"):
            if not self._status_timer.isActive():
                self._status_timer.start()

        self._status_tick()

    def _status_reset(self):
        """Reset to idle state."""
        self._status_set("idle")
        c = self._get_colors()
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet(
            f"color:{c.status_idle}; font-size:11px; font-family:'Segoe UI', sans-serif;"
        )

    def _status_tick(self):
        """Timer callback — rebuild and display current status text."""
        text = self._status_format()
        color = self._status_color()
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color:{color}; font-size:11px; font-family:'Segoe UI', sans-serif;"
        )

    def _status_format(self):
        """Build status display string from current state."""
        state = self._status_state

        if state == "idle":
            return "Ready"

        elapsed = time.time() - self._status_phase_start if self._status_phase_start else 0
        elapsed_str = self._format_elapsed(elapsed)
        iter_str = (
            f"  [{self._iteration}/{_config.MAX_ITERATIONS}]"
            if self._iteration > 0
            else ""
        )

        if state == "thinking":
            return f"Thinking... {elapsed_str}{iter_str}"

        if state == "executing_tool":
            tool = self._status_tool_name
            desc = self._status_tool_desc
            if desc:
                display = desc[:40] + ("..." if len(desc) > 40 else "")
                return f'Executing {tool} "{display}"  {elapsed_str}{iter_str}'
            fallback = self._TOOL_DISPLAY.get(tool, tool)
            return f"Executing {fallback}...  {elapsed_str}{iter_str}"

        if state == "stopping":
            return f"Stopping... {elapsed_str}"

        return "Ready"

    @staticmethod
    def _format_elapsed(seconds):
        """Format elapsed time as '4.5s' or '2m 15s'."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"

    def _status_color(self):
        """Return hex color for the current state."""
        c = self._get_colors()
        return {
            "idle": c.status_idle,
            "thinking": c.status_thinking,
            "executing_tool": c.status_executing,
            "stopping": c.status_stopping,
        }.get(self._status_state, c.status_idle)
