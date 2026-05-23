"""Streaming display and chat bubble helpers for AgentPanel."""
from __future__ import annotations

import time

from PySide6 import QtCore
from PySide6.QtGui import QTextCursor

from ui.chat_renderer import esc, markdown_to_html


class _PanelStreamMixin:
    """Chat display helpers and streaming bubble management."""

    # ---- Chat display helpers ----

    def _append_user_msg(self, text):
        c = self._get_colors()
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.user_bubble_bg}; padding:8px 12px;">'
            f'<b style="color:{c.user_bubble_text};">You:</b> {esc(text)}'
            f'</td></tr></table>'
        )
        self._scroll_bottom()

    def _append_agent_msg(self, text):
        c = self._get_colors()
        html = markdown_to_html(text, colors={"code_bg": c.code_bg, "code_border": c.code_border})
        self.chat_display.append(
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.agent_bubble_bg}; padding:10px 12px; '
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

        preview = full_result[:200]
        needs_expand = len(full_result) > 200
        ellipsis = "..." if needs_expand else ""

        toggle_link = ""
        if needs_expand:
            result_key = f"tool_{iteration}_{name}_{time.monotonic_ns()}"
            self._pending_tool_results[result_key] = full_result
            toggle_link = (
                f' <a href="expand:{result_key}"'
                f' style="color:{c.button_primary}; font-size:11px;">'
                f'Show details</a>'
            )

        self.chat_display.append(
            f'<div style="margin:2px 0 2px 20px;font-size:12px;color:{c.tool_text};">'
            f'{icon} {esc(label)}'
            f' <span style="font-size:11px;">{esc(preview)}{ellipsis}</span>'
            f'{toggle_link}'
            f'</div>'
        )
        self._scroll_bottom()

    def _append_system_msg(self, text):
        c = self._get_colors()
        self.chat_display.append(
            f'<div style="margin:4px 0; color:{c.system_text}; font-style:italic; '
            f'font-size:12px; text-align:center;">{esc(text)}</div>'
        )
        self._scroll_bottom()

    def _render_reasoning_block(self):
        """Render accumulated reasoning content as a gray block."""
        if not self._reasoning_text:
            return
        c = self._get_colors()
        preview = self._reasoning_text[:300]
        needs_expand = len(self._reasoning_text) > 300
        ellipsis = "..." if needs_expand else ""

        toggle_link = ""
        if needs_expand:
            result_key = f"reasoning_{self._iteration}_{time.monotonic_ns()}"
            self._pending_tool_results[result_key] = self._reasoning_text
            toggle_link = (
                f' <a href="expand:{result_key}"'
                f' style="color:{c.button_primary}; font-size:11px;">'
                f'Show all</a>'
            )

        self.chat_display.append(
            f'<div style="margin:4px 0 2px 0; padding:6px 10px;'
            f' background-color:{c.reasoning_bg};'
            f' border-left:2px solid {c.reasoning_border};'
            f' border-radius:3px; font-size:12px;'
            f' color:{c.reasoning_text}; font-style:italic;">'
            f'<b style="font-size:11px; font-style:normal;">Reasoning:</b> '
            f'{esc(preview)}{ellipsis}'
            f'{toggle_link}'
            f'</div>'
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
        c = self._get_colors()
        html = markdown_to_html(
            self._streaming_text,
            colors={"code_bg": c.code_bg, "code_border": c.code_border},
        )
        bubble = (
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="background-color:{c.agent_bubble_bg}; padding:10px 12px; '
            f'border-left:3px solid {c.agent_bubble_border};">'
            f'<b style="color:{c.agent_bubble_text};">Agent:</b><br>'
            f'{html}'
            f'</td></tr></table>'
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
