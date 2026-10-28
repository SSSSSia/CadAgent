"""Integration tests for the loop ↔ tools result-prefix protocol (S0-E6).

agent/tools.py communicates execute_code outcomes to agent/loop.py through
the FIRST LINE of the result string (loop.py handle_tool_results):

    "OK: ..."     → quality passed (incl. "passed with warnings")
    "FAIL: ..."   → quality failed
    "ERROR: ..."  → execution failed
    "SUCCESS: ..."→ non-execute_code tools (undo_last) — must NOT touch
                    quality tracking

core/quality.py format_quality_report() emits the OK:/FAIL: lines and
agent/tools.py _attempt_auto_fix() currently emits "AUTO-FIX APPLIED:"
— see the xfail test documenting the S1-A1 bug: a successful auto-fix is
misjudged as a quality failure because its prefix matches no branch.
"""
from __future__ import annotations

import pytest

from core.session import ChatSession
from agent.controller import AgentController
from agent.loop import AgentLoop, LoopActionKind, ToolExecution


# ---- Harness (same pattern as test_agent_loop.py) ----

def _make_loop(mode: str = "tool_calling", context: str = "doc state"):
    ctrl = AgentController(ChatSession())
    return AgentLoop(ctrl, context, mode), ctrl


def _tool_execution(
    tool_name="execute_code",
    result="OK: Code executed.",
    is_error=False,
    tool_id="tc_1",
):
    return ToolExecution(
        tool_name=tool_name,
        tool_args='{"code":"pass"}',
        tool_id=tool_id,
        description="test",
        result=result,
        is_error=is_error,
    )


# ---- Prefix → quality-state tracking ----

class TestPrefixQualityTracking:
    def test_ok_prefix_marks_passed(self):
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        ])
        assert loop._last_quality_passed is True
        assert loop._last_quality_summary.startswith("OK:")

    def test_ok_with_warnings_marks_passed(self):
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(
                result="OK: Code executed. CAD quality check passed with warnings.\n"
                       "Warnings:\n  - Document has 2 shape objects"
            )
        ])
        assert loop._last_quality_passed is True

    def test_fail_prefix_marks_failed(self):
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(result="FAIL: Code executed but CAD quality check failed.")
        ])
        assert loop._last_quality_passed is False

    def test_error_prefix_marks_failed(self):
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(result="ERROR: NameError: name 'x' is not defined")
        ])
        assert loop._last_quality_passed is False

    def test_success_prefix_from_undo_does_not_touch_quality(self):
        """undo_last returns "SUCCESS: ..." — must not set quality state."""
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(tool_name="undo_last", result="SUCCESS: Document restored.")
        ])
        assert loop._last_quality_passed is None
        # but execute_codeCalled stays False, so the gate still applies
        assert loop._execute_code_called is False

    def test_summary_is_first_line_only(self):
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(
                result="FAIL: Code executed but CAD quality check failed.\n"
                       "Quality issues:\n  - Expected 1 solid, got 2"
            )
        ])
        assert loop._last_quality_summary == "FAIL: Code executed but CAD quality check failed."

    def test_auto_fix_success_prefix_marks_passed(self):
        """A successful auto-fix must count as a PASS, not a failure.

        Legacy auto-fix results (pre-S1 tools.py) led with 'AUTO-FIX
        APPLIED:'; the loop now judges them by the embedded quality report
        lines. Current tools.py emits OK:/FAIL: headers directly.
        """
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(
                result="AUTO-FIX APPLIED:\n"
                       "- Hint: translate() modifies in-place.\n"
                       "OK: Code executed. CAD quality check PASSED."
            )
        ])
        assert loop._last_quality_passed is True

    def test_auto_fix_legacy_prefix_with_embedded_fail_marks_failed(self):
        """Legacy auto-fix header whose embedded report failed → failure."""
        loop, _ = _make_loop()
        loop.handle_tool_results([
            _tool_execution(
                result="AUTO-FIX APPLIED:\n"
                       "- Hint: translate() modifies in-place.\n"
                       "FAIL: Code executed but CAD quality check failed.\n"
                       "Quality issues:\n  - Expected 1 solid, got 2"
            )
        ])
        assert loop._last_quality_passed is False


# ---- Behavior: prefix state drives the finish gate ----

class TestPrefixDrivesFinishGate:
    def _stream_done(self, loop, ctrl):
        ctrl.session.add_assistant_message({"role": "assistant", "content": "done"})
        return loop.handle_stream_done(
            {"choices": [{"message": {"content": "done", "tool_calls": None},
                          "finish_reason": "stop"}]},
            has_streaming_text=False,
        )

    def test_fail_result_blocks_finish(self):
        loop, ctrl = _make_loop()
        loop.prepare_llm_call()
        loop.handle_tool_results([
            _tool_execution(result="FAIL: Code executed but CAD quality check failed.")
        ])
        action = self._stream_done(loop, ctrl)
        # Gate blocks: loop must NOT finish; it re-prepares an LLM call
        # with an injected quality-gate user message.
        assert action.kind == LoopActionKind.CALL_LLM
        assert any(
            m.get("role") == "user" and "CAD QUALITY GATE" in m.get("content", "")
            for m in ctrl.session.get_messages()
        )

    def test_ok_result_allows_finish(self):
        loop, ctrl = _make_loop()
        loop.prepare_llm_call()
        loop.handle_tool_results([
            _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        ])
        action = self._stream_done(loop, ctrl)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True
