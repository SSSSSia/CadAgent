"""Settings dialog for CadAgent — configure API, model, and agent parameters."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request

from PySide6 import QtCore, QtWidgets

import core.config as _config


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

class SettingsDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CadAgent Settings")
        self.setMinimumWidth(460)
        self.setModal(True)
        self._setup_ui()
        self._load_current_values()

    # ---- UI construction ----

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- Provider preset ---
        preset_group = QtWidgets.QGroupBox("Provider Preset")
        preset_layout = QtWidgets.QHBoxLayout(preset_group)
        self.combo_provider = QtWidgets.QComboBox()
        for p in PROVIDER_PRESETS:
            self.combo_provider.addItem(p["name"])
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        preset_layout.addWidget(self.combo_provider)
        layout.addWidget(preset_group)

        # --- API Configuration ---
        api_group = QtWidgets.QGroupBox("API Configuration")
        api_form = QtWidgets.QFormLayout(api_group)
        api_form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.edit_url = QtWidgets.QLineEdit()
        self.edit_url.setPlaceholderText("https://api.example.com/v1")
        api_form.addRow("API Base URL:", self.edit_url)

        key_row = QtWidgets.QHBoxLayout()
        self.edit_key = QtWidgets.QLineEdit()
        self.edit_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_key.setPlaceholderText("sk-...")
        key_row.addWidget(self.edit_key, 1)
        self.btn_toggle_key = QtWidgets.QPushButton("Show")
        self.btn_toggle_key.setFixedWidth(50)
        self.btn_toggle_key.setCheckable(True)
        self.btn_toggle_key.clicked.connect(self._on_toggle_key)
        key_row.addWidget(self.btn_toggle_key)
        api_form.addRow("API Key:", key_row)

        self.edit_model = QtWidgets.QLineEdit()
        self.edit_model.setPlaceholderText("model-name")
        api_form.addRow("Model Name:", self.edit_model)

        layout.addWidget(api_group)

        # --- Agent Parameters ---
        agent_group = QtWidgets.QGroupBox("Agent Parameters")
        agent_form = QtWidgets.QFormLayout(agent_group)
        agent_form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.spin_max_tokens = QtWidgets.QSpinBox()
        self.spin_max_tokens.setRange(256, 32768)
        self.spin_max_tokens.setSingleStep(256)
        self.spin_max_tokens.setToolTip("Maximum output tokens per LLM request")
        agent_form.addRow("Max Tokens:", self.spin_max_tokens)

        self.spin_max_iter = QtWidgets.QSpinBox()
        self.spin_max_iter.setRange(1, 50)
        self.spin_max_iter.setToolTip("Maximum agent loop iterations")
        agent_form.addRow("Max Iterations:", self.spin_max_iter)

        layout.addWidget(agent_group)

        # --- Vision Model (optional) ---
        self.vision_group = QtWidgets.QGroupBox("Vision Model (Optional)")
        self.vision_group.setCheckable(True)
        self.vision_group.setChecked(False)
        vision_form = QtWidgets.QFormLayout(self.vision_group)
        vision_form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.chk_vision_same_as_main = QtWidgets.QCheckBox(
            "Use same API as main model"
        )
        self.chk_vision_same_as_main.setToolTip(
            "Auto-fill Vision API URL and Key from the main API configuration"
        )
        self.chk_vision_same_as_main.toggled.connect(
            self._on_vision_same_as_main_toggled
        )
        vision_form.addRow("", self.chk_vision_same_as_main)

        self.combo_vision_provider = QtWidgets.QComboBox()
        for p in VISION_PROVIDER_PRESETS:
            self.combo_vision_provider.addItem(p["name"])
        self.combo_vision_provider.currentIndexChanged.connect(
            self._on_vision_provider_changed
        )
        vision_form.addRow("Provider:", self.combo_vision_provider)

        self.edit_vision_url = QtWidgets.QLineEdit()
        self.edit_vision_url.setPlaceholderText("https://api.example.com/v1")
        vision_form.addRow("API Base URL:", self.edit_vision_url)

        vision_key_row = QtWidgets.QHBoxLayout()
        self.edit_vision_key = QtWidgets.QLineEdit()
        self.edit_vision_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_vision_key.setPlaceholderText("sk-...")
        vision_key_row.addWidget(self.edit_vision_key, 1)
        self.btn_toggle_vision_key = QtWidgets.QPushButton("Show")
        self.btn_toggle_vision_key.setFixedWidth(50)
        self.btn_toggle_vision_key.setCheckable(True)
        self.btn_toggle_vision_key.clicked.connect(
            lambda checked: self._toggle_password(
                self.edit_vision_key, self.btn_toggle_vision_key
            )
        )
        vision_key_row.addWidget(self.btn_toggle_vision_key)
        vision_form.addRow("API Key:", vision_key_row)

        self.edit_vision_model = QtWidgets.QLineEdit()
        self.edit_vision_model.setPlaceholderText("vision-model-name")
        vision_form.addRow("Model Name:", self.edit_vision_model)

        self.spin_vision_max_tokens = QtWidgets.QSpinBox()
        self.spin_vision_max_tokens.setRange(256, 16384)
        self.spin_vision_max_tokens.setSingleStep(256)
        self.spin_vision_max_tokens.setToolTip(
            "Maximum output tokens per vision API request"
        )
        vision_form.addRow("Max Tokens:", self.spin_vision_max_tokens)

        self.spin_vision_temperature = QtWidgets.QDoubleSpinBox()
        self.spin_vision_temperature.setRange(0.0, 2.0)
        self.spin_vision_temperature.setSingleStep(0.1)
        self.spin_vision_temperature.setDecimals(2)
        self.spin_vision_temperature.setToolTip(
            "Temperature for vision model responses"
        )
        vision_form.addRow("Temperature:", self.spin_vision_temperature)

        self.btn_test_vision = QtWidgets.QPushButton("Test Vision API")
        self.btn_test_vision.setStyleSheet(
            "QPushButton{padding:6px 14px;border-radius:3px}"
        )
        self.btn_test_vision.clicked.connect(self._on_test_vision_connection)
        vision_form.addRow("", self.btn_test_vision)

        layout.addWidget(self.vision_group)

        # --- Buttons ---
        btn_row = QtWidgets.QHBoxLayout()

        self.btn_test = QtWidgets.QPushButton("Test Connection")
        self.btn_test.setStyleSheet(
            "QPushButton{padding:6px 14px;border-radius:3px}"
        )
        self.btn_test.clicked.connect(self._on_test_connection)
        btn_row.addWidget(self.btn_test)

        btn_row.addStretch()

        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("padding:6px 14px")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_apply = QtWidgets.QPushButton("Apply")
        self.btn_apply.setStyleSheet(
            "QPushButton{background:#4a90d9;color:white;padding:6px 16px;"
            "border-radius:3px;font-weight:bold}"
            "QPushButton:hover{background:#357abd}"
        )
        self.btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self.btn_apply)

        layout.addLayout(btn_row)

        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(
            "QDialog { font-family: 'Segoe UI', sans-serif; font-size: 13px; }"
            "QGroupBox { font-weight: bold; border: 1px solid #ddd; "
            "  border-radius: 4px; margin-top: 8px; padding-top: 14px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
            "QLineEdit { padding: 5px 8px; border: 1px solid #ddd; border-radius: 3px; }"
            "QSpinBox { padding: 5px 8px; border: 1px solid #ddd; border-radius: 3px; }"
            "QComboBox { padding: 5px 8px; border: 1px solid #ddd; border-radius: 3px; }"
        )

    # ---- Load / Save ----

    def _load_current_values(self):
        self.edit_url.setText(_config.API_BASE_URL)
        self.edit_key.setText(_config.API_KEY)
        self.edit_model.setText(_config.MODEL_NAME)
        self.spin_max_tokens.setValue(_config.MAX_TOKENS)
        self.spin_max_iter.setValue(_config.MAX_ITERATIONS)

        # Match provider preset (by url + model)
        for i, p in enumerate(PROVIDER_PRESETS):
            if p["url"] == _config.API_BASE_URL and p["model"] == _config.MODEL_NAME:
                self.combo_provider.setCurrentIndex(i)
                return
        # No match — set to Custom
        self.combo_provider.setCurrentIndex(len(PROVIDER_PRESETS) - 1)

        # Vision config
        if _config.VISION_API_BASE_URL:
            self.vision_group.setChecked(True)
            self.edit_vision_url.setText(_config.VISION_API_BASE_URL)
            self.edit_vision_key.setText(_config.VISION_API_KEY)
            self.edit_vision_model.setText(_config.VISION_MODEL_NAME)
            for i, p in enumerate(VISION_PROVIDER_PRESETS):
                if (p["url"] == _config.VISION_API_BASE_URL
                        and p["model"] == _config.VISION_MODEL_NAME):
                    self.combo_vision_provider.setCurrentIndex(i)
                    break
            else:
                self.combo_vision_provider.setCurrentIndex(
                    len(VISION_PROVIDER_PRESETS) - 1
                )
            # Auto-detect "same as main" if URL and Key match
            if (_config.VISION_API_BASE_URL == _config.API_BASE_URL
                    and _config.VISION_API_KEY == _config.API_KEY):
                self.chk_vision_same_as_main.setChecked(True)
        else:
            self.vision_group.setChecked(False)

        self.spin_vision_max_tokens.setValue(_config.VISION_MAX_TOKENS)
        self.spin_vision_temperature.setValue(_config.VISION_TEMPERATURE)

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
        """Toggle password visibility for a QLineEdit."""
        if toggle_btn.isChecked():
            edit_widget.setEchoMode(QtWidgets.QLineEdit.Normal)
            toggle_btn.setText("Hide")
        else:
            edit_widget.setEchoMode(QtWidgets.QLineEdit.Password)
            toggle_btn.setText("Show")

    def _on_test_connection(self):
        url = self.edit_url.text().strip()
        key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()

        if not url:
            QtWidgets.QMessageBox.warning(self, "Test Connection", "API Base URL is empty.")
            return

        self.btn_test.setEnabled(False)
        self.btn_test.setText("Testing...")

        try:
            endpoint = url.rstrip("/") + "/chat/completions"
            payload = json.dumps({
                "model": model or "test",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(endpoint, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                model_used = data.get("model", model)
                QtWidgets.QMessageBox.information(
                    self, "Test Connection",
                    f"Connection successful!\n\nModel: {model_used}",
                )
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            QtWidgets.QMessageBox.critical(
                self, "Test Connection",
                f"Connection failed: HTTP {e.code} {e.reason}\n\n{body}",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Test Connection",
                f"Connection failed: {type(e).__name__}: {e}",
            )
        finally:
            self.btn_test.setEnabled(True)
            self.btn_test.setText("Test Connection")

    def _on_vision_provider_changed(self, index):
        if index < 0 or index >= len(VISION_PROVIDER_PRESETS):
            return
        preset = VISION_PROVIDER_PRESETS[index]
        if preset["name"] == "Custom":
            return
        self.edit_vision_url.setText(preset["url"])
        self.edit_vision_model.setText(preset["model"])

    def _on_vision_same_as_main_toggled(self, checked):
        if checked:
            self.edit_vision_url.setText(self.edit_url.text())
            self.edit_vision_key.setText(self.edit_key.text())
            self.edit_vision_url.setEnabled(False)
            self.edit_vision_key.setEnabled(False)
            self.combo_vision_provider.setEnabled(False)
        else:
            self.edit_vision_url.setEnabled(True)
            self.edit_vision_key.setEnabled(True)
            self.combo_vision_provider.setEnabled(True)

    def _on_test_vision_connection(self):
        url = self.edit_vision_url.text().strip()
        key = self.edit_vision_key.text().strip()
        model = self.edit_vision_model.text().strip()

        if not url:
            QtWidgets.QMessageBox.warning(
                self, "Test Vision API", "Vision API Base URL is empty."
            )
            return

        self.btn_test_vision.setEnabled(False)
        self.btn_test_vision.setText("Testing...")

        try:
            endpoint = url.rstrip("/") + "/chat/completions"
            import base64
            tiny_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
                b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
                b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            b64 = base64.b64encode(tiny_png).decode("ascii")
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
            req = urllib.request.Request(endpoint, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                model_used = data.get("model", model)
                QtWidgets.QMessageBox.information(
                    self, "Test Vision API",
                    f"Vision API connection successful!\n\nModel: {model_used}",
                )
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            QtWidgets.QMessageBox.critical(
                self, "Test Vision API",
                f"Connection failed: HTTP {e.code} {e.reason}\n\n{body}",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Test Vision API",
                f"Connection failed: {type(e).__name__}: {e}",
            )
        finally:
            self.btn_test_vision.setEnabled(True)
            self.btn_test_vision.setText("Test Vision API")

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

        if self.vision_group.isChecked():
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
                    "Fill all Vision fields or uncheck Vision Model."
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
