"""Tests for core tool definitions and prompts.

Tests cover:
- Tool definition schemas (pure data, no FreeCAD)
- Prompt structure and context placeholder
- Snapshot per-document support (no FreeCAD)
"""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tool_defs import TOOL_DEFINITIONS
from agent.prompts import (
    AGENT_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT,
)

# Load snapshot module without FreeCAD
_spec = importlib.util.spec_from_file_location(
    "snapshot",
    os.path.join(os.path.dirname(__file__), "..", "core", "snapshot.py"),
)
_snap_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_snap_mod)
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
    # Simplified to 3 core tools: execute_code, undo_last, export_step
    assert len(TOOL_DEFINITIONS) == 3


def test_tool_names():
    names = [td["function"]["name"] for td in TOOL_DEFINITIONS]
    assert "execute_code" in names
    assert "undo_last" in names
    assert "export_step" in names


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------

def test_agent_prompt_has_core_tools():
    # Verify the 3 core tools are mentioned
    assert "execute_code" in AGENT_SYSTEM_PROMPT
    assert "undo_last" in AGENT_SYSTEM_PROMPT
    assert "export_step" in AGENT_SYSTEM_PROMPT


def test_agent_prompt_workflow():
    # Verify workflow mentions iterative building
    assert "iteratively" in AGENT_SYSTEM_PROMPT
    assert "WORKFLOW" in AGENT_SYSTEM_PROMPT


def test_react_prompt_has_core_tools():
    # Verify XML examples for the 3 core tools
    assert '<tool name="execute_code">' in REACT_SYSTEM_PROMPT
    assert '<tool name="undo_last">' in REACT_SYSTEM_PROMPT
    assert '<tool name="export_step">' in REACT_SYSTEM_PROMPT


def test_all_prompts_have_context_placeholder():
    assert "{context}" in AGENT_SYSTEM_PROMPT
    assert "{context}" in REACT_SYSTEM_PROMPT


def test_agent_prompt_critical_rules():
    # Verify critical rules section exists
    assert "CRITICAL RULES" in AGENT_SYSTEM_PROMPT
    assert "Variables PERSIST" in AGENT_SYSTEM_PROMPT
    assert "Boolean ops" in AGENT_SYSTEM_PROMPT
    assert "translate()" in AGENT_SYSTEM_PROMPT


def test_react_prompt_critical_rules():
    # Verify critical rules section exists in ReAct prompt too
    assert "CRITICAL RULES" in REACT_SYSTEM_PROMPT
    assert "Variables PERSIST" in REACT_SYSTEM_PROMPT
    assert "Boolean ops" in REACT_SYSTEM_PROMPT
    assert "translate()" in REACT_SYSTEM_PROMPT


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
