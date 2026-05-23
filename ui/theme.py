"""Theme colors for CadAgent panel — adapts to FreeCAD light/dark theme."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeColors:
    """All named colors used by the panel, resolved for the current palette."""
    # Surfaces
    chat_bg: str
    user_bubble_bg: str
    user_bubble_text: str
    agent_bubble_bg: str
    agent_bubble_border: str
    agent_bubble_text: str
    # Tool / status
    tool_icon_success: str
    tool_icon_error: str
    tool_text: str
    system_text: str
    reasoning_bg: str
    reasoning_text: str
    reasoning_border: str
    # UI chrome
    border: str
    input_bg: str
    button_primary: str
    button_primary_hover: str
    button_disabled: str
    button_text: str
    combo_bg: str
    selection_bg: str
    selection_text: str
    # Status
    status_idle: str
    status_thinking: str
    status_executing: str
    status_stopping: str
    status_success: str
    status_error: str
    # Token label
    token_ok: str
    token_warn: str
    token_danger: str
    # Code
    code_bg: str
    code_border: str


def _is_dark_mode(palette) -> bool:
    bg = palette.color(palette.ColorRole.Window)
    return bg.lightness() < 128


def get_theme_colors(palette=None) -> ThemeColors:
    if palette is None:
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance()
        palette = app.palette() if app else None
        if palette is None:
            return _LIGHT_COLORS

    if _is_dark_mode(palette):
        return _DARK_COLORS
    return _LIGHT_COLORS


_LIGHT_COLORS = ThemeColors(
    chat_bg="#ffffff",
    user_bubble_bg="#e8f0fe",
    user_bubble_text="#1a5276",
    agent_bubble_bg="#f0faf4",
    agent_bubble_border="#0d904f",
    agent_bubble_text="#0d904f",
    tool_icon_success="#2e7d32",
    tool_icon_error="#d32f2f",
    tool_text="#888888",
    system_text="#888888",
    reasoning_bg="#f5f5f5",
    reasoning_text="#666666",
    reasoning_border="#cccccc",
    border="#dddddd",
    input_bg="#ffffff",
    button_primary="#4a90d9",
    button_primary_hover="#357abd",
    button_disabled="#aaaaaa",
    button_text="#ffffff",
    combo_bg="#fafafa",
    selection_bg="#4a90d9",
    selection_text="#ffffff",
    status_idle="#666666",
    status_thinking="#d4a017",
    status_executing="#2e7d32",
    status_stopping="#999999",
    status_success="#0d904f",
    status_error="#d32f2f",
    token_ok="#888888",
    token_warn="#d4a017",
    token_danger="#d32f2f",
    code_bg="#f4f4f4",
    code_border="#dddddd",
)

_DARK_COLORS = ThemeColors(
    chat_bg="#1e1e1e",
    user_bubble_bg="#1a3a5c",
    user_bubble_text="#b0d4f1",
    agent_bubble_bg="#1a3c2a",
    agent_bubble_border="#2e7d32",
    agent_bubble_text="#81c784",
    tool_icon_success="#66bb6a",
    tool_icon_error="#ef5350",
    tool_text="#aaaaaa",
    system_text="#888888",
    reasoning_bg="#2a2a2a",
    reasoning_text="#b0b0b0",
    reasoning_border="#555555",
    border="#444444",
    input_bg="#2a2a2a",
    button_primary="#3a7bd5",
    button_primary_hover="#4a8be5",
    button_disabled="#555555",
    button_text="#ffffff",
    combo_bg="#2a2a2a",
    selection_bg="#3a7bd5",
    selection_text="#ffffff",
    status_idle="#999999",
    status_thinking="#d4a017",
    status_executing="#66bb6a",
    status_stopping="#777777",
    status_success="#66bb6a",
    status_error="#ef5350",
    token_ok="#aaaaaa",
    token_warn="#d4a017",
    token_danger="#ef5350",
    code_bg="#2a2a2a",
    code_border="#444444",
)
