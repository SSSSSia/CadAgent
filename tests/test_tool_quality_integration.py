"""Tests for quality gate integration in agent/tools.py.

Verifies that quality check exceptions return FAIL (not OK) and that
normal quality reports are correctly forwarded.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers import load_tools_module


# ---------------------------------------------------------------------------
# Mock FreeCAD and Part before loading tools.py
# ---------------------------------------------------------------------------

def _load_tools():
    """Load tools module with mocked FreeCAD/Part in sys.modules."""
    return load_tools_module()


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
