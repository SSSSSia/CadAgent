"""
doc_analyzer — extract geometry info from a FreeCAD document as text context.

Thin adapter layer: extracts FreeCAD shape data into plain data structures
and delegates analysis to core/geometry_analyzer.py.
"""
from __future__ import annotations

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
    if geom_type == "Plane" and hasattr(face, "normalAt"):
        n = face.normalAt(0, 0)
        normal = (round(n.x, 2), round(n.y, 2), round(n.z, 2))
    radius = getattr(surf, "Radius", None)
    center = None
    axis = None
    if radius is not None:
        c = getattr(surf, "Center", None)
        if c:
            center = (c.x, c.y, c.z)
        a = getattr(surf, "Axis", None)
        if a:
            axis = (a.x, a.y, a.z)
    return FaceInfo(
        geom_type=geom_type, area=area, normal=normal,
        radius=radius, center=center, axis=axis,
    )


def _extract_shape_info(shape) -> ShapeInfo:
    bb = shape.BoundBox
    com = getattr(shape, "CenterOfMass", None)
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
        solids=[
            SolidInfo(faces=[_extract_face_info(f) for f in solid.Faces])
            for solid in shape.Solids
        ],
    )


def analyze_document(doc=None) -> str:
    """提取 FreeCAD 文档的几何信息，返回文本描述。"""
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
        lines.append(describe_shape(info))

    return "\n".join(lines)
