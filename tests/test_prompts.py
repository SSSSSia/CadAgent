"""Tests for agent/prompts.py — prompt content invariants.

Validates that all 6 prompts (2 agent loop + 4 legacy) conform to the
helper-first, quality-gate-aware paradigm established in Phase 1-2.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec = importlib.util.spec_from_file_location(
    "prompts",
    os.path.join(os.path.dirname(__file__), "..", "agent", "prompts.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AGENT_SYSTEM_PROMPT = _mod.AGENT_SYSTEM_PROMPT
REACT_SYSTEM_PROMPT = _mod.REACT_SYSTEM_PROMPT
SYSTEM_PROMPT_NEW = _mod.SYSTEM_PROMPT_NEW
SYSTEM_PROMPT_MODIFY = _mod.SYSTEM_PROMPT_MODIFY
SYSTEM_PROMPT_DERIVE = _mod.SYSTEM_PROMPT_DERIVE
SYSTEM_PROMPT_VARIANT = _mod.SYSTEM_PROMPT_VARIANT

ALL_PROMPTS = {
    "AGENT_SYSTEM_PROMPT": AGENT_SYSTEM_PROMPT,
    "REACT_SYSTEM_PROMPT": REACT_SYSTEM_PROMPT,
    "SYSTEM_PROMPT_NEW": SYSTEM_PROMPT_NEW,
    "SYSTEM_PROMPT_MODIFY": SYSTEM_PROMPT_MODIFY,
    "SYSTEM_PROMPT_DERIVE": SYSTEM_PROMPT_DERIVE,
    "SYSTEM_PROMPT_VARIANT": SYSTEM_PROMPT_VARIANT,
}

AGENT_PROMPTS = {
    "AGENT_SYSTEM_PROMPT": AGENT_SYSTEM_PROMPT,
    "REACT_SYSTEM_PROMPT": REACT_SYSTEM_PROMPT,
}

LEGACY_PROMPTS = {
    "SYSTEM_PROMPT_NEW": SYSTEM_PROMPT_NEW,
    "SYSTEM_PROMPT_MODIFY": SYSTEM_PROMPT_MODIFY,
    "SYSTEM_PROMPT_DERIVE": SYSTEM_PROMPT_DERIVE,
    "SYSTEM_PROMPT_VARIANT": SYSTEM_PROMPT_VARIANT,
}

HELPER_NAMES = [
    "extract_solid",
    "safe_fuse",
    "safe_cut",
    "make_hollow_cylinder",
    "make_ring",
    "make_box_handle",
    "make_arc_handle",
    "ensure_doc",
]


class TestAgentPromptsContainHelpers:
    """Agent prompts must reference all helper functions."""

    @pytest.mark.parametrize("helper", HELPER_NAMES)
    def test_agent_prompt_has_helper(self, helper):
        assert helper in AGENT_SYSTEM_PROMPT, (
            f"AGENT_SYSTEM_PROMPT missing helper: {helper}"
        )

    @pytest.mark.parametrize("helper", HELPER_NAMES)
    def test_react_prompt_has_helper(self, helper):
        assert helper in REACT_SYSTEM_PROMPT, (
            f"REACT_SYSTEM_PROMPT missing helper: {helper}"
        )


class TestLegacyPromptsContainCQApi:
    """Legacy prompts must reference CQ-style boolean ops (.cut()/.union())."""

    CQ_PATTERNS = [".cut(", ".union("]

    @pytest.mark.parametrize("name,prompt", list(LEGACY_PROMPTS.items()))
    @pytest.mark.parametrize("pattern", CQ_PATTERNS)
    def test_legacy_has_cq_pattern(self, name, prompt, pattern):
        assert pattern in prompt, f"{name} missing CQ pattern: {pattern}"


class TestPromptForbiddenContent:
    """No prompt may contain forbidden legacy patterns."""

    FORBIDDEN = [
        ("makePipe(profile)", "makePipe as default handle solution"),
        ("wire.makePipe()", "makePipe in wire context"),
        ("NEVER use makeBox for handles", "anti-makeBox rule"),
        ("NEVER use 'FreeCADGui'", "anti-FreeCADGui rule — now the official name"),
        ("Pre-imported: FreeCAD, Part, math, Gui", "old alias-based pre-import list"),
        ("import FreeCADGui as Gui", "import alias for FreeCADGui"),
        ("rim.translate(Vector(", "bare Vector in example code"),
    ]

    @pytest.mark.parametrize("name,prompt", list(ALL_PROMPTS.items()))
    @pytest.mark.parametrize("forbidden,reason", FORBIDDEN)
    def test_no_forbidden_content(self, name, prompt, forbidden, reason):
        assert forbidden not in prompt, (
            f"{name} contains forbidden pattern ({reason}): {forbidden}"
        )


class TestFencedCodeBlocks:
    """All prompts must have balanced triple-backtick fences."""

    @pytest.mark.parametrize("name,prompt", list(ALL_PROMPTS.items()))
    def test_balanced_backticks(self, name, prompt):
        count = prompt.count("```")
        assert count % 2 == 0, (
            f"{name} has {count} triple-backtick sequences (odd, unbalanced)"
        )


class TestBuildSimplestSolid:
    """Agent prompts must contain the build-simplest-solid principle."""

    @pytest.mark.parametrize("name,prompt", list(AGENT_PROMPTS.items()))
    def test_contains_simplest_solid(self, name, prompt):
        lower = prompt.lower()
        assert "simplest" in lower and "solid" in lower, (
            f"{name} missing 'simplest ... solid' principle"
        )


class TestContextPlaceholder:
    """Verify {context} placeholders are correctly placed."""

    def test_agent_has_context(self):
        assert "{context}" in AGENT_SYSTEM_PROMPT

    def test_react_has_context(self):
        assert "{context}" in REACT_SYSTEM_PROMPT

    def test_new_no_context(self):
        assert "{context}" not in SYSTEM_PROMPT_NEW

    def test_modify_has_context(self):
        assert "{context}" in SYSTEM_PROMPT_MODIFY

    def test_derive_has_context(self):
        assert "{context}" in SYSTEM_PROMPT_DERIVE

    def test_variant_has_context(self):
        assert "{context}" in SYSTEM_PROMPT_VARIANT


class TestLegacyNoRawFuse:
    """Legacy prompts must not have bare .fuse() in code examples.

    CQ-style prompts use .cut()/.union() as chain methods — .fuse() is the
    old FreeCAD API that should not appear in examples.
    Code lines are lines starting with whitespace (indented code, not bullets).
    The regex (?<!safe_)\\.fuse\\( matches raw fuse calls.
    """

    RAW_FUSE_RE = re.compile(r"(?<!safe_)\.fuse\(")

    @pytest.mark.parametrize("name,prompt", list(LEGACY_PROMPTS.items()))
    def test_no_raw_fuse_in_code(self, name, prompt):
        for i, line in enumerate(prompt.split("\n"), 1):
            stripped = line.lstrip()
            if not stripped or not line[0].isspace():
                continue
            match = self.RAW_FUSE_RE.search(line)
            assert match is None, (
                f"{name} line {i} has raw .fuse(): {line.strip()}"
            )


class TestNoMakeLoftExample:
    """SYSTEM_PROMPT_NEW must not have Part.makeLoft as a code example."""

    def test_no_make_loft(self):
        assert "Part.makeLoft" not in SYSTEM_PROMPT_NEW


class TestNoBSplineExample:
    """SYSTEM_PROMPT_NEW must not have Part.BSplineCurve() as a code example."""

    def test_no_bspline(self):
        assert "Part.BSplineCurve()" not in SYSTEM_PROMPT_NEW


class TestAgentPromptsFailRule:
    """Agent prompts must instruct to fix on FAIL/ERROR."""

    @pytest.mark.parametrize("name,prompt", list(AGENT_PROMPTS.items()))
    def test_has_fail_error_rule(self, name, prompt):
        lower = prompt.lower()
        has_fail = "fail" in lower and "error" in lower
        has_fix = "fix" in lower
        assert has_fail and has_fix, (
            f"{name} missing FAIL/ERROR → fix rule"
        )
