"""Tests for agent/prompts.py — prompt content invariants.

Validates that both agent-loop prompts conform to the
helper-first, quality-gate-aware paradigm established in Phase 1-2.
"""
from __future__ import annotations

import re

import pytest

from tests.helpers import load_module

_mod = load_module("prompts", "agent", "prompts.py")

AGENT_SYSTEM_PROMPT = _mod.AGENT_SYSTEM_PROMPT
REACT_SYSTEM_PROMPT = _mod.REACT_SYSTEM_PROMPT

AGENT_PROMPTS = {
    "AGENT_SYSTEM_PROMPT": AGENT_SYSTEM_PROMPT,
    "REACT_SYSTEM_PROMPT": REACT_SYSTEM_PROMPT,
}

# Both live prompts share the invariant suites below (was 6 prompts before
# the legacy single-shot prompts were removed in S6).
ALL_PROMPTS = AGENT_PROMPTS

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
        ('also "XZ", "YZ"', "workplane plane claims — only XY is supported"),
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


class TestCQSemanticsDocumented:
    """S5: agent prompts must match the implemented CQ semantics."""

    @pytest.mark.parametrize("name,prompt", list(AGENT_PROMPTS.items()))
    def test_extrude_not_centered_documented(self, name, prompt):
        assert "NOT centered" in prompt, (
            f"{name} must document that extrude rises from the workplane"
        )

    @pytest.mark.parametrize("name,prompt", list(AGENT_PROMPTS.items()))
    def test_both_true_documented(self, name, prompt):
        assert "both=True" in prompt

    @pytest.mark.parametrize("name,prompt", list(AGENT_PROMPTS.items()))
    def test_workplane_origin_documented(self, name, prompt):
        assert "workplane(offset=N)" in prompt


class TestSharedPromptSections:
    """S6-A13: both prompts assemble from shared section constants.

    Guards against re-duplicating the sections: the shared pieces must
    stay identical between the two prompts.
    """

    def test_prompts_share_identical_tail(self):
        """Everything from CLARIFICATION POLICY to {context} is common."""
        idx_a = AGENT_SYSTEM_PROMPT.index("CLARIFICATION POLICY:")
        idx_r = REACT_SYSTEM_PROMPT.index("CLARIFICATION POLICY:")
        assert AGENT_SYSTEM_PROMPT[idx_a:] == REACT_SYSTEM_PROMPT[idx_r:]

    def test_prompts_share_identical_workflow(self):
        idx_a = AGENT_SYSTEM_PROMPT.index("WORKFLOW:")
        idx_r = REACT_SYSTEM_PROMPT.index("WORKFLOW:")
        end_a = AGENT_SYSTEM_PROMPT.index("7. Respond")
        end_r = REACT_SYSTEM_PROMPT.index("7. Respond")
        assert AGENT_SYSTEM_PROMPT[idx_a:end_a] == REACT_SYSTEM_PROMPT[idx_r:end_r]

    def test_mode_specific_sections_differ(self):
        assert "AVAILABLE TOOLS:" in AGENT_SYSTEM_PROMPT
        assert "AVAILABLE TOOLS:" not in REACT_SYSTEM_PROMPT
        assert "TOOL CALLING FORMAT" in REACT_SYSTEM_PROMPT
        assert "TOOL CALLING FORMAT" not in AGENT_SYSTEM_PROMPT
