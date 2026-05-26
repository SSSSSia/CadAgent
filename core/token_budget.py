"""Token budget management — prevents conversation history from exceeding API limits.

GLM-5.1 context window ~32K tokens. We reserve ~8K for system prompt + output,
leaving ~24K for conversation history.
"""
from __future__ import annotations

import json

import core.config as _config


def _is_cjk(cp: int) -> bool:
    """Check if a Unicode code point belongs to a CJK range."""
    return (0x4E00 <= cp <= 0x9FFF   # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF   # CJK Extension A
            or 0xF900 <= cp <= 0xFAFF   # CJK Compatibility Ideographs
            or 0x3000 <= cp <= 0x303F   # CJK Symbols and Punctuation
            or 0xFF00 <= cp <= 0xFFEF)  # Halfwidth and Fullwidth Forms


def estimate_tokens(text: str) -> int:
    """Rough token estimate.

    Rules: English ~4 chars/token, Chinese ~1.5 chars/token.
    Mixed text is split into CJK and non-CJK runs and estimated separately.
    """
    if not text:
        return 0

    cjk = 0
    other = 0
    for ch in text:
        if _is_cjk(ord(ch)):
            cjk += 1
        else:
            other += 1

    return max(1, int(cjk / 1.5) + int(other / 4))


def _estimate_message_tokens(msg: dict) -> int:
    """Estimate tokens for a single message dict."""
    total = 4  # overhead for role, delimiters
    for value in msg.values():
        if isinstance(value, str):
            total += estimate_tokens(value)
        elif isinstance(value, list):
            total += estimate_tokens(json.dumps(value, ensure_ascii=False))
    return total


def trim_messages(messages: list[dict], max_tokens: int = None) -> list[dict]:
    """Trim message list to fit within token budget.

    Strategy:
    1. Always keep first message (system prompt)
    2. Protect last N messages (N = min(6, len-2))
    3. Phase 1 — truncate middle tool/assistant content
    4. Phase 2 — delete assistant(tool_calls) + consecutive tool results as
       atomic units (never leaves orphaned tool_calls or tool results)
    5. Phase 3 — replace remaining middle history with a summary

    Returns a new list; does not modify the original.
    """
    if max_tokens is None:
        max_tokens = _config.MAX_CONTEXT_TOKENS
    if not messages:
        return []

    total = sum(_estimate_message_tokens(m) for m in messages)
    if total <= max_tokens:
        return list(messages)

    result = [dict(m) for m in messages]

    def _tail_size():
        return min(6, max(1, len(result) - 2))

    # Phase 1: truncate middle tool_result and assistant content
    tail = _tail_size()
    end = len(result) - tail
    for i in range(1, end):
        msg = result[i]
        role = msg.get("role", "")
        if role == "tool":
            content = msg.get("content", "")
            if len(content) > 200:
                result[i] = {**msg, "content": content[:200] + "\n...[truncated]"}
        elif role == "assistant":
            content = msg.get("content", "")
            if content and len(content) > 300:
                result[i] = {**msg, "content": content[:300] + "\n...[truncated]"}

    total = sum(_estimate_message_tokens(m) for m in result)
    if total <= max_tokens:
        return result

    # Phase 2: delete assistant(tool_calls) + all consecutive tool results
    # as atomic units — prevents orphaned tool_calls or tool results
    tail = _tail_size()
    i = 1
    while i < len(result) - tail and total > max_tokens:
        msg = result[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            # Find extent of consecutive tool results
            pair_end = i + 1
            while pair_end < len(result) and result[pair_end].get("role") == "tool":
                pair_end += 1
            # Only remove if entire group is in the trim zone
            if pair_end <= len(result) - tail:
                removed = sum(_estimate_message_tokens(result[j])
                              for j in range(i, pair_end))
                del result[i:pair_end]
                total -= removed
                continue
        i += 1

    if total <= max_tokens:
        return result

    # Phase 3: replace middle history with a summary
    tail = _tail_size()
    mid_end = len(result) - tail
    if mid_end > 1:
        middle = result[1:mid_end]
        summary_msg = {"role": "user", "content": summarize_old_messages(middle)}
        if _estimate_message_tokens(summary_msg) < sum(
                _estimate_message_tokens(m) for m in middle):
            result = [result[0], summary_msg] + result[mid_end:]

    return result


def token_summary(messages: list[dict]) -> tuple[int, int]:
    """Return (used_tokens, max_tokens) for display purposes."""
    used = sum(_estimate_message_tokens(m) for m in messages)
    return used, _config.MAX_CONTEXT_TOKENS


def summarize_old_messages(messages: list[dict]) -> str:
    """Compress a batch of old messages into a one-line summary.

    Used to replace many history messages with a single summary entry,
    preserving key context without the full token cost.
    """
    if not messages:
        return "No prior design history."

    tool_count = 0
    user_actions = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and content:
            snippet = content.strip()[:50]
            user_actions.append(snippet)
        elif role == "tool":
            tool_count += 1
        elif role == "assistant" and msg.get("tool_calls"):
            tool_count += len(msg["tool_calls"])

    parts = []
    if user_actions:
        parts.append(f"user request: {user_actions[-1]}")
    if tool_count:
        parts.append(f"executed {tool_count} tool calls")

    return ("Design history: " + ", ".join(parts)) if parts else "Design history: no prior actions"
