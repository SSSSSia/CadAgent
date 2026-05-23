"""Text processing utilities."""
from __future__ import annotations

import re


def strip_markdown(text: str) -> str:
    """去掉 LLM 输出中可能包裹的 markdown 代码块标记。"""
    text = text.strip()
    text = re.sub(r"^```(?:python)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()
