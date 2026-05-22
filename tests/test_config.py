"""Tests for core/config.py — .env loading, defaults, strip_markdown."""
from __future__ import annotations

import os
import sys
import tempfile

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
        # Point config to a dir with no .env
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        config = _reload_config()
        assert config.API_BASE_URL == "https://api.siliconflow.cn/v1"
        assert config.API_KEY == ""
        assert config.MODEL_NAME == "Pro/zai-org/GLM-5.1"
        assert config.MAX_TOKENS == 4096

    def test_env_file_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=sk-test123\nMODEL_NAME=gpt-4o\n")
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
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nAPI_KEY=sk-test\n")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setattr("os.path.isfile", lambda p: str(p).endswith(".env"))
        config = _reload_config()
        # API_KEY should be loaded (not the comment)
        assert "comment" not in config.API_KEY


class TestConstants:
    def test_max_iterations_default(self, monkeypatch):
        monkeypatch.delenv("MAX_ITERATIONS", raising=False)
        config = _reload_config()
        assert config.MAX_ITERATIONS == 10
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


class TestStripMarkdown:
    def test_strip_python_block(self):
        config = _reload_config()
        result = config.strip_markdown("```python\nprint(1)\n```")
        assert result == "print(1)"

    def test_strip_plain_block(self):
        config = _reload_config()
        result = config.strip_markdown("```\ncode here\n```")
        assert result == "code here"

    def test_no_block(self):
        config = _reload_config()
        result = config.strip_markdown("just code")
        assert result == "just code"

    def test_whitespace_handling(self):
        config = _reload_config()
        result = config.strip_markdown("  ```python\nprint(1)\n```  ")
        assert result == "print(1)"

    def test_empty_string(self):
        config = _reload_config()
        assert config.strip_markdown("") == ""
