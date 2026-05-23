"""API configuration and environment loading."""
from __future__ import annotations

import os
import re


def _load_env() -> dict:
    """从 .env 文件加载配置到环境变量（不覆盖已有值），然后返回配置字典。"""
    defaults = {
        "API_BASE_URL": "https://api.siliconflow.cn/v1",
        "API_KEY": "",
        "MODEL_NAME": "Pro/zai-org/GLM-5.1",
        "MAX_TOKENS": "4096",
    }
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
    return {k: os.environ.get(k, v) for k, v in defaults.items()}


_CFG_DEFAULTS = {
    "API_BASE_URL": "https://api.siliconflow.cn/v1",
    "API_KEY": "",
    "MODEL_NAME": "Pro/zai-org/GLM-5.1",
    "MAX_TOKENS": "4096",
}


def _apply_env(cfg: dict):
    """从 cfg dict 设置 os.environ（不覆盖已有值）。"""
    for k, v in cfg.items():
        if k not in os.environ:
            os.environ[k] = v


def _refresh_constants():
    """Re-derive all module-level constants from os.environ."""
    global API_BASE_URL, API_KEY, MODEL_NAME, MAX_TOKENS, _cfg
    global MAX_ITERATIONS, MAX_SNAPSHOTS, MAX_CONTEXT_TOKENS, LLM_TIMEOUT
    _cfg = {k: os.environ.get(k, v) for k, v in _CFG_DEFAULTS.items()}
    API_BASE_URL = _cfg["API_BASE_URL"]
    API_KEY = _cfg["API_KEY"]
    MODEL_NAME = _cfg["MODEL_NAME"]
    MAX_TOKENS = int(_cfg["MAX_TOKENS"])
    MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "20"))
    MAX_SNAPSHOTS = int(os.environ.get("MAX_SNAPSHOTS", "10"))
    MAX_CONTEXT_TOKENS = int(os.environ.get("MAX_CONTEXT_TOKENS", "24000"))
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))


# Initial load
_apply_env(_load_env())
_cfg = {}
_refresh_constants()


def reload(new_values: dict = None) -> dict:
    """Reload configuration from .env or apply new values.

    Updates os.environ and all module-level constants.
    Returns the updated config dict.
    """
    if new_values:
        for k, v in new_values.items():
            os.environ[k] = str(v)
    _refresh_constants()
    return dict(_cfg)


# --- Validation thresholds ---
VALIDATE_VOLUME_THRESHOLD = 0.01
VALIDATE_DIMENSION_THRESHOLD = 0.001


def strip_markdown(text: str) -> str:
    """去掉 LLM 输出中可能包裹的 markdown 代码块标记。"""
    text = text.strip()
    text = re.sub(r"^```(?:python)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()
