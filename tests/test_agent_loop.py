"""Tests for agent/loop.py — AgentLoop state machine (pure logic, no Qt/FreeCAD)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.session import ChatSession
from agent.controller import AgentController
from agent.loop import AgentLoop, LoopAction, LoopActionKind, ToolExecution


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
