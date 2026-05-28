"""Tests for core/config.py — .env loading, defaults, constants."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# Reload config to test cleanly
def _reload_config():
    import importlib
    import core.config
    importlib.reload(core.config)
    return core.config


class TestLoadEnv:
    def test_defaults_without_env_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("MODEL_NAME", raising=False)
        monkeypatch.delenv("MAX_TOKENS", raising=False)
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        config = _reload_config()
        assert config.API_BASE_URL == "https://api.siliconflow.cn/v1"
        assert config.API_KEY == ""
        assert config.MODEL_NAME == "Pro/zai-org/GLM-5.1"
        assert config.MAX_TOKENS == 4096

    def test_env_file_values(self, tmp_path, monkeypatch):
        monkeypatch.setenv("API_KEY", "sk-test123")
        monkeypatch.setenv("MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.API_KEY == "sk-test123"
        assert config.MODEL_NAME == "gpt-4o"

    def test_env_not_overwrite_existing(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "existing-key")
        config = _reload_config()
        assert config.API_KEY == "existing-key"
        monkeypatch.delenv("API_KEY")

    def test_env_skips_comments(self, tmp_path, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setattr("os.path.isfile", lambda p: str(p).endswith(".env"))
        config = _reload_config()
        assert "comment" not in config.API_KEY


class TestConstants:
    def test_max_iterations_default(self, monkeypatch):
        monkeypatch.delenv("MAX_ITERATIONS", raising=False)
        config = _reload_config()
        assert config.MAX_ITERATIONS == 20
        assert isinstance(config.MAX_ITERATIONS, int)

    def test_max_snapshots_default(self):
        config = _reload_config()
        assert config.MAX_SNAPSHOTS == 10

    def test_max_context_tokens_default(self):
        config = _reload_config()
        assert config.MAX_CONTEXT_TOKENS == 24000

    def test_llm_timeout_default(self):
        config = _reload_config()
        assert config.LLM_TIMEOUT == 180

    def test_validation_thresholds(self):
        config = _reload_config()
        assert config.VALIDATE_VOLUME_THRESHOLD == 0.01
        assert config.VALIDATE_DIMENSION_THRESHOLD == 0.001

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MAX_ITERATIONS", "20")
        config = _reload_config()
        assert config.MAX_ITERATIONS == 20
        monkeypatch.delenv("MAX_ITERATIONS")

    def test_strip_markdown_backward_compat(self):
        """strip_markdown is re-exported from config for backward compat."""
        config = _reload_config()
        assert callable(config.strip_markdown)
        assert config.strip_markdown("```python\nx=1\n```") == "x=1"


class TestVisionConfig:
    def test_vision_defaults_empty(self, monkeypatch):
        monkeypatch.delenv("VISION_API_BASE_URL", raising=False)
        monkeypatch.delenv("VISION_API_KEY", raising=False)
        monkeypatch.delenv("VISION_MODEL_NAME", raising=False)
        config = _reload_config()
        assert config.VISION_API_BASE_URL == ""
        assert config.VISION_API_KEY == ""
        assert config.VISION_MODEL_NAME == ""

    def test_vision_env_override(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-vision-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.VISION_API_BASE_URL == "https://api.example.com/v1"
        assert config.VISION_API_KEY == "sk-vision-test"
        assert config.VISION_MODEL_NAME == "gpt-4o"
        monkeypatch.delenv("VISION_API_BASE_URL")
        monkeypatch.delenv("VISION_API_KEY")
        monkeypatch.delenv("VISION_MODEL_NAME")

    def test_vision_enabled_false_when_empty(self, monkeypatch):
        monkeypatch.delenv("VISION_API_BASE_URL", raising=False)
        monkeypatch.delenv("VISION_API_KEY", raising=False)
        monkeypatch.delenv("VISION_MODEL_NAME", raising=False)
        config = _reload_config()
        assert config.vision_enabled() is False

    def test_vision_enabled_true(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-vision-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.vision_enabled() is True
        monkeypatch.delenv("VISION_API_BASE_URL")
        monkeypatch.delenv("VISION_API_KEY")
        monkeypatch.delenv("VISION_MODEL_NAME")

    def test_vision_enabled_false_partial(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.vision_enabled() is False
        monkeypatch.delenv("VISION_API_BASE_URL")
        monkeypatch.delenv("VISION_API_KEY")
        monkeypatch.delenv("VISION_MODEL_NAME")

    def test_vision_max_tokens_default(self, monkeypatch):
        monkeypatch.delenv("VISION_MAX_TOKENS", raising=False)
        config = _reload_config()
        assert config.VISION_MAX_TOKENS == 2048

    def test_vision_temperature_default(self, monkeypatch):
        monkeypatch.delenv("VISION_TEMPERATURE", raising=False)
        config = _reload_config()
        assert config.VISION_TEMPERATURE == 0.3

    def test_vision_timeout_default(self, monkeypatch):
        monkeypatch.delenv("VISION_TIMEOUT", raising=False)
        config = _reload_config()
        assert config.VISION_TIMEOUT == 60

    def test_vision_params_env_override(self, monkeypatch):
        monkeypatch.setenv("VISION_MAX_TOKENS", "4096")
        monkeypatch.setenv("VISION_TEMPERATURE", "0.7")
        monkeypatch.setenv("VISION_TIMEOUT", "120")
        config = _reload_config()
        assert config.VISION_MAX_TOKENS == 4096
        assert config.VISION_TEMPERATURE == 0.7
        assert config.VISION_TIMEOUT == 120
        monkeypatch.delenv("VISION_MAX_TOKENS")
        monkeypatch.delenv("VISION_TEMPERATURE")
        monkeypatch.delenv("VISION_TIMEOUT")
