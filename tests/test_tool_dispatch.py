"""Tests for agent/tool_dispatch.py — dispatch routing without FreeCAD."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tool_dispatch import dispatch_tool, register_tool, available_tools


def test_unknown_tool_returns_error():
    result = dispatch_tool("nonexistent_tool", "{}")
    assert result.startswith("ERROR")
    assert "nonexistent_tool" in result
    assert "Unknown" in result


def test_dispatch_calls_handler():
    def _handler(args_json):
        return f"handled: {args_json}"
    register_tool("test_tool", _handler)
    result = dispatch_tool("test_tool", '{"key": "val"}')
    assert result == 'handled: {"key": "val"}'


def test_dispatch_catches_handler_exception():
    def _bad_handler(args_json):
        raise ValueError("oops")
    register_tool("bad_tool", _bad_handler)
    result = dispatch_tool("bad_tool", "{}")
    assert result.startswith("ERROR")
    assert "ValueError" in result
    assert "oops" in result


def test_available_tools_lists_registered():
    register_tool("_test_avail", lambda x: "ok")
    assert "_test_avail" in available_tools()


def test_handler_receives_raw_json():
    received = []
    register_tool("_test_capture", lambda x: received.append(x) or "ok")
    dispatch_tool("_test_capture", '{"a": 1}')
    assert received == ['{"a": 1}']


def test_error_prefix_handler():
    """Handlers returning ERROR-prefixed strings are passed through."""
    register_tool("_test_err", lambda x: "ERROR: something failed")
    result = dispatch_tool("_test_err", "{}")
    assert result == "ERROR: something failed"


def test_fail_prefix_handler():
    register_tool("_test_fail", lambda x: "FAIL: validation failed")
    result = dispatch_tool("_test_fail", "{}")
    assert result == "FAIL: validation failed"
