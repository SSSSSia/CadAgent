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
import traceback

import FreeCAD
import FreeCADGui

from PySide6 import QtCore, QtWidgets

from agent.controller import AgentController
from agent.loop import AgentLoop, LoopAction, LoopActionKind, ToolExecution
from core.session import ChatSession
from core.doc_analyzer import analyze_document
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
            usage = None

            for chunk in call_llm_streaming(self.messages, tools=self.tools):
                if self.isInterruptionRequested():
                    break

                choices = chunk.get("choices", [])
                if not choices:
                    # usage-only chunks carry empty choices (include_usage)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
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
                        "Malformed tool call: incomplete JSON arguments "
                        "(stream truncated or invalid model output)"
                    )
                    return

            msg: dict = {"content": content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if finish_reason is None:
                finish_reason = "tool_calls" if tool_calls else "stop"

            # Hybrid token estimation: remember the provider-reported usage
            # so the next trim/calibration uses real numbers (S2-B4).
            if usage:
                total = (usage.get("prompt_tokens") or 0) + (
                    usage.get("completion_tokens") or 0
                )
                if total > 0:
                    try:
                        from core.token_budget import record_provider_usage
                        record_provider_usage(total, self.messages)
                    except Exception:
                        pass

            self.streamDone.emit({
                "choices": [{"message": msg, "finish_reason": finish_reason}]
            })

        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class AgentPanel(QtWidgets.QDockWidget, _PanelUIMixin, _PanelStreamMixin, _PanelSessionMixin, _PanelStatusMixin):
    """Chat-style dock panel for CadAgent."""

    def __init__(self, parent=None):
        super().__init__("CadAgent", parent)
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._sync_all_state(new_session_id=self._session.session_id)
        self._controller = None
        self._loop: AgentLoop | None = None
        self._mode = "auto"
        # True between _on_send and finish/recover — gates the steering path
        self._turn_active = False
        # True while an IME composition (preedit) is active in the input box
        self._ime_preedit = False
        # All live LLM threads. The list keeps the ONLY Python references so
        # a still-running thread is never garbage-collected (Qt fatal:
        # "Destroyed while thread is still running") — S1-D1/D2.
        self._llm_threads: list = []
        self._streaming_text = ""
        self._stream_replace_start = 0
        self._stream_timer = None
        self._theme_colors = None
        self._store = SessionStore()
        self._setup_ui()

    # ---- Theme ----

    def _get_colors(self):
        if self._theme_colors is None:
            from ui.theme import get_theme_colors
            self._theme_colors = get_theme_colors()
        return self._theme_colors

    def _reset_turn_state(self):
        """Reset per-turn loop and streaming state.

        Single source of truth (S3-D18): this block was copy-pasted in four
        places, and the missing per-turn reset on send caused the ReAct
        display wipe (S3-D6) — a stale _stream_replace_start deleted live
        chat content when the next turn finalized.
        """
        self._controller = None
        self._loop = None
        self._turn_active = False
        self._streaming_text = ""
        self._stream_replace_start = 0
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()

    # ---- Session lifecycle: unified state synchronization ----

    def _sync_all_state(self, new_session_id=None):
        """Synchronize all three state layers for a session transition.

        Clears persistent vars, param store, and snapshots in one place.
        Every lifecycle method (new, switch, delete, close) should call
        this instead of doing partial cleanup.
        """
        from agent.tools import clear_persistent_vars, set_code_history, set_param_store
        from core.snapshot import cleanup_all_snapshots, set_snapshot_session_id
        clear_persistent_vars()
        set_param_store({})
        set_code_history([])
        cleanup_all_snapshots()
        if new_session_id:
            set_snapshot_session_id(new_session_id)

    # ---- Event filter for multi-line input ----

    def eventFilter(self, obj, event):
        if obj is self.text_input:
            if event.type() == event.Type.InputMethod:
                # Track IME composition (S3-D11): Enter while a preedit is
                # active must commit the composition, not send the message.
                self._ime_preedit = bool(event.preeditString())
                return False
            if event.type() == event.Type.KeyPress:
                if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                    if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                        return False  # default newline behavior
                    if self._ime_preedit:
                        return False  # composing — let the IME handle the key
                    self._on_send()
                    return True  # event consumed
        return super().eventFilter(obj, event)

    # ---- State machine: send -> call LLM (bg) -> execute tools (main) -> repeat ----

    def _set_running(self, running):
        self.btn_send.setEnabled(not running)
        # Input stays enabled while running: typing + Enter queues a
        # steering message instead of starting a second turn (S3-D7).
        self.btn_stop.setEnabled(running)
        self.btn_new_session.setEnabled(not running)
        self.session_combo.setEnabled(not running)
        self.btn_delete_session.setEnabled(not running and self.session_combo.currentIndex() > 0)
        if running:
            # Remember focus ownership so finishing a turn never steals
            # focus from elsewhere in FreeCAD (S3-D15)
            self._had_input_focus = self.text_input.hasFocus()
        else:
            if getattr(self, "_had_input_focus", False):
                self.text_input.setFocus()
            self._update_undo_button_state()

    def _on_send(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            return

        # Steering (S3-D7): input during a running turn is queued and
        # injected at the next LLM call boundary — not a second turn.
        if self._turn_active and self._loop is not None and not self._loop.stopped:
            if self._loop.queue_steering(text):
                self._append_user_msg(text)
                self.text_input.clear()
                self._append_system_msg("Queued — sent to the model at the next step.")
                return

        # Per-turn reset FIRST — stale streaming cursor state from a previous
        # turn (ReAct mode especially) used to delete live content (S3-D6).
        self._reset_turn_state()

        self._append_user_msg(text)
        self.text_input.clear()
        self._set_running(True)

        # Everything past this point must never leave the panel stuck with
        # all controls disabled (S1-D5): no signal would ever fire to
        # restore them.
        try:
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
            self._turn_active = True
            self._execute_action(action)
        except Exception as e:
            self._recover_after_internal_error(e)

    def _recover_after_internal_error(self, exc: Exception):
        """Restore the panel after an unexpected error inside the agent turn.

        Deliberately does NOT touch the streaming bubble via stale cursor
        state (that hazard is fixed separately in S3); it only neutralizes
        the streaming state so later finalize/remove calls are inert.
        """
        log_error(
            f"Internal error in agent turn: {type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc()}"
        )
        self._turn_active = False
        self._streaming_text = ""
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        if self._controller is not None and self._loop is not None:
            try:
                self._finish_from_action(LoopAction(
                    kind=LoopActionKind.FINISH, success=False,
                    summary=f"Internal error: {type(exc).__name__}: {exc}",
                    iterations=self._loop.iteration,
                ))
                return
            except Exception:
                log_error("Recovery via _finish_from_action failed; "
                          "falling back to direct UI restore")
        try:
            self._append_system_msg(f"Internal error: {exc}")
        except Exception:
            pass
        self._set_running(False)
        try:
            self._status_reset()
        except Exception:
            pass

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
        self._update_params_label()

    def _update_params_label(self):
        """Show extracted parameters in the status bar (S7-F2).

        Params are injected into later turns' context (loop.py); making
        them visible keeps the README's parameter contract honest.
        """
        from agent.tools import get_param_store, format_params_label
        text = format_params_label(get_param_store())
        self.params_label.setText(text)
        self.params_label.setVisible(bool(text))

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
        thread = _LlmCallThread(action.messages, action.tools, parent=self)
        thread.chunkReady.connect(self._on_stream_chunk)
        thread.streamDone.connect(self._on_stream_done)
        thread.error.connect(self._on_llm_error)
        thread.finished.connect(lambda t=thread: self._forget_thread(t))
        self._llm_threads.append(thread)
        thread.start()

    # ---- LLM thread lifecycle (S1-D1/D2) ----

    def _live_threads(self) -> list:
        """Threads that are still running."""
        return [t for t in self._llm_threads if t.isRunning()]

    def _forget_thread(self, thread) -> None:
        """Drop a finished thread's reference (connected to finished)."""
        try:
            self._llm_threads.remove(thread)
        except ValueError:
            pass

    def _shutdown_threads(self, wait_ms: int) -> None:
        """Interrupt all live threads and wait (bounded) for them to end.

        A thread blocked inside urllib (up to LLM_TIMEOUT) can outlive the
        wait; it stays referenced in _llm_threads so it is never destroyed
        while running. True interruptible I/O is tracked as S3-D8.
        """
        live = self._live_threads()
        for t in live:
            t.requestInterruption()
        for t in live:
            if not t.wait(wait_ms):
                log_warning(
                    "LLM thread did not stop within "
                    f"{wait_ms}ms; it will finish in the background"
                )
        self._llm_threads = [t for t in self._llm_threads if t.isRunning()]

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

            # ReAct rounds stream raw <tool> XML as plain text — strip the
            # blocks so the bubble shows only prose (S3-D15)
            if self._streaming_text and "<tool" in self._streaming_text:
                from agent.react_parser import strip_tool_tags
                self._streaming_text = strip_tool_tags(self._streaming_text)

            # Finalize or remove streaming bubble first
            if self._streaming_text and self._streaming_text.strip():
                self._finalize_streaming_bubble()
            else:
                self._remove_streaming_bubble()

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
        try:
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

            # Sync parameters, code history and persistent vars to session
            try:
                from agent.tools import (
                    get_code_history, get_param_store, get_persistent_vars,
                )
                self._controller.session.parameters = get_param_store()
                self._controller.session.code_history = get_code_history()
                self._controller.session.persistent_vars = get_persistent_vars()
            except Exception:
                pass
            self._update_params_label()  # params changed with this tool run

            next_action = self._loop.handle_tool_results(executions)
            self._execute_action(next_action)
        except Exception as e:
            self._recover_after_internal_error(e)

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
                gui_doc = FreeCADGui.activeDocument()
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
            self._status_finish(True, f"Done  {elapsed_str}  {iters} iters  Turn {turns}")
        else:
            self._status_finish(False, f"Failed  {elapsed_str}  {iters} iters  Turn {turns}")

        self._set_running(False)
        self._turn_active = False
        self._refresh_session_list()

    def _on_chat_anchor(self, url):
        """Open http/https chat links in the system browser (S3-D15).

        Other schemes (file:, javascript:...) are ignored — links were
        previously rendered blue but did nothing on click.
        """
        from PySide6.QtGui import QDesktopServices
        url_str = url.toString() if hasattr(url, "toString") else str(url)
        if url_str.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    # ---- Event handlers ----

    def _on_stop(self):
        if self._loop:
            self._loop.request_stop()
        for t in self._live_threads():
            t.requestInterruption()
        self._status_set("stopping")

    def _on_new_session(self):
        # Confirm before discarding the view of a session with real turns
        # (it is saved and stays in the session list) — S3-D14
        if self._session.user_turn_count() > 0:
            from PySide6 import QtWidgets
            reply = QtWidgets.QMessageBox.question(
                self, "New Session",
                "Start a new session? The current conversation is saved "
                "and remains in the session list.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        # Stop the running threads and disconnect signals so stale
        # streamDone / chunkReady don't hit the cleared state below.
        if self._loop:
            self._loop.request_stop()
        for t in self._live_threads():
            for sig, slot in (
                (t.chunkReady, self._on_stream_chunk),
                (t.streamDone, self._on_stream_done),
                (t.error, self._on_llm_error),
            ):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._shutdown_threads(3000)
        self._store.save_if_not_empty(self._session)
        self._session = ChatSession()
        self._current_session_id = self._session.session_id
        self._sync_all_state(new_session_id=self._session.session_id)
        self._reset_turn_state()
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

        from core.paths import subdir
        uploads_dir = subdir("uploads")

        ext = os.path.splitext(file_path)[1]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_name = f"{timestamp}{ext}"
        dest_path = os.path.join(uploads_dir, dest_name)
        shutil.copy2(file_path, dest_path)

        current_text = self.text_input.toPlainText()
        marker = f" [image: {dest_path}]"
        self.text_input.setPlainText(current_text + marker)

        self._append_system_msg(f"Attached image: {dest_name}")

    def _on_undo(self):
        """User clicked Undo — restore document from most recent snapshot."""
        from core.snapshot import restore_latest_snapshot, snapshot_count, has_snapshot

        if not has_snapshot():
            self._append_system_msg("Nothing to undo — no snapshots available.")
            return

        if self._live_threads():
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
        # Interrupt and (bounded) wait for LLM threads first — destroying a
        # running QThread is a hard Qt abort (S1-D1).
        self._shutdown_threads(5000)
        self._store.save_if_not_empty(self._session)
        from core.snapshot import cleanup_all_snapshots
        cleanup_all_snapshots()
        super().closeEvent(event)
