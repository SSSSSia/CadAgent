"""ReAct text parser — extract <tool> tags from LLM text output.

Supports multiple fallback strategies for robustness with weak models:
1. Standard paired tags with relaxed whitespace
2. Self-closing tags
3. Unclosed tags (model stopped generating)
"""
from __future__ import annotations

import json
import re

# Strategy 1: Standard paired tags (relaxed whitespace, case-insensitive)
_TOOL_TAG_RE = re.compile(
    r'<tool\s+name\s*=\s*["\'](\w+)["\']\s*>\s*(.*?)\s*</tool\s*>',
    re.DOTALL | re.IGNORECASE,
)

# Strategy 2: Self-closing tags
_TOOL_SELF_CLOSE_RE = re.compile(
    r'<tool\s+name\s*=\s*["\'](\w+)["\']\s*/>',
    re.IGNORECASE,
)

# Strategy 3: Unclosed tags (model stopped generating)
_TOOL_UNCLOSED_RE = re.compile(
    r'<tool\s+name\s*=\s*["\'](\w+)["\']\s*>\s*(.*?)(?=\s*<tool\s|$)',
    re.DOTALL | re.IGNORECASE,
)


def _clean_args(args_raw: str) -> str:
    """Strip markdown fences and normalize whitespace."""
    args_raw = args_raw.strip()
    args_raw = re.sub(r'^```(?:json)?\s*\n?', '', args_raw)
    args_raw = re.sub(r'\n?```\s*$', '', args_raw)
    return args_raw.strip()


def _normalize_args(args_raw: str) -> str:
    """Ensure arguments is valid JSON, with fixups for common mistakes."""
    args_raw = _clean_args(args_raw)

    if not args_raw or args_raw == "{}":
        return "{}"

    # Try as-is (strict=False allows newlines inside JSON strings — needed for multi-line code)
    try:
        json.loads(args_raw, strict=False)
        return args_raw
    except (json.JSONDecodeError, ValueError):
        pass

    # Fixup: missing closing brace
    if args_raw.startswith("{") and not args_raw.rstrip().endswith("}"):
        args_raw = args_raw.rstrip() + "}"
    try:
        json.loads(args_raw, strict=False)
        return args_raw
    except (json.JSONDecodeError, ValueError):
        pass

    # Fixup: trailing comma before closing brace
    args_raw = re.sub(r',\s*}', '}', args_raw)
    try:
        json.loads(args_raw, strict=False)
        return args_raw
    except (json.JSONDecodeError, ValueError):
        pass

    # Last resort: wrap as {"input": ...}
    return json.dumps({"input": args_raw})


def parse_react_tool_calls(text: str) -> list[dict]:
    """Parse <tool name="xxx">...</tool> tags from LLM text output.

    Returns list of synthetic tool_call dicts matching the OpenAI format:
        [{"id": "react_N", "function": {"name": "...", "arguments": "..."}}]
    """
    # Strategy 1: Standard paired tags
    calls = []
    for i, m in enumerate(_TOOL_TAG_RE.finditer(text)):
        calls.append({
            "id": f"react_{i}",
            "function": {
                "name": m.group(1),
                "arguments": _normalize_args(m.group(2)),
            },
        })
    if calls:
        return calls

    # Strategy 2: Self-closing tags
    for i, m in enumerate(_TOOL_SELF_CLOSE_RE.finditer(text)):
        calls.append({
            "id": f"react_{i}",
            "function": {"name": m.group(1), "arguments": "{}"},
        })
    if calls:
        return calls

    # Strategy 3: Unclosed tags
    for i, m in enumerate(_TOOL_UNCLOSED_RE.finditer(text)):
        calls.append({
            "id": f"react_{i}",
            "function": {
                "name": m.group(1),
                "arguments": _normalize_args(m.group(2)),
            },
        })
    return calls
