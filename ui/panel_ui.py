"""UI construction mixin for AgentPanel — widget creation, layout, styling."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class _PanelUIMixin:
    """_setup_ui() — creates all widgets, layouts, and styles."""

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
        self.session_combo.currentIndexChanged.connect(self._on_session_selected)
        main_layout.addWidget(self.session_combo)

        # --- Chat history ---
        self.chat_display = QtWidgets.QTextBrowser()
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.document().setDefaultStyleSheet(
            "p { margin: 0; }"
        )
        main_layout.addWidget(self.chat_display, 1)

        # --- Input area ---
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(4)

        self.text_input = QtWidgets.QTextEdit()
        self.text_input.setPlaceholderText("Describe the part you want to design...")
        self.text_input.setAcceptRichText(False)
        self.text_input.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.text_input.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.text_input.setFixedHeight(36)
        self.text_input.setMinimumHeight(36)
        self.text_input.textChanged.connect(self._on_input_text_changed)
        self.text_input.installEventFilter(self)
        input_row.addWidget(self.text_input, 1)

        self.btn_attach = QtWidgets.QPushButton("📎")
        self.btn_attach.setFixedSize(36, 36)
        self.btn_attach.setToolTip("Attach image for vision analysis")
        self.btn_attach.clicked.connect(self._on_attach_image)
        input_row.addWidget(self.btn_attach)

        self.btn_send = QtWidgets.QPushButton("Send")
        self.btn_send.setFixedHeight(36)
        self.btn_send.setMinimumWidth(70)
        self.btn_send.clicked.connect(self._on_send)
        input_row.addWidget(self.btn_send)
        main_layout.addLayout(input_row)

        # --- Control buttons ---
        ctrl_row = QtWidgets.QHBoxLayout()
        ctrl_row.setSpacing(3)

        self.btn_undo = QtWidgets.QPushButton("Undo")
        self.btn_undo.setEnabled(False)
        self.btn_undo.setToolTip("Undo last agent operation (restore document snapshot)")
        self.btn_undo.clicked.connect(self._on_undo)
        ctrl_row.addWidget(self.btn_undo)

        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        ctrl_row.addWidget(self.btn_stop)

        self.btn_new_session = QtWidgets.QPushButton("New")
        self.btn_new_session.clicked.connect(self._on_new_session)
        ctrl_row.addWidget(self.btn_new_session)

        self.btn_delete_session = QtWidgets.QPushButton("Delete")
        self.btn_delete_session.setToolTip("Delete selected session")
        self.btn_delete_session.setEnabled(False)
        self.btn_delete_session.clicked.connect(self._on_delete_session)
        ctrl_row.addWidget(self.btn_delete_session)

        ctrl_row.addStretch()

        self.btn_settings = QtWidgets.QPushButton("⚙")
        self.btn_settings.setFixedSize(30, 26)
        self.btn_settings.setToolTip("Configure CadAgent API and parameters")
        self.btn_settings.clicked.connect(self._on_settings)
        ctrl_row.addWidget(self.btn_settings)

        main_layout.addLayout(ctrl_row)

        # --- Status bar (token + status on one line) ---
        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 2, 0, 0)
        status_row.setSpacing(0)
        self.token_label = QtWidgets.QLabel("Tokens: 0 / 24000")
        self.status_label = QtWidgets.QLabel("Ready")
        status_row.addWidget(self.token_label)
        status_row.addStretch()
        status_row.addWidget(self.status_label)
        main_layout.addLayout(status_row)

        # Apply theme-aware styles
        self._apply_dynamic_styles()

        self._append_system_msg(
            "CadAgent ready. Describe a part and I'll create it in FreeCAD."
        )
        self._refresh_session_list()
        self._setup_status()

        container.setLayout(main_layout)
        self.setWidget(container)

    def _apply_dynamic_styles(self):
        """Rebuild all widget stylesheets using current theme colors."""
        c = self._get_colors()
        font = "'Segoe UI', sans-serif"

        self.session_combo.setStyleSheet(
            f"QComboBox {{"
            f"  font-family: {font};"
            f"  font-size: 12px;"
            f"  padding: 4px 8px;"
            f"  border: 1px solid {c.border};"
            f"  border-radius: 3px;"
            f"  background: {c.combo_bg};"
            f"}}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{"
            f"  font-size: 12px;"
            f"  border: 1px solid {c.border};"
            f"  selection-background-color: {c.selection_bg};"
            f"  selection-color: {c.selection_text};"
            f"}}"
        )
        self.chat_display.setStyleSheet(
            f"QTextBrowser {{"
            f"  font-family: {font};"
            f"  font-size: 13px;"
            f"  background: {c.chat_bg};"
            f"  border: 1px solid {c.border};"
            f"  border-radius: 4px;"
            f"  padding: 8px;"
            f"}}"
        )
        self.text_input.setStyleSheet(
            f"QTextEdit {{"
            f"  font-family: {font};"
            f"  font-size: 13px;"
            f"  border: 1px solid {c.border};"
            f"  border-radius: 4px;"
            f"  padding: 5px 8px;"
            f"  background: {c.input_bg};"
            f"}}"
        )
        self.btn_attach.setStyleSheet(
            f"QPushButton{{background:{c.input_bg};border:1px solid {c.border};"
            f"border-radius:4px;font-size:15px}}"
            f"QPushButton:hover{{background:{c.button_primary_hover};"
            f"color:{c.button_text}}}"
        )
        self.btn_send.setStyleSheet(
            f"QPushButton{{background:{c.button_primary};color:{c.button_text};"
            f"padding:6px 16px;border:none;border-radius:4px;"
            f"font-weight:bold;font-size:13px}}"
            f"QPushButton:hover{{background:{c.button_primary_hover}}}"
            f"QPushButton:disabled{{background:{c.button_disabled}}}"
        )
        ctrl_style = (
            f"QPushButton{{background:transparent;border:1px solid {c.border};"
            f"border-radius:3px;padding:3px 10px;font-size:11px;"
            f"font-family:{font};color:{c.status_idle}}}"
            f"QPushButton:hover{{background:{c.combo_bg}}}"
            f"QPushButton:disabled{{color:{c.button_disabled};border-color:transparent}}"
        )
        for btn in (self.btn_undo, self.btn_stop,
                    self.btn_new_session, self.btn_delete_session):
            btn.setStyleSheet(ctrl_style)
        self.btn_settings.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid {c.border};"
            f"border-radius:3px;font-size:14px}}"
            f"QPushButton:hover{{background:{c.combo_bg}}}"
        )
        self.token_label.setStyleSheet(
            f"color:{c.token_ok}; font-size:10px; font-family:{font};"
        )
        self.status_label.setStyleSheet(
            f"color:{c.status_idle}; font-size:10px; font-family:{font};"
        )

    def _on_input_text_changed(self):
        """Auto-resize input to fit content (1-5 lines)."""
        doc = self.text_input.document()
        doc.setTextWidth(self.text_input.width())
        h = doc.size().height()
        min_h = 36
        max_h = 130
        new_h = int(max(min_h, min(h + 10, max_h)))
        self.text_input.setFixedHeight(new_h)
