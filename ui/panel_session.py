"""Session management mixin for AgentPanel — load, switch, save."""
from __future__ import annotations

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
        self._iteration = 0
        self._stopped = False
        self._streaming_text = ""
        self._stream_replace_start = 0
        if self._stream_timer and self._stream_timer.isActive():
            self._stream_timer.stop()
        self._restore_chat_display(loaded)
        turns = loaded.user_turn_count()
        msgs = loaded.message_count()
        self.status_label.setText(f"Session loaded | {turns} turns | {msgs} messages")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        used, budget = token_summary(loaded.get_messages())
        self._update_token_label(used, budget)
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
