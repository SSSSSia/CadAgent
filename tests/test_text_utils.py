"""Tests for core/text_utils.py — strip_markdown."""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec = importlib.util.spec_from_file_location(
    "text_utils",
    os.path.join(os.path.dirname(__file__), "..", "core", "text_utils.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
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
