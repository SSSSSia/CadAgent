"""Agent loop state machine — pure-logic routing extracted from UI.

Owns: iteration count, mode, stop flag, timing.
References: AgentController (session + result).
Does NOT own: threads, UI, FreeCAD.

Usage:
    loop = AgentLoop(controller, context, last_mode)
    action = loop.start(user_text)
    # caller interprets action, starts LLM thread
    action = loop.handle_stream_done(llm_data, has_streaming_text)
    # caller interprets action...
    action = loop.handle_tool_results(executions)
    # caller interprets action...
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from agent.react_parser import parse_react_tool_calls
from agent.tool_defs import TOOL_DEFINITIONS
from agent.prompts import AGENT_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from core.token_budget import trim_messages, token_summary
import core.config as _config
from core.logger import log_info


class LoopActionKind(Enum):
    CALL_LLM = "call_llm"
    EXECUTE_TOOLS = "execute_tools"
    FINISH = "finish"


@dataclass
class LoopAction:
    kind: LoopActionKind

    # CALL_LLM
    messages: list[dict] | None = None
    tools: list[dict] | None = None
    iteration: int = 0
    token_used: int = 0
    token_budget: int = 0
    token_trimmed: bool = False

    # EXECUTE_TOOLS
    tool_calls: list[dict] = field(default_factory=list)

    # FINISH
    success: bool = False
    summary: str = ""
    from_stream: bool = False
    iterations: int = 0

    # Display hints
    status_state: str = ""
    system_message: str = ""


@dataclass
class ToolExecution:
    tool_name: str
    tool_args: str
    tool_id: str
    description: str
    result: str
    is_error: bool


class AgentLoop:
    """Pure-logic agent loop state machine.

    Returns LoopAction instructions for the caller (UI layer) to interpret.
    No Qt or FreeCAD dependencies.
    """

    def __init__(self, controller, context: str, last_mode: str = "auto"):
        self._controller = controller
        self._context = context
        self._mode: str = last_mode or "auto"
        self._iteration: int = 0
        self._stopped: bool = False
        self._start_time: float = time.time()
        self._recent_errors: list[str] = []

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def start_time(self) -> float:
        return self._start_time

    def request_stop(self) -> None:
        self._stopped = True

    def start(self, user_text: str) -> LoopAction:
        ctx = self._build_context()
        system_content = AGENT_SYSTEM_PROMPT.replace("{context}", ctx)
        self._controller.session.set_system_prompt(system_content)
        self._controller.session.add_user_message(user_text)
        log_info(f"Agent loop started: mode=auto, context={len(self._context)} chars")
        return self.prepare_llm_call()

    def _build_context(self) -> str:
        """Build full context string including parameters and document state."""
        param_ctx = ""
        try:
            from agent.tools import get_param_store
            params = get_param_store()
        except ImportError:
            params = {}
        if params:
            lines = ["CURRENT DESIGN PARAMETERS:"]
            for name, value in sorted(params.items()):
                lines.append(f"  {name} = {value}")
            param_ctx = "\n" + "\n".join(lines)

        doc_ctx = f"\nCURRENT DOCUMENT CONTEXT:\n{self._context}" if self._context else ""
        return param_ctx + doc_ctx

    def prepare_llm_call(self) -> LoopAction:
        if self._stopped:
            return LoopAction(
                kind=LoopActionKind.FINISH,
                success=False,
                summary="Agent stopped.",
                iterations=self._iteration,
            )

        if self._iteration >= _config.MAX_ITERATIONS:
            return LoopAction(
                kind=LoopActionKind.FINISH,
                success=False,
                summary="Max iterations reached.",
                iterations=self._iteration,
            )

        self._iteration += 1

        tools = TOOL_DEFINITIONS if self._mode != "react" else None

        original_count = len(self._controller.session.get_messages())
        messages = trim_messages(self._controller.session.get_messages())
        used, budget = token_summary(messages)
        trimmed = len(messages) < original_count

        log_info(
            f"LLM call iteration {self._iteration}/{_config.MAX_ITERATIONS}, "
            f"mode={self._mode}, {len(messages)} messages"
        )

        return LoopAction(
            kind=LoopActionKind.CALL_LLM,
            messages=messages,
            tools=tools,
            iteration=self._iteration,
            token_used=used,
            token_budget=budget,
            token_trimmed=trimmed,
            status_state="thinking",
        )

    def handle_stream_done(self, data: dict, has_streaming_text: bool) -> LoopAction:
        choice = data["choices"][0]
        assistant_msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")
        content = assistant_msg.get("content", "")
        has_tools = bool(assistant_msg.get("tool_calls"))
        log_info(
            f"LLM response: finish_reason={finish_reason}, "
            f"has_tool_calls={has_tools}, content_len={len(content)}"
        )

        self._controller.session.add_assistant_message(assistant_msg)

        # --- Mode auto-detection (first iteration) ---
        if self._mode == "auto" and finish_reason == "stop" and self._iteration == 1:
            parsed = parse_react_tool_calls(content)
            if parsed:
                self._mode = "react"
                self._controller.session.last_mode = "react"
                ctx = self._build_context()
                react_prompt = REACT_SYSTEM_PROMPT.replace("{context}", ctx)
                self._controller.session.set_system_prompt(react_prompt)
                return LoopAction(
                    kind=LoopActionKind.EXECUTE_TOOLS,
                    tool_calls=parsed,
                    system_message="Model does not support tool calling, switched to ReAct mode.",
                )
            else:
                self._mode = "tool_calling"
                self._controller.session.last_mode = "tool_calling"
                return LoopAction(
                    kind=LoopActionKind.FINISH,
                    success=True,
                    summary=content,
                    from_stream=has_streaming_text,
                    iterations=self._iteration,
                )

        # --- Tool calling mode (native API) ---
        if finish_reason == "tool_calls":
            self._mode = "tool_calling"
            self._controller.session.last_mode = "tool_calling"
            return LoopAction(
                kind=LoopActionKind.EXECUTE_TOOLS,
                tool_calls=assistant_msg.get("tool_calls", []),
            )

        # --- ReAct mode: check for <tool> tags ---
        if self._mode == "react":
            parsed = parse_react_tool_calls(content)
            if parsed:
                return LoopAction(
                    kind=LoopActionKind.EXECUTE_TOOLS,
                    tool_calls=parsed,
                )
            return LoopAction(
                kind=LoopActionKind.FINISH,
                success=True,
                summary=content,
                iterations=self._iteration,
            )

        # --- finish_reason == "stop" with no tools — agent done ---
        return LoopAction(
            kind=LoopActionKind.FINISH,
            success=True,
            summary=content,
            from_stream=has_streaming_text,
            iterations=self._iteration,
        )

    def handle_tool_results(self, executions: list[ToolExecution]) -> LoopAction:
        for ex in executions:
            result_text = ex.result

            # Error dedup: warn if same error keeps recurring
            if ex.is_error:
                err_sig = ex.result[:60]
                if any(err_sig[:40] in prev for prev in self._recent_errors):
                    result_text = (
                        ex.result
                        + "\n\nWARNING: REPEATED ERROR. "
                        "You MUST change your approach. Do NOT resubmit similar code."
                    )
                self._recent_errors.append(err_sig)
                if len(self._recent_errors) > 3:
                    self._recent_errors.pop(0)

            if self._mode == "react":
                self._controller.session.add_user_message(
                    f"[Tool Result for {ex.tool_name}]:\n{result_text}"
                )
            else:
                self._controller.session.add_tool_result(ex.tool_id, result_text)

            if ex.is_error:
                self._controller.result.errors.append(
                    f"[Iter {self._iteration}] {ex.tool_name}: {ex.result[:100]}"
                )
            self._controller.result.tool_calls_log.append({
                "iteration": self._iteration,
                "name": ex.tool_name,
                "description": ex.description,
                "result_preview": ex.result[:200],
                "is_error": ex.is_error,
            })

        return self.prepare_llm_call()

    def handle_error(self, error_msg: str) -> LoopAction:
        return LoopAction(
            kind=LoopActionKind.FINISH,
            success=False,
            summary=f"API error: {error_msg}",
            iterations=self._iteration,
        )
