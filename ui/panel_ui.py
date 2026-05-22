"""UI construction mixin for AgentPanel — widget creation, layout, styling."""
from __future__ import annotations

from PySide6 import QtWidgets


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

        # --- Token budget ---
        self.token_label = QtWidgets.QLabel("Tokens: 0 / 24000")
        self.token_label.setStyleSheet("color:#888; font-size:10px;")
        main_layout.addWidget(self.token_label)

        # --- Status bar ---
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color:#666; font-size:11px;")
        main_layout.addWidget(self.status_label)

        self._append_system_msg(
            "CadAgent ready. Describe a part and I'll create it in FreeCAD."
        )
        self._refresh_session_list()

        container.setLayout(main_layout)
        self.setWidget(container)
