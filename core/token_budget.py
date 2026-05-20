"""Token budget management — prevents conversation history from exceeding API limits.

GLM-5.1 context window ~32K tokens. We reserve ~8K for system prompt + output,
leaving ~24K for conversation history.
"""
from __future__ import annotations

import re

MAX_CONTEXT_TOKENS = 24000  # leave 8K for output and system prompt


def estimate_tokens(text: str) -> int:
    """Rough token estimate.

    Rules: English ~4 chars/token, Chinese ~1.5 chars/token.
    Mixed text is split into CJK and non-CJK runs and estimated separately.
    """
    if not text:
        return 0

    cjk_chars = 0
    other_chars = 0
    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿' or '豈' <= ch <= '﫿':
            cjk_chars += 1
        else:
            other_chars += 1

    return max(1, int(cjk_chars / 1.5) + int(other_chars / 4))


def _estimate_message_tokens(msg: dict) -> int:
    """Estimate tokens for a single message dict."""
    total = 4  # overhead for role, delimiters
    for key, value in msg.items():
        if isinstance(value, str):
            total += estimate_tokens(value)
        elif isinstance(value, list):
            # tool_calls etc.
            import json
            total += estimate_tokens(json.dumps(value, ensure_ascii=False))
    return total


def trim_messages(messages: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict]:
    """Trim message list to fit within token budget.

    Strategy (oldest first):
    1. Always keep first message (system prompt)
    2. Always keep last 6 messages (recent interaction)
    3. Truncate middle tool_result messages to 200 chars
    4. Truncate middle assistant messages content to 300 chars
    5. If still over budget: delete middle tool + tool_result pairs
    6. Never delete user messages

    Returns a new list; does not modify the original.
    """
    if not messages:
        return []

    total = sum(_estimate_message_tokens(m) for m in messages)
    if total <= max_tokens:
        return list(messages)

    result = [dict(m) for m in messages]  # deep-copy each message

    # If we have <= 7 messages, nothing to trim between first and last 6
    if len(result) <= 7:
        return result

    # Phase 1: truncate middle tool_result and assistant content
    first_idx = 1  # keep system prompt
    last_idx = len(result) - 6

    for i in range(first_idx, last_idx):
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

    # Phase 2: delete middle tool + tool_result pairs, oldest first
    i = 1
    while i < len(result) - 6 and total > max_tokens:
        if result[i].get("role") == "tool":
            removed_tokens = _estimate_message_tokens(result[i])
            result.pop(i)
            total -= removed_tokens
            continue
        # Also remove the assistant message that triggered the tool call
        # if it's in the middle zone and has tool_calls
        if (result[i].get("role") == "assistant"
                and result[i].get("tool_calls")
                and i < len(result) - 6):
            # Check if next message is a tool result (pair)
            if i + 1 < len(result) and result[i + 1].get("role") == "tool":
                removed_tokens = (_estimate_message_tokens(result[i])
                                  + _estimate_message_tokens(result[i + 1]))
                result.pop(i)      # assistant with tool_calls
                result.pop(i)      # tool result
                total -= removed_tokens
                continue
        i += 1

    return result


def summarize_old_messages(messages: list[dict]) -> str:
    """Compress a batch of old messages into a one-line summary.

    Used to replace many history messages with a single summary entry,
    preserving key context without the full token cost.
    """
    if not messages:
        return "之前没有设计历史。"

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
        last_action = user_actions[-1]
        parts.append(f"用户指令：{last_action}")
    if tool_count:
        parts.append(f"执行了 {tool_count} 次工具调用")

    summary = "之前的设计历史：" + "，".join(parts) if parts else "之前的设计历史：无关键操作"
    return summary
