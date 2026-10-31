"""Tests for the parametric rebuild engine (P12.2) — apply_param_values +
rebuild_with_params in agent/tools.py, and clear_cq_objects in cad_helpers."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from tests.helpers import install_sys_modules, load_tools_module, restore_sys_modules

NL = chr(10)

TOOLS, _FC_MOCK, _FCGUI_MOCK = load_tools_module()


# ---------------------------------------------------------------------------
# apply_param_values (pure function)
# ---------------------------------------------------------------------------

class TestApplyParamValues:

    def test_replaces_matched_param_lines(self):
        code = NL.join(["OD = 40", "H = 90", "body = cq.Workplane('XY').box(OD, OD, H)"])
        out = TOOLS.apply_param_values(code, {"OD": 60})
        assert out == NL.join(["OD = 60", "H = 90", "body = cq.Workplane('XY').box(OD, OD, H)"])

    def test_replaces_multiple_params(self):
        code = NL.join(["OD = 40", "H = 90", "x = 1"])
        out = TOOLS.apply_param_values(code, {"OD": 60, "H": 120})
        assert out.split(NL)[:2] == ["OD = 60", "H = 120"]

    def test_keeps_float_form(self):
        out = TOOLS.apply_param_values("TOL = 0.1", {"TOL": 0.5})
        assert out == "TOL = 0.5"

    def test_keeps_int_form(self):
        out = TOOLS.apply_param_values("N = 8", {"N": 12})
        assert out == "N = 12"

    def test_non_param_and_unmatched_lines_untouched(self):
        code = NL.join(["body = box(OD)", "od_lower = 3", "# OD = 99 comment"])
        out = TOOLS.apply_param_values(code, {"OD": 60})
        assert out == code  # lowercase / comment / expression lines untouched

    def test_empty_params_returns_same_code(self):
        code = "OD = 40" + NL + "x = 1"
        assert TOOLS.apply_param_values(code, {}) == code


# ---------------------------------------------------------------------------
# clear_cq_objects (cad_helpers ownership)
# ---------------------------------------------------------------------------

class TestClearCqObjects:
    """cad_helpers.clear_cq_objects: removes only cq_show-owned objects."""

    def _doc(self):
        doc = MagicMock()
        own = MagicMock()
        own.Name = "cqobj_1"
        own.Label = "Cup"
        user = MagicMock()
        user.Name = "Part"
        user.Label = "Part"
        doc.Objects = [own, user]
        return doc, user

    def _clear(self, doc):
        import sys
        cad = sys.modules.get("agent.cad_helpers")
        if cad is None or not hasattr(cad, "clear_cq_objects"):
            # Load the real module under mocked FreeCAD/Part (full-suite runs
            # may leave no usable cad_helpers in sys.modules).
            saved = install_sys_modules(
                {"FreeCAD": MagicMock(), "Part": MagicMock()})
            try:
                from tests.helpers import load_module
                cad = load_module("cad_helpers_rb", "agent", "cad_helpers.py")
            finally:
                restore_sys_modules(saved)
        return cad.clear_cq_objects(doc)

    def test_removes_only_cq_owned_objects(self):
        doc, _user = self._doc()
        removed = self._clear(doc)
        assert removed == 1
        doc.removeObject.assert_called_once_with("cqobj_1")

    def test_no_owned_objects_is_noop(self):
        doc = MagicMock()
        doc.Objects = [MagicMock(Name="Part")]
        assert self._clear(doc) == 0
        doc.removeObject.assert_not_called()


# ---------------------------------------------------------------------------
# rebuild_with_params (mocked FreeCAD + snapshot + quality)
# ---------------------------------------------------------------------------

class TestRebuildWithParams:

    def _setup_env(self, docs=("Model",), quality_report=None):
        """Build a mocked environment: docs by name, snapshot and quality patched."""
        import core.snapshot as snapshot_mod
        import core.quality as quality_mod
        from core.quality import QualityReport

        tools, mock_fc, _ = load_tools_module()
        doc_map = {}
        for name in docs:
            d = MagicMock()
            d.Name = name
            d.Objects = []
            doc_map[name] = d
        mock_fc.ActiveDocument = doc_map[docs[0]]
        mock_fc.getDocument = lambda n: doc_map.get(n)
        mock_fc.newDocument = lambda n: doc_map.setdefault(n, MagicMock(Name=n, Objects=[]))

        if quality_report is None:
            quality_report = QualityReport(
                passed=True, severity="ok", issues=[], summary="PASSED")

        restore_calls = []
        take_calls = []
        state = {
            "restore": lambda: restore_calls.append("SUCCESS: Document restored.") or restore_calls[-1],
            "take": lambda doc=None: take_calls.append(doc),
        }
        orig = (snapshot_mod.restore_latest_snapshot, snapshot_mod.take_snapshot_for_doc,
                snapshot_mod.take_snapshot, quality_mod.analyze_document_quality)
        snapshot_mod.restore_latest_snapshot = state["restore"]
        snapshot_mod.take_snapshot_for_doc = lambda doc: state["take"](doc)
        snapshot_mod.take_snapshot = lambda: state["take"](None)
        quality_mod.analyze_document_quality = (
            lambda doc, assembly_mode=False: quality_report)
        saved = install_sys_modules({"FreeCAD": mock_fc})
        tools.clear_persistent_vars()
        tools.set_code_history([])

        def restore_all():
            (snapshot_mod.restore_latest_snapshot, snapshot_mod.take_snapshot_for_doc,
             snapshot_mod.take_snapshot, quality_mod.analyze_document_quality) = orig
            restore_sys_modules(saved)
            tools.clear_persistent_vars()
            tools.set_code_history([])

        return tools, doc_map, take_calls, restore_calls, restore_all

    def test_no_history_returns_error(self):
        tools, doc_map, _t, _r, restore_all = self._setup_env()
        try:
            result = tools.rebuild_with_params({"OD": 60})
            assert result.startswith("ERROR")
            assert "No rebuildable code history" in result
        finally:
            restore_all()

    def test_missing_document_returns_error(self):
        tools, doc_map, _t, _r, restore_all = self._setup_env(docs=("A",))
        tools.set_code_history([("Gone", "x = 1")])
        try:
            result = tools.rebuild_with_params({})
            assert result.startswith("ERROR")
            assert "Gone" in result
        finally:
            restore_all()

    def test_successful_rebuild_replays_and_updates_params(self):
        tools, doc_map, takes, _r, restore_all = self._setup_env()
        code1 = "A = 5"
        code2 = "B = A * 2"
        tools.set_code_history([("Model", code1), ("Model", code2)])
        try:
            result = tools.rebuild_with_params({"A": 10})
            assert result.startswith("OK:")
            assert "2 step(s)" in result
            assert takes == [doc_map["Model"]]  # one snapshot for one doc
            # Cross-segment variable continuity: B derived from replayed A
            assert tools.get_persistent_vars().get("B") == 20
            # Parameter store updated to the new values
            assert tools.get_param_store() == {"A": 10}
        finally:
            restore_all()

    def test_failed_step_rolls_back_all_snapshots(self):
        tools, doc_map, takes, restores, restore_all = self._setup_env(
            docs=("A", "B"))
        tools.set_code_history([
            ("A", "x = 1"),
            ("B", "1 / 0"),      # step 2 explodes
        ])
        try:
            result = tools.rebuild_with_params({})
            assert result.startswith("FAIL:")
            assert "step 2" in result
            assert "ZeroDivisionError" in result
            assert len(takes) == 2              # snapshots for A and B
            assert len(restores) == 2           # both rolled back
            # Namespace cleaned after failure
            assert tools.get_persistent_vars() == {}
        finally:
            restore_all()

    def test_quality_failure_flips_header_to_fail(self):
        from core.quality import QualityIssue, QualityReport
        bad = QualityReport(
            passed=False, severity="fail",
            issues=[QualityIssue(code="NO_SOLID", severity="fail", message="no solids")],
            summary="FAILED")
        tools, doc_map, _t, _r, restore_all = self._setup_env(quality_report=bad)
        tools.set_code_history([("Model", "x = 1")])
        try:
            result = tools.rebuild_with_params({"X": 1})
            assert result.startswith("FAIL: Rebuild completed but CAD quality check failed.")
        finally:
            restore_all()

    def test_active_document_segments_routed_to_active(self):
        tools, doc_map, takes, _r, restore_all = self._setup_env(docs=("Here",))
        tools.set_code_history([("", "x = 1")])   # recorded with no doc name
        try:
            result = tools.rebuild_with_params({})
            assert result.startswith("OK:")
            assert takes == [doc_map["Here"]]
        finally:
            restore_all()
