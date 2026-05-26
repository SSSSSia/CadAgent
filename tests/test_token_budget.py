"""Tests for core/token_budget.py — estimate_tokens, trim_messages, summarize_old_messages."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.token_budget import estimate_tokens, trim_messages, summarize_old_messages, token_summary


# ---- estimate_tokens ----

def test_estimate_empty():
    assert estimate_tokens("") == 0


def test_estimate_english():
    tokens = estimate_tokens("Hello world this is a test")
    assert tokens > 0
    # ~28 chars / 4 = 7 tokens
    assert 5 <= tokens <= 10


def test_estimate_chinese():
    tokens = estimate_tokens("你好世界")
    # 4 CJK chars / 1.5 ≈ 3 tokens
    assert tokens >= 2


def test_estimate_mixed():
    tokens = estimate_tokens("Hello 你好 world 世界")
    assert tokens > 0


def test_estimate_minimum():
    assert estimate_tokens("a") == 1


# ---- trim_messages ----

def _make_messages(n, content="short"):
    msgs = [{"role": "system", "content": "system prompt"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"{content} {i}"})
        msgs.append({"role": "assistant", "content": f"response {i}"})
    return msgs


def test_trim_under_budget():
    msgs = _make_messages(2)
    result = trim_messages(msgs, max_tokens=99999)
    assert len(result) == len(msgs)


def test_trim_preserves_system_prompt():
    msgs = _make_messages(20, content="x" * 500)
    result = trim_messages(msgs, max_tokens=200)
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "system prompt"


def test_trim_preserves_recent():
    msgs = _make_messages(20, content="x" * 500)
    result = trim_messages(msgs, max_tokens=200)
    # Last 6 messages should be kept
    last_roles = [m["role"] for m in result[-6:]]
    assert "user" in last_roles or "assistant" in last_roles


def test_trim_empty_list():
    assert trim_messages([]) == []


def test_trim_does_not_modify_original():
    msgs = _make_messages(5, content="x" * 500)
    original_len = len(msgs)
    trim_messages(msgs, max_tokens=50)
    assert len(msgs) == original_len


def test_trim_small_list():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    result = trim_messages(msgs, max_tokens=5)
    assert len(result) == 2


# ---- summarize_old_messages ----

def test_summarize_empty():
    assert summarize_old_messages([]) == "No prior design history."


def test_summarize_user_messages():
    msgs = [
        {"role": "user", "content": "Create a flange"},
        {"role": "assistant", "content": "Done"},
    ]
    result = summarize_old_messages(msgs)
    assert "Create a flange" in result
    assert "user request" in result


def test_summarize_tool_calls():
    msgs = [
        {"role": "user", "content": "Create box"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "ok"},
    ]
    result = summarize_old_messages(msgs)
    assert "tool calls" in result


def test_summarize_truncates_long_content():
    msgs = [{"role": "user", "content": "x" * 200}]
    result = summarize_old_messages(msgs)
    # snippet should be truncated to 50 chars
    assert len(result) < 200


# ---- Phase 2: tool pair removal ----

def test_trim_removes_tool_pairs_atomically():
    """Phase 2 should remove assistant(tool_calls) + tool results together."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "execute_code", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "x" * 2000, "tool_call_id": "c1"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "response"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "final"},
        {"role": "assistant", "content": "done"},
    ]
    result = trim_messages(msgs, max_tokens=30)
    # No orphaned tool results
    assert all(m.get("role") != "tool" for m in result)


def test_trim_multi_tool_calls():
    """Phase 2 handles multiple tool_calls in one assistant message."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do multiple"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "execute_code", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "execute_code", "arguments": "{}"}},
        ]},
        {"role": "tool", "content": "result1", "tool_call_id": "c1"},
        {"role": "tool", "content": "result2", "tool_call_id": "c2"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "ok"},
    ]
    result = trim_messages(msgs, max_tokens=30)
    # No tool results should remain without their parent assistant
    for i, m in enumerate(result):
        if m.get("role") == "tool":
            # Find parent assistant — must exist
            assert any(
                mj.get("role") == "assistant" and mj.get("tool_calls")
                for mj in result[:i]
            ), "Orphaned tool result without parent assistant"


def test_trim_no_orphaned_tool_calls():
    """After trimming, every remaining tool_call has a matching tool result."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "step1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "execute_code", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "x" * 2000, "tool_call_id": "c1"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "step2"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "execute_code", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "y" * 2000, "tool_call_id": "c2"},
        {"role": "assistant", "content": "done2"},
        {"role": "user", "content": "thanks"},
        {"role": "assistant", "content": "welcome"},
    ]
    result = trim_messages(msgs, max_tokens=100)
    # Verify pairing integrity
    for m in result:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tc_ids = {tc["id"] for tc in m["tool_calls"]}
            tool_ids = {
                mj.get("tool_call_id")
                for mj in result
                if mj.get("role") == "tool"
            }
            assert tc_ids.issubset(tool_ids), (
                f"Orphaned tool_calls: {tc_ids - tool_ids}"
            )


# ---- Small list handling ----

def test_trim_small_list_truncates():
    """Small lists that exceed budget still get truncated."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "x" * 5000},
        {"role": "assistant", "content": "y" * 5000},
    ]
    result = trim_messages(msgs, max_tokens=100)
    assert result[0]["role"] == "system"
    # Result should be no larger than input
    assert len(result) <= len(msgs)


# ---- Phase 3: summary fallback ----

def test_trim_phase3_summary_replaces_middle():
    """When Phases 1-2 are insufficient, Phase 3 summarizes middle history."""
    msgs = [
        {"role": "system", "content": "sys"},
    ]
    # Build a long conversation that won't fit in budget
    for i in range(15):
        msgs.append({"role": "user", "content": f"request {i} " + "x" * 500})
        msgs.append({"role": "assistant", "content": f"response {i} " + "y" * 500})

    result = trim_messages(msgs, max_tokens=200)
    assert result[0]["role"] == "system"
    # Should be significantly shorter than original
    assert len(result) < len(msgs)


# ---- CJK punctuation estimation ----

def test_estimate_cjk_punctuation():
    """CJK punctuation should be estimated at CJK rate, not English rate."""
    # CJK punctuation: 、、。！
    text = "、、。！"
    tokens = estimate_tokens(text)
    # 4 CJK chars / 1.5 ≈ 3 tokens
    assert tokens >= 2
    # Should NOT be estimated as English (4 chars / 4 = 1)
    assert tokens >= 2


def test_estimate_fullwidth_chars():
    """Fullwidth forms (ＡＢＣ１２３) should be estimated at CJK rate."""
    text = "ＡＢＣ１２３"
    tokens = estimate_tokens(text)
    # 6 CJK-range chars / 1.5 = 4 tokens
    assert tokens >= 3


# ---- token_summary ----

def test_token_summary_returns_tuple():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    used, budget = token_summary(msgs)
    assert isinstance(used, int)
    assert isinstance(budget, int)
    assert used > 0
    assert budget > 0


def test_token_summary_empty():
    used, budget = token_summary([])
    assert used == 0
    assert budget > 0


def test_token_summary_budget_matches_config():
    from core.config import MAX_CONTEXT_TOKENS
    _, budget = token_summary([{"role": "system", "content": "sys"}])
    assert budget == MAX_CONTEXT_TOKENS
