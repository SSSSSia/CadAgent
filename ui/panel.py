"""
AgentPanel — chat-style dock panel for CadAgent.

Thread safety model:
  - LLM API calls run in a background QThread (slow, network I/O)
  - Tool execution (exec(), FreeCAD API) runs in the main thread
  - State machine alternates between: call_llm (background) -> execute_tools (main) -> repeat
"""
from __future__ import annotations

import json
import os
import time

import FreeCAD
import FreeCADGui as Gui

from PySide6 import QtCore, QtWidgets

from agent.controller import AgentController
from agent.loop import AgentLoop, LoopAction, LoopActionKind, ToolExecution
from core.session import ChatSession
from core.doc_analyzer import analyze_document
from core.token_budget import token_summary
from core.session_store import SessionStore
from agent.tools import dispatch_tool
import core.config as _config
from core.llm_client import call_llm_streaming
from core.logger import log_info, log_warning, log_error

from ui.panel_ui import _PanelUIMixin
from ui.panel_stream import _PanelStreamMixin
from ui.panel_session import _PanelSessionMixin
from ui.panel_status import _PanelStatusMixin


class _LlmCallThread(QtCore.QThread):
    """Background thread: streams LLM API response, emits incremental chunks."""
    chunkReady = QtCore.Signal(str)
    reasoningReady = QtCore.Signal(str)
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

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                fr = choice.get("finish_reason")
                if fr:
                    finish_reason = fr

                # Text streaming
                c = delta.get("content")
                if c:
                    content += c
                    self.chunkReady.emit(c)

                # Reasoning content — disabled (not shown in UI)
                # rc = delta.get("reasoning_content")
                # if rc:
                #     self.reasoningReady.emit(rc)

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

            # Validate tool_calls arguments — truncated SSE streams leave
            # incomplete JSON that would crash in dispatch_tool().
            for tc in tool_calls:
                try:
                    json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    self.error.emit(
                        "Stream interrupted: incomplete tool call arguments"
                    )
                    return

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


