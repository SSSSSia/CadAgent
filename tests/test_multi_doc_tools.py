"""Tests for multi-document / assembly support (ROADMAP 7.3).

Tests cover:
- Tool definition schemas (pure data, no FreeCAD)
- Prompt assembly guidance presence
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


def test_list_documents_definition():
    td = _get_tool_def("list_documents")
    assert td, "list_documents tool definition not found"
    props = td["function"]["parameters"]["properties"]
    assert "include_geometry" in props
    assert props["include_geometry"]["type"] == "boolean"


def test_create_assembly_definition():
    td = _get_tool_def("create_assembly")
    assert td, "create_assembly tool definition not found"
    props = td["function"]["parameters"]["properties"]
    assert "name" in props
    assert "parts" in props
    assert props["parts"]["type"] == "array"
    # Check required fields
    assert "name" in td["function"]["parameters"]["required"]


def test_create_assembly_part_items_schema():
    td = _get_tool_def("create_assembly")
    parts_schema = td["function"]["parameters"]["properties"]["parts"]
    item_props = parts_schema["items"]["properties"]
    assert "source_document" in item_props
    assert "object_label" in item_props
    assert "position" in item_props
    assert "rotation" in item_props
    # position is array of numbers
    assert item_props["position"]["type"] == "array"
    assert item_props["position"]["items"]["type"] == "number"


def test_execute_code_has_document_param():
    td = _get_tool_def("execute_code")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props
    assert props["document"]["type"] == "string"
    # document is NOT required
    assert "document" not in td["function"]["parameters"]["required"]


def test_analyze_geometry_has_document_param():
    td = _get_tool_def("analyze_geometry")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props
    assert props["document"]["type"] == "string"


def test_validate_design_has_document_param():
    td = _get_tool_def("validate_design")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props


def test_export_step_has_document_param():
    td = _get_tool_def("export_step")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props


def test_measure_distance_has_document_param():
    td = _get_tool_def("measure_distance")
    props = td["function"]["parameters"]["properties"]
    assert "document" in props


def test_all_tools_count():
    # 10 base tools + update_parameter + list_parameters = 12
    assert len(TOOL_DEFINITIONS) == 12


# ---------------------------------------------------------------------------
# Prompt assembly guidance tests
# ---------------------------------------------------------------------------

def test_agent_prompt_has_assembly_tools():
    assert "list_documents" in AGENT_SYSTEM_PROMPT
    assert "create_assembly" in AGENT_SYSTEM_PROMPT


def test_agent_prompt_has_assembly_mode():
    # Assembly mode was simplified — just verify assembly tools are listed
    assert "create_assembly" in AGENT_SYSTEM_PROMPT
    assert "list_documents" in AGENT_SYSTEM_PROMPT


def test_react_prompt_has_assembly_tools():
    assert "list_documents" in REACT_SYSTEM_PROMPT
    assert "create_assembly" in REACT_SYSTEM_PROMPT


def test_react_prompt_has_assembly_mode():
    # Assembly mode was simplified — just verify assembly tools are listed
    assert "create_assembly" in REACT_SYSTEM_PROMPT


def test_react_prompt_has_xml_examples():
    assert '<tool name="list_documents">' in REACT_SYSTEM_PROMPT
    assert '<tool name="create_assembly">' in REACT_SYSTEM_PROMPT


def test_all_prompts_have_context_placeholder():
    assert "{context}" in AGENT_SYSTEM_PROMPT
    assert "{context}" in REACT_SYSTEM_PROMPT


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
