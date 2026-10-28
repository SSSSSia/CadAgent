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


class TestAutoFixResultPrefix:
    """S1-A1: _attempt_auto_fix result headers must reflect quality outcome."""

    def _run_auto_fix(self, quality_fn):
        """Drive _attempt_auto_fix with snapshot/quality patched.

        Patches: core.snapshot restore/take (no real FreeCAD), sys.modules
        FreeCAD (for _clean_stale_namespace_vars's import), and the quality
        analyzer. Returns the result string.
        """
        import core.snapshot as snapshot_mod
        import core.quality as quality_mod
        from tests.helpers import install_sys_modules, restore_sys_modules

        tools, mock_fc, _ = _load_tools()
        mock_doc = MagicMock()
        mock_doc.Objects = []
        mock_fc.ActiveDocument = mock_doc

        tools.clear_persistent_vars()
        orig_restore = snapshot_mod.restore_latest_snapshot
        orig_take = snapshot_mod.take_snapshot
        orig_quality = quality_mod.analyze_document_quality
        snapshot_mod.restore_latest_snapshot = lambda: "SUCCESS: Document restored."
        snapshot_mod.take_snapshot = lambda: None
        quality_mod.analyze_document_quality = quality_fn
        saved = install_sys_modules({"FreeCAD": mock_fc})
        try:
            return tools._attempt_auto_fix(
                original_error=ValueError("original failure"),
                original_code="bad = 1",
                fixed_code="x = 1",
                hint_text="translate() modifies in-place.",
                auto_created_doc=False,
            )
        finally:
            restore_sys_modules(saved)
            snapshot_mod.restore_latest_snapshot = orig_restore
            snapshot_mod.take_snapshot = orig_take
            quality_mod.analyze_document_quality = orig_quality
            tools.clear_persistent_vars()

    def test_auto_fix_with_passing_quality_returns_ok_header(self):
        from core.quality import QualityReport
        report = QualityReport(
            passed=True, severity="ok", issues=[],
            summary="Quality check PASSED for 'Test'.",
        )
        result = self._run_auto_fix(lambda doc, assembly_mode=False: report)
        assert result.startswith("OK: Auto-fix applied and code executed.")
        assert "AUTO-FIX APPLIED:" in result
        assert "PASSED" in result

    def test_auto_fix_with_failing_quality_returns_fail_header(self):
        from core.quality import QualityReport
        report = QualityReport(
            passed=False, severity="fail", issues=[],
            summary="Quality check FAILED for 'Test'.",
        )
        result = self._run_auto_fix(lambda doc, assembly_mode=False: report)
        assert result.startswith("FAIL: Auto-fix applied but CAD quality check failed.")

    def test_auto_fix_quality_crash_returns_fail_header(self):
        def boom(doc, assembly_mode=False):
            raise RuntimeError("quality check exploded")
        result = self._run_auto_fix(boom)
        assert result.startswith("FAIL: Auto-fix applied but CAD quality check crashed.")


class TestExportStlObjExtension:
    """S1-A8: STL/OBJ export validates extension vs format, single write."""

    def _run_export(self, tools, mock_fc, fmt, filename):
        import core.quality as quality_mod
        from core.quality import QualityReport
        orig_quality = quality_mod.analyze_document_quality
        quality_mod.analyze_document_quality = lambda doc, assembly_mode=False: QualityReport(
            passed=True, severity="ok", issues=[], summary="PASSED",
        )
        mock_shape = MagicMock()
        mock_shape.isNull.return_value = False
        mock_shape.tessellate.return_value = ([], [])
        mock_obj = MagicMock()
        mock_obj.Shape = mock_shape
        mock_doc = MagicMock()
        mock_doc.Objects = [mock_obj]
        mock_fc.ActiveDocument = mock_doc
        try:
            return tools._tool_export_step(
                json.dumps({"filename": filename, "format": fmt})
            )
        finally:
            quality_mod.analyze_document_quality = orig_quality

    def _with_mesh_mock(self, fn):
        from tests.helpers import install_sys_modules, restore_sys_modules
        tools, mock_fc, _ = _load_tools()
        mesh_mod = MagicMock()
        saved = install_sys_modules({"Mesh": mesh_mod})
        try:
            return fn(tools, mock_fc, mesh_mod), mesh_mod
        finally:
            restore_sys_modules(saved)

    def test_no_extension_appends_format(self):
        def run(tools, mock_fc, mesh_mod):
            return self._run_export(tools, mock_fc, "stl", "out")
        result, mesh_mod = self._with_mesh_mock(run)
        assert result.startswith("SUCCESS")
        written = mesh_mod.Mesh.return_value.write.call_args[0][0]
        assert written.endswith("out.stl")

    def test_matching_extension_ok(self):
        def run(tools, mock_fc, mesh_mod):
            return self._run_export(tools, mock_fc, "obj", "part.obj")
        result, mesh_mod = self._with_mesh_mock(run)
        assert result.startswith("SUCCESS")
        assert mesh_mod.Mesh.return_value.write.call_count == 1

    def test_mismatched_extension_errors(self):
        def run(tools, mock_fc, mesh_mod):
            return self._run_export(tools, mock_fc, "stl", "part.obj")
        result, mesh_mod = self._with_mesh_mock(run)
        assert result.startswith("ERROR")
        assert "extension" in result
        mesh_mod.Mesh.return_value.write.assert_not_called()
