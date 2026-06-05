"""Tests for agent/loop.py — AgentLoop state machine (pure logic, no Qt/FreeCAD)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.session import ChatSession
from agent.controller import AgentController
from agent.loop import AgentLoop, LoopAction, LoopActionKind, ToolExecution
import core.config as _config


# ---- Helpers ----

def _make_controller() -> AgentController:
    return AgentController(ChatSession())


def _make_loop(mode: str = "auto", context: str = ""):
    ctrl = _make_controller()
    return AgentLoop(ctrl, context, mode), ctrl


def _llm_response(content="", tool_calls=None, finish_reason="stop"):
    msg = {"content": content or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": finish_reason}]
    }


def _tool_call(name="execute_code", args='{"code":"pass"}', call_id="tc_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


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


# ---- start() ----

def test_start_returns_call_llm():
    loop, ctrl = _make_loop()
    action = loop.start("make a box")
    assert action.kind == LoopActionKind.CALL_LLM
    assert action.messages is not None
    assert len(action.messages) >= 2


def test_start_sets_system_prompt():
    loop, ctrl = _make_loop(context="Box 10x10x10")
    loop.start("make a box")
    msgs = ctrl.session.get_messages()
    assert msgs[0]["role"] == "system"
    assert "Box 10x10x10" in msgs[0]["content"]


def test_start_adds_user_message():
    loop, ctrl = _make_loop()
    loop.start("create a cylinder")
    msgs = ctrl.session.get_messages()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "create a cylinder"


def test_start_increments_iteration():
    loop, _ = _make_loop()
    loop.start("hello")
    assert loop.iteration == 1


# ---- prepare_llm_call() ----

def test_prepare_respects_max_iterations():
    loop, _ = _make_loop()
    loop._iteration = 100
    action = loop.prepare_llm_call()
    assert action.kind == LoopActionKind.FINISH
    assert not action.success
    assert "Max iterations" in action.summary


def test_prepare_respects_stop_flag():
    loop, _ = _make_loop()
    loop.request_stop()
    action = loop.prepare_llm_call()
    assert action.kind == LoopActionKind.FINISH
    assert not action.success
    assert "stopped" in action.summary


def test_prepare_returns_tools_for_tool_calling():
    loop, _ = _make_loop(mode="tool_calling")
    action = loop.prepare_llm_call()
    assert action.kind == LoopActionKind.CALL_LLM
    assert action.tools is not None


def test_prepare_returns_none_tools_for_react():
    loop, _ = _make_loop(mode="react")
    action = loop.prepare_llm_call()
    assert action.kind == LoopActionKind.CALL_LLM
    assert action.tools is None


def test_prepare_increments_iteration():
    loop, _ = _make_loop()
    assert loop.iteration == 0
    loop.prepare_llm_call()
    assert loop.iteration == 1
    loop.prepare_llm_call()
    assert loop.iteration == 2


# ---- handle_stream_done() mode auto-detection ----

def test_auto_detect_tool_calling():
    loop, ctrl = _make_loop()
    loop.start("test")
    tc = _tool_call()
    data = _llm_response(tool_calls=[tc], finish_reason="tool_calls")
    action = loop.handle_stream_done(data, False)
    assert action.kind == LoopActionKind.EXECUTE_TOOLS
    assert loop.mode == "tool_calling"
    assert ctrl.session.last_mode == "tool_calling"


def test_auto_detect_react_fallback():
    loop, ctrl = _make_loop()
    loop.start("test")
    data = _llm_response(
        content='<tool name="execute_code"><parameter name="code">pass</parameter></tool>',
        finish_reason="stop",
    )
    action = loop.handle_stream_done(data, False)
    assert action.kind == LoopActionKind.EXECUTE_TOOLS
    assert loop.mode == "react"
    assert ctrl.session.last_mode == "react"
    assert "ReAct mode" in action.system_message


def test_auto_detect_final_answer():
    loop, ctrl = _make_loop()
    loop.start("test")
    data = _llm_response(content="I've created the part.", finish_reason="stop")
    action = loop.handle_stream_done(data, True)
    assert action.kind == LoopActionKind.FINISH
    assert action.success
    assert loop.mode == "tool_calling"
    assert action.from_stream is True


# ---- handle_stream_done() react mode ----

def test_react_with_tool_tags():
    loop, _ = _make_loop(mode="react")
    loop.prepare_llm_call()
    data = _llm_response(
        content='<tool name="execute_code"><parameter name="code">pass</parameter></tool>',
        finish_reason="stop",
    )
    action = loop.handle_stream_done(data, False)
    assert action.kind == LoopActionKind.EXECUTE_TOOLS


def test_react_no_tool_tags_finishes():
    loop, _ = _make_loop(mode="react")
    loop.prepare_llm_call()
    data = _llm_response(content="Design complete.", finish_reason="stop")
    action = loop.handle_stream_done(data, False)
    assert action.kind == LoopActionKind.FINISH
    assert action.success


# ---- handle_stream_done() tool_calling mode ----

def test_tool_calling_with_tool_calls():
    loop, _ = _make_loop(mode="tool_calling")
    loop.prepare_llm_call()
    tc = _tool_call()
    data = _llm_response(tool_calls=[tc], finish_reason="tool_calls")
    action = loop.handle_stream_done(data, False)
    assert action.kind == LoopActionKind.EXECUTE_TOOLS
    assert len(action.tool_calls) == 1


def test_tool_calling_stop_finishes():
    loop, _ = _make_loop(mode="tool_calling")
    loop.prepare_llm_call()
    data = _llm_response(content="Done!", finish_reason="stop")
    action = loop.handle_stream_done(data, True)
    assert action.kind == LoopActionKind.FINISH
    assert action.success
    assert action.summary == "Done!"


# ---- handle_tool_results() ----

def test_tool_results_adds_to_session_tool_calling():
    loop, ctrl = _make_loop(mode="tool_calling")
    loop.prepare_llm_call()
    tc = _tool_call(call_id="tc_42")
    ctrl.session.add_assistant_message({
        "role": "assistant", "content": "",
        "tool_calls": [tc],
    })
    ex = ToolExecution(
        tool_name="execute_code", tool_args='{}', tool_id="tc_42",
        description="test", result="SUCCESS: done", is_error=False,
    )
    loop.handle_tool_results([ex])
    msgs = ctrl.session.get_messages()
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "tc_42"


def test_tool_results_adds_user_message_in_react():
    loop, ctrl = _make_loop(mode="react")
    loop.prepare_llm_call()
    ex = ToolExecution(
        tool_name="execute_code", tool_args='{}', tool_id="",
        description="test", result="SUCCESS", is_error=False,
    )
    loop.handle_tool_results([ex])
    msgs = ctrl.session.get_messages()
    user_msgs = [m for m in msgs if m["role"] == "user" and "[Tool Result" in m.get("content", "")]
    assert len(user_msgs) == 1


def test_tool_results_returns_next_call():
    loop, _ = _make_loop(mode="tool_calling")
    loop.prepare_llm_call()
    ex = ToolExecution(
        tool_name="execute_code", tool_args='{}', tool_id="tc_1",
        description="", result="OK", is_error=False,
    )
    action = loop.handle_tool_results([ex])
    assert action.kind == LoopActionKind.CALL_LLM


def test_tool_results_logs_errors():
    loop, ctrl = _make_loop(mode="tool_calling")
    loop.prepare_llm_call()
    ctrl.session.add_assistant_message({
        "role": "assistant", "content": "",
        "tool_calls": [_tool_call(call_id="tc_err")],
    })
    ex = ToolExecution(
        tool_name="execute_code", tool_args='{}', tool_id="tc_err",
        description="", result="ERROR: bad code", is_error=True,
    )
    loop.handle_tool_results([ex])
    assert len(ctrl.result.errors) == 1
    assert "execute_code" in ctrl.result.errors[0]
    assert len(ctrl.result.tool_calls_log) == 1
    assert ctrl.result.tool_calls_log[0]["is_error"]


# ---- handle_error() ----

def test_handle_error_returns_finish():
    loop, _ = _make_loop()
    action = loop.handle_error("timeout")
    assert action.kind == LoopActionKind.FINISH
    assert not action.success
    assert "timeout" in action.summary


# ---- request_stop() ----

def test_request_stop():
    loop, _ = _make_loop()
    assert not loop.stopped
    loop.request_stop()
    assert loop.stopped


def test_request_stop_idempotent():
    loop, _ = _make_loop()
    loop.request_stop()
    loop.request_stop()
    assert loop.stopped


# ---- Iteration tracking ----

def test_iteration_increments_across_loop():
    loop, ctrl = _make_loop(mode="tool_calling")
    loop.start("test")
    assert loop.iteration == 1
    tc = _tool_call()
    ctrl.session.add_assistant_message({
        "role": "assistant", "content": "", "tool_calls": [tc],
    })
    ex = ToolExecution(
        tool_name="execute_code", tool_args='{}', tool_id=tc["id"],
        description="", result="OK", is_error=False,
    )
    action = loop.handle_tool_results([ex])
    assert loop.iteration == 2
    assert action.kind == LoopActionKind.CALL_LLM


# ---- start_time ----

def test_start_time_set():
    loop, _ = _make_loop()
    assert loop.start_time > 0
    import time
    assert time.time() - loop.start_time < 5


# ===========================================================================
# Phase 1.3: Quality gate tracking
# ===========================================================================

class TestQualityGateTracking:
    """Test that handle_tool_results correctly tracks quality state."""

    def test_ok_result_sets_passed_true(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        loop.handle_tool_results([ex])
        assert loop._last_quality_passed is True
        assert "OK" in loop._last_quality_summary
        assert ctrl.result.last_quality_passed is True

    def test_fail_result_sets_passed_false(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Code executed but CAD quality check failed.",
            is_error=True,
        )
        loop.handle_tool_results([ex])
        assert loop._last_quality_passed is False
        assert "FAIL" in loop._last_quality_summary
        assert ctrl.result.last_quality_passed is False

    def test_error_result_sets_passed_false(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(result="ERROR: ValueError: bad input", is_error=True)
        loop.handle_tool_results([ex])
        assert loop._last_quality_passed is False
        assert ctrl.result.last_quality_passed is False

    def test_non_execute_code_does_not_change_quality(self):
        loop, _ = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex1 = _tool_execution(result="OK: Code executed.")
        loop.handle_tool_results([ex1])
        assert loop._last_quality_passed is True

        loop.prepare_llm_call()
        ex2 = _tool_execution(
            tool_name="undo_last", result="SUCCESS: Snapshot restored."
        )
        loop.handle_tool_results([ex2])
        assert loop._last_quality_passed is True

    def test_no_tools_run_quality_is_none(self):
        loop, _ = _make_loop()
        assert loop._last_quality_passed is None


# ===========================================================================
# Phase 1.3: Quality gate blocking
# ===========================================================================

class TestQualityGateBlocking:
    """Test that handle_stream_done blocks FINISH when quality gate failed."""

    def test_react_mode_blocks_finish_on_fail(self):
        loop, ctrl = _make_loop(mode="react")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Code executed but CAD quality check failed.",
            is_error=True,
        )
        loop.handle_tool_results([ex])
        data = _llm_response(content="Design complete.", finish_reason="stop")
        action = loop.handle_stream_done(data, False)
        assert action.kind == LoopActionKind.CALL_LLM

    def test_tool_calling_mode_blocks_finish_on_fail(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Quality check failed.", is_error=True
        )
        loop.handle_tool_results([ex])
        data = _llm_response(content="I'm done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.CALL_LLM

    def test_quality_passed_allows_finish(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        loop.handle_tool_results([ex])
        data = _llm_response(content="All done.", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_no_quality_data_allows_finish(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        data = _llm_response(content="Simple response.", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_auto_detect_first_iteration_not_blocked(self):
        loop, ctrl = _make_loop()
        loop.start("test")
        data = _llm_response(content="Just a text response.", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_quality_gate_injects_feedback_message(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(result="FAIL: Quality check failed.", is_error=True)
        loop.handle_tool_results([ex])
        data = _llm_response(content="Done!", finish_reason="stop")
        loop.handle_stream_done(data, True)
        user_msgs = [m for m in ctrl.session.get_messages() if m["role"] == "user"]
        feedback = [m for m in user_msgs if "QUALITY GATE" in m["content"]]
        assert len(feedback) == 1

    def test_quality_gate_recovers_on_ok(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex1 = _tool_execution(result="FAIL: Quality check failed.", is_error=True)
        loop.handle_tool_results([ex1])
        assert loop._last_quality_passed is False

        loop.prepare_llm_call()
        tc = _tool_call()
        ctrl.session.add_assistant_message({
            "role": "assistant", "content": "", "tool_calls": [tc],
        })
        ex2 = _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        loop.handle_tool_results([ex2])
        assert loop._last_quality_passed is True

        data = _llm_response(content="Done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_max_iterations_is_safety_net(self):
        loop, ctrl = _make_loop(mode="tool_calling")
        loop._iteration = _config.MAX_ITERATIONS - 1
        loop.prepare_llm_call()
        ex = _tool_execution(result="FAIL: Quality check failed.", is_error=True)
        loop.handle_tool_results([ex])
        data = _llm_response(content="Done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is False
        assert "Max iterations" in action.summary


# ===========================================================================
# Phase 6: execute_code tracking and context-aware gate
# ===========================================================================

class TestExecuteCodeTracking:
    """Test that execute_code tracking gates FINISH correctly."""

    def test_execute_code_called_flag_set(self):
        loop, _ = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        assert loop._execute_code_called is False
        ex = _tool_execution(result="OK: Code executed.")
        loop.handle_tool_results([ex])
        assert loop._execute_code_called is True

    def test_no_execute_code_with_context_blocks_finish(self):
        loop, ctrl = _make_loop(mode="tool_calling", context="Box 10x10x10")
        loop.start("make a box")
        data = _llm_response(content="Done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.CALL_LLM

    def test_no_execute_code_without_context_allows_finish(self):
        loop, ctrl = _make_loop(mode="tool_calling", context="")
        loop.start("hello")
        data = _llm_response(content="Hi there!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_execute_code_called_then_ok_allows_finish(self):
        loop, ctrl = _make_loop(mode="tool_calling", context="Box 10x10x10")
        loop.start("make a box")
        tc = _tool_call()
        ctrl.session.add_assistant_message({
            "role": "assistant", "content": "", "tool_calls": [tc],
        })
        ex = _tool_execution(result="OK: Code executed. CAD quality check PASSED.")
        loop.handle_tool_results([ex])
        data = _llm_response(content="All done.", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.FINISH
        assert action.success is True

    def test_non_execute_code_tool_does_not_set_flag(self):
        loop, _ = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            tool_name="undo_last", result="SUCCESS: Snapshot restored."
        )
        loop.handle_tool_results([ex])
        assert loop._execute_code_called is False


# ===========================================================================
# Progressive context injection (text-to-cad inspired)
# ===========================================================================

class TestProgressiveContextInjection:
    """Test that _build_context() injects phase-aware reference snippets."""

    def test_first_iteration_includes_checklist(self):
        """Iteration 0 should include the first-execution checklist."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 0
        ctx = loop._build_context()
        assert "FIRST EXECUTION CHECKLIST" in ctx
        assert "cylinder(H, R)" in ctx

    def test_second_iteration_excludes_checklist(self):
        """Iteration 1+ should NOT include the first-execution checklist."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 1
        ctx = loop._build_context()
        assert "FIRST EXECUTION CHECKLIST" not in ctx

    def test_quality_failure_includes_repair_guidance(self):
        """When quality fails, context should include repair guidance."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 2
        loop._last_quality_passed = False
        ctx = loop._build_context()
        assert "QUALITY REPAIR GUIDANCE" in ctx
        assert "MULTI_SOLID" in ctx

    def test_quality_pass_no_repair_guidance(self):
        """When quality passes, no repair guidance should be injected."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 2
        loop._last_quality_passed = True
        ctx = loop._build_context()
        assert "QUALITY REPAIR GUIDANCE" not in ctx

    def test_repeated_errors_includes_repair_loop(self):
        """After 2+ errors, context should include repair loop strategy."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 3
        loop._recent_errors = ["err1", "err2", "err3"]
        ctx = loop._build_context()
        assert "REPAIR STRATEGY" in ctx

    def test_single_error_no_repair_loop(self):
        """With 0-1 errors, no repair loop should be injected."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 2
        loop._recent_errors = ["err1"]
        ctx = loop._build_context()
        assert "REPAIR STRATEGY" not in ctx

    def test_iteration_urgency_near_limit(self):
        """Near max iterations, urgency message should appear."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = _config.MAX_ITERATIONS - 1
        ctx = loop._build_context()
        assert "WARNING" in ctx
        assert "iteration limit" in ctx

    def test_iteration_urgency_not_early(self):
        """Early iterations should not show urgency."""
        loop, _ = _make_loop(context="some doc")
        loop._iteration = 1
        ctx = loop._build_context()
        assert "iteration limit" not in ctx

    def test_doc_context_included(self):
        """Document context should always be included when present."""
        loop, _ = _make_loop(context="Box 10x10x10")
        loop._iteration = 5
        ctx = loop._build_context()
        assert "Box 10x10x10" in ctx
        assert "CURRENT DOCUMENT CONTEXT" in ctx

    def test_empty_context_no_doc_section(self):
        """Empty document context should not produce a section."""
        loop, _ = _make_loop(context="")
        loop._iteration = 0
        ctx = loop._build_context()
        assert "CURRENT DOCUMENT CONTEXT" not in ctx


