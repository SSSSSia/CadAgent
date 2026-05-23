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
