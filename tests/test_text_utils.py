"""Tests for core/text_utils.py — strip_markdown."""
from __future__ import annotations

from tests.helpers import load_module

_mod = load_module("text_utils", "core", "text_utils.py")
strip_markdown = _mod.strip_markdown


def test_strip_python_block():
    result = strip_markdown("```python\nprint(1)\n```")
    assert result == "print(1)"


def test_strip_plain_block():
    result = strip_markdown("```\ncode here\n```")
    assert result == "code here"


def test_no_block():
    result = strip_markdown("just code")
    assert result == "just code"


def test_whitespace_handling():
    result = strip_markdown("  ```python\nprint(1)\n```  ")
    assert result == "print(1)"


def test_empty_string():
    assert strip_markdown("") == ""


def test_multiline_code():
    result = strip_markdown("```python\na = 1\nb = 2\n```")
    assert result == "a = 1\nb = 2"


def test_code_with_trailing_newline():
    result = strip_markdown("```python\nx = 42\n```\n")
    assert result == "x = 42"
