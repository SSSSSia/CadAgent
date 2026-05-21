"""
AgentPanel — chat-style dock panel for the AI CAD Agent.

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
from core.token_budget import trim_messages
from core.session_store import SessionStore
from agent.prompts import AGENT_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from agent.react_parser import parse_react_tool_calls
from agent.tools import dispatch_tool
from agent.tool_defs import TOOL_DEFINITIONS
from core.config import MAX_ITERATIONS
from core.llm_client import call_llm_streaming
from PySide6.QtGui import QTextCursor
from ui.chat_renderer import esc, markdown_to_html


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


class AgentPanel(QtWidgets.QDockWidget):
    """Chat-style dock panel for AI CAD Agent."""

    def __init__(self, parent=None):
        super().__init__("AI CAD Agent", parent)
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

    # ---- UI construction ----

    def _setup_ui(self):
        self.setMinimumWidth(380)
        self.setMinimumHeight(480)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
        )

        container = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(container)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # --- Session selector ---
        self.session_combo = QtWidgets.QComboBox()
        self.session_combo.setStyleSheet(
            "QComboBox {"
            "  font-family: 'Segoe UI', sans-serif;"
            "  font-size: 12px;"
            "  padding: 4px 8px;"
            "  border: 1px solid #ddd;"
            "  border-radius: 3px;"
            "  background: #fafafa;"
            "}"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView {"
            "  font-size: 12px;"
            "  border: 1px solid #ddd;"
            "  selection-background-color: #4a90d9;"
            "  selection-color: white;"
            "}"
        )
        self.session_combo.addItem("当前会话")
        self.session_combo.currentIndexChanged.connect(self._on_session_selected)
        main_layout.addWidget(self.session_combo)

        # --- Chat history ---
        self.chat_display = QtWidgets.QTextBrowser()
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.setStyleSheet(
            "QTextBrowser {"
            "  font-family: 'Segoe UI', sans-serif;"
            "  font-size: 13px;"
            "  background: #ffffff;"
            "  border: 1px solid #ddd;"
            "  border-radius: 4px;"
            "  padding: 8px;"
            "}"
        )
        main_layout.addWidget(self.chat_display, 1)

        # --- Input area ---
        input_row = QtWidgets.QHBoxLayout()
        self.text_input = QtWidgets.QLineEdit()
        self.text_input.setPlaceholderText("Describe the part you want to design...")
        self.text_input.returnPressed.connect(self._on_send)
        input_row.addWidget(self.text_input, 1)

        self.btn_send = QtWidgets.QPushButton("Send")
        self.btn_send.setStyleSheet(
            "QPushButton{background:#4a90d9;color:white;padding:6px 16px;"
            "border-radius:3px;font-weight:bold}"
            "QPushButton:hover{background:#357abd}"
            "QPushButton:disabled{background:#aaa}"
        )
        self.btn_send.clicked.connect(self._on_send)
        input_row.addWidget(self.btn_send)
        main_layout.addLayout(input_row)

        # --- Control buttons ---
        ctrl_row = QtWidgets.QHBoxLayout()

        self.btn_undo = QtWidgets.QPushButton("Undo")
        self.btn_undo.setStyleSheet("padding:5px 12px")
        self.btn_undo.setEnabled(False)
        self.btn_undo.setToolTip("Undo last agent operation (restore document snapshot)")
        self.btn_undo.clicked.connect(self._on_undo)
        ctrl_row.addWidget(self.btn_undo)

        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setStyleSheet("padding:5px 12px")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        ctrl_row.addWidget(self.btn_stop)

        self.btn_new_session = QtWidgets.QPushButton("New Session")
        self.btn_new_session.setStyleSheet("padding:5px 12px")
        self.btn_new_session.clicked.connect(self._on_new_session)
        ctrl_row.addWidget(self.btn_new_session)

        ctrl_row.addStretch()
        main_layout.addLayout(ctrl_row)

        # --- Status bar ---
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        main_layout.addWidget(self.status_label)

        self._append_system_msg(
            "AI CAD Agent ready. Describe a part and I'll create it in FreeCAD."
        )
        self._refresh_session_list()

        container.setLayout(main_layout)
        self.setWidget(container)

    # ---- Session history management ----

    def _refresh_session_list(self):
        sessions = self._store.list_sessions()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem("当前会话")
        for s in sessions:
            summary_text = s.get("summary", "") or "No summary"
            display = f"{summary_text[:30]} | {s.get('created_at', '')[:10]}"
            self.session_combo.addItem(display, s["session_id"])
        idx = 0
        for i in range(1, self.session_combo.count()):
            if self.session_combo.itemData(i) == self._current_session_id:
                idx = i
                break
        self.session_combo.setCurrentIndex(idx)
        self.session_combo.blockSignals(False)

    def _on_session_selected(self, index):
        if index <= 0:
            return
        session_id = self.session_combo.itemData(index)
        if not session_id or session_id == self._current_session_id:
            return
        if self._llm_thread and self._llm_thread.isRunning():
            self._append_system_msg("Agent 运行中，无法切换会话。")
            self._refresh_session_list()
            return
        self._store.save(self._session)
        loaded = self._store.load(session_id)
        if loaded is None:
            self._append_system_msg("加载会话失败。")
            self._refresh_session_list()
            return
        self._session = loaded
        self._current_session_id = loaded.session_id
        self._controller = None
        self._restore_chat_display(loaded)
        turns = loaded.user_turn_count()
        msgs = loaded.message_count()
        self.status_label.setText(f"Session loaded | {turns} turns | {msgs} messages")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        self._refresh_session_list()

    def _restore_chat_display(self, session):
        self.chat_display.clear()
        for msg in session.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self._append_user_msg(content)
            elif role == "assistant" and content:
                self._append_agent_msg(content)
        if self.chat_display.document().isEmpty():
            self._append_system_msg("Session loaded. History restored.")

    # ---- Chat display helpers ----

    def _append_user_msg(self, text):
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:#e8f0fe; padding:8px 12px;">'
            f'<b style="color:#1a5276;">You:</b> {esc(text)}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_agent_msg(self, text):
        html = markdown_to_html(text)
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:#f0faf4; padding:10px 12px; border-left:3px solid #0d904f;">'
            f'<b style="color:#0d904f;">Agent:</b><br>'
            f'{html}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_tool_msg(self, iteration, name, desc, preview, is_error):
        icon = '<span style="color:#d32f2f;">&#10007;</span>' if is_error else '<span style="color:#2e7d32;">&#10003;</span>'
        label = f"[{iteration}] {name}"
        if desc:
            label += f" — {desc}"
        self.chat_display.append(
            f'<div style="margin:2px 0 2px 20px;font-size:12px;color:#888;">'
            f'{icon} {esc(label)}</div>'
        )
        self._scroll_bottom()

    def _append_system_msg(self, text):
        self.chat_display.append(
            f'<div style="margin:4px 0; color:#888; font-style:italic; '
            f'font-size:12px; text-align:center;">{esc(text)}</div>'
        )
        self._scroll_bottom()

    def _scroll_bottom(self):
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---- Streaming display helpers ----

    def _start_streaming_bubble(self):
        """Create an empty agent bubble and record cursor position for replacement."""
        self._streaming_text = ""
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._stream_replace_start = cursor.position()
        # Insert empty bubble shell
        self._append_agent_msg("")

    def _on_stream_chunk(self, delta_text):
        """Accumulate streaming text and schedule a batched UI update."""
        if self._mode == "react":
            return
        self._streaming_text += delta_text
        if self._stream_timer is None:
            self._stream_timer = QtCore.QTimer(self)
            self._stream_timer.setSingleShot(True)
            self._stream_timer.setInterval(80)
            self._stream_timer.timeout.connect(self._update_streaming_display)
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _update_streaming_display(self):
        """Replace the streaming bubble with current accumulated text."""
        if not self._streaming_text:
            return
        html = markdown_to_html(self._streaming_text)
        bubble = (
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            '<td style="background-color:#f0faf4; padding:10px 12px; '
            'border-left:3px solid #0d904f;">'
            '<b style="color:#0d904f;">Agent:</b><br>'
            f'{html}'
            '</td></tr></table>'
        )
        cursor = QTextCursor(self.chat_display.document())
        cursor.setPosition(self._stream_replace_start)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertHtml(bubble)
        self._scroll_bottom()

    def _finalize_streaming_bubble(self):
        """Final re-render of the streaming bubble after stream ends."""
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        if self._streaming_text:
            self._update_streaming_display()

    def _remove_streaming_bubble(self):
        """Remove the streaming placeholder bubble (for tool_calls with no text)."""
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        cursor = QTextCursor(self.chat_display.document())
        cursor.setPosition(self._stream_replace_start)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._streaming_text = ""

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
            except Exception:
                pass

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

        # Start first LLM call
        self._call_llm()

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

        messages = trim_messages(self._controller.session.get_messages())
        self._llm_thread = _LlmCallThread(messages, tools)
        self._llm_thread.chunkReady.connect(self._on_stream_chunk)
        self._llm_thread.streamDone.connect(self._on_stream_done)
        self._llm_thread.error.connect(self._on_llm_error)
        self._llm_thread.start()

    def _on_stream_done(self, data):
        """Streaming complete — finalize display, then route response."""
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason", "")
        content = choice.get("message", {}).get("content", "")

        # Finalize or remove streaming bubble based on content
        if self._streaming_text and self._streaming_text.strip():
            self._finalize_streaming_bubble()
        else:
            self._remove_streaming_bubble()

        self._handle_llm_response(data, _streamed=bool(self._streaming_text))

    def _handle_llm_response(self, data, _streamed=False):
        """Route LLM response to the appropriate handler."""
        choice = data["choices"][0]
        assistant_msg = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")
        content = assistant_msg.get("content", "")

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
                except Exception:
                    pass

            # Execute tool in main thread (FreeCAD safe)
            tool_result = dispatch_tool(tool_name, tool_args)

            # Update undo button state (snapshot was taken if execute_code)
            self._update_undo_button_state()

            # ReAct mode: use user message for tool results (model doesn't understand role="tool")
            if self._mode == "react":
                self._controller.session.add_user_message(
                    f"[Tool Result for {tool_name}]:\n{tool_result}"
                )
            else:
                self._controller.session.add_tool_result(tool_id, tool_result)

            is_error = tool_result.startswith("ERROR")
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
            except Exception:
                pass
            try:
                view = Gui.activeDocument().activeView()
                view.viewIsometric()
                view.fitAll()
            except Exception:
                pass

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
