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
from agent.references import (
    REF_FIRST_ITERATION, REF_QUALITY_FAILURE, REF_REPAIR_LOOP,
    REF_ITERATION_URGENCY, REF_QUALITY_PASSED_WARN, QUALITY_FIX_MAP,
)
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
        self._execute_code_called: bool = False
        self._last_quality_passed: bool | None = None
        self._last_quality_summary: str = ""

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
        """Build full context string including parameters, document state,
        and phase-aware reference snippets injected based on agent state.

        Inspired by text-to-cad's progressive documentation pattern:
        instead of sending the full reference every turn, inject only
        what's relevant for the current phase. This saves tokens (24K budget)
        and focuses the LLM's attention.
        """
        parts: list[str] = []

        # --- Always: parameters ---
        try:
            from agent.tools import get_param_store
            params = get_param_store()
        except ImportError:
            params = {}
        if params:
            lines = ["CURRENT DESIGN PARAMETERS:"]
            for name, value in sorted(params.items()):
                lines.append(f"  {name} = {value}")
            parts.append("\n" + "\n".join(lines))

        # --- Always: document context ---
        if self._context:
            parts.append(f"\nCURRENT DOCUMENT CONTEXT:\n{self._context}")

        # --- Phase-aware: first iteration checklist ---
        if self._iteration == 0:
            parts.append(REF_FIRST_ITERATION)

        # --- Phase-aware: quality failure guidance ---
        if self._last_quality_passed is False:
            parts.append(REF_QUALITY_FAILURE)

        # --- Phase-aware: repeated errors ---
        if len(self._recent_errors) >= 2:
            parts.append(REF_REPAIR_LOOP)

        # --- Phase-aware: quality passed with warnings ---
        if self._last_quality_passed is True and self._last_quality_summary:
            if "warn" in self._last_quality_summary.lower():
                parts.append(REF_QUALITY_PASSED_WARN)

        # --- Phase-aware: approaching iteration limit ---
        if self._iteration >= _config.MAX_ITERATIONS - 2 and self._iteration > 0:
            parts.append(
                REF_ITERATION_URGENCY.format(
                    max_iter=_config.MAX_ITERATIONS,
                    current=self._iteration,
                )
            )

        return "".join(parts)

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
            allowed, reason = self._check_quality_gate()
            if not allowed:
                return self._quality_gate_block(reason)
            return LoopAction(
                kind=LoopActionKind.FINISH,
                success=True,
                summary=content,
                iterations=self._iteration,
            )

        # --- finish_reason == "stop" with no tools — agent done ---
        allowed, reason = self._check_quality_gate()
        if not allowed:
            return self._quality_gate_block(reason)
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
                err_sig = ex.result[:120]
                is_repeated = any(
                    err_sig[:80] == prev[:80] for prev in self._recent_errors
                )
                if is_repeated:
                    # Inject targeted repair hint from error_hint() if available
                    repair_hint = self._get_error_repair_hint(ex)
                    if repair_hint:
                        result_text = (
                            ex.result
                            + "\n\nWARNING: REPEATED ERROR.\n"
                            + repair_hint
                            + "\nYou MUST change your approach. "
                            "Do NOT resubmit similar code."
                        )
                    else:
                        result_text = (
                            ex.result
                            + "\n\nWARNING: REPEATED ERROR. "
                            "You MUST change your approach. "
                            "Do NOT resubmit similar code."
                        )
                self._recent_errors.append(err_sig)
                if len(self._recent_errors) > 5:
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

            # Phase 1.3: Track quality state from execute_code results
            if ex.tool_name == "execute_code":
                self._execute_code_called = True
                first_line = ex.result.split("\n", 1)[0]
                if ex.result.startswith("OK:"):
                    self._last_quality_passed = True
                elif ex.result.startswith("FAIL:") or ex.result.startswith("ERROR:"):
                    self._last_quality_passed = False
                else:
                    self._last_quality_passed = False
                self._last_quality_summary = first_line
                self._controller.result.last_quality_passed = self._last_quality_passed
                self._controller.result.last_quality_summary = self._last_quality_summary

        return self.prepare_llm_call()

    def _check_quality_gate(self) -> tuple[bool, str]:
        """Check whether the quality gate allows FINISH with success=True.

        Returns (allowed, reason). allowed=True if gate passes or is not
        applicable (no execute_code has run yet AND no document context).
        """
        if not self._execute_code_called and self._context:
            return False, (
                "No execute_code was called. When there is an active document, "
                "you must use execute_code to create or modify geometry before finishing."
            )
        if self._last_quality_passed is None or self._last_quality_passed:
            return True, ""
        return False, self._last_quality_summary

    def _quality_gate_block(self, reason: str) -> LoopAction:
        """Block FINISH, inject quality feedback with targeted fix suggestion.

        Inspired by text-to-cad's classified repair loop: instead of a generic
        "fix geometry" message, extract the specific QualityIssue code from the
        failure reason and inject a targeted repair instruction from
        QUALITY_FIX_MAP.
        """
        fix_hint = self._get_quality_fix_suggestion()
        if fix_hint:
            msg = (
                f"CAD QUALITY GATE: {reason}\n"
                f"Fix: {fix_hint}\n\n"
                "You MUST use execute_code to fix the issue before finishing. "
                "Do NOT respond with a summary — write code to fix the geometry."
            )
        else:
            msg = (
                f"CAD QUALITY GATE: {reason}\n\n"
                "You MUST use execute_code to fix the issue before finishing. "
                "Do NOT respond with a summary — write code to create or fix the geometry."
            )
        self._controller.session.add_user_message(msg)
        log_info(f"Quality gate blocked FINISH: {reason[:100]}")
        return self.prepare_llm_call()

    def _get_quality_fix_suggestion(self) -> str:
        """Extract targeted fix suggestion from the last quality summary.

        Maps known QualityIssue codes (e.g., NO_SOLID, MULTI_SOLID) to
        concrete repair instructions from QUALITY_FIX_MAP.

        Matches both the exact code (NO_SOLID) and natural language variants
        (no solid, separate solids, compound shape, invalid shape, etc.)
        that appear in quality report messages.
        """
        summary = self._last_quality_summary
        if not summary:
            return ""

        # Exact code match first (e.g., "NO_SOLID" in quality JSON)
        for code, hint in QUALITY_FIX_MAP.items():
            if code in summary:
                return hint

        # Natural language fallback — match key phrases from quality messages
        summary_lower = summary.lower()
        nl_map = {
            "no solid": "NO_SOLID",
            "separate solid": "MULTI_SOLID",
            "multiple object": "MULTIPLE_OBJECTS",
            "compound shape": "COMPOUND_SHAPE",
            "invalid shape": "INVALID_SHAPE",
            "negative volume": "NEGATIVE_VOLUME",
            "dimension": "DIMENSION_SUSPICIOUS",
            "no active document": "NO_DOCUMENT",
        }
        for phrase, code in nl_map.items():
            if phrase in summary_lower and code in QUALITY_FIX_MAP:
                return QUALITY_FIX_MAP[code]

        return ""

    def _get_error_repair_hint(self, ex: ToolExecution) -> str:
        """Extract a targeted repair hint for a repeated tool execution error.

        Inspired by text-to-cad's classified repair loop. Uses error_hint()
        from code_fixes.py to classify the error and return a specific fix
        instruction. This runs in-process (no FreeCAD import needed) since
        error_hint() only does regex/string matching on the error text.

        Falls back to generic guidance if error_hint() returns nothing useful.
        """
        try:
            from agent.code_fixes import error_hint

            # Build a lightweight exception object from the error text
            # error_hint() matches on exception type name and message string
            err_text = ex.result
            # Try to extract exception type from common error prefixes
            # e.g., "NameError: name 'x' is not defined"
            exc_type = None
            exc_msg = err_text
            for known_type in ("NameError", "AttributeError", "TypeError",
                               "ValueError", "RuntimeError", "KeyError",
                               "IndexError", "ImportError"):
                if err_text.startswith(known_type):
                    exc_type = known_type
                    # Extract message after "TypeName: "
                    if ":" in err_text:
                        exc_msg = err_text.split(":", 1)[1].strip()
                    break

            if exc_type:
                # Create a minimal exception-like object for error_hint()
                class _FakeExc(Exception):
                    def __init__(self):
                        self.__class__.__name__ = exc_type
                        Exception.__init__(self, exc_msg)

                hint_text, _ = error_hint(_FakeExc(), ex.description or "")
                if hint_text:
                    return f"Repair hint: {hint_text}"
        except Exception:
            pass  # Non-critical — fall back to generic guidance

        # Generic fallback for repeated errors
        return ("Repair hint: Change ONE thing at a time — overlap distance, "
                "boolean order, or construction method. If stuck, use "
                "undo_last and try a different approach.")

    def handle_error(self, error_msg: str) -> LoopAction:
        return LoopAction(
            kind=LoopActionKind.FINISH,
            success=False,
            summary=f"API error: {error_msg}",
            iterations=self._iteration,
        )
