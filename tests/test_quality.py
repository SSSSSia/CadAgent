"""Tests for core/quality.py — structured CAD quality analysis."""
from __future__ import annotations

from core.geometry_analyzer import ShapeInfo, SolidInfo, FaceInfo, TopologyIssue
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
        issues = _map_topology_issues([TopologyIssue("NO_SOLID", "No solid components.")])
        assert len(issues) == 1
        assert issues[0].code == "NO_SOLID"
        assert issues[0].severity == "fail"

    def test_multi_solid(self):
        issues = _map_topology_issues([TopologyIssue("MULTI_SOLID", "3 separate solids.")])
        assert len(issues) == 1
        assert issues[0].code == "MULTI_SOLID"

    def test_compound(self):
        issues = _map_topology_issues([TopologyIssue("COMPOUND_SHAPE", "Compound shape.")])
        assert len(issues) == 1
        assert issues[0].code == "COMPOUND_SHAPE"

    def test_negative_volume(self):
        issues = _map_topology_issues(
            [TopologyIssue("NEGATIVE_VOLUME", "Negative volume (-500.0 mm3).")]
        )
        assert len(issues) == 1
        assert issues[0].code == "NEGATIVE_VOLUME"

    def test_multiple_issues(self):
        tops = [
            TopologyIssue("COMPOUND_SHAPE", "Compound shape."),
            TopologyIssue("MULTI_SOLID", "2 separate solids."),
        ]
        issues = _map_topology_issues(tops)
        assert len(issues) == 2
        codes = {i.code for i in issues}
        assert codes == {"COMPOUND_SHAPE", "MULTI_SOLID"}

    def test_zero_volume_maps_to_fail(self):
        issues = _map_topology_issues(
            [TopologyIssue("NO_VOLUME", "Degenerate solid with zero volume (0 mm3).")]
        )
        assert issues[0].code == "NO_VOLUME"
        assert issues[0].severity == "fail"

    def test_tiny_volume_maps_to_warn(self):
        issues = _map_topology_issues(
            [TopologyIssue("TINY_VOLUME", "Suspiciously small volume (0.001 mm3).")]
        )
        assert issues[0].code == "TINY_VOLUME"
        assert issues[0].severity == "warn"

    def test_unknown_code_maps_to_fail(self):
        """A reworded/unknown topology code must fail conservatively (S2-B10).

        Previously there was no else branch: an unmatched message silently
        disappeared, turning a fail into a pass.
        """
        issues = _map_topology_issues(
            [TopologyIssue("SOME_NEW_CODE", "Whatever new wording.")]
        )
        assert len(issues) == 1
        assert issues[0].code == "SOME_NEW_CODE"
        assert issues[0].severity == "fail"


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

    def test_multiple_objects_warns(self):
        """MULTIPLE_OBJECTS is a warning, not a failure — stale intermediates."""
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Small", _small_shape_info()),
        ])
        assert report.passed is True
        assert report.severity == "warn"
        assert any(i.code == "MULTIPLE_OBJECTS" for i in report.issues)
        multi_issues = [i for i in report.issues if i.code == "MULTIPLE_OBJECTS"]
        assert all(i.severity == "warn" for i in multi_issues)

    def test_multiple_objects_warn_in_assembly_mode(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Small", _small_shape_info()),
        ], assembly_mode=True)
        assert report.passed is True
        multi_issues = [i for i in report.issues if i.code == "MULTIPLE_OBJECTS"]
        assert all(i.severity == "warn" for i in multi_issues)

    def test_warn_only_passes_true(self):
        """Warnings-only (assembly mode) should still pass = True."""
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Small", _small_shape_info()),
        ], assembly_mode=True)
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


# ===========================================================================
# Phase 6: All-shapes fail checking
# ===========================================================================

