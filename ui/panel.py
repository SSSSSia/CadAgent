"""
AgentPanel — chat-style dock panel for CadAgent.

Thread safety model:
  - LLM API calls run in a background QThread (slow, network I/O)
  - Tool execution (exec(), FreeCAD API) runs in the main thread
  - State machine alternates between: call_llm (background) -> execute_tools (main) -> repeat
"""
from __future__ import annotations

import json

import FreeCAD
import FreeCADGui as Gui

from PySide6 import QtCore, QtWidgets

from agent.controller import AgentController
from core.session import ChatSession
from core.doc_analyzer import analyze_document
from core.token_budget import trim_messages, token_summary
from core.session_store import SessionStore
from agent.prompts import AGENT_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from agent.react_parser import parse_react_tool_calls
from agent.tools import dispatch_tool
from agent.tool_defs import TOOL_DEFINITIONS
from core.config import MAX_ITERATIONS
from core.llm_client import call_llm_streaming
from core.logger import log_info, log_warning, log_error

from ui.panel_ui import _PanelUIMixin
from ui.panel_stream import _PanelStreamMixin
from ui.panel_session import _PanelSessionMixin


class _LlmCallThread(QtCore.QThread):
    """Background thread: streams LLM API response, emits incremental chunks."""
    chunkReady = QtCore.Signal(str)
    streamDone = QtCore.Signal(dict)
    error = QtCore.Signal(str)

    def __init__(self, messages, tools, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.tools = tools

    def run(self):
        try:
            content = ""
            tc_map = {}  # index -> {id, function: {name, arguments}}
            finish_reason = None

            for chunk in call_llm_streaming(self.messages, tools=self.tools):
                if self.isInterruptionRequested():
                    break

                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr

                # Text streaming
                c = delta.get("content")
                if c:
                    content += c
                    self.chunkReady.emit(c)

                # Tool calls accumulation
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_map:
                        tc_map[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tc_map[idx]
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        entry["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["function"]["arguments"] += fn["arguments"]

            # Assemble final message (same format as non-streaming response)
            tool_calls = [tc_map[i] for i in sorted(tc_map)] if tc_map else []
            msg: dict = {"content": content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if finish_reason is None:
                finish_reason = "tool_calls" if tool_calls else "stop"

            self.streamDone.emit({
                "choices": [{"message": msg, "finish_reason": finish_reason}]
            })

        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class AgentPanel(QtWidgets.QDockWidget, _PanelUIMixin, _PanelStreamMixin, _PanelSessionMixin):
    """Chat-style dock panel for CadAgent."""

    def __init__(self, parent=None):
        super().__init__("CadAgent", parent)
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._controller = None
        self._iteration = 0
        self._stopped = False
        self._llm_thread = None
        self._streaming_text = ""
        self._stream_replace_start = 0
        self._stream_timer = None
        self._store = SessionStore()
        self._setup_ui()

    # ---- State machine: send -> call LLM (bg) -> execute tools (main) -> repeat ----

    def _set_running(self, running):
        self.btn_send.setEnabled(not running)
        self.text_input.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.session_combo.setEnabled(not running)
        if not running:
            self.text_input.setFocus()
            self._update_undo_button_state()

    def _on_send(self):
        text = self.text_input.text().strip()
        if not text:
            return

        self._append_user_msg(text)
        self.text_input.clear()
        self._set_running(True)

        # Gather document context (main thread — safe)
        context = ""
        doc = FreeCAD.ActiveDocument
        if doc:
            try:
                context = analyze_document(doc)
            except Exception as e:
                log_warning(f"Document analysis failed: {e}")
                context = ""

        # Initialize controller
        self._controller = AgentController(self._session)
        self._iteration = 0
        self._stopped = False
        self._mode = "auto"  # "auto" | "tool_calling" | "react"
        self._context = context

        # Add user message to session
        self._controller.session.add_user_message(text)

        # Set system prompt — start with tool calling version
        system_content = AGENT_SYSTEM_PROMPT.format(
            context=f"\nCURRENT DOCUMENT CONTEXT:\n{context}" if context else ""
        )
        self._controller.session.set_system_prompt(system_content)

        self._store.save(self._session)

        self.status_label.setText("Agent thinking...")
        self.status_label.setStyleSheet("color:#d4a017; font-size:11px;")

        # Show token usage after adding user message
        used, budget = token_summary(self._controller.session.get_messages())
        self._update_token_label(used, budget)

        # Start first LLM call
        log_info(f"Agent loop started: mode=auto, context={len(context)} chars")
        self._call_llm()

    def _update_token_label(self, used: int, budget: int, trimmed: bool = False):
        """Update the token budget status label with color coding."""
        ratio = used / budget if budget else 0
        if ratio > 0.9:
            color = "#d32f2f"
        elif ratio > 0.7:
            color = "#d4a017"
        else:
            color = "#888"
        tag = " [trimmed]" if trimmed else ""
        self.token_label.setText(f"Tokens: {used} / {budget}{tag}")
        self.token_label.setStyleSheet(f"color:{color}; font-size:10px;")

    def _call_llm(self):
        """Kick off a background streaming LLM API call."""
        if self._stopped or self._iteration >= MAX_ITERATIONS:
            self._finish("Agent stopped." if self._stopped else "Max iterations reached.", False)
            return

        self._iteration += 1

        # In react mode, don't send tools parameter (model doesn't support it)
        tools = TOOL_DEFINITIONS if self._mode != "react" else None

        # Start streaming bubble (skip for react — needs full text before display)
        if self._mode != "react":
            self._start_streaming_bubble()

        original_count = len(self._controller.session.get_messages())
        messages = trim_messages(self._controller.session.get_messages())
        used, budget = token_summary(messages)
        self._update_token_label(used, budget, trimmed=(len(messages) < original_count))
        log_info(f"LLM call iteration {self._iteration}/{MAX_ITERATIONS}, mode={self._mode}, {len(messages)} messages")
        self._llm_thread = _LlmCallThread(messages, tools)
        self._llm_thread.chunkReady.connect(self._on_stream_chunk)
        self._llm_thread.streamDone.connect(self._on_stream_done)
        self._llm_thread.error.connect(self._on_llm_error)
        self._llm_thread.start()

    def _on_stream_done(self, data):
        """Streaming complete — finalize display, then route response."""
        try:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content", "")

            # Finalize or remove streaming bubble based on content
            if self._streaming_text and self._streaming_text.strip():
                self._finalize_streaming_bubble()
            else:
                self._remove_streaming_bubble()

            self._handle_llm_response(data, _streamed=bool(self._streaming_text))
        except Exception as e:
            log_error(f"Error in stream handler: {e}")
            self._remove_streaming_bubble()
            self._finish(f"Internal error: {e}", False)

    def _handle_llm_response(self, data, _streamed=False):
        """Route LLM response to the appropriate handler."""
        choice = data["choices"][0]
        assistant_msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")
        content = assistant_msg.get("content", "")
        has_tools = bool(assistant_msg.get("tool_calls"))
        log_info(f"LLM response: finish_reason={finish_reason}, has_tool_calls={has_tools}, content_len={len(content)}")

        self._controller.session.add_assistant_message(assistant_msg)

        # --- Mode auto-detection (first iteration) ---
        if self._mode == "auto" and finish_reason == "stop" and self._iteration == 1:
            parsed = parse_react_tool_calls(content)
            if parsed:
                # Model doesn't support tool calling, switch to ReAct
                self._mode = "react"
                self._append_system_msg("Model does not support tool calling, switched to ReAct mode.")
                react_prompt = REACT_SYSTEM_PROMPT.format(
                    context=f"\nCURRENT DOCUMENT CONTEXT:\n{self._context}" if self._context else ""
                )
                self._controller.session.set_system_prompt(react_prompt)
                self._execute_tools(parsed)
                return
            else:
                # Model returned a final answer directly
                self._mode = "tool_calling"
                self._finish(content, True, _from_stream=_streamed)
                return

        # --- Tool calling mode (native API) ---
        if finish_reason == "tool_calls":
            self._mode = "tool_calling"
            tool_calls = assistant_msg.get("tool_calls", [])
            self._execute_tools(tool_calls)
            return

        # --- ReAct mode: check for <tool> tags in text ---
        if self._mode == "react":
            parsed = parse_react_tool_calls(content)
            if parsed:
                self._execute_tools(parsed)
                return
            self._finish(content, True)
            return

        # --- finish_reason == "stop" with no tool tags — agent done ---
        self._finish(content, True, _from_stream=_streamed)

    def _on_llm_error(self, msg):
        log_error(f"LLM API error: {msg}")
        self._remove_streaming_bubble()
        self._finish(f"API error: {msg}", False)

    def _execute_tools(self, tool_calls):
        """Execute tools in the MAIN thread (safe for FreeCAD)."""
        for tc in tool_calls:
            if self._stopped:
                break

            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", "{}")
            tool_id = tc.get("id", "")

            desc = ""
            if tool_name == "execute_code":
                try:
                    desc = json.loads(tool_args).get("description", "")
                except json.JSONDecodeError as e:
                    log_warning(f"Failed to parse tool args JSON: {e}")

            # Execute tool in main thread (FreeCAD safe)
            tool_result = dispatch_tool(tool_name, tool_args)
            is_error = tool_result.startswith("ERROR") or tool_result.startswith("FAIL")
            if is_error:
                log_error(f"Tool '{tool_name}' failed at iteration {self._iteration}: {tool_result[:300]}")

            # Update undo button state (snapshot was taken if execute_code)
            self._update_undo_button_state()

            # ReAct mode: use user message for tool results (model doesn't understand role="tool")
            if self._mode == "react":
                self._controller.session.add_user_message(
                    f"[Tool Result for {tool_name}]:\n{tool_result}"
                )
            else:
                self._controller.session.add_tool_result(tool_id, tool_result)

            self._append_tool_msg(
                self._iteration, tool_name, desc,
                tool_result[:200], is_error,
            )
            if is_error:
                self._controller.result.errors.append(
                    f"[Iter {self._iteration}] {tool_name}: {tool_result[:100]}"
                )
            self._controller.result.tool_calls_log.append({
                "iteration": self._iteration,
                "name": tool_name,
                "description": desc,
                "result_preview": tool_result[:200],
                "is_error": is_error,
            })

        # Tools done — next iteration
        self.status_label.setText(f"Agent thinking... (iteration {self._iteration + 1}/{MAX_ITERATIONS})")
        self._call_llm()

    def _finish(self, summary, success, _from_stream=False):
        """Agent loop complete — show results."""
        log_info(f"Agent finished: success={success}, iterations={self._iteration}, summary={summary[:100]}")
        if not _from_stream:
            self._append_agent_msg(summary)

        if success:
            self._controller.result.success = True
            self._controller.result.summary = summary
            self._controller.session.update_summary(summary)

            # Snapshot document state + fit view
            try:
                doc = FreeCAD.ActiveDocument
                if doc:
                    self._controller.session.update_document_state(analyze_document(doc))
            except Exception as e:
                log_warning(f"Failed to save document state: {e}")
            try:
                gui_doc = Gui.activeDocument()
                if gui_doc:
                    view = gui_doc.activeView()
                    if view:
                        view.viewIsometric()
                        view.fitAll()
            except Exception as e:
                log_warning(f"Failed to adjust 3D view: {e}")

        self._store.save(self._session)

        turns = self._controller.session.user_turn_count()
        iters = self._iteration
        if success:
            self.status_label.setText(f"Done | {iters} iterations | Turn {turns}")
            self.status_label.setStyleSheet("color:#0d904f; font-size:11px;")
        else:
            self.status_label.setText(f"Failed | {iters} iterations | Turn {turns}")
            self.status_label.setStyleSheet("color:#d32f2f; font-size:11px;")

        self._set_running(False)
        self._refresh_session_list()

    # ---- Event handlers ----

    def _on_stop(self):
        self._stopped = True
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.requestInterruption()
        self.status_label.setText("Stopping...")

    def _on_new_session(self):
        self._stopped = True
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.requestInterruption()
            self._llm_thread.quit()
            self._llm_thread.wait(1000)
        self._store.save(self._session)
        from core.snapshot import cleanup_all_snapshots
        cleanup_all_snapshots()
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._controller = None
        self.chat_display.clear()
        self._append_system_msg("New session started. Describe a part to begin.")
        self.status_label.setText("Ready")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        self._set_running(False)
        self._refresh_session_list()

    def _on_undo(self):
        """User clicked Undo — restore document from most recent snapshot."""
        from core.snapshot import restore_latest_snapshot, snapshot_count, has_snapshot

        if not has_snapshot():
            self._append_system_msg("Nothing to undo — no snapshots available.")
            return

        if self._llm_thread and self._llm_thread.isRunning():
            self._append_system_msg("Cannot undo while agent is running.")
            return

        result = restore_latest_snapshot()
        is_error = result.startswith("ERROR")

        self._append_tool_msg(
            self._iteration, "undo_last (user)", "",
            result[:200], is_error,
        )

        if not is_error:
            self._append_system_msg(f"Undo successful. {snapshot_count()} snapshot(s) remaining.")
        else:
            self._append_system_msg(f"Undo failed: {result}")

        self._update_undo_button_state()

    def _update_undo_button_state(self):
        """Enable/disable undo button based on snapshot availability."""
        from core.snapshot import has_snapshot
        self.btn_undo.setEnabled(has_snapshot())

    def closeEvent(self, event):
        self._store.save_current_on_close(self._session)
        super().closeEvent(event)
