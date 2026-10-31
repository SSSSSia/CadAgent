"""Tests for core tool definitions and prompts.

Tests cover:
- Tool definition schemas (pure data, no FreeCAD)
- Prompt structure and context placeholder
- Snapshot per-document support (no FreeCAD)
"""
from __future__ import annotations

from agent.tool_defs import TOOL_DEFINITIONS
from agent.prompts import (
    AGENT_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT,
)
from tests.helpers import load_module

# Load snapshot module without FreeCAD
_snap_mod = load_module("snapshot", "core", "snapshot.py")
SnapshotManager = _snap_mod.SnapshotManager


# ---------------------------------------------------------------------------
# Tool definition schema tests
# ---------------------------------------------------------------------------

def _get_tool_def(name: str) -> dict:
    for td in TOOL_DEFINITIONS:
        if td["function"]["name"] == name:
            return td
    return {}


def test_execute_code_definition():
    td = _get_tool_def("execute_code")
    assert td, "execute_code tool definition not found"
    props = td["function"]["parameters"]["properties"]
    assert "code" in props
    assert "description" in props
    assert "document" in props
    assert props["code"]["type"] == "string"
    assert props["document"]["type"] == "string"
    # document is NOT required
    assert "document" not in td["function"]["parameters"]["required"]
    # code and description ARE required
    assert "code" in td["function"]["parameters"]["required"]
    assert "description" in td["function"]["parameters"]["required"]


def test_undo_last_definition():
    td = _get_tool_def("undo_last")
    assert td, "undo_last tool definition not found"
    # undo_last has no required parameters
    assert td["function"]["parameters"]["required"] == []


def test_export_step_definition():
    td = _get_tool_def("export_step")
    assert td, "export_step tool definition not found"
    props = td["function"]["parameters"]["properties"]
    assert "filename" in props
    assert "format" in props
    assert "document" in props
    assert props["filename"]["type"] == "string"
    # filename IS required
    assert "filename" in td["function"]["parameters"]["required"]


def test_export_step_has_document_param():
    td = _get_tool_def("export_step")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props
    assert props["document"]["type"] == "string"


def test_all_tools_count():
    # 3 core tools + 2 vision tools: execute_code, undo_last, export_step, capture_view, analyze_image
    assert len(TOOL_DEFINITIONS) == 5


def test_tool_names():
    names = [td["function"]["name"] for td in TOOL_DEFINITIONS]
    assert "execute_code" in names
    assert "undo_last" in names
    assert "export_step" in names
    assert "capture_view" in names
    assert "analyze_image" in names


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------
# S7-E5: this file keeps only the tool-coverage assertions unique to it
# (all 5 tools reachable in both modes). Generic prompt-content checks
# (context placeholder, CRITICAL RULES wording, vision notes...) live in
# test_prompts.py — maintaining both copies had already caused drift.

def test_agent_prompt_has_core_tools():
    # Verify all 5 tools are mentioned
    assert "execute_code" in AGENT_SYSTEM_PROMPT
    assert "undo_last" in AGENT_SYSTEM_PROMPT
    assert "export_step" in AGENT_SYSTEM_PROMPT
    assert "capture_view" in AGENT_SYSTEM_PROMPT
    assert "analyze_image" in AGENT_SYSTEM_PROMPT


def test_react_prompt_has_core_tools():
    # Verify XML examples for all 5 tools
    assert '<tool name="execute_code">' in REACT_SYSTEM_PROMPT
    assert '<tool name="undo_last">' in REACT_SYSTEM_PROMPT
    assert '<tool name="export_step">' in REACT_SYSTEM_PROMPT
    assert '<tool name="capture_view">' in REACT_SYSTEM_PROMPT
    assert '<tool name="analyze_image">' in REACT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Snapshot per-document support tests
# ---------------------------------------------------------------------------

def test_snapshot_take_accepts_none():
    m = SnapshotManager()
    # take(None) should behave same as take() — returns None (no FreeCAD)
    result = m.take(None)
    assert result is None


def test_snapshot_take_accepts_explicit_none_kwarg():
    m = SnapshotManager()
    result = m.take(doc=None)
    assert result is None


def test_snapshot_manager_take_signature():
    """Verify take() method accepts doc parameter."""
    import inspect
    sig = inspect.signature(SnapshotManager.take)
    params = list(sig.parameters.keys())
    assert "doc" in params
