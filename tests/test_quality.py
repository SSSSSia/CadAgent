"""Tests for core/quality.py — structured CAD quality analysis."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.geometry_analyzer import ShapeInfo, SolidInfo, FaceInfo
from core.quality import (
    QualityIssue,
    QualityReport,
    analyze_quality_from_infos,
    format_quality_report,
    _map_topology_issues,
    _select_main_shape,
)


# ---------------------------------------------------------------------------
# Shape helpers (reuse patterns from test_geometry_analyzer)
# ---------------------------------------------------------------------------

def _box_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=1000.0,
        faces=6, edges=12, vertices=8,
        center_of_mass=(5, 5, 5),
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0),
        ])],
    )


def _cylinder_info():
    return ShapeInfo(
        bound_box={"XMin": -5, "XMax": 5, "YMin": -5, "YMax": 5, "ZMin": 0, "ZMax": 20},
        volume=1570.8,
        faces=3, edges=2, vertices=0,
        center_of_mass=(0, 0, 10),
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Cylinder", area=628.3, radius=5.0),
        ])],
    )


def _multi_solid_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 20, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=2000.0,
        faces=12, edges=24, vertices=16,
        shape_type="Compound",
        solid_count=2,
        solids=[
            SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)]),
            SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)]),
        ],
    )


def _no_solid_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=0.0,
        faces=6, edges=12, vertices=8,
        shape_type="Shell",
        solid_count=0,
        solids=[],
    )


def _compound_no_solid_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=0.0,
        faces=2, edges=2, vertices=2,
        shape_type="Compound",
        solid_count=0,
        solids=[],
    )


def _compound_one_solid_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=1000.0,
        faces=6, edges=12, vertices=8,
        shape_type="Compound",
        solid_count=1,
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0),
        ])],
    )


def _negative_volume_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=-500.0,
        faces=6, edges=12, vertices=8,
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0),
        ])],
    )


def _huge_dimension_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 50000, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=5000000.0,
        faces=6, edges=12, vertices=8,
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)])],
    )


def _tiny_dimension_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 0.005, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=0.05,
        faces=6, edges=12, vertices=8,
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)])],
    )


def _small_shape_info():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 2, "YMin": 0, "YMax": 2, "ZMin": 0, "ZMax": 2},
        volume=8.0,
        faces=6, edges=12, vertices=8,
        shape_type="Solid",
        solid_count=1,
        solids=[SolidInfo(faces=[FaceInfo(geom_type="Plane", area=4.0)])],
    )


# ===========================================================================
# Tests: _select_main_shape
# ===========================================================================

class TestSelectMainShape:
    def test_empty_returns_none(self):
        assert _select_main_shape([]) is None

    def test_single_returns_it(self):
        info = _box_info()
        result = _select_main_shape([("Box", info)])
        assert result == ("Box", info)

    def test_picks_largest_volume(self):
        small = _small_shape_info()
        big = _box_info()
        result = _select_main_shape([("Small", small), ("Big", big)])
        assert result[0] == "Big"


# ===========================================================================
# Tests: _map_topology_issues
# ===========================================================================

class TestMapTopologyIssues:
    def test_empty_list(self):
        assert _map_topology_issues([]) == []

    def test_no_solid(self):
        issues = _map_topology_issues(["No solid components."])
        assert len(issues) == 1
        assert issues[0].code == "NO_SOLID"
        assert issues[0].severity == "fail"

    def test_multi_solid(self):
        issues = _map_topology_issues(["3 separate solids."])
        assert len(issues) == 1
        assert issues[0].code == "MULTI_SOLID"

    def test_compound(self):
        issues = _map_topology_issues(["Compound shape."])
        assert len(issues) == 1
        assert issues[0].code == "COMPOUND_SHAPE"

    def test_negative_volume(self):
        issues = _map_topology_issues(["Negative volume (-500.0 mm3)."])
        assert len(issues) == 1
        assert issues[0].code == "NEGATIVE_VOLUME"

    def test_multiple_issues(self):
        strings = ["Compound shape.", "2 separate solids."]
        issues = _map_topology_issues(strings)
        assert len(issues) == 2
        codes = {i.code for i in issues}
        assert codes == {"COMPOUND_SHAPE", "MULTI_SOLID"}


# ===========================================================================
# Tests: analyze_quality_from_infos
# ===========================================================================

class TestAnalyzeQualityOk:
    def test_single_box_passes(self):
        report = analyze_quality_from_infos([("Box", _box_info())])
        assert report.passed is True
        assert report.severity == "ok"
        assert "PASSED" in report.summary

    def test_single_cylinder_passes(self):
        report = analyze_quality_from_infos([("Cyl", _cylinder_info())])
        assert report.passed is True
        assert report.severity == "ok"


class TestAnalyzeQualityFail:
    def test_empty_returns_no_shape_objects(self):
        report = analyze_quality_from_infos([])
        assert report.passed is False
        assert report.severity == "fail"
        assert any(i.code == "NO_SHAPE_OBJECTS" for i in report.issues)

    def test_no_solid_fails(self):
        report = analyze_quality_from_infos([("Shell", _no_solid_info())])
        assert report.passed is False
        assert report.severity == "fail"
        assert any(i.code == "NO_SOLID" for i in report.issues)

    def test_multi_solid_fails(self):
        report = analyze_quality_from_infos([("Multi", _multi_solid_info())])
        assert report.passed is False
        assert report.severity == "fail"
        assert any(i.code == "MULTI_SOLID" for i in report.issues)

    def test_multi_solid_assembly_mode_passes(self):
        report = analyze_quality_from_infos(
            [("Multi", _multi_solid_info())], assembly_mode=True,
        )
        assert report.passed is True
        # MULTI_SOLID should be downgraded to warn in assembly mode
        multi_issues = [i for i in report.issues if i.code == "MULTI_SOLID"]
        assert all(i.severity == "warn" for i in multi_issues)

    def test_compound_no_solid_fails(self):
        report = analyze_quality_from_infos(
            [("Comp", _compound_no_solid_info())],
        )
        assert report.passed is False
        codes = {i.code for i in report.issues}
        assert "COMPOUND_SHAPE" in codes

    def test_compound_one_solid_passes(self):
        report = analyze_quality_from_infos(
            [("Comp", _compound_one_solid_info())],
        )
        assert report.passed is True

    def test_negative_volume_fails(self):
        report = analyze_quality_from_infos(
            [("Neg", _negative_volume_info())],
        )
        assert report.passed is False
        assert any(i.code == "NEGATIVE_VOLUME" for i in report.issues)

    def test_any_fail_makes_passed_false(self):
        """Any fail issue should make report.passed = False."""
        report = analyze_quality_from_infos([("Shell", _no_solid_info())])
        assert report.passed is False
        assert report.severity == "fail"


class TestAnalyzeQualityWarn:
    def test_dimension_suspicious_large(self):
        report = analyze_quality_from_infos([("Huge", _huge_dimension_info())])
        assert report.passed is True
        assert report.severity == "warn"
        assert any(i.code == "DIMENSION_SUSPICIOUS" for i in report.issues)

    def test_dimension_suspicious_tiny(self):
        report = analyze_quality_from_infos([("Tiny", _tiny_dimension_info())])
        assert report.passed is True
        assert report.severity == "warn"
        assert any(i.code == "DIMENSION_SUSPICIOUS" for i in report.issues)

    def test_multiple_objects_warn(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Small", _small_shape_info()),
        ])
        assert report.passed is True
        assert any(i.code == "MULTIPLE_OBJECTS" for i in report.issues)

    def test_warn_only_passes_true(self):
        """Warnings-only should still pass = True."""
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Small", _small_shape_info()),
        ])
        assert report.passed is True
        assert report.severity == "warn"


# ===========================================================================
# Tests: format_quality_report
# ===========================================================================

class TestFormatQualityReport:
    def test_ok_report(self):
        report = QualityReport(
            passed=True, severity="ok",
            issues=[], summary="Quality check PASSED for 'Box'.",
        )
        text = format_quality_report(report)
        assert text.startswith("OK:")
        assert "PASSED" in text

    def test_fail_report(self):
        report = QualityReport(
            passed=False, severity="fail",
            issues=[
                QualityIssue(
                    code="MULTI_SOLID", severity="fail",
                    message="2 separate solids.",
                    suggestion="Extend one shape INTO the other.",
                ),
            ],
            summary="Quality check FAILED for 'Obj': 2 separate solids.",
        )
        text = format_quality_report(report)
        assert text.startswith("FAIL:")
        assert "2 separate solids" in text
        assert "Required action" in text

    def test_warn_report(self):
        report = QualityReport(
            passed=True, severity="warn",
            issues=[
                QualityIssue(
                    code="DIMENSION_SUSPICIOUS", severity="warn",
                    message="X-dimension is 50000.0mm.",
                ),
            ],
            summary="Quality check passed with warnings for 'Obj'.",
        )
        text = format_quality_report(report)
        assert text.startswith("OK:")
        assert "warnings" in text
        assert "50000" in text

    def test_empty_issues_ok(self):
        report = QualityReport(
            passed=True, severity="ok", issues=[], summary="",
        )
        text = format_quality_report(report)
        assert "PASSED" in text