# ===========================================================================
# Quality gate fix suggestion (text-to-cad classified repair)
# ===========================================================================

class TestQualityGateFixSuggestion:
    """Test that _quality_gate_block() injects targeted fix suggestions."""

    def test_no_solid_injects_fix(self):
        """Quality gate should suggest fix for NO_SOLID failure."""
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Quality check FAILED: No solid components.",
            is_error=True,
        )
        loop.handle_tool_results([ex])
        assert loop._last_quality_passed is False

        data = _llm_response(content="Done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.CALL_LLM

        # Check the injected message contains the fix
        user_msgs = [m for m in ctrl.session.get_messages() if m["role"] == "user"]
        feedback = [m for m in user_msgs if "QUALITY GATE" in m["content"]]
        assert len(feedback) == 1
        assert "Fix:" in feedback[0]["content"]

    def test_generic_failure_no_known_code(self):
        """Unknown failure codes should still block but with generic message."""
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Quality check FAILED: Unknown issue XYZ.",
            is_error=True,
        )
        loop.handle_tool_results([ex])
        assert loop._last_quality_passed is False

        data = _llm_response(content="Done!", finish_reason="stop")
        action = loop.handle_stream_done(data, True)
        assert action.kind == LoopActionKind.CALL_LLM

        user_msgs = [m for m in ctrl.session.get_messages() if m["role"] == "user"]
        feedback = [m for m in user_msgs if "QUALITY GATE" in m["content"]]
        assert len(feedback) == 1
        # No "Fix:" prefix since code is unknown
        assert "Fix:" not in feedback[0]["content"]
        assert "execute_code" in feedback[0]["content"]

    def test_get_quality_fix_suggestion_multi_solid(self):
        """MULTI_SOLID should return overlap guidance."""
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()
        ex = _tool_execution(
            result="FAIL: Quality check FAILED: Document has 2 separate solids.",
            is_error=True,
        )
        loop.handle_tool_results([ex])
        hint = loop._get_quality_fix_suggestion()
        assert "overlap" in hint.lower()

    def test_get_quality_fix_suggestion_no_match(self):
        """Unknown summary should return empty string."""
        loop, _ = _make_loop()
        loop._last_quality_summary = "Something completely unknown"
        hint = loop._get_quality_fix_suggestion()
        assert hint == ""


