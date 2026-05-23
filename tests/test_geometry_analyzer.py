"""Tests for core/geometry_analyzer.py — pure geometry analysis without FreeCAD."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.geometry_analyzer import (
    ShapeInfo, SolidInfo, FaceInfo,
    infer_shape_type, detect_planar_faces, describe_shape,
)


def _box_shape():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=1000.0,
        faces=6, edges=12, vertices=8,
        center_of_mass=(5, 5, 5),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0, normal=(1, 0, 0)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(-1, 0, 0)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 1, 0)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, -1, 0)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 0, 1)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 0, -1)),
        ])],
    )


def _cylinder_shape():
    return ShapeInfo(
        bound_box={"XMin": -5, "XMax": 5, "YMin": -5, "YMax": 5, "ZMin": 0, "ZMax": 20},
        volume=1570.8,
        faces=3, edges=2, vertices=0,
        center_of_mass=(0, 0, 10),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Cylinder", area=628.3, radius=5.0,
                     center=(0, 0, 10), axis=(0, 0, 1)),
            FaceInfo(geom_type="Plane", area=78.5, normal=(0, 0, 1)),
            FaceInfo(geom_type="Plane", area=78.5, normal=(0, 0, -1)),
        ])],
    )


def _multi_solid_shape():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 20, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=2000.0,
        faces=12, edges=24, vertices=16,
        solids=[
            SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)]),
            SolidInfo(faces=[FaceInfo(geom_type="Plane", area=100.0)]),
        ],
    )


# ---- infer_shape_type ----

def test_infer_box():
    assert infer_shape_type(_box_shape()) == "Box"


def test_infer_cylinder():
    assert infer_shape_type(_cylinder_shape()) == "Solid cylinder"


def test_infer_multi_solid():
    assert infer_shape_type(_multi_solid_shape()) == "Multi-solid assembly"


def test_infer_complex_boolean():
    info = ShapeInfo(solids=[SolidInfo(faces=[
        FaceInfo(geom_type="Plane") for _ in range(25)
    ])])
    assert infer_shape_type(info) == "Complex boolean result"


def test_infer_other_curved_returns_none():
    info = ShapeInfo(solids=[SolidInfo(faces=[
        FaceInfo(geom_type="Sphere"),
        FaceInfo(geom_type="Plane"),
    ])])
    assert infer_shape_type(info) is None


def test_infer_empty_returns_none():
    info = ShapeInfo(solids=[])
    assert infer_shape_type(info) is None


# ---- detect_planar_faces ----

def test_planar_faces_groups_parallel():
    info = _box_shape()
    result = detect_planar_faces(info)
    # 3 pairs of parallel planes (normal: ±X, ±Y, ±Z)
    parallel = [r for r in result if "parallel" in r]
    assert len(parallel) == 3


def test_planar_faces_filters_small():
    info = ShapeInfo(solids=[SolidInfo(faces=[
        FaceInfo(geom_type="Plane", area=50.0, normal=(1, 0, 0)),
        FaceInfo(geom_type="Plane", area=200.0, normal=(0, 1, 0)),
    ])])
    result = detect_planar_faces(info, min_area=100.0)
    assert len(result) == 1
    assert "area=200.0" in result[0]


def test_planar_faces_no_planes():
    info = _cylinder_shape()
    # Cylinder shape has planes but they might be filtered
    result = detect_planar_faces(info, min_area=0.0)
    assert len(result) >= 1


# ---- describe_shape ----

def test_describe_shape_box():
    text = describe_shape(_box_shape())
    assert "Bounding box:" in text
    assert "Overall: 10.0 x 10.0 x 10.0" in text
    assert "Volume: 1000.0" in text
    assert "Faces: 6" in text
    assert "Center of mass:" in text
    assert "Inferred type: Box" in text
    assert "Detected planar features:" in text


def test_describe_shape_cylinder():
    text = describe_shape(_cylinder_shape())
    assert "R=5.0mm" in text
    assert "Detected cylindrical features:" in text
    assert "Inferred type: Solid cylinder" in text


def test_describe_shape_multi_solid():
    text = describe_shape(_multi_solid_shape())
    assert "Multi-solid assembly" in text


def test_describe_shape_no_volume():
    info = ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=0.0,
        faces=6, edges=12, vertices=8,
    )
    text = describe_shape(info)
    assert "Volume" not in text
