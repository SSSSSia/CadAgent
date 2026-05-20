"""ReAct text parser — extract <tool> tags from LLM text output."""
from __future__ import annotations

import json
import re

_TOOL_TAG_RE = re.compile(
    r'<tool\s+name=["\'](\w+)["\']>\s*(.*?)\s*</tool>',
    re.DOTALL,
)


def parse_react_tool_calls(text: str) -> list[dict]:
    """Parse <tool name="xxx">...</tool> tags from LLM text output.

    Returns list of synthetic tool_call dicts matching the OpenAI format:
        [{"id": "react_N", "function": {"name": "...", "arguments": "..."}}]
    """
    calls = []
    for i, m in enumerate(_TOOL_TAG_RE.finditer(text)):
        name = m.group(1)
        args_raw = m.group(2).strip()
        # ensure arguments is valid JSON
        try:
            json.loads(args_raw)
        except (json.JSONDecodeError, ValueError):
            # wrap plain text as {"input": ...} for tools that accept simple args
            if not args_raw or args_raw in ("{}", ""):
                args_raw = "{}"
            else:
                args_raw = json.dumps({"input": args_raw})
        calls.append({
            "id": f"react_{i}",
            "function": {"name": name, "arguments": args_raw},
        })
    return calls
