"""Streaming display and chat bubble helpers for AgentPanel."""
from __future__ import annotations

from PySide6 import QtCore
from PySide6.QtGui import QTextCursor

from ui.chat_renderer import esc, markdown_to_html


class _PanelStreamMixin:
    """Chat display helpers and streaming bubble management."""

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
