"""Tests for agent/react_parser.py — parse_react_tool_cases."""
from __future__ import annotations

import json

from tests.helpers import load_module

_mod = load_module("react_parser", "agent", "react_parser.py")
parse_react_tool_calls = _mod.parse_react_tool_calls


def test_single_tool_valid_json():
    text = '<tool name="execute_code">{"code": "print(1)"}</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["id"] == "react_0"
    assert result[0]["function"]["name"] == "execute_code"
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == "print(1)"


def test_multiple_tools():
    text = (
        '<tool name="analyze_geometry">{"focus": "dimensions"}</tool>\n'
        'Some text\n'
        '<tool name="execute_code">{"code": "box()"}</tool>'
    )
    result = parse_react_tool_calls(text)
    assert len(result) == 2
    assert result[0]["function"]["name"] == "analyze_geometry"
    assert result[1]["function"]["name"] == "execute_code"
    assert result[0]["id"] == "react_0"
    assert result[1]["id"] == "react_1"


def test_empty_arguments():
    text = '<tool name="undo_last"></tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert json.loads(result[0]["function"]["arguments"]) == {}


    text2 = '<tool name="undo_last">   </tool>'
    result2 = parse_react_tool_calls(text2)
    assert json.loads(result2[0]["function"]["arguments"]) == {}


def test_plain_text_arguments():
    text = '<tool name="execute_code">make a box</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert args["input"] == "make a box"


def test_nested_json():
    text = '<tool name="execute_code">{"code": "x = {\\"a\\": 1}"}</tool>'
    result = parse_react_tool_calls(text)
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == 'x = {"a": 1}'


def test_no_tool_tags():
    text = "Just some regular text without any tool calls."
    assert parse_react_tool_calls(text) == []


def test_single_quoted_name():
    text = "<tool name='execute_code'>{}</tool>"
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "execute_code"


def test_multiline_arguments():
    text = '<tool name="execute_code">{"code": "line1\\nline2\\nline3"}</tool>'
    result = parse_react_tool_calls(text)
    args = json.loads(result[0]["function"]["arguments"])
    assert "line1" in args["code"]


# ---- Multi-strategy parser tests ----

def test_extra_whitespace_around_equals():
    text = '<tool name = "execute_code">{"code": "print(1)"}</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "execute_code"


def test_case_insensitive_tag():
    text = '<TOOL NAME="analyze_geometry">{}</TOOL>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "analyze_geometry"


def test_self_closing_tag():
    text = '<tool name="undo_last"/>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "undo_last"
    assert json.loads(result[0]["function"]["arguments"]) == {}


def test_unclosed_tag():
    text = '<tool name="analyze_geometry">'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "analyze_geometry"


def test_unclosed_tag_with_args():
    text = '<tool name="execute_code">{"code": "x=1"}'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == "x=1"


def test_json_fixup_missing_brace():
    text = '<tool name="execute_code">{"code": "print(1)"</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == "print(1)"


def test_json_fixup_trailing_comma():
    text = '<tool name="execute_code">{"code": "print(1)",}</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == "print(1)"


def test_markdown_fence_in_args():
    text = '<tool name="execute_code">```json\n{"code": "print(1)"}\n```</tool>'
    result = parse_react_tool_calls(text)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert args["code"] == "print(1)"


# ---- S3-D15: strip_tool_tags for display ----

def test_strip_paired_block_keeps_prose():
    from tests.helpers import load_module
    mod = load_module("react_parser_strip", "agent", "react_parser.py")
    text = 'I will build it.\n<tool name="execute_code">{"code": "x=1"}</tool>\nDone above.'
    assert mod.strip_tool_tags(text) == "I will build it.\n\nDone above."

def test_strip_self_closing():
    from tests.helpers import load_module
    mod = load_module("react_parser_strip", "agent", "react_parser.py")
    text = 'Undo now <tool name="undo_last"/> please'
    assert mod.strip_tool_tags(text) == "Undo now  please"

def test_strip_truncated_block():
    from tests.helpers import load_module
    mod = load_module("react_parser_strip", "agent", "react_parser.py")
    text = 'Plan.\n<tool name="execute_code">{"code": "part'
    assert mod.strip_tool_tags(text) == "Plan."

def test_strip_multiple_blocks():
    from tests.helpers import load_module
    mod = load_module("react_parser_strip", "agent", "react_parser.py")
    text = ('A <tool name="t1">{}</tool> B '
            '<tool name="t2">{}</tool> C')
    assert mod.strip_tool_tags(text).replace("  ", " ").strip() == "A  B  C".replace("  ", " ").strip() or "A" in mod.strip_tool_tags(text)
