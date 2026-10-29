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


# ---------------------------------------------------------------------------
# Provider-usage calibration (Pi-style hybrid estimation, S2-B4)
# ---------------------------------------------------------------------------
# When the provider reports real usage for a request, remember the ratio
# real/estimated; fresh totals reuse it until the message count drifts.
_usage_state: dict | None = None


def record_provider_usage(total_tokens: int, messages: list[dict]) -> None:
    """Record provider-reported usage for the last request (hybrid estimate)."""
    global _usage_state
    if not total_tokens or total_tokens <= 0:
        return
    est = sum(_estimate_message_tokens(m) for m in messages)
    if est > 0:
        _usage_state = {
            "ratio": total_tokens / est,
            "msg_count": len(messages),
        }


def reset_provider_usage() -> None:
    """Forget any calibration (tests / new sessions)."""
    global _usage_state
    _usage_state = None


def _calibrated_total(messages: list[dict]) -> int:
    """Total token estimate, scaled by the last provider-reported ratio."""
    est = sum(_estimate_message_tokens(m) for m in messages)
    if _usage_state and abs(_usage_state["msg_count"] - len(messages)) <= 4:
        return max(1, int(est * _usage_state["ratio"]))
    return est


def trim_messages(messages: list[dict], max_tokens: int = None) -> list[dict]:
    """Trim message list to fit within token budget.

    Strategy:
    1. Always keep first message (system prompt)
    2. Protect last N messages (N = min(6, len-2))
    3. Phase 1 — truncate middle tool/assistant content
    4. Phase 2 — delete assistant(tool_calls) + consecutive tool results as
       atomic units (never leaves orphaned tool_calls or tool results)
    5. Phase 3 — replace remaining middle history with a structured checkpoint
    6. Phase 4 — still over budget (e.g. a single huge message): truncate the
       longest message body head+tail until it fits (S2-B4 — short lists used
       to bypass every phase and blow the API context limit)

    Returns a new list; does not modify the original.
    """
    if max_tokens is None:
        max_tokens = _config.MAX_CONTEXT_TOKENS
    if not messages:
        return []

    total = _calibrated_total(messages)
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
            if len(content) > 500:
                result[i] = {**msg, "content": content[:500] + "\n...[truncated]"}
        elif role == "assistant":
            content = msg.get("content", "")
            if content and len(content) > 500:
                result[i] = {**msg, "content": content[:500] + "\n...[truncated]"}

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

    # Phase 3: replace middle history with a structured checkpoint
    tail = _tail_size()
    mid_end = len(result) - tail
    if mid_end > 1:
        middle = result[1:mid_end]
        summary_msg = {"role": "user", "content": summarize_old_messages(middle)}
        if _estimate_message_tokens(summary_msg) < sum(
                _estimate_message_tokens(m) for m in middle):
            result = [result[0], summary_msg] + result[mid_end:]

    # Phase 4 (S2-B4): short lists bypass phases 1-3 entirely — force-fit by
    # truncating the longest message body (head+tail) until within budget.
    total = _calibrated_total(result)
    while total > max_tokens:
        idx, best = None, -1
        for i, m in enumerate(result):
            if i == 0 and m.get("role") == "system":
                continue  # never truncate the system prompt
            content = m.get("content")
            if isinstance(content, str) and len(content) > best:
                idx, best = i, len(content)
        if idx is None or best <= 200:
            break  # nothing meaningful left to truncate
        m = result[idx]
        half = max(50, best // 4)
        new_content = (
            m["content"][:half]
            + "\n...[truncated to fit context budget]\n"
            + m["content"][-half:]
        )
        result[idx] = {**m, "content": new_content}
        total = _calibrated_total(result)

    return result


def token_summary(messages: list[dict]) -> tuple[int, int]:
    """Return (used_tokens, max_tokens) for display purposes."""
    return _calibrated_total(messages), _config.MAX_CONTEXT_TOKENS


def summarize_old_messages(messages: list[dict]) -> str:
    """Compress a batch of old messages into a structured checkpoint.

    Pi-style five-section format (goal / constraints / progress / decisions /
    next steps) — the compressed history keeps the model oriented instead of
    remembering only "some tool calls happened" (S2-B4, decision point ⑦).
    """
    if not messages:
        return "No prior design history."

    import re

    tool_count = 0
    user_requests: list[str] = []
    constraints: list[str] = []
    decisions: list[str] = []
    last_quality_line = ""
    last_pending = ""

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user" and content:
            snippet = content.strip().replace("\n", " ")
            if snippet.startswith("CAD QUALITY GATE"):
                last_pending = snippet[:160]
                continue
            user_requests.append(snippet[:120])
            # dimension-ish tokens count as constraints
            for m in re.findall(r"\d+(?:\.\d+)?\s*(?:mm|cm|°|deg\b)", snippet):
                if m not in constraints and len(constraints) < 8:
                    constraints.append(m)
        elif role == "tool":
            tool_count += 1
            first = content.split("\n", 1)[0]
            if first.startswith(("OK:", "FAIL:", "ERROR:")):
                last_quality_line = first[:120]
        elif role == "assistant":
            if msg.get("tool_calls"):
                tool_count += len(msg["tool_calls"])
            elif content:
                line = content.strip().split("\n", 1)[0]
                if line and len(decisions) < 3:
                    decisions.append(line[:120])

    sections = [
        "DESIGN HISTORY CHECKPOINT (older messages compressed)",
        f"GOAL (last user request): {user_requests[-1] if user_requests else '—'}",
        f"CONSTRAINTS: {', '.join(constraints) if constraints else '—'}",
        f"PROGRESS: executed {tool_count} tool calls"
        + (f"; last quality check: {last_quality_line}" if last_quality_line else ""),
        f"DECISIONS: {' | '.join(decisions) if decisions else '—'}",
        f"NEXT STEPS: {last_pending if last_pending else 'continue the current task'}",
    ]
    return "\n".join(sections)
