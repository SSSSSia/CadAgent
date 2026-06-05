"""
doc_analyzer — extract geometry info from a FreeCAD document as text context.

Thin adapter layer: extracts FreeCAD shape data into plain data structures
and delegates analysis to core/geometry_analyzer.py.
"""
from __future__ import annotations

import math

import FreeCAD

from core.geometry_analyzer import (
    ShapeInfo, SolidInfo, FaceInfo,
    describe_shape,
)


def _extract_face_info(face) -> FaceInfo:
    surf = face.Surface
    geom_type = getattr(surf, "geomType", "Unknown")
    area = face.Area if hasattr(face, "Area") else 0.0
    normal = None
    center = None
    axis = None
    cone_half_angle = None

    if geom_type == "Plane" and hasattr(face, "normalAt"):
        n = face.normalAt(0, 0)
        normal = (round(n.x, 2), round(n.y, 2), round(n.z, 2))

    # Radius-based surfaces (Cylinder, Sphere, Cone, Torus)
    radius = getattr(surf, "Radius", None)
    if radius is not None:
        c = getattr(surf, "Center", None)
        if c:
            center = (c.x, c.y, c.z)
        a = getattr(surf, "Axis", None)
        if a:
            axis = (a.x, a.y, a.z)

    # Cone-specific: half-angle
    if geom_type == "Cone":
        sa = getattr(surf, "SemiAngle", None)
        if sa is not None:
            cone_half_angle = round(math.degrees(sa), 2)

    # Plane center point (for symmetry and wall-thickness detection)
    if geom_type == "Plane" and center is None:
        if hasattr(face, "CenterOfMass"):
            c = face.CenterOfMass
            center = (c.x, c.y, c.z)
        elif hasattr(face, "BoundBox"):
            bb = face.BoundBox
            center = (
                (bb.XMin + bb.XMax) / 2,
                (bb.YMin + bb.YMax) / 2,
                (bb.ZMin + bb.ZMax) / 2,
            )

    return FaceInfo(
        geom_type=geom_type, area=area, normal=normal,
        radius=radius, center=center, axis=axis,
        cone_half_angle=cone_half_angle,
    )


def _extract_shape_info(shape) -> ShapeInfo:
    bb = shape.BoundBox
    com = getattr(shape, "CenterOfMass", None)
    solid_list = shape.Solids
    return ShapeInfo(
        bound_box={
            "XMin": bb.XMin, "XMax": bb.XMax,
            "YMin": bb.YMin, "YMax": bb.YMax,
            "ZMin": bb.ZMin, "ZMax": bb.ZMax,
        },
        volume=shape.Volume,
        faces=len(shape.Faces),
        edges=len(shape.Edges),
        vertices=len(shape.Vertexes),
        center_of_mass=(com.x, com.y, com.z) if com else None,
        shape_type=shape.ShapeType,
        solid_count=len(solid_list),
        solids=[
            SolidInfo(faces=[_extract_face_info(f) for f in solid.Faces])
            for solid in solid_list
        ],
    )


def analyze_document(doc=None, concise: bool = False) -> str:
    """提取 FreeCAD 文档的几何信息，返回文本描述。

    Args:
        doc: FreeCAD Document (defaults to ActiveDocument).
        concise: If True, produce a compact summary (~4 lines per object)
                 instead of the full detailed analysis.  Used in
                 execute_code tool results to reduce LLM context bloat.
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return "(No active document)"

    lines = [f"Current document: '{doc.Name}', objects:"]

    for obj in doc.Objects:
        if not hasattr(obj, "Shape") or obj.Shape is None:
            continue
        if obj.Shape.isNull():
            continue

        lines.append(f"- '{obj.Label}' (type: {obj.TypeId})")
        info = _extract_shape_info(obj.Shape)
        if concise:
            from core.geometry_analyzer import describe_shape_concise
            lines.append(describe_shape_concise(info))
        else:
            lines.append(describe_shape(info))

    return "\n".join(lines)


def analyze_all_documents() -> str:
    """Analyze all open FreeCAD documents and return combined context."""
    docs = FreeCAD.listDocuments()
    if not docs:
        return "(No documents open)"

    active_name = FreeCAD.ActiveDocument.Name if FreeCAD.ActiveDocument else ""
    lines = []
    for name, doc in docs.items():
        marker = " [ACTIVE]" if name == active_name else ""
        lines.append(f"=== Document: '{name}'{marker} ===")
        doc_analysis = analyze_document(doc)
        for line in doc_analysis.split("\n")[1:]:
            lines.append(line)
        lines.append("")

    return "\n".join(lines)
