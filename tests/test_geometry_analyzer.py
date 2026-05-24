"""Tests for core/geometry_analyzer.py — pure geometry analysis without FreeCAD."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.geometry_analyzer import (
    ShapeInfo, SolidInfo, FaceInfo,
    infer_shape_type, detect_planar_faces, describe_shape,
    detect_conical_faces, detect_spherical_faces,
    detect_helical_faces, detect_hole_patterns,
    detect_symmetry, detect_wall_thickness,
)


def _box_shape():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 10, "YMin": 0, "YMax": 10, "ZMin": 0, "ZMax": 10},
        volume=1000.0,
        faces=6, edges=12, vertices=8,
        center_of_mass=(5, 5, 5),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0, normal=(1, 0, 0), center=(10, 5, 5)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(-1, 0, 0), center=(0, 5, 5)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 1, 0), center=(5, 10, 5)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, -1, 0), center=(5, 0, 5)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 0, 1), center=(5, 5, 10)),
            FaceInfo(geom_type="Plane", area=100.0, normal=(0, 0, -1), center=(5, 5, 0)),
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


def _cone_shape():
    return ShapeInfo(
        bound_box={"XMin": -5, "XMax": 5, "YMin": -5, "YMax": 5, "ZMin": 0, "ZMax": 20},
        volume=1047.2, faces=3, edges=2, vertices=1,
        center_of_mass=(0, 0, 5),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Cone", area=314.0, radius=5.0,
                     center=(0, 0, 0), axis=(0, 0, 1),
                     cone_half_angle=14.04),
            FaceInfo(geom_type="Plane", area=78.5, normal=(0, 0, 1),
                     center=(0, 0, 20)),
        ])],
    )


def _sphere_shape():
    return ShapeInfo(
        bound_box={"XMin": -5, "XMax": 5, "YMin": -5, "YMax": 5, "ZMin": -5, "ZMax": 5},
        volume=523.6, faces=2, edges=1, vertices=0,
        center_of_mass=(0, 0, 0),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Sphere", area=314.16, radius=5.0, center=(0, 0, 0)),
        ])],
    )


def _bolt_hole_pattern_shape():
    faces = [
        FaceInfo(geom_type="Cylinder", area=100.0, radius=3.0,
                 center=(20, 0, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Cylinder", area=100.0, radius=3.0,
                 center=(0, 20, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Cylinder", area=100.0, radius=3.0,
                 center=(-20, 0, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Cylinder", area=100.0, radius=3.0,
                 center=(0, -20, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Plane", area=100.0, normal=(0, 0, 1),
                 center=(0, 0, 0)),
    ]
    return ShapeInfo(
        bound_box={"XMin": -25, "XMax": 25, "YMin": -25, "YMax": 25, "ZMin": 0, "ZMax": 10},
        volume=1000.0, faces=5, edges=4, vertices=0,
        center_of_mass=(0, 0, 5),
        solids=[SolidInfo(faces=faces)],
    )


def _symmetric_shape():
    faces = []
    for nx, ny in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        faces.append(FaceInfo(geom_type="Plane", area=100.0,
                              normal=(nx, ny, 0),
                              center=(nx * 5, ny * 5, 0)))
    for nz in [1, -1]:
        faces.append(FaceInfo(geom_type="Plane", area=100.0,
                              normal=(0, 0, nz),
                              center=(0, 0, nz * 5)))
    return ShapeInfo(
        bound_box={"XMin": -5, "XMax": 5, "YMin": -5, "YMax": 5, "ZMin": -5, "ZMax": 5},
        volume=1000.0, faces=6, edges=12, vertices=8,
        center_of_mass=(0, 0, 0),
        solids=[SolidInfo(faces=faces)],
    )


def _thin_wall_shape():
    return ShapeInfo(
        bound_box={"XMin": 0, "XMax": 100, "YMin": 0, "YMax": 50, "ZMin": 0, "ZMax": 10},
        volume=5000.0, faces=6, edges=12, vertices=8,
        center_of_mass=(50, 25, 5),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=5000.0, normal=(0, 0, 1),
                     center=(50, 25, 10)),
            FaceInfo(geom_type="Plane", area=5000.0, normal=(0, 0, -1),
                     center=(50, 25, 0)),
            FaceInfo(geom_type="Plane", area=500.0, normal=(1, 0, 0),
                     center=(100, 25, 5)),
            FaceInfo(geom_type="Plane", area=500.0, normal=(-1, 0, 0),
                     center=(0, 25, 5)),
            FaceInfo(geom_type="Plane", area=1000.0, normal=(0, 1, 0),
                     center=(50, 50, 5)),
            FaceInfo(geom_type="Plane", area=1000.0, normal=(0, -1, 0),
                     center=(50, 0, 5)),
        ])],
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
        FaceInfo(geom_type="SomeOther"),
        FaceInfo(geom_type="Plane"),
    ])])
    assert infer_shape_type(info) is None


def test_infer_empty_returns_none():
    info = ShapeInfo(solids=[])
    assert infer_shape_type(info) is None


def test_infer_cone():
    assert infer_shape_type(_cone_shape()) == "Cone/frustum"


def test_infer_sphere():
    assert infer_shape_type(_sphere_shape()) == "Sphere"


def test_infer_helix():
    info = ShapeInfo(solids=[SolidInfo(faces=[
        FaceInfo(geom_type="Helix"),
        FaceInfo(geom_type="Plane"),
    ])])
    assert infer_shape_type(info) == "Threaded part"


# ---- detect_planar_faces ----

def test_planar_faces_groups_parallel():
    info = _box_shape()
    result = detect_planar_faces(info)
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
    result = detect_planar_faces(info, min_area=0.0)
    assert len(result) >= 1


# ---- detect_conical_faces ----

def test_detect_conical():
    result = detect_conical_faces(_cone_shape())
    assert len(result) == 1
    assert "half-angle=14.0deg" in result[0]


def test_detect_conical_none():
    result = detect_conical_faces(_box_shape())
    assert result == []


# ---- detect_spherical_faces ----

def test_detect_spherical():
    result = detect_spherical_faces(_sphere_shape())
    assert len(result) == 1
    assert "R=5.0mm" in result[0]


def test_detect_spherical_none():
    result = detect_spherical_faces(_box_shape())
    assert result == []


# ---- detect_helical_faces ----

def test_detect_helical():
    info = ShapeInfo(solids=[SolidInfo(faces=[
        FaceInfo(geom_type="Helix"),
        FaceInfo(geom_type="Plane"),
    ])])
    result = detect_helical_faces(info)
    assert len(result) == 1
    assert "thread" in result[0].lower()


def test_detect_helical_none():
    result = detect_helical_faces(_box_shape())
    assert result == []


# ---- detect_hole_patterns ----

def test_hole_pattern_circular():
    result = detect_hole_patterns(_bolt_hole_pattern_shape())
    assert len(result) == 1
    assert "Circular" in result[0]
    assert "4 holes" in result[0]


def test_hole_pattern_none():
    result = detect_hole_patterns(_box_shape())
    assert result == []


def test_hole_pattern_single_cylinder():
    result = detect_hole_patterns(_cylinder_shape())
    assert result == []


def test_hole_pattern_linear():
    faces = [
        FaceInfo(geom_type="Cylinder", area=50.0, radius=2.0,
                 center=(0, 0, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Cylinder", area=50.0, radius=2.0,
                 center=(10, 0, 0), axis=(0, 0, 1)),
        FaceInfo(geom_type="Cylinder", area=50.0, radius=2.0,
                 center=(20, 0, 0), axis=(0, 0, 1)),
    ]
    info = ShapeInfo(
        center_of_mass=(10, 0, 0),
        solids=[SolidInfo(faces=faces)],
    )
    result = detect_hole_patterns(info)
    assert len(result) == 1
    assert "Linear" in result[0]


# ---- detect_symmetry ----

def test_symmetry_box():
    result = detect_symmetry(_symmetric_shape())
    assert len(result) == 3


def test_symmetry_asymmetric():
    info = ShapeInfo(
        center_of_mass=(3, 3, 3),
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0, center=(0, 0, 0)),
            FaceInfo(geom_type="Plane", area=50.0, center=(10, 10, 10)),
        ])],
    )
    result = detect_symmetry(info)
    assert result == []


def test_symmetry_no_center_of_mass():
    info = ShapeInfo(
        center_of_mass=None,
        solids=[SolidInfo(faces=[
            FaceInfo(geom_type="Plane", area=100.0, center=(0, 0, 0)),
        ])],
    )
    result = detect_symmetry(info)
    assert result == []


# ---- detect_wall_thickness ----

def test_wall_thickness_thin():
    result = detect_wall_thickness(_thin_wall_shape())
    assert len(result) >= 1
    assert "10.0mm" in result[0]


def test_wall_thickness_thick():
    result = detect_wall_thickness(_box_shape())
    assert result == []


# ---- describe_shape (existing) ----

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


# ---- describe_shape (new features) ----

def test_describe_shape_cone():
    text = describe_shape(_cone_shape())
    assert "conical features" in text.lower()
    assert "Cone/frustum" in text


def test_describe_shape_sphere():
    text = describe_shape(_sphere_shape())
    assert "spherical features" in text.lower()
    assert "Sphere" in text


def test_describe_shape_hole_pattern():
    text = describe_shape(_bolt_hole_pattern_shape())
    assert "hole pattern" in text.lower() or "Circular" in text


def test_describe_shape_symmetry():
    text = describe_shape(_symmetric_shape())
    assert "Symmetry" in text


def test_describe_shape_thin_wall():
    text = describe_shape(_thin_wall_shape())
    assert "Thin-wall" in text
