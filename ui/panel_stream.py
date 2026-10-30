"""Streaming display and chat bubble helpers for AgentPanel."""
from __future__ import annotations

import time

from PySide6 import QtCore
from PySide6.QtGui import QTextCursor, QTextBlockFormat

from ui.chat_renderer import esc, markdown_to_html


class _PanelStreamMixin:
    """Chat display helpers and streaming bubble management."""

    # ---- Chat display helpers ----

    def _append_user_msg(self, text):
        c = self._get_colors()
        text = text.strip()
        self._insert_html(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.user_bubble_bg}; padding:8px 12px;">'
            f'<b style="color:{c.user_bubble_text};">You:</b> {esc(text)}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_agent_msg(self, text):
        c = self._get_colors()
        html = markdown_to_html(text, colors={"code_bg": c.code_bg, "code_border": c.code_border})
        self._insert_html(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.agent_bubble_bg}; padding:8px 12px; '
            f'border-left:3px solid {c.agent_bubble_border};">'
            f'<b style="color:{c.agent_bubble_text};">Agent:</b><br>'
            f'{html}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_tool_msg(self, iteration, name, desc, full_result, is_error):
        c = self._get_colors()
        icon = (
            f'<span style="color:{c.tool_icon_error};">&#10007;</span>'
            if is_error
            else f'<span style="color:{c.tool_icon_success};">&#10003;</span>'
        )
        label = f"[{iteration}] {name}"
        if desc:
            label += f" — {desc}"

        self._insert_html(
            f'<div style="margin:2px 0 2px 20px;font-size:12px;color:{c.tool_text};">'
            f'{icon} {esc(label)}'
            f'</div>'
        )

        # Result preview (S3-D10): tool output used to be completely
        # invisible — errors included. Show the first lines inline; errors
        # get a wider preview and error coloring.
        result_text = (full_result or "").strip()
        if result_text:
            result_lines = result_text.split("\n")
            shown = result_lines[:8] if is_error else result_lines[:3]
            hidden = len(result_lines) - len(shown)
            body = esc("\n".join(shown))
            if hidden > 0:
                body += f'<br><i>... ({hidden} more lines — see log/cadagent.log)</i>'
            bg = c.preview_bg  # neutral block background
            color = c.tool_text if not is_error else c.tool_icon_error
            self._insert_html(
                f'<div style="margin:0 0 2px 20px; padding:4px 8px; '
                f'font-size:11px; color:{color}; background-color:{bg}; '
                f'border-radius:3px; white-space:pre-wrap;">{body}</div>'
            )
        self._scroll_bottom()

    def _append_system_msg(self, text):
        c = self._get_colors()
        self._insert_html(
            f'<div style="margin:4px 0; color:{c.system_text}; font-style:italic; '
            f'font-size:12px; text-align:center;">{esc(text)}</div>'
        )
        self._scroll_bottom()

    def _insert_html(self, html):
        """Insert HTML at the end of the document with compact block margins."""
        doc = self.chat_display.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        start = cursor.position()
        cursor.insertHtml(f'<div style="margin:0; padding:0;">{html}</div>')
        self._compact_blocks_from(start)

    def _compact_blocks_from(self, start_pos):
        """Set block top/bottom margins to 0 from start_pos to document end."""
        doc = self.chat_display.document()
        cur = QTextCursor(doc)
        pos = min(start_pos, max(0, doc.characterCount() - 1))
        cur.setPosition(pos)
        cur.beginEditBlock()
        while True:
            fmt = cur.blockFormat()
            if fmt.bottomMargin() > 0 or fmt.topMargin() > 0:
                fmt.setBottomMargin(0)
                fmt.setTopMargin(0)
                cur.setBlockFormat(fmt)
            if not cur.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cur.endEditBlock()

    def _scroll_bottom(self):
        sb = self.chat_display.verticalScrollBar()
        # Respect the user scrolling up while output streams (S3-D15):
        # auto-scroll pauses when >50px from the bottom and resumes as
        # soon as they scroll back down.
        if sb.maximum() - sb.value() > 50:
            return
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
        if self._loop.mode == "react" if self._loop else False:
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
        doc = self.chat_display.document()
        max_pos = doc.characterCount() - 1
        start = min(self._stream_replace_start, max(0, max_pos))
        c = self._get_colors()
        html = markdown_to_html(
            self._streaming_text,
            colors={"code_bg": c.code_bg, "code_border": c.code_border},
        )
        bubble = (
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.agent_bubble_bg}; padding:8px 12px; '
            f'border-left:3px solid {c.agent_bubble_border};">'
            f'<b style="color:{c.agent_bubble_text};">Agent:</b><br>'
            f'{html}'
            f'</td></tr></table>'
        )
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertHtml(bubble)
        self._compact_blocks_from(start)
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
        doc = self.chat_display.document()
        max_pos = doc.characterCount() - 1
        start = min(self._stream_replace_start, max(0, max_pos))
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._streaming_text = ""
