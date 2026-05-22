"""Tests for ui/chat_renderer.py — esc, _esc_html, markdown_to_html."""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec = importlib.util.spec_from_file_location(
    "chat_renderer",
    os.path.join(os.path.dirname(__file__), "..", "ui", "chat_renderer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
esc = _mod.esc
_esc_html = _mod._esc_html
markdown_to_html = _mod.markdown_to_html


# ---- _esc_html ----

def test_esc_html_special_chars():
    assert _esc_html("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_esc_html_no_newline_conversion():
    assert _esc_html("line1\nline2") == "line1\nline2"


def test_esc_html_empty():
    assert _esc_html("") == ""


# ---- esc ----

def test_esc_newlines():
    assert esc("line1\nline2") == "line1<br>line2"


def test_esc_xss():
    result = esc("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_esc_ampersand():
    assert esc("a & b") == "a &amp; b"


# ---- markdown_to_html ----

def test_plain_text():
    result = markdown_to_html("Hello world")
    assert "Hello world" in result


def test_headers():
    assert "<h3" in markdown_to_html("## Title")
    assert "<h4" in markdown_to_html("### Subtitle")


def test_bold():
    result = markdown_to_html("This is **bold** text")
    assert "<b>bold</b>" in result


def test_inline_code():
    result = markdown_to_html("Use `print()` here")
    assert "<code" in result
    assert "print()" in result


def test_code_block():
    result = markdown_to_html("```python\nprint(1)\n```")
    assert "<pre" in result
    assert "print(1)" in result


def test_code_block_escapes_html():
    result = markdown_to_html("```\n<div>test</div>\n```")
    assert "&lt;div&gt;" in result
    assert "<div>" not in result.replace("&lt;div&gt;", "")


def test_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    result = markdown_to_html(md)
    assert "<table" in result
    assert "<th" in result
    assert "<td" in result


def test_unordered_list():
    result = markdown_to_html("- item1\n- item2")
    assert "<ul" in result
    assert "<li>item1</li>" in result
    assert "<li>item2</li>" in result


def test_ordered_list():
    result = markdown_to_html("1. first\n2. second")
    assert "<ol" in result
    assert "<li>first</li>" in result


def test_horizontal_rule():
    result = markdown_to_html("---")
    assert "<hr>" in result


def test_xss_prevention():
    result = markdown_to_html('<script>alert("xss")</script>')
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_empty_input():
    assert markdown_to_html("") == ""


def test_mixed_content():
    md = "## Title\n\nSome **bold** and `code`\n\n- item1\n- item2"
    result = markdown_to_html(md)
    assert "<h3" in result
    assert "<b>bold</b>" in result
    assert "<code" in result
    assert "<ul" in result
