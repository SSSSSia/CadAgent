"""Tests for core/config.py — .env loading, defaults, constants."""
from __future__ import annotations

import os

from tests.helpers import reload_config as _reload_isolated


def _reload_config():
    """Plain reload — callers control the environment via monkeypatch.

    Used by TestLoadEnv/TestVisionConfig, whose assertions only touch keys
    they set explicitly. TestConstants uses _reload_isolated instead so it
    never depends on the developer's real .env (S0-E3).
    """
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
    """Defaults must hold regardless of the developer's real .env (S0-E3)."""

    def test_max_iterations_default(self):
        config = _reload_isolated()
        assert config.MAX_ITERATIONS == 20
        assert isinstance(config.MAX_ITERATIONS, int)

    def test_max_snapshots_default(self):
        config = _reload_isolated()
        assert config.MAX_SNAPSHOTS == 10

    def test_max_context_tokens_default(self):
        config = _reload_isolated()
        assert config.MAX_CONTEXT_TOKENS == 24000

    def test_llm_timeout_default(self):
        config = _reload_isolated()
        assert config.LLM_TIMEOUT == 180

    def test_validation_thresholds(self):
        config = _reload_isolated()
        assert config.VALIDATE_VOLUME_THRESHOLD == 0.01
        assert config.VALIDATE_DIMENSION_THRESHOLD == 0.001

    def test_env_override(self):
        config = _reload_isolated(env={"MAX_ITERATIONS": "30"})
        assert config.MAX_ITERATIONS == 30

    def test_strip_markdown_backward_compat(self):
        """strip_markdown is re-exported from config for backward compat."""
        config = _reload_isolated()
        assert callable(config.strip_markdown)
        assert config.strip_markdown("```python\nx=1\n```") == "x=1"


class TestVisionConfig:
    def test_vision_defaults_empty(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "")
        monkeypatch.setenv("VISION_API_KEY", "")
        monkeypatch.setenv("VISION_MODEL_NAME", "")
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

    def test_vision_enabled_false_when_empty(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "")
        monkeypatch.setenv("VISION_API_KEY", "")
        monkeypatch.setenv("VISION_MODEL_NAME", "")
        config = _reload_config()
        assert config.vision_enabled() is False

    def test_vision_enabled_true(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-vision-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.vision_enabled() is True

    def test_vision_enabled_false_partial(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        config = _reload_config()
        assert config.vision_enabled() is False

    def test_vision_max_tokens_default(self, monkeypatch):
        monkeypatch.setenv("VISION_MAX_TOKENS", "2048")
        config = _reload_config()
        assert config.VISION_MAX_TOKENS == 2048

    def test_vision_temperature_default(self, monkeypatch):
        monkeypatch.setenv("VISION_TEMPERATURE", "0.3")
        config = _reload_config()
        assert config.VISION_TEMPERATURE == 0.3

    def test_vision_timeout_default(self, monkeypatch):
        monkeypatch.setenv("VISION_TIMEOUT", "60")
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


class TestTolerantParsing:
    """S1-B1: blank/garbage numeric values must fall back to defaults,
    never crash the workbench at import or on Settings Apply."""

    def test_blank_and_garbage_values_fall_back_to_defaults(self):
        config = _reload_isolated(env={
            "MAX_TOKENS": "4O96",        # typo (letter O)
            "TEMPERATURE": "",
            "MAX_ITERATIONS": "  ",
            "MAX_SNAPSHOTS": "ten",
            "MAX_CONTEXT_TOKENS": "",
            "LLM_TIMEOUT": "-",
            "VISION_MAX_TOKENS": "",
            "VISION_TEMPERATURE": "",
            "VISION_TIMEOUT": "nan-ish",
        })
        assert config.MAX_TOKENS == 4096
        assert config.TEMPERATURE == 0.1
        assert config.MAX_ITERATIONS == 20
        assert config.MAX_SNAPSHOTS == 10
        assert config.MAX_CONTEXT_TOKENS == 24000
        assert config.LLM_TIMEOUT == 180
        assert config.VISION_MAX_TOKENS == 2048
        assert config.VISION_TEMPERATURE == 0.3
        assert config.VISION_TIMEOUT == 60

    def test_valid_string_values_still_parse(self):
        config = _reload_isolated(env={
            "MAX_TOKENS": "8192",
            "TEMPERATURE": "0.7",
            "LLM_TIMEOUT": " 60 ",
        })
        assert config.MAX_TOKENS == 8192
        assert config.TEMPERATURE == 0.7
        assert config.LLM_TIMEOUT == 60


class TestLoadEnvFile:
    """S1-B3: BOM and quoted values in .env files."""

    def test_bom_and_quotes(self, tmp_path, monkeypatch):
        import core.config as cfg_mod
        env_file = tmp_path / ".env"
        # utf-8-sig BOM + quoted value + plain value
        env_file.write_bytes(
            b"\xef\xbb\xbfAPI_KEY=\"sk-quoted\"\nMODEL_NAME=plain-model\n"
        )
        for key in ("API_KEY", "MODEL_NAME"):
            monkeypatch.delenv(key, raising=False)
        try:
            cfg_mod._load_env(str(env_file))
            assert os.environ["API_KEY"] == "sk-quoted"
            assert os.environ["MODEL_NAME"] == "plain-model"
        finally:
            for key in ("API_KEY", "MODEL_NAME"):
                monkeypatch.delenv(key, raising=False)

    def test_existing_env_not_overwritten(self, tmp_path, monkeypatch):
        import core.config as cfg_mod
        env_file = tmp_path / ".env"
        env_file.write_text("API_KEY=from-file\n", encoding="utf-8")
        monkeypatch.setenv("API_KEY", "from-env")
        try:
            cfg_mod._load_env(str(env_file))
            assert os.environ["API_KEY"] == "from-env"
        finally:
            monkeypatch.delenv("API_KEY", raising=False)