class TestAllShapesFailCheck:
    """Non-main shapes with fail-level issues should be detected."""

    def test_non_main_shape_no_solid_detected(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("BadShell", _no_solid_info()),
        ])
        assert report.passed is False
        codes = {i.code for i in report.issues}
        assert "NO_SOLID" in codes

    def test_non_main_shape_negative_volume_detected(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("NegVol", _negative_volume_info()),
        ])
        assert report.passed is False
        codes = {i.code for i in report.issues}
        assert "NEGATIVE_VOLUME" in codes

    def test_non_main_shape_fail_prefixes_label(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("BadShell", _no_solid_info()),
        ])
        no_solid_issues = [i for i in report.issues if i.code == "NO_SOLID"]
        assert any("[BadShell]" in i.message for i in no_solid_issues)

    def test_multiple_non_main_shapes_all_checked(self):
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Neg", _negative_volume_info()),
            ("NoSolid", _no_solid_info()),
        ])
        assert report.passed is False
        codes = {i.code for i in report.issues}
        assert "NEGATIVE_VOLUME" in codes
        assert "NO_SOLID" in codes

    def test_non_main_shape_warn_not_propagated(self):
        """Warn-level issues from non-main shapes should NOT be added."""
        # A compound with 1 solid produces COMPOUND_SHAPE with warn severity
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("Comp1Solid", _compound_one_solid_info()),
        ])
        # COMPOUND_SHAPE from non-main should NOT appear (severity=warn, not fail)
        compound_issues = [
            i for i in report.issues if i.code == "COMPOUND_SHAPE"
        ]
        assert len(compound_issues) == 0

    def test_assembly_mode_non_main_shape_fail_still_detected(self):
        """Even in assembly mode, fail-level issues on non-main shapes should fail."""
        report = analyze_quality_from_infos([
            ("Big", _box_info()),
            ("BadShell", _no_solid_info()),
        ], assembly_mode=True)
        assert report.passed is False
        codes = {i.code for i in report.issues}
        assert "NO_SOLID" in codes


# ===========================================================================
# Tests: duplicate-label identity skip + volume gates in full analysis (S2-B8/B9)
# ===========================================================================

class TestIdentitySkipAndVolumeGates:

    def test_duplicate_labels_both_checked(self):
        """Two objects sharing a label: the non-main one's FAIL-level issue
        must still surface. The old label comparison skipped it, turning a
        fail into a silent pass (S2-B9)."""
        main = _box_info()  # volume 1000 -> main shape
        broken = ShapeInfo(
            bound_box={"XMin": 0, "XMax": 4, "YMin": 0, "YMax": 4, "ZMin": 0, "ZMax": 4},
            volume=0.0, solid_count=1, shape_type="Solid",
            solids=[SolidInfo(faces=[])],
        )
        report = analyze_quality_from_infos([("Part", main), ("Part", broken)])
        assert report.passed is False
        codes = {i.code for i in report.issues if i.severity == "fail"}
        assert "NO_VOLUME" in codes

    def test_non_main_zero_volume_fails_report(self):
        main = _box_info()
        degenerate = ShapeInfo(
            bound_box={"XMin": 0, "XMax": 4, "YMin": 0, "YMax": 4, "ZMin": 0, "ZMax": 4},
            volume=0.0, solid_count=1, shape_type="Solid",
            solids=[SolidInfo(faces=[])],
        )
        report = analyze_quality_from_infos([("Main", main), ("Stub", degenerate)])
        assert report.passed is False
        codes = {i.code for i in report.issues if i.severity == "fail"}
        assert "NO_VOLUME" in codes

    def test_main_zero_volume_fails_report(self):
        degenerate = ShapeInfo(
            bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
            volume=0.0, solid_count=1, shape_type="Solid",
            solids=[SolidInfo(faces=[])],
        )
        report = analyze_quality_from_infos([("Only", degenerate)])
        assert report.passed is False
        assert any(i.code == "NO_VOLUME" for i in report.issues)

    def test_main_tiny_volume_passes_with_warning(self):
        tiny = ShapeInfo(
            bound_box={"XMin": 0, "XMax": 100, "YMin": 0, "YMax": 100, "ZMin": 0, "ZMax": 100},
            volume=0.001, solid_count=1, shape_type="Solid",
            solids=[SolidInfo(faces=[])],
        )
        report = analyze_quality_from_infos([("Hollow", tiny)])
        assert report.passed is True
        assert report.severity == "warn"
        assert any(i.code == "TINY_VOLUME" for i in report.issues)
