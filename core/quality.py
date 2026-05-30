"""CAD quality judgment -- structured pass/fail analysis for geometry.

Two-layer design (same pattern as doc_analyzer + geometry_analyzer):
- Pure analysis: takes ShapeInfo dataclasses, returns QualityReport
- FreeCAD integration: takes FreeCAD Document, delegates to pure analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.geometry_analyzer import (
    ShapeInfo,
    detect_topology_issues,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QualityIssue:
    code: str           # "NO_SOLID", "MULTI_SOLID", etc.
    severity: str       # "fail" | "warn"
    message: str
    suggestion: str = ""


@dataclass
class QualityReport:
    passed: bool
    severity: str       # "ok" | "warn" | "fail"
    issues: list[QualityIssue] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Topology string → structured issue mapping
# ---------------------------------------------------------------------------

def _map_topology_issues(
    topo_strings: list[str],
    solid_count: int = 0,
) -> list[QualityIssue]:
    """Convert detect_topology_issues() strings into QualityIssue objects.

    Args:
        topo_strings: output of detect_topology_issues().
        solid_count: used to decide severity for Compound shapes.
    """
    issues: list[QualityIssue] = []
    for s in topo_strings:
        if "No solid components" in s:
            issues.append(QualityIssue(
                code="NO_SOLID", severity="fail", message=s,
                suggestion="Use Part.makeBox/makeCylinder instead of "
                           "makePolygon+extrude to create a solid.",
            ))
        elif "separate solids" in s:
            issues.append(QualityIssue(
                code="MULTI_SOLID", severity="fail", message=s,
                suggestion="Shapes must PHYSICALLY OVERLAP for fuse() to "
                           "merge into one solid. Extend one shape INTO the "
                           "other by at least 0.5mm.",
            ))
        elif "Compound shape" in s:
            # Compound with exactly 1 solid is extractable — warn, not fail
            sev = "warn" if solid_count == 1 else "fail"
            issues.append(QualityIssue(
                code="COMPOUND_SHAPE", severity=sev, message=s,
                suggestion="Extract solid: if shape.Solids: "
                           "shape = shape.Solids[0]",
            ))
        elif "Negative volume" in s:
            issues.append(QualityIssue(
                code="NEGATIVE_VOLUME", severity="fail", message=s,
                suggestion="Inside-out geometry. Check winding order or "
                           "reverse construction order.",
            ))
    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_main_shape(
    shape_infos: list[tuple[str, ShapeInfo]],
) -> tuple[str, ShapeInfo] | None:
    """Select the primary shape (largest absolute volume)."""
    if not shape_infos:
        return None
    return max(shape_infos, key=lambda pair: abs(pair[1].volume))


def _check_dimension_warnings(info: ShapeInfo) -> list[QualityIssue]:
    """Warn if bounding box dimensions are suspiciously large or tiny."""
    issues: list[QualityIssue] = []
    bb = info.bound_box
    if not bb:
        return issues
    for axis in ("X", "Y", "Z"):
        lo = bb.get(f"{axis}Min", 0)
        hi = bb.get(f"{axis}Max", 0)
        dim = abs(hi - lo)
        if dim > 10000:
            issues.append(QualityIssue(
                code="DIMENSION_SUSPICIOUS", severity="warn",
                message=f"{axis}-dimension is {dim:.1f}mm (extremely large).",
                suggestion="Verify dimensions match requirements.",
            ))
            break  # one warning is enough
        if 0 < dim < 0.01:
            issues.append(QualityIssue(
                code="DIMENSION_SUSPICIOUS", severity="warn",
                message=f"{axis}-dimension is {dim:.4f}mm (extremely small).",
                suggestion="Verify dimensions match requirements.",
            ))
            break
    return issues


# ---------------------------------------------------------------------------
# Pure analysis (no FreeCAD dependency)
# ---------------------------------------------------------------------------

def analyze_quality_from_infos(
    shape_infos: list[tuple[str, ShapeInfo]],
    assembly_mode: bool = False,
) -> QualityReport:
    """Analyze CAD quality from ShapeInfo dataclasses.

    Args:
        shape_infos: list of (label, ShapeInfo) pairs from document objects.
        assembly_mode: if True, allow multiple separate solids.

    Returns:
        QualityReport with structured pass/fail result.
    """
    issues: list[QualityIssue] = []

    # --- Document-level: no shapes at all ---
    if not shape_infos:
        return QualityReport(
            passed=False,
            severity="fail",
            issues=[QualityIssue(
                code="NO_SHAPE_OBJECTS", severity="fail",
                message="Document has no usable shape objects.",
                suggestion="Use doc.addObject('Part::Feature', 'Name') and "
                           "set obj.Shape to a Part solid.",
            )],
            summary="No shape objects in document.",
        )

    # --- Fail/warn: multiple objects ---
    if len(shape_infos) > 1 and not assembly_mode:
        issues.append(QualityIssue(
            code="MULTIPLE_OBJECTS", severity="fail",
            message=f"Document has {len(shape_infos)} shape objects; "
                    f"expected 1 for a single-part design.",
            suggestion="Use assembly_mode=True for multi-part designs, "
                       "or fuse all shapes into one solid.",
        ))
    elif len(shape_infos) > 1 and assembly_mode:
        issues.append(QualityIssue(
            code="MULTIPLE_OBJECTS", severity="warn",
            message=f"Document has {len(shape_infos)} shape objects (assembly mode).",
        ))

    # --- Select main shape ---
    main_label, main_info = _select_main_shape(shape_infos)

    # --- Check ALL non-main shapes for fail-level issues ---
    for label, info in shape_infos:
        if label == main_label:
            continue
        non_main_topo = detect_topology_issues(info)
        non_main_issues = _map_topology_issues(non_main_topo, info.solid_count)
        for iss in non_main_issues:
            if iss.severity == "fail":
                iss.message = f"[{label}] {iss.message}"
                issues.append(iss)

    # --- Reuse existing topology detection on main shape ---
    topo_strings = detect_topology_issues(main_info)
    topo_issues = _map_topology_issues(topo_strings, main_info.solid_count)

    # In assembly mode, downgrade MULTI_SOLID and COMPOUND_SHAPE to warnings
    if assembly_mode:
        for iss in topo_issues:
            if iss.code in ("MULTI_SOLID", "COMPOUND_SHAPE"):
                iss.severity = "warn"
                iss.suggestion = ""

    issues.extend(topo_issues)

    # --- Dimension warnings ---
    issues.extend(_check_dimension_warnings(main_info))

    # --- Build report ---
    has_fail = any(iss.severity == "fail" for iss in issues)
    has_warn = any(iss.severity == "warn" for iss in issues)

    if has_fail:
        severity = "fail"
        passed = False
        fail_msgs = [iss.message for iss in issues if iss.severity == "fail"]
        summary = f"Quality check FAILED for '{main_label}': " + "; ".join(fail_msgs)
    elif has_warn:
        severity = "warn"
        passed = True
        warn_msgs = [iss.message for iss in issues if iss.severity == "warn"]
        summary = f"Quality check passed with warnings for '{main_label}': " + "; ".join(warn_msgs)
    else:
        severity = "ok"
        passed = True
        summary = f"Quality check PASSED for '{main_label}'."

    return QualityReport(
        passed=passed,
        severity=severity,
        issues=issues,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# FreeCAD integration layer
# ---------------------------------------------------------------------------

def analyze_document_quality(doc, assembly_mode: bool = False) -> QualityReport:
    """Analyze CAD quality of a FreeCAD document.

    Args:
        doc: FreeCAD Document object. If None, returns NO_DOCUMENT fail.
        assembly_mode: if True, allow multiple separate solids.

    Returns:
        QualityReport with structured pass/fail result.
    """
    if doc is None:
        return QualityReport(
            passed=False,
            severity="fail",
            issues=[QualityIssue(
                code="NO_DOCUMENT", severity="fail",
                message="No active document.",
                suggestion="Create a document first: "
                           "doc = FreeCAD.newDocument('Model')",
            )],
            summary="No active document.",
        )

    from core.doc_analyzer import _extract_shape_info

    # Collect (label, ShapeInfo) for all valid shape objects
    pairs: list[tuple[str, ShapeInfo]] = []
    for obj in doc.Objects:
        if not hasattr(obj, "Shape") or obj.Shape is None:
            continue
        if obj.Shape.isNull():
            continue
        info = _extract_shape_info(obj.Shape)
        pairs.append((obj.Label, info))

    report = analyze_quality_from_infos(pairs, assembly_mode)

    # Additional FreeCAD-only check: shape.isValid() for ALL objects
    for obj in doc.Objects:
        if not hasattr(obj, "Shape") or obj.Shape is None:
            continue
        if obj.Shape.isNull():
            continue
        if not obj.Shape.isValid():
            label = obj.Label
            report.issues.append(QualityIssue(
                code="INVALID_SHAPE", severity="fail",
                message=f"Object '{label}' has invalid shape geometry.",
                suggestion="Boolean operation may have produced "
                           "invalid result. Ensure shapes "
                           "overlap correctly.",
            ))
            report.passed = False
            report.severity = "fail"
            fail_msgs = [i.message for i in report.issues if i.severity == "fail"]
            report.summary = "Quality check FAILED: " + "; ".join(fail_msgs)

    return report


# ---------------------------------------------------------------------------
# Formatting for LLM consumption
# ---------------------------------------------------------------------------

def format_quality_report(report: QualityReport) -> str:
    """Format a QualityReport into a human-readable string for the LLM."""
    if report.severity == "ok":
        return "OK: Code executed. CAD quality check PASSED."

    lines = []
    if report.severity == "fail":
        lines.append("FAIL: Code executed but CAD quality check failed.")
    elif report.severity == "warn":
        lines.append("OK: Code executed. CAD quality check passed with warnings.")

    if report.issues:
        fail_issues = [i for i in report.issues if i.severity == "fail"]
        warn_issues = [i for i in report.issues if i.severity == "warn"]

        if fail_issues:
            lines.append("Quality issues:")
            for iss in fail_issues:
                line = f"  - {iss.message}"
                if iss.suggestion:
                    line += f" Fix: {iss.suggestion}"
                lines.append(line)

        if report.severity == "fail":
            lines.append(
                "Required action: rebuild or modify geometry so the final "
                "result is one valid solid."
            )

        if warn_issues:
            lines.append("Warnings:")
            for iss in warn_issues:
                lines.append(f"  - {iss.message}")

    return "\n".join(lines)
