"""API configuration and environment loading."""
from __future__ import annotations

import os

from core.text_utils import strip_markdown  # noqa: F401 — backward compat


_CFG_DEFAULTS = {
    "API_BASE_URL": "https://api.siliconflow.cn/v1",
    "API_KEY": "",
    "MODEL_NAME": "Pro/zai-org/GLM-5.1",
    "MAX_TOKENS": "4096",
    "TEMPERATURE": "0.1",
    "VISION_API_BASE_URL": "",
    "VISION_API_KEY": "",
    "VISION_MODEL_NAME": "",
    "VISION_MAX_TOKENS": "2048",
    "VISION_TEMPERATURE": "0.3",
    "VISION_TIMEOUT": "60",
}


class Config:
    """Encapsulated configuration state.

    Reads from os.environ (populated by .env file at startup).
    Call refresh() to re-derive values after environment changes.
    """

    def __init__(self):
        self.API_BASE_URL: str = ""
        self.API_KEY: str = ""
        self.MODEL_NAME: str = ""
        self.MAX_TOKENS: int = 0
        self.TEMPERATURE: float = 0.1
        self.MAX_ITERATIONS: int = 0
        self.MAX_SNAPSHOTS: int = 0
        self.MAX_CONTEXT_TOKENS: int = 0
        self.LLM_TIMEOUT: int = 0
        self.VALIDATE_VOLUME_THRESHOLD: float = 0.01
        self.VALIDATE_DIMENSION_THRESHOLD: float = 0.001
        self.VISION_API_BASE_URL: str = ""
        self.VISION_API_KEY: str = ""
        self.VISION_MODEL_NAME: str = ""
        self.VISION_MAX_TOKENS: int = 2048
        self.VISION_TEMPERATURE: float = 0.3
        self.VISION_TIMEOUT: int = 60
        self._cfg: dict = {}
        self.refresh()

    def refresh(self) -> dict:
        """Re-derive all values from os.environ."""
        self._cfg = {k: os.environ.get(k, v) for k, v in _CFG_DEFAULTS.items()}
        self.API_BASE_URL = self._cfg["API_BASE_URL"]
        self.API_KEY = self._cfg["API_KEY"]
        self.MODEL_NAME = self._cfg["MODEL_NAME"]
        self.MAX_TOKENS = int(self._cfg["MAX_TOKENS"])
        self.TEMPERATURE = float(self._cfg["TEMPERATURE"])
        self.MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "20"))
        self.MAX_SNAPSHOTS = int(os.environ.get("MAX_SNAPSHOTS", "10"))
        self.MAX_CONTEXT_TOKENS = int(os.environ.get("MAX_CONTEXT_TOKENS", "24000"))
        self.LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
        self.VISION_API_BASE_URL = self._cfg.get("VISION_API_BASE_URL", "")
        self.VISION_API_KEY = self._cfg.get("VISION_API_KEY", "")
        self.VISION_MODEL_NAME = self._cfg.get("VISION_MODEL_NAME", "")
        self.VISION_MAX_TOKENS = int(os.environ.get("VISION_MAX_TOKENS", "2048"))
        self.VISION_TEMPERATURE = float(os.environ.get("VISION_TEMPERATURE", "0.3"))
        self.VISION_TIMEOUT = int(os.environ.get("VISION_TIMEOUT", "60"))
        return dict(self._cfg)


def _load_env() -> dict:
    """从 .env 文件加载配置到环境变量（不覆盖已有值），然后返回配置字典。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
    return {k: os.environ.get(k, v) for k, v in _CFG_DEFAULTS.items()}


# ---------------------------------------------------------------------------
# Module-level singleton + convenience constants (backward compatible)
# ---------------------------------------------------------------------------

_load_env()

_default_config = Config()

# Expose as module-level constants so `import core.config as _config; _config.X` works
API_BASE_URL = _default_config.API_BASE_URL
API_KEY = _default_config.API_KEY
MODEL_NAME = _default_config.MODEL_NAME
MAX_TOKENS = _default_config.MAX_TOKENS
TEMPERATURE = _default_config.TEMPERATURE
MAX_ITERATIONS = _default_config.MAX_ITERATIONS
MAX_SNAPSHOTS = _default_config.MAX_SNAPSHOTS
MAX_CONTEXT_TOKENS = _default_config.MAX_CONTEXT_TOKENS
LLM_TIMEOUT = _default_config.LLM_TIMEOUT
VALIDATE_VOLUME_THRESHOLD = _default_config.VALIDATE_VOLUME_THRESHOLD
VALIDATE_DIMENSION_THRESHOLD = _default_config.VALIDATE_DIMENSION_THRESHOLD
VISION_API_BASE_URL = _default_config.VISION_API_BASE_URL
VISION_API_KEY = _default_config.VISION_API_KEY
VISION_MODEL_NAME = _default_config.VISION_MODEL_NAME
VISION_MAX_TOKENS = _default_config.VISION_MAX_TOKENS
VISION_TEMPERATURE = _default_config.VISION_TEMPERATURE
VISION_TIMEOUT = _default_config.VISION_TIMEOUT


def _refresh_constants():
    """Re-derive module-level constants from the default Config instance."""
    global API_BASE_URL, API_KEY, MODEL_NAME, MAX_TOKENS, TEMPERATURE
    global MAX_ITERATIONS, MAX_SNAPSHOTS, MAX_CONTEXT_TOKENS, LLM_TIMEOUT
    global VALIDATE_VOLUME_THRESHOLD, VALIDATE_DIMENSION_THRESHOLD
    global VISION_API_BASE_URL, VISION_API_KEY, VISION_MODEL_NAME
    global VISION_MAX_TOKENS, VISION_TEMPERATURE, VISION_TIMEOUT
    _default_config.refresh()
    API_BASE_URL = _default_config.API_BASE_URL
    API_KEY = _default_config.API_KEY
    MODEL_NAME = _default_config.MODEL_NAME
    MAX_TOKENS = _default_config.MAX_TOKENS
    TEMPERATURE = _default_config.TEMPERATURE
    MAX_ITERATIONS = _default_config.MAX_ITERATIONS
    MAX_SNAPSHOTS = _default_config.MAX_SNAPSHOTS
    MAX_CONTEXT_TOKENS = _default_config.MAX_CONTEXT_TOKENS
    LLM_TIMEOUT = _default_config.LLM_TIMEOUT
    VALIDATE_VOLUME_THRESHOLD = _default_config.VALIDATE_VOLUME_THRESHOLD
    VALIDATE_DIMENSION_THRESHOLD = _default_config.VALIDATE_DIMENSION_THRESHOLD
    VISION_API_BASE_URL = _default_config.VISION_API_BASE_URL
    VISION_API_KEY = _default_config.VISION_API_KEY
    VISION_MODEL_NAME = _default_config.VISION_MODEL_NAME
    VISION_MAX_TOKENS = _default_config.VISION_MAX_TOKENS
    VISION_TEMPERATURE = _default_config.VISION_TEMPERATURE
    VISION_TIMEOUT = _default_config.VISION_TIMEOUT


def vision_enabled() -> bool:
    """Return True if all three vision config values are non-empty."""
    return bool(VISION_API_BASE_URL and VISION_API_KEY and VISION_MODEL_NAME)


def reload(new_values: dict = None) -> dict:
    """Reload configuration from .env or apply new values.

    Updates os.environ and all module-level constants.
    Returns the updated config dict.
    """
    if new_values:
        for k, v in new_values.items():
            os.environ[k] = str(v)
    _refresh_constants()
    return dict(_default_config._cfg)
