"""Tests for quality gate integration in agent/tools.py.

Verifies that quality check exceptions return FAIL (not OK) and that
normal quality reports are correctly forwarded.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Mock FreeCAD and Part before loading tools.py
# ---------------------------------------------------------------------------

def _setup_mock_freecad():
    """Create mock FreeCAD/FreeCADGui/Part modules."""
    mock_freecad = MagicMock()
    mock_freecad.ActiveDocument = MagicMock()
    mock_freecad.ActiveDocument.Objects = []
    mock_freecad.newDocument = MagicMock(return_value=mock_freecad.ActiveDocument)

    mock_freecadgui = MagicMock()
    mock_freecadgui.activeDocument = MagicMock(return_value=None)

    mock_part = MagicMock()

    saved = {}
    for key in ("FreeCAD", "FreeCADGui", "Part"):
        saved[key] = sys.modules.get(key)

    sys.modules["FreeCAD"] = mock_freecad
    sys.modules["FreeCADGui"] = mock_freecadgui
    sys.modules["Part"] = mock_part

    return saved, mock_freecad, mock_freecadgui


def _restore_modules(saved):
    """Restore original sys.modules entries."""
    for key, val in saved.items():
        if val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = val


def _load_tools():
    """Load tools module with mocked FreeCAD/Part in sys.modules."""
    saved, mock_fc, mock_fcg = _setup_mock_freecad()

    # Also need PySide6 for capture_view
    mock_pyside6 = MagicMock()
    saved["PySide6"] = sys.modules.get("PySide6")
    sys.modules["PySide6"] = mock_pyside6

    file_path = os.path.join(
        os.path.dirname(__file__), "..", "agent", "tools.py"
    )
    spec = importlib.util.spec_from_file_location("tools", file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    _restore_modules(saved)
    return mod, mock_fc, mock_fcg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQualityCheckCrashReturnsFail:
    """When analyze_document_quality crashes, result must be FAIL."""

    def _run_with_quality_fn(self, tools, mock_fc, quality_fn):
        """Execute _tool_execute_code with a patched quality function."""
        import core.quality as quality_mod
        original_fn = quality_mod.analyze_document_quality
        quality_mod.analyze_document_quality = quality_fn
        try:
            mock_shape = MagicMock()
            mock_shape.isNull.return_value = False
            mock_obj = MagicMock()
            mock_obj.Shape = mock_shape
            mock_doc = MagicMock()
            mock_doc.Objects = [mock_obj]
            mock_fc.ActiveDocument = mock_doc

            args = json.dumps({"code": "x = 1"})
            return tools._tool_execute_code(args)
        finally:
            quality_mod.analyze_document_quality = original_fn

    def test_quality_crash_returns_fail(self):
        tools, mock_fc, _ = _load_tools()
        result = self._run_with_quality_fn(
            tools, mock_fc,
            lambda doc, assembly_mode=False: (_ for _ in ()).throw(
                RuntimeError("quality check exploded")
            ),
        )
        assert result.startswith("FAIL:")
        assert "quality check crashed" in result

    def test_normal_quality_pass_returns_ok(self):
        tools, mock_fc, _ = _load_tools()
        from core.quality import QualityReport
        passing_report = QualityReport(
            passed=True, severity="ok", issues=[],
            summary="Quality check PASSED for 'Test'.",
        )
        result = self._run_with_quality_fn(
            tools, mock_fc,
            lambda doc, assembly_mode=False: passing_report,
        )
        assert result.startswith("OK:")
        assert "PASSED" in result

    def test_normal_quality_fail_returns_fail(self):
        tools, mock_fc, _ = _load_tools()
        from core.quality import QualityReport, QualityIssue
        failing_report = QualityReport(
            passed=False, severity="fail",
            issues=[QualityIssue(
                code="NO_SOLID", severity="fail",
                message="No solid components.",
            )],
            summary="Quality check FAILED: No solid components.",
        )
        result = self._run_with_quality_fn(
            tools, mock_fc,
            lambda doc, assembly_mode=False: failing_report,
        )
        assert result.startswith("FAIL:")
        assert "No solid components" in result