class AgentPanel(QtWidgets.QDockWidget, _PanelUIMixin, _PanelStreamMixin, _PanelSessionMixin, _PanelStatusMixin):
    """Chat-style dock panel for CadAgent."""

    def __init__(self, parent=None):
        super().__init__("CadAgent", parent)
        from agent.tools import clear_persistent_vars
        clear_persistent_vars()
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._controller = None
        self._loop: AgentLoop | None = None
        self._mode = "auto"
        self._llm_thread = None
        self._streaming_text = ""
        self._stream_replace_start = 0
        self._stream_timer = None
        self._reasoning_text = ""
        self._theme_colors = None
        self._store = SessionStore()
        self._setup_ui()

    # ---- Theme ----

    def _get_colors(self):
        if self._theme_colors is None:
            from ui.theme import get_theme_colors
            self._theme_colors = get_theme_colors()
        return self._theme_colors

    def _refresh_theme(self):
        from ui.theme import get_theme_colors
        self._theme_colors = get_theme_colors()
        self._apply_dynamic_styles()

    # ---- Event filter for multi-line input ----

    def eventFilter(self, obj, event):
        if obj is self.text_input and event.type() == event.Type.KeyPress:
            if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                    return False  # default newline behavior
                self._on_send()
                return True  # event consumed
        return super().eventFilter(obj, event)

    # ---- State machine: send -> call LLM (bg) -> execute tools (main) -> repeat ----

    def _set_running(self, running):
        self.btn_send.setEnabled(not running)
        self.text_input.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_new_session.setEnabled(not running)
        self.session_combo.setEnabled(not running)
        self.btn_delete_session.setEnabled(not running and self.session_combo.currentIndex() > 0)
        if not running:
            self.text_input.setFocus()
            self._update_undo_button_state()

    def _on_send(self):
        text = self.text_input.toPlainText().strip()
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
                # If multiple documents are open, include all of them
                all_docs = FreeCAD.listDocuments()
                if len(all_docs) > 1:
                    from core.doc_analyzer import analyze_all_documents
                    context = analyze_all_documents()
                else:
                    context = analyze_document(doc)
            except Exception as e:
                log_warning(f"Document analysis failed: {e}")
                context = ""

        # Initialize controller and loop
        self._controller = AgentController(self._session)

        self._loop = AgentLoop(self._controller, context, self._session.last_mode)
        self._mode = self._session.last_mode

        self._store.save_if_not_empty(self._session)

        action = self._loop.start(text)
        self._execute_action(action)

    def _update_token_label(self, used: int, budget: int, trimmed: bool = False):
        """Update the token budget status label with color coding."""
        c = self._get_colors()
        ratio = used / budget if budget else 0
        if ratio > 0.9:
            color = c.token_danger
        elif ratio > 0.7:
            color = c.token_warn
        else:
            color = c.token_ok
        tag = " [trimmed]" if trimmed else ""
        self.token_label.setText(f"Tokens: {used} / {budget}{tag}")
        self.token_label.setStyleSheet(f"color:{color}; font-size:10px;")

    def _execute_action(self, action: LoopAction):
        if action.kind == LoopActionKind.CALL_LLM:
            self._start_llm_call(action)
        elif action.kind == LoopActionKind.EXECUTE_TOOLS:
            if action.system_message:
                self._append_system_msg(action.system_message)
            self._mode = self._loop.mode
            self._run_tool_calls(action)
        elif action.kind == LoopActionKind.FINISH:
            self._finish_from_action(action)

    def _start_llm_call(self, action: LoopAction):
        """Kick off a background streaming LLM API call."""
        self._status_set(action.status_state)
        self._mode = self._loop.mode

        # Start streaming bubble (skip for react — needs full text before display)
        if self._mode != "react":
            self._start_streaming_bubble()

        self._update_token_label(action.token_used, action.token_budget, action.token_trimmed)
        self._llm_thread = _LlmCallThread(action.messages, action.tools)
        self._llm_thread.chunkReady.connect(self._on_stream_chunk)
        self._llm_thread.reasoningReady.connect(self._on_reasoning_chunk)
        self._llm_thread.streamDone.connect(self._on_stream_done)
        self._llm_thread.error.connect(self._on_llm_error)
        self._llm_thread.start()

    def _on_reasoning_chunk(self, text):
        """Accumulate reasoning content from models that support it."""
        self._reasoning_text += text

    def _on_stream_done(self, data):
        """Streaming complete — finalize display, then route response."""
        if self._controller is None:
            self._remove_streaming_bubble()
            return
        try:
            choices = data.get("choices", [])
            if not choices:
                self._remove_streaming_bubble()
                self._finish_from_action(LoopAction(
                    kind=LoopActionKind.FINISH, success=False,
                    summary="API returned empty response.",
                ))
                return
            content = choices[0].get("message", {}).get("content", "")

            # Save position so reasoning can be inserted before the bubble
            bubble_start = self._stream_replace_start

            # Finalize or remove streaming bubble first
            if self._streaming_text and self._streaming_text.strip():
                self._finalize_streaming_bubble()
            else:
                self._remove_streaming_bubble()
                bubble_start = None  # no bubble to insert before

            # Reasoning block — disabled
            # self._render_reasoning_block(insert_before_pos=bubble_start)
            self._reasoning_text = ""

            has_streaming_text = bool(self._streaming_text and self._streaming_text.strip())
            action = self._loop.handle_stream_done(data, has_streaming_text)
            self._execute_action(action)
        except Exception as e:
            log_warning(f"Error in stream handler: {e}")
            self._remove_streaming_bubble()
            self._finish_from_action(LoopAction(
                kind=LoopActionKind.FINISH, success=False,
                summary=f"Internal error: {e}",
            ))

    def _on_llm_error(self, msg):
        log_warning(f"LLM API error: {msg}")
        self._remove_streaming_bubble()
        if self._controller is None:
            return
        action = self._loop.handle_error(msg)
        self._execute_action(action)

    def _run_tool_calls(self, action: LoopAction):
        """Execute tools in the MAIN thread (safe for FreeCAD)."""
        executions = []
        for tc in action.tool_calls:
            if self._loop.stopped:
                break

            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", "{}")
            tool_id = tc.get("id", "")

            self._status_set("executing_tool", tool_name)

            desc = ""
            if tool_name == "execute_code":
                try:
                    desc = json.loads(tool_args).get("description", "")
                except json.JSONDecodeError as e:
                    log_warning(f"Failed to parse tool args JSON: {e}")

            if desc:
                self._status_tool_desc = desc
                self._status_tick()

            # Execute tool in main thread (FreeCAD safe)
            tool_result = dispatch_tool(tool_name, tool_args)
            is_error = tool_result.startswith("ERROR") or tool_result.startswith("FAIL")
            if is_error:
                log_warning(f"Tool '{tool_name}' failed at iteration {self._loop.iteration}: {tool_result[:300]}")

            # Update undo button state (snapshot was taken if execute_code)
            self._update_undo_button_state()

            self._append_tool_msg(
                self._loop.iteration, tool_name, desc,
                tool_result, is_error,
            )

            executions.append(ToolExecution(
                tool_name=tool_name, tool_args=tool_args, tool_id=tool_id,
                description=desc, result=tool_result, is_error=is_error,
            ))

        # Sync parameters and persistent vars from tools to session
        try:
            from agent.tools import get_param_store, get_persistent_vars
            self._controller.session.parameters = get_param_store()
            self._controller.session.persistent_vars = get_persistent_vars()
        except Exception:
            pass

        next_action = self._loop.handle_tool_results(executions)
        self._execute_action(next_action)

    def _finish_from_action(self, action: LoopAction):
        """Agent loop complete — show results."""
        c = self._get_colors()
        log_info(f"Agent finished: success={action.success}, iterations={action.iterations}, summary={action.summary[:100]}")
        if not action.from_stream:
            self._append_agent_msg(action.summary)

        if action.success:
            self._controller.result.success = True
            self._controller.result.summary = action.summary
            self._controller.session.update_summary(action.summary)

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

        self._store.save_if_not_empty(self._session)

        self._status_timer.stop()
        total_elapsed = time.time() - self._loop.start_time if self._loop else 0
        elapsed_str = self._format_elapsed(total_elapsed)
        turns = self._controller.session.user_turn_count()
        iters = action.iterations or self._loop.iteration if self._loop else 0
        if action.success:
            self.status_label.setText(f"Done  {elapsed_str}  {iters} iters  Turn {turns}")
            self.status_label.setStyleSheet(
                f"color:{c.status_success}; font-size:11px; font-family:'Segoe UI', sans-serif;"
            )
        else:
            self.status_label.setText(f"Failed  {elapsed_str}  {iters} iters  Turn {turns}")
            self.status_label.setStyleSheet(
                f"color:{c.status_error}; font-size:11px; font-family:'Segoe UI', sans-serif;"
            )

        self._set_running(False)
        self._refresh_session_list()

    # ---- Event handlers ----

    def _on_stop(self):
        if self._loop:
            self._loop.request_stop()
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.requestInterruption()
        self._status_set("stopping")

    def _on_new_session(self):
        # Stop the running thread and disconnect signals so stale
        # streamDone / chunkReady don't hit the cleared state below.
        if self._loop:
            self._loop.request_stop()
        if self._llm_thread and self._llm_thread.isRunning():
            self._llm_thread.chunkReady.disconnect(self._on_stream_chunk)
            self._llm_thread.reasoningReady.disconnect(self._on_reasoning_chunk)
            self._llm_thread.streamDone.disconnect(self._on_stream_done)
            self._llm_thread.error.disconnect(self._on_llm_error)
            self._llm_thread.requestInterruption()
            self._llm_thread.quit()
            self._llm_thread.wait(3000)
        self._store.save_if_not_empty(self._session)
        from agent.tools import clear_persistent_vars
        clear_persistent_vars()
        from core.snapshot import cleanup_all_snapshots
        cleanup_all_snapshots()
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._controller = None
        self._loop = None
        self._streaming_text = ""
        self._stream_replace_start = 0
        self._reasoning_text = ""
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        self.chat_display.clear()
        self._append_system_msg("New session started. Describe a part to begin.")
        self._status_reset()
        self._set_running(False)
        self._refresh_session_list()

    def _on_attach_image(self):
        """Open file dialog to select an image, copy to uploads, insert reference."""
        from PySide6 import QtWidgets
        import shutil
        from datetime import datetime

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not file_path:
            return

        uploads_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "uploads"
        )
        os.makedirs(uploads_dir, exist_ok=True)

        ext = os.path.splitext(file_path)[1]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_name = f"{timestamp}{ext}"
        dest_path = os.path.join(uploads_dir, dest_name)
        shutil.copy2(file_path, dest_path)

        current_text = self.text_input.toPlainText()
        marker = f" [image: {dest_path}]"
        self.text_input.setPlainText(current_text + marker)

        self.status_label.setText(f"Attached: {dest_name}")

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
            self._loop.iteration if self._loop else 0, "undo_last (user)", "",
            result, is_error,
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

    def _on_settings(self):
        from ui.settings_dialog import SettingsDialog
        SettingsDialog(parent=self).exec()

    def closeEvent(self, event):
        self._store.save_current_on_close(self._session)
        super().closeEvent(event)
