"""Settings dialog for CadAgent — configure API, model, and agent parameters."""
from __future__ import annotations

import base64
import json
import os
import struct
import tempfile
import urllib.error
import urllib.request
import zlib

from PySide6 import QtCore, QtWidgets

import core.config as _config
from ui.theme import get_theme_colors


# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------

PROVIDER_PRESETS = [
    {"name": "SiliconFlow", "url": "https://api.siliconflow.cn/v1",
     "model": "Pro/zai-org/GLM-5.1"},
    {"name": "DeepSeek", "url": "https://api.deepseek.com/v1",
     "model": "deepseek-chat"},
    {"name": "ZhipuAI", "url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4-plus"},
    {"name": "Qwen", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen-plus"},
    {"name": "OpenAI", "url": "https://api.openai.com/v1",
     "model": "gpt-4o"},
    {"name": "Moonshot", "url": "https://api.moonshot.cn/v1",
     "model": "moonshot-v1-128k"},
    {"name": "Local (Ollama)", "url": "http://localhost:11434/v1",
     "model": "qwen3:8b"},
    {"name": "Custom", "url": "", "model": ""},
]

VISION_PROVIDER_PRESETS = [
    {"name": "SiliconFlow", "url": "https://api.siliconflow.cn/v1",
     "model": "Pro/zai-org/GLM-4V-Plus"},
    {"name": "DeepSeek", "url": "https://api.deepseek.com/v1",
     "model": "deepseek-chat"},
    {"name": "ZhipuAI", "url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4v-plus"},
    {"name": "Qwen", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen-vl-plus"},
    {"name": "OpenAI", "url": "https://api.openai.com/v1",
     "model": "gpt-4o"},
    {"name": "Moonshot", "url": "https://api.moonshot.cn/v1",
     "model": "moonshot-v1-128k"},
    {"name": "Local (Ollama)", "url": "http://localhost:11434/v1",
     "model": "llava"},
    {"name": "Custom", "url": "", "model": ""},
]


def _env_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")


def _save_to_env(values: dict):
    """Write config values to .env, preserving comments and structure."""
    path = _env_path()

    # Read existing lines
    existing_lines: list[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing_lines = f.readlines()

    written_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in values:
                new_lines.append(f"{key}={values[key]}\n")
                written_keys.add(key)
                continue
        new_lines.append(line)

    # Append any keys not found in the file
    for key, value in values.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")

    # Atomic write
    dir_name = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".env")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        os.replace(tmp, path)
    except Exception:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

# Shared stylesheet templates (color placeholders filled at runtime)
_GROUP_STYLE = (
    "QGroupBox {{ font-weight: bold; border: 1px solid {border}; "
    "border-radius: 4px; margin-top: 10px; padding-top: 16px; }}"
    "QGroupBox::title {{ subcontrol-origin: margin; left: 10px; "
    "padding: 0 4px; color: {text}; }}"
)
_INPUT_STYLE = (
    "QLineEdit {{ padding: 5px 8px; border: 1px solid {border}; "
    "border-radius: 3px; background: {input_bg}; }}"
    "QLineEdit:focus {{ border-color: #4a90d9; }}"
    "QSpinBox, QDoubleSpinBox {{ padding: 5px 8px; "
    "border: 1px solid {border}; border-radius: 3px; background: {input_bg}; }}"
    "QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: #4a90d9; }}"
    "QComboBox {{ padding: 5px 8px; border: 1px solid {border}; "
    "border-radius: 3px; background: {combo_bg}; }}"
)
_BTN_STYLE = "padding:6px 14px; border-radius:3px;"
_PRIMARY_BTN = (
    "QPushButton {{ background:#4a90d9; color:white; padding:6px 16px; "
    "border-radius:3px; font-weight:bold; border:none; }}"
    "QPushButton:hover {{ background:#357abd; }}"
    "QPushButton:disabled {{ background:#aaccee; }}"
)
_TAB_STYLE = (
    "QTabWidget::pane {{ border: 1px solid {border}; border-radius: 2px; "
    "background: transparent; }}"
    "QTabBar::tab {{ padding: 8px 20px; margin-right: 2px; "
    "border: 1px solid {border}; border-bottom: none; "
    "border-top-left-radius: 4px; border-top-right-radius: 4px; "
    "background: {input_bg}; }}"
    "QTabBar::tab:selected {{ background: white; "
    "border-bottom: 1px solid white; }}"
    "QTabBar::tab:!selected {{ margin-top: 2px; }}"
)


def _make_test_png_b64() -> str:
    """Generate a valid 32x32 red PNG as base64 for vision API testing."""
    size = 32
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    compressed = zlib.compress(rows)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    return base64.b64encode(sig + ihdr + idat + iend).decode("ascii")


def _build_main_llm_tab(parent: SettingsDialog) -> QtWidgets.QWidget:
    """Build the Main LLM configuration tab."""
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)

    # --- API Configuration (includes provider preset + agent params) ---
    api_group = QtWidgets.QGroupBox("API Configuration")
    api_form = QtWidgets.QFormLayout(api_group)
    api_form.setLabelAlignment(QtCore.Qt.AlignRight)
    api_form.setFormAlignment(QtCore.Qt.AlignLeft)
    api_form.setHorizontalSpacing(12)
    api_form.setVerticalSpacing(8)

    # Provider preset as first row
    parent.combo_provider = QtWidgets.QComboBox()
    for p in PROVIDER_PRESETS:
        parent.combo_provider.addItem(p["name"])
    parent.combo_provider.currentIndexChanged.connect(parent._on_provider_changed)
    api_form.addRow("Provider:", parent.combo_provider)

    # API fields
    parent.edit_url = QtWidgets.QLineEdit()
    parent.edit_url.setPlaceholderText("https://api.example.com/v1")
    api_form.addRow("API Base URL:", parent.edit_url)

    key_row = QtWidgets.QHBoxLayout()
    key_row.setSpacing(4)
    parent.edit_key = QtWidgets.QLineEdit()
    parent.edit_key.setEchoMode(QtWidgets.QLineEdit.Password)
    parent.edit_key.setPlaceholderText("sk-...")
    key_row.addWidget(parent.edit_key, 1)
    parent.btn_toggle_key = QtWidgets.QPushButton("Show")
    parent.btn_toggle_key.setFixedWidth(50)
    parent.btn_toggle_key.setCheckable(True)
    parent.btn_toggle_key.clicked.connect(parent._on_toggle_key)
    key_row.addWidget(parent.btn_toggle_key)
    api_form.addRow("API Key:", key_row)

    parent.edit_model = QtWidgets.QLineEdit()
    parent.edit_model.setPlaceholderText("model-name")
    api_form.addRow("Model Name:", parent.edit_model)

    # Agent params (merged into same group)
    parent.spin_max_tokens = QtWidgets.QSpinBox()
    parent.spin_max_tokens.setRange(256, 32768)
    parent.spin_max_tokens.setSingleStep(256)
    parent.spin_max_tokens.setToolTip("Maximum output tokens per LLM request")
    parent.spin_max_tokens.setFixedWidth(120)
    api_form.addRow("Max Tokens:", parent.spin_max_tokens)

    parent.spin_max_iter = QtWidgets.QSpinBox()
    parent.spin_max_iter.setRange(1, 50)
    parent.spin_max_iter.setToolTip("Maximum agent loop iterations")
    parent.spin_max_iter.setFixedWidth(120)
    api_form.addRow("Max Iterations:", parent.spin_max_iter)

    # Test Connection button inside the group
    btn_row = QtWidgets.QHBoxLayout()
    btn_row.addStretch()
    parent.btn_test = QtWidgets.QPushButton("Test Connection")
    parent.btn_test.setFixedWidth(140)
    parent.btn_test.clicked.connect(parent._on_test_connection)
    btn_row.addWidget(parent.btn_test)
    api_form.addRow("", btn_row)

    layout.addWidget(api_group)
    layout.addStretch()
    return page


def _build_vision_tab(parent: SettingsDialog) -> QtWidgets.QWidget:
    """Build the Vision Model configuration tab."""
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    # Enable checkbox at top
    parent.chk_vision_enabled = QtWidgets.QCheckBox("Enable Vision Model")
    parent.chk_vision_enabled.setToolTip(
        "Enable vision tools (capture_view, analyze_image) for visual verification"
    )
    parent.chk_vision_enabled.toggled.connect(parent._on_vision_enabled_toggled)
    layout.addWidget(parent.chk_vision_enabled)

    # Vision configuration group (always visible, content disabled when unchecked)
    vision_group = QtWidgets.QGroupBox("Vision Model Configuration")
    vision_form = QtWidgets.QFormLayout(vision_group)
    vision_form.setLabelAlignment(QtCore.Qt.AlignRight)
    vision_form.setFormAlignment(QtCore.Qt.AlignLeft)
    vision_form.setHorizontalSpacing(12)
    vision_form.setVerticalSpacing(8)

    # "Same as main" checkbox
    parent.chk_vision_same_as_main = QtWidgets.QCheckBox(
        "Use same API as main model"
    )
    parent.chk_vision_same_as_main.setToolTip(
        "Auto-fill Vision API URL and Key from the main API configuration"
    )
    parent.chk_vision_same_as_main.toggled.connect(
        parent._on_vision_same_as_main_toggled
    )
    vision_form.addRow("", parent.chk_vision_same_as_main)

    # Provider
    parent.combo_vision_provider = QtWidgets.QComboBox()
    for p in VISION_PROVIDER_PRESETS:
        parent.combo_vision_provider.addItem(p["name"])
    parent.combo_vision_provider.currentIndexChanged.connect(
        parent._on_vision_provider_changed
    )
    vision_form.addRow("Provider:", parent.combo_vision_provider)

    # API fields
    parent.edit_vision_url = QtWidgets.QLineEdit()
    parent.edit_vision_url.setPlaceholderText("https://api.example.com/v1")
    vision_form.addRow("API Base URL:", parent.edit_vision_url)

    vision_key_row = QtWidgets.QHBoxLayout()
    vision_key_row.setSpacing(4)
    parent.edit_vision_key = QtWidgets.QLineEdit()
    parent.edit_vision_key.setEchoMode(QtWidgets.QLineEdit.Password)
    parent.edit_vision_key.setPlaceholderText("sk-...")
    vision_key_row.addWidget(parent.edit_vision_key, 1)
    parent.btn_toggle_vision_key = QtWidgets.QPushButton("Show")
    parent.btn_toggle_vision_key.setFixedWidth(50)
    parent.btn_toggle_vision_key.setCheckable(True)
    parent.btn_toggle_vision_key.clicked.connect(
        lambda checked: parent._toggle_password(
            parent.edit_vision_key, parent.btn_toggle_vision_key
        )
    )
    vision_key_row.addWidget(parent.btn_toggle_vision_key)
    vision_form.addRow("API Key:", vision_key_row)

    parent.edit_vision_model = QtWidgets.QLineEdit()
    parent.edit_vision_model.setPlaceholderText("vision-model-name")
    vision_form.addRow("Model Name:", parent.edit_vision_model)

    # Vision params
    parent.spin_vision_max_tokens = QtWidgets.QSpinBox()
    parent.spin_vision_max_tokens.setRange(256, 16384)
    parent.spin_vision_max_tokens.setSingleStep(256)
    parent.spin_vision_max_tokens.setToolTip(
        "Maximum output tokens per vision API request"
    )
    parent.spin_vision_max_tokens.setFixedWidth(120)
    vision_form.addRow("Max Tokens:", parent.spin_vision_max_tokens)

    parent.spin_vision_temperature = QtWidgets.QDoubleSpinBox()
    parent.spin_vision_temperature.setRange(0.0, 2.0)
    parent.spin_vision_temperature.setSingleStep(0.1)
    parent.spin_vision_temperature.setDecimals(2)
    parent.spin_vision_temperature.setToolTip(
        "Temperature for vision model responses"
    )
    parent.spin_vision_temperature.setFixedWidth(120)
    vision_form.addRow("Temperature:", parent.spin_vision_temperature)

    # Test Vision API button
    test_row = QtWidgets.QHBoxLayout()
    test_row.addStretch()
    parent.btn_test_vision = QtWidgets.QPushButton("Test Vision API")
    parent.btn_test_vision.setFixedWidth(140)
    parent.btn_test_vision.clicked.connect(parent._on_test_vision_connection)
    test_row.addWidget(parent.btn_test_vision)
    vision_form.addRow("", test_row)

    parent._vision_config_group = vision_group
    layout.addWidget(vision_group)
    layout.addStretch()
    return page


class _TestWorker(QtCore.QThread):
    """Background worker for API connection testing."""
    success = QtCore.Signal(str)
    error = QtCore.Signal(str)

    def __init__(self, endpoint, headers, payload, timeout=15):
        super().__init__()
        self._endpoint = endpoint
        self._headers = headers
        self._payload = payload
        self._timeout = timeout

    def run(self):
        try:
            req = urllib.request.Request(
                self._endpoint, data=self._payload, headers=self._headers
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.success.emit(data.get("model", ""))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            self.error.emit(f"HTTP {e.code} {e.reason}\n\n{body}")
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class SettingsDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CadAgent Settings")
        self.setMinimumWidth(520)
        self.setMinimumHeight(300)
        self.setModal(True)
        self._test_worker = None
        self._test_btn = None
        self._test_btn_label = ""
        self._test_title = ""
        self._setup_ui()
        self._load_current_values()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_style()

    # ---- UI construction ----

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Tab widget
        self.tabs = QtWidgets.QTabWidget()

        # Main LLM tab (wrapped in scroll area)
        main_page = _build_main_llm_tab(self)
        main_scroll = QtWidgets.QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setWidget(main_page)
        main_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tabs.addTab(main_scroll, "Main LLM")

        # Vision Model tab (wrapped in scroll area)
        vision_page = _build_vision_tab(self)
        vision_scroll = QtWidgets.QScrollArea()
        vision_scroll.setWidgetResizable(True)
        vision_scroll.setWidget(vision_page)
        vision_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tabs.addTab(vision_scroll, "Vision Model")

        layout.addWidget(self.tabs)

        # --- Bottom button bar ---
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_apply = QtWidgets.QPushButton("Apply")
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)

        layout.addLayout(btn_row)

        self._apply_style()

    def _apply_style(self):
        colors = get_theme_colors()
        group_style = _GROUP_STYLE.format(
            border=colors.border, text=colors.agent_bubble_text
        )
        input_style = _INPUT_STYLE.format(
            border=colors.border,
            input_bg=colors.input_bg,
            combo_bg=colors.combo_bg,
        )
        tab_style = _TAB_STYLE.format(
            border=colors.border, input_bg=colors.input_bg
        )
        self.setStyleSheet(
            "QDialog { font-family: 'Segoe UI', sans-serif; font-size: 13px; }"
            + group_style + input_style + tab_style
        )
        # Style test buttons
        test_btn_style = (
            "QPushButton {{ padding: 6px 16px; border: 1px solid {border}; "
            "border-radius: 3px; background: {input_bg}; }}"
            "QPushButton:hover {{ background: {combo_bg}; }}"
            "QPushButton:disabled {{ color: gray; }}"
        ).format(
            border=colors.border,
            input_bg=colors.input_bg,
            combo_bg=colors.combo_bg,
        )
        self.btn_test.setStyleSheet(test_btn_style)
        self.btn_test_vision.setStyleSheet(test_btn_style)

        # Bottom bar buttons
        cancel_style = (
            "QPushButton {{ padding: 6px 20px; border: 1px solid {border}; "
            "border-radius: 3px; background: {input_bg}; }}"
            "QPushButton:hover {{ background: {combo_bg}; }}"
        ).format(border=colors.border, input_bg=colors.input_bg,
                 combo_bg=colors.combo_bg)
        apply_style = (
            "QPushButton {{ background: {primary}; color: white; "
            "padding: 6px 20px; border-radius: 3px; font-weight: bold; "
            "border: none; }}"
            "QPushButton:hover {{ background: {primary_hover}; }}"
        ).format(primary=colors.button_primary,
                 primary_hover=colors.button_primary_hover)
        self.btn_cancel.setStyleSheet(cancel_style)
        self.btn_apply.setStyleSheet(apply_style)

    # ---- Vision state ----

    def _on_vision_enabled_toggled(self, checked):
        """Toggle all vision config controls based on enable checkbox."""
        self._set_vision_controls_enabled(checked)
        if checked:
            self._sync_vision_same_as_main(
                self.chk_vision_same_as_main.isChecked()
            )

    def _set_vision_controls_enabled(self, enabled: bool):
        """Enable or disable all vision configuration widgets."""
        for w in [
            self.chk_vision_same_as_main,
            self.combo_vision_provider,
            self.edit_vision_url,
            self.edit_vision_key,
            self.edit_vision_model,
            self.spin_vision_max_tokens,
            self.spin_vision_temperature,
            self.btn_toggle_vision_key,
            self.btn_test_vision,
        ]:
            w.setEnabled(enabled)

    def _sync_vision_same_as_main(self, same_as_main: bool):
        if same_as_main:
            self.edit_vision_url.setText(self.edit_url.text())
            self.edit_vision_key.setText(self.edit_key.text())
        self.edit_vision_url.setEnabled(not same_as_main)
        self.edit_vision_key.setEnabled(not same_as_main)
        self.combo_vision_provider.setEnabled(not same_as_main)
        self.btn_toggle_vision_key.setEnabled(not same_as_main)

    def _on_vision_same_as_main_toggled(self, checked):
        if self.chk_vision_enabled.isChecked():
            self._sync_vision_same_as_main(checked)

    # ---- Load / Save ----

    def _load_current_values(self):
        self.edit_url.setText(_config.API_BASE_URL)
        self.edit_key.setText(_config.API_KEY)
        self.edit_model.setText(_config.MODEL_NAME)
        self.spin_max_tokens.setValue(_config.MAX_TOKENS)
        self.spin_max_iter.setValue(_config.MAX_ITERATIONS)

        # Match provider preset (by url + model)
        matched = False
        for i, p in enumerate(PROVIDER_PRESETS):
            if p["url"] == _config.API_BASE_URL and p["model"] == _config.MODEL_NAME:
                self.combo_provider.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            self.combo_provider.setCurrentIndex(len(PROVIDER_PRESETS) - 1)

        # Vision config
        vision_enabled = bool(_config.VISION_API_BASE_URL)
        self.chk_vision_enabled.setChecked(vision_enabled)
        self.edit_vision_url.setText(_config.VISION_API_BASE_URL)
        self.edit_vision_key.setText(_config.VISION_API_KEY)
        self.edit_vision_model.setText(_config.VISION_MODEL_NAME)
        self.spin_vision_max_tokens.setValue(_config.VISION_MAX_TOKENS)
        self.spin_vision_temperature.setValue(_config.VISION_TEMPERATURE)

        if vision_enabled:
            # Match vision provider preset
            for i, p in enumerate(VISION_PROVIDER_PRESETS):
                if (p["url"] == _config.VISION_API_BASE_URL
                        and p["model"] == _config.VISION_MODEL_NAME):
                    self.combo_vision_provider.setCurrentIndex(i)
                    break
            else:
                self.combo_vision_provider.setCurrentIndex(
                    len(VISION_PROVIDER_PRESETS) - 1
                )
            # Auto-detect "same as main"
            if (_config.VISION_API_BASE_URL == _config.API_BASE_URL
                    and _config.VISION_API_KEY == _config.API_KEY):
                self.chk_vision_same_as_main.setChecked(True)

        self._set_vision_controls_enabled(vision_enabled)

    def _on_provider_changed(self, index):
        if index < 0 or index >= len(PROVIDER_PRESETS):
            return
        preset = PROVIDER_PRESETS[index]
        if preset["name"] == "Custom":
            return
        self.edit_url.setText(preset["url"])
        self.edit_model.setText(preset["model"])

    def _on_toggle_key(self, checked):
        self._toggle_password(self.edit_key, self.btn_toggle_key)

    @staticmethod
    def _toggle_password(edit_widget, toggle_btn):
        if toggle_btn.isChecked():
            edit_widget.setEchoMode(QtWidgets.QLineEdit.Normal)
            toggle_btn.setText("Hide")
        else:
            edit_widget.setEchoMode(QtWidgets.QLineEdit.Password)
            toggle_btn.setText("Show")

    # ---- Test connection (async) ----

    def _start_test(self, btn, btn_label, title, endpoint, headers, payload, timeout):
        btn.setEnabled(False)
        btn.setText("Testing...")
        self._test_btn = btn
        self._test_btn_label = btn_label
        self._test_title = title
        self._test_worker = _TestWorker(endpoint, headers, payload, timeout)
        self._test_worker.success.connect(self._on_test_success)
        self._test_worker.error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_success(self, model_name):
        self._test_btn.setEnabled(True)
        self._test_btn.setText(self._test_btn_label)
        QtWidgets.QMessageBox.information(
            self, self._test_title,
            f"Connection successful!\n\nModel: {model_name}",
        )

    def _on_test_error(self, msg):
        self._test_btn.setEnabled(True)
        self._test_btn.setText(self._test_btn_label)
        QtWidgets.QMessageBox.critical(
            self, self._test_title,
            f"Connection failed: {msg}",
        )

    def _on_test_connection(self):
        url = self.edit_url.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "Test Connection", "API Base URL is empty.")
            return
        key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()

        endpoint = url.rstrip("/") + "/chat/completions"
        payload = json.dumps({
            "model": model or "test",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        self._start_test(
            self.btn_test, "Test Connection", "Test Connection",
            endpoint, headers, payload, timeout=15
        )

    def _on_vision_provider_changed(self, index):
        if index < 0 or index >= len(VISION_PROVIDER_PRESETS):
            return
        preset = VISION_PROVIDER_PRESETS[index]
        if preset["name"] == "Custom":
            return
        self.edit_vision_url.setText(preset["url"])
        self.edit_vision_model.setText(preset["model"])

    def _on_test_vision_connection(self):
        url = self.edit_vision_url.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(
                self, "Test Vision API", "Vision API Base URL is empty."
            )
            return
        key = self.edit_vision_key.text().strip()
        model = self.edit_vision_model.text().strip()

        endpoint = url.rstrip("/") + "/chat/completions"
        b64 = _make_test_png_b64()
        payload = json.dumps({
            "model": model or "test",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "ping"},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]
            }],
            "max_tokens": 5,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        self._start_test(
            self.btn_test_vision, "Test Vision API", "Test Vision API",
            endpoint, headers, payload, timeout=30
        )

    def _on_apply(self):
        url = self.edit_url.text().strip()
        key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()

        if not url:
            QtWidgets.QMessageBox.warning(self, "Validation", "API Base URL cannot be empty.")
            return
        if not key:
            QtWidgets.QMessageBox.warning(self, "Validation", "API Key cannot be empty.")
            return
        if not model:
            QtWidgets.QMessageBox.warning(self, "Validation", "Model Name cannot be empty.")
            return

        values = {
            "API_BASE_URL": url,
            "API_KEY": key,
            "MODEL_NAME": model,
            "MAX_TOKENS": str(self.spin_max_tokens.value()),
            "MAX_ITERATIONS": str(self.spin_max_iter.value()),
        }

        if self.chk_vision_enabled.isChecked():
            # Sync "same as main" before reading values
            if self.chk_vision_same_as_main.isChecked():
                self.edit_vision_url.setText(self.edit_url.text())
                self.edit_vision_key.setText(self.edit_key.text())
            v_url = self.edit_vision_url.text().strip()
            v_key = self.edit_vision_key.text().strip()
            v_model = self.edit_vision_model.text().strip()
            if not v_url or not v_key or not v_model:
                QtWidgets.QMessageBox.warning(
                    self, "Validation",
                    "Vision Model is enabled but fields are incomplete.\n"
                    "Fill all Vision fields or disable Vision Model."
                )
                return
            values["VISION_API_BASE_URL"] = v_url
            values["VISION_API_KEY"] = v_key
            values["VISION_MODEL_NAME"] = v_model
            values["VISION_MAX_TOKENS"] = str(
                self.spin_vision_max_tokens.value()
            )
            values["VISION_TEMPERATURE"] = str(
                self.spin_vision_temperature.value()
            )
        else:
            values["VISION_API_BASE_URL"] = ""
            values["VISION_API_KEY"] = ""
            values["VISION_MODEL_NAME"] = ""
            values["VISION_MAX_TOKENS"] = ""
            values["VISION_TEMPERATURE"] = ""

        _save_to_env(values)
        _config.reload(values)
        self.accept()
