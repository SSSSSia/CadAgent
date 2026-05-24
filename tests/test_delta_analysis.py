"""Tests for document state delta analysis functions in agent/tools.py.

These are pure-text functions that only use the re module, so we define them
locally to avoid importing tools.py (which requires FreeCAD).
"""
from __future__ import annotations

import re


def _extract_total_volume(state: str) -> float | None:
    volumes = re.findall(r"Volume:\s*([\d.]+)", state)
    if not volumes:
        return None
    return sum(float(v) for v in volumes)


def _compute_delta(pre_state: str, post_state: str) -> str:
    pre_objs = set(re.findall(r"- '([^']+)'", pre_state))
    post_objs = set(re.findall(r"- '([^']+)'", post_state))

    added = sorted(post_objs - pre_objs)
    removed = sorted(pre_objs - post_objs)

    pre_vol = _extract_total_volume(pre_state)
    post_vol = _extract_total_volume(post_state)

    parts = []
    if added:
        parts.append(f"New objects: {', '.join(added)}")
    if removed:
        parts.append(f"Removed objects: {', '.join(removed)}")
    if pre_vol is not None and post_vol is not None:
        delta = post_vol - pre_vol
        pct = (delta / pre_vol * 100) if pre_vol != 0 else 0
        direction = "+" if delta >= 0 else ""
        parts.append(f"Volume: {pre_vol:.0f} -> {post_vol:.0f} mm3 ({direction}{pct:.1f}%)")

    return "; ".join(parts) if parts else "No changes detected"


# ---- _extract_total_volume ----

def test_extract_volume_single_object():
    state = "Volume: 6000.0 mm3"
    assert _extract_total_volume(state) == 6000.0


def test_extract_volume_multiple_objects():
    state = "Volume: 6000.0 mm3\n  Volume: 3000.0 mm3"
    assert _extract_total_volume(state) == 9000.0


def test_extract_volume_no_volume():
    state = "(no active document)"
    assert _extract_total_volume(state) is None


def test_extract_volume_empty_string():
    assert _extract_total_volume("") is None


# ---- _compute_delta: no changes ----

def test_delta_no_changes():
    state = "Current document: 'Test', objects:\n- 'Box' (type: Part::Feature)"
    assert _compute_delta(state, state) == "No changes detected"


def test_delta_both_empty():
    assert _compute_delta("(no active document)", "(no active document)") == "No changes detected"


# ---- _compute_delta: object changes ----

def test_delta_new_object():
    pre = "Current document: 'Test', objects:\n- 'Box' (type: Part::Feature)"
    post = "Current document: 'Test', objects:\n- 'Box' (type: Part::Feature)\n- 'Hole' (type: Part::Feature)"
    result = _compute_delta(pre, post)
    assert "New objects: Hole" in result


def test_delta_removed_object():
    pre = "Current document: 'Test', objects:\n- 'Box' (type: Part::Feature)\n- 'Hole' (type: Part::Feature)"
    post = "Current document: 'Test', objects:\n- 'Box' (type: Part::Feature)"
    result = _compute_delta(pre, post)
    assert "Removed objects: Hole" in result


def test_delta_multiple_new_objects():
    pre = "Current document: 'Test', objects:"
    post = "Current document: 'Test', objects:\n- 'Zyz' (type: Part::Feature)\n- 'Abc' (type: Part::Feature)"
    result = _compute_delta(pre, post)
    assert "New objects:" in result
    assert "Abc" in result
    assert "Zyz" in result


# ---- _compute_delta: volume changes ----

def test_delta_volume_increase():
    pre = (
        "Current document: 'Test', objects:\n"
        "- 'Box' (type: Part::Feature)\n"
        "  Volume: 1000.0 mm3"
    )
    post = (
        "Current document: 'Test', objects:\n"
        "- 'Box' (type: Part::Feature)\n"
        "  Volume: 1500.0 mm3"
    )
    result = _compute_delta(pre, post)
    assert "Volume:" in result
    assert "+50.0%" in result


def test_delta_volume_decrease():
    pre = (
        "Current document: 'Test', objects:\n"
        "- 'Box' (type: Part::Feature)\n"
        "  Volume: 2000.0 mm3"
    )
    post = (
        "Current document: 'Test', objects:\n"
        "- 'Box' (type: Part::Feature)\n"
        "  Volume: 1000.0 mm3"
    )
    result = _compute_delta(pre, post)
    assert "Volume:" in result
    assert "-50.0%" in result


def test_delta_volume_one_side_none():
    pre = "(no active document)"
    post = (
        "Current document: 'Test', objects:\n"
        "- 'Box' (type: Part::Feature)\n"
        "  Volume: 1000.0 mm3"
    )
    result = _compute_delta(pre, post)
    assert "Volume:" not in result
    assert "New objects: Box" in result


# ---- _compute_delta: combined ----

def test_delta_new_object_with_volume():
    pre = (
        "Current document: 'Test', objects:\n"
        "- 'Base' (type: Part::Feature)\n"
        "  Volume: 5000.0 mm3"
    )
    post = (
        "Current document: 'Test', objects:\n"
        "- 'Base' (type: Part::Feature)\n"
        "  Volume: 5000.0 mm3\n"
        "- 'Hole' (type: Part::Feature)\n"
        "  Volume: 200.0 mm3"
    )
    result = _compute_delta(pre, post)
    assert "New objects: Hole" in result
    assert "Volume:" in result
    assert "+4.0%" in result


def test_delta_label_with_special_chars():
    pre = "Current document: 'Test', objects:"
    post = "Current document: 'Test', objects:\n- 'My-Part' (type: Part::Feature)"
    result = _compute_delta(pre, post)
    assert "New objects: My-Part" in result