# ===========================================================================
# Error dedup with repair hints (text-to-cad classified repair)
# ===========================================================================

class TestErrorDedupWithRepairHint:
    """Test that repeated errors inject classified repair hints."""

    def test_repeated_error_includes_repair_hint(self):
        """Second occurrence of same error should include repair hint."""
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()

        # First error — no warning
        ex1 = _tool_execution(
            result="NameError: name 'cq' is not defined",
            is_error=True,
        )
        loop.handle_tool_results([ex1])

        # Second error — same error, should include warning + hint
        ctrl.session.add_assistant_message({
            "role": "assistant", "content": "", "tool_calls": [_tool_call()],
        })
        loop.prepare_llm_call()
        ex2 = _tool_execution(
            result="NameError: name 'cq' is not defined",
            is_error=True,
        )
        loop.handle_tool_results([ex2])

        # Check the last user/tool message includes WARNING
        tool_results = [m for m in ctrl.session.get_messages() if m["role"] == "tool"]
        assert len(tool_results) >= 1
        last_result = tool_results[-1]["content"]
        assert "WARNING: REPEATED ERROR" in last_result

    def test_different_errors_no_warning(self):
        """Different errors should not trigger dedup warning."""
        loop, ctrl = _make_loop(mode="tool_calling")
        loop.prepare_llm_call()

        ex1 = _tool_execution(result="NameError: x not defined", is_error=True)
        loop.handle_tool_results([ex1])

        ctrl.session.add_assistant_message({
            "role": "assistant", "content": "", "tool_calls": [_tool_call()],
        })
        loop.prepare_llm_call()
        ex2 = _tool_execution(result="TypeError: bad arg", is_error=True)
        loop.handle_tool_results([ex2])

        tool_results = [m for m in ctrl.session.get_messages() if m["role"] == "tool"]
        assert len(tool_results) >= 1
        last_result = tool_results[-1]["content"]
        assert "WARNING: REPEATED ERROR" not in last_result
