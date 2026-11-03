"""Language selection for ui/strings.py. No Qt or FreeCAD required."""
from __future__ import annotations

from ui.strings import _EN, _ZH, current_lang, t


def test_default_is_english(monkeypatch):
    monkeypatch.delenv("CADAGENT_LANG", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr("ui.strings._freecad_language", lambda: "")
    assert current_lang() == "en"
    assert t("stop") == "Stop"
    assert "Partial" in t("stopped_by_user")


def test_env_selects_chinese(monkeypatch):
    monkeypatch.setenv("CADAGENT_LANG", "zh")
    assert current_lang() == "zh"
    assert t("stop") == "停止"
    assert "已停止" in t("stopped_by_user")
    assert t("status_interrupted", elapsed="1.0s", iters=2, turns=1).startswith("已中断")


def test_env_english_overrides_lang(monkeypatch):
    monkeypatch.setenv("CADAGENT_LANG", "en")
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr("ui.strings._freecad_language", lambda: "Chinese")
    assert current_lang() == "en"
    assert t("send") == "Send"


def test_freecad_language_selects_chinese(monkeypatch):
    monkeypatch.delenv("CADAGENT_LANG", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr("ui.strings._freecad_language", lambda: "zh_CN")
    assert current_lang() == "zh"


def test_lang_env_selects_chinese_without_override(monkeypatch):
    monkeypatch.delenv("CADAGENT_LANG", raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr("ui.strings._freecad_language", lambda: "")
    assert current_lang() == "zh"


def test_tables_share_keys():
    assert set(_EN) == set(_ZH)
    assert "OD" in t("invalid_value_body", raw="x", name="OD")


def test_missing_key_falls_back_to_english(monkeypatch):
    monkeypatch.setenv("CADAGENT_LANG", "zh")
    assert t("this_key_does_not_exist") == "this_key_does_not_exist"
