"""Session management mixin for AgentPanel — load, switch, save, delete."""
from __future__ import annotations

from PySide6 import QtWidgets

from core.token_budget import token_summary


class _PanelSessionMixin:
    """Session history management — list, switch, restore display."""

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
        self.btn_delete_session.setEnabled(idx > 0)
        self.session_combo.blockSignals(False)

    def _on_session_selected(self, index):
        self.btn_delete_session.setEnabled(index > 0)
        if index <= 0:
            if self._llm_thread and self._llm_thread.isRunning():
                self._refresh_session_list()
                return
            self._store.save_if_not_empty(self._session)
            from core.session import ChatSession
            self._session = ChatSession()
            self._current_session_id = self._session.session_id
            self._mode = "auto"
            self._controller = None
            self._loop = None
            self._streaming_text = ""
            self._stream_replace_start = 0
            self._reasoning_text = ""
            self._pending_tool_results = {}
            if self._stream_timer and self._stream_timer.isActive():
                self._stream_timer.stop()
            self.chat_display.clear()
            self._append_system_msg("New session started. Describe a part to begin.")
            self._status_reset()
            self._update_token_label(0, 0)
            return
        session_id = self.session_combo.itemData(index)
        if not session_id or session_id == self._current_session_id:
            return
        if self._llm_thread and self._llm_thread.isRunning():
            self._append_system_msg("Agent 运行中，无法切换会话。")
            self._refresh_session_list()
            return
        self._store.save_if_not_empty(self._session)
        loaded = self._store.load(session_id)
        if loaded is None:
            self._append_system_msg("加载会话失败。")
            self._refresh_session_list()
            return
        self._session = loaded
        self._current_session_id = loaded.session_id
        self._mode = loaded.last_mode
        self._controller = None
        self._loop = None
        self._streaming_text = ""
        self._stream_replace_start = 0
        self._reasoning_text = ""
        self._pending_tool_results = {}
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        self._restore_chat_display(loaded)
        c = self._get_colors()
        turns = loaded.user_turn_count()
        msgs = loaded.message_count()
        self.status_label.setText(f"Session loaded | {turns} turns | {msgs} messages")
        self.status_label.setStyleSheet(
            f"color:{c.status_idle}; font-size:11px; font-family:'Segoe UI', sans-serif;"
        )
        used, budget = token_summary(loaded.get_messages())
        self._update_token_label(used, budget)
        self._refresh_session_list()

    def _restore_chat_display(self, session):
        self.chat_display.clear()
        iteration = 0
        for msg in session.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                self._append_user_msg(content)
            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    iteration += 1
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        name = fn.get("name", "")
                        desc = ""
                        if name == "execute_code":
                            try:
                                import json
                                desc = json.loads(fn.get("arguments", "{}")).get("description", "")
                            except (json.JSONDecodeError, KeyError):
                                pass
                        self._append_tool_msg(iteration, name, desc, "", False)
                if content:
                    self._append_agent_msg(content)
            elif role == "tool":
                is_error = content.startswith("ERROR") or content.startswith("FAIL")
                tool_id = msg.get("tool_call_id", "")
                label = "tool_result"
                # Find tool name from the preceding assistant message
                for prev in reversed(session.messages):
                    if prev.get("role") == "assistant" and prev.get("tool_calls"):
                        for tc in prev["tool_calls"]:
                            if tc.get("id") == tool_id:
                                label = tc["function"].get("name", "tool_result")
                                break
                        break
                self._append_tool_msg(iteration, label, "", content, is_error)
        if self.chat_display.document().isEmpty():
            self._append_system_msg("Session loaded. History restored.")

    def _on_delete_session(self):
        index = self.session_combo.currentIndex()
        if index <= 0:
            return

        session_id = self.session_combo.itemData(index)
        if not session_id:
            return

        if self._llm_thread and self._llm_thread.isRunning():
            self._append_system_msg("Agent is running. Cannot delete session.")
            return

        display_text = self.session_combo.itemText(index)
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Session",
            f"Permanently delete this session?\n\n{display_text}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        is_active = session_id == self._current_session_id
        success = self._store.delete(session_id)
        if not success:
            self._append_system_msg("Failed to delete session.")
            return

        if is_active:
            from core.session import ChatSession
            self._session = ChatSession()
            self._current_session_id = self._session.session_id
            self._controller = None
            self._loop = None
            self._streaming_text = ""
            self._stream_replace_start = 0
            self._reasoning_text = ""
            self._pending_tool_results = {}
            if self._stream_timer and self._stream_timer.isActive():
                self._stream_timer.stop()
            self.chat_display.clear()
            self._append_system_msg("Session deleted. New session started.")

        self._refresh_session_list()
