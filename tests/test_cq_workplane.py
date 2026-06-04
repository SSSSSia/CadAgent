"""Tests for agent/cq.py — CadQuery-style Workplane wrapper.

Uses mock objects to simulate FreeCAD's Part module, following the project
pattern of importlib.util.spec_from_file_location to avoid real FreeCAD deps.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import os
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Minimal FreeCAD / Part mock so we can load cq.py without a real FreeCAD
# ---------------------------------------------------------------------------

@dataclass
class _MockShape:
    """Lightweight FreeCAD shape stand-in."""
    shape_type: str = "Solid"
    is_null: bool = False
    volume: float = 0.0
    solids: list = None
    bounds: tuple = (0, 0, 0, 0, 0, 0)
    area: float = 0.0

    def __post_init__(self):
        if self.solids is None:
            self.solids = [self]

    # ShapeType is a property in FreeCAD, not an attribute
    @property
    def ShapeType(self):
        return self.shape_type

    def isNull(self):
        return self.is_null

    @property
    def Solids(self):
        return self.solids

    @property
    def Volume(self):
        return self.volume

    def copy(self):
        return _MockShape(
            shape_type=self.shape_type,
            is_null=self.is_null,
            volume=self.volume,
            solids=[self],
            bounds=self.bounds,
        )

    def translate(self, vec):
        """Simulate translate — just update bounds."""
        self.bounds = tuple(b + v for b, v in zip(self.bounds, [vec.x, vec.y, vec.z,
                                                                 vec.x, vec.y, vec.z]))

    def fuse(self, other):
        return _MockShape(shape_type="Solid",
                          volume=self.volume + other.volume,
                          solids=[self],
                          bounds=(0, 0, 0, 0, 0, 0))

    def cut(self, other):
        return _MockShape(shape_type="Solid", solids=[self],
                          volume=max(0, self.volume - other.volume))

    def common(self, other):
        return _MockShape(shape_type="Solid", solids=[self], volume=0)

    def rotate(self, center, axis, angle):
        pass  # no-op in mock

    def mirror(self, base, normal):
        pass  # no-op in mock


@dataclass
class _MockVector:
    x: float = 0
    y: float = 0
    z: float = 0


def _make_fc_mock():
    """Build a minimal FreeCAD mock module."""
    fc = type(sys)("FreeCAD")

    class _Doc:
        Name = "MockDoc"
        _active = None

        def __init__(self):
            _Doc._active = self
            self._objects = []

        def addObject(self, t, name):
            obj = _MockObj(name)
            self._objects.append(obj)
            return obj

        def recompute(self):
            pass

        @classmethod
        def ActiveDocument(cls):
            return cls._active

        @classmethod
        def newDocument(cls, name):
            d = cls()
            d.Name = name
            return d

        @classmethod
        def getDocument(cls, name):
            if cls._active and cls._active.Name == name:
                return cls._active
            raise RuntimeError("no such document")

        @classmethod
        def listDocuments(cls):
            return {cls._active.Name: cls._active} if cls._active else {}

        @classmethod
        def getUserAppDataDir(cls):
            return "/tmp/mock_fc"

        @classmethod
        def openDocument(cls, path):
            return cls.newDocument("restored")

        @classmethod
        def closeDocument(cls, name):
            pass

    fc.ActiveDocument = _Doc.ActiveDocument
    fc.newDocument = _Doc.newDocument
    fc.getDocument = _Doc.getDocument
    fc.listDocuments = _Doc.listDocuments
    fc.getUserAppDataDir = _Doc.getUserAppDataDir
    fc.openDocument = _Doc.openDocument
    fc.closeDocument = _Doc.closeDocument
    fc.Document = _Doc
    fc.Vector = _MockVector

    # Part mock
    part = type(sys)("Part")

    def _make_box(L, W, H, p=None):
        return _MockShape(shape_type="Solid", volume=L * W * H,
                          bounds=(0, 0, 0, L, W, H))

    def _make_cylinder(r, h, p=None, a=None):
        return _MockShape(shape_type="Solid", volume=math.pi * r * r * h,
                          bounds=(0, 0, 0, 2 * r, 2 * r, h))

    def _make_cone(r1, r2, h, p=None, a=None):
        return _MockShape(shape_type="Solid",
                          volume=math.pi * h * (r1 * r1 + r2 * r2 + r1 * r2) / 3,
                          bounds=(0, 0, 0, 2 * max(r1, r2), 2 * max(r1, r2), h))

    def _make_sphere(r, p=None):
        return _MockShape(shape_type="Solid", volume=4 / 3 * math.pi * r ** 3,
                          bounds=(-r, -r, -r, r, r, r))

    def _make_torus(major_r, minor_r, p=None):
        return _MockShape(shape_type="Solid",
                          volume=2 * math.pi ** 2 * major_r * minor_r ** 2,
                          bounds=(-major_r - minor_r, -major_r - minor_r,
                                  -minor_r, major_r + minor_r, major_r + minor_r,
                                  minor_r))

    def _make_line(p1, p2):
        return _MockShape(shape_type="Edge")

    part.makeBox = _make_box
    part.makeCylinder = _make_cylinder
    part.makeCone = _make_cone
    part.makeSphere = _make_sphere
    part.makeTorus = _make_torus
    part.makeLine = _make_line

    class _Wire:
        def __init__(self, edges):
            pass

        def isClosed(self):
            return True

        def makePipe(self, profile):
            return _MockShape(shape_type="Solid", volume=100)

    part.Wire = _Wire

    class _Face:
        def __init__(self, wire):
            pass

        def extrude(self, vec):
            return _MockShape(shape_type="Solid", volume=500)

    part.Face = _Face

    return fc, part


# Install mocks (save originals so we can restore for other test modules)
_ORIG_MODULES = {
    k: sys.modules.get(k) for k in
    ("FreeCAD", "Part", "agent.cad_helpers", "agent.cq")
}

_fc_mock, _part_mock = _make_fc_mock()
sys.modules["FreeCAD"] = _fc_mock
sys.modules["Part"] = _part_mock

# Also mock cad_helpers functions used by cq.py
def _extract_solid(shape):
    if shape is None:
        raise ValueError("Null shape")
    if shape.isNull():
        raise ValueError("Null shape")
    if shape.ShapeType == "Solid":
        return shape
    solids = shape.Solids
    if len(solids) == 0:
        raise ValueError("No solid components")
    if len(solids) > 1:
        raise ValueError(f"Expected 1 solid, got {len(solids)}")
    return solids[0]


def _safe_fuse(a, b):
    result = a.fuse(b)
    return _extract_solid(result)


def _safe_cut(a, b):
    result = a.cut(b)
    return _extract_solid(result)


def _make_hollow_cylinder(outer_r, inner_r, height, bottom=0):
    if outer_r <= inner_r:
        raise ValueError("outer_r must be > inner_r")
    outer = _part_mock.makeCylinder(outer_r, height)
    inner_h = max(height - bottom, 0.1)
    inner = _part_mock.makeCylinder(inner_r, inner_h)
    if bottom > 0:
        inner.translate(_MockVector(0, 0, bottom))
    return _safe_cut(outer, inner)


_mock_cad_helpers = type(sys)("agent.cad_helpers")
_mock_cad_helpers.extract_solid = _extract_solid
_mock_cad_helpers.safe_fuse = _safe_fuse
_mock_cad_helpers.safe_cut = _safe_cut
_mock_cad_helpers.make_hollow_cylinder = _make_hollow_cylinder
_mock_cad_helpers.make_ring = lambda *a, **kw: _MockShape(shape_type="Solid", volume=100)
_mock_cad_helpers.make_box_handle = lambda *a, **kw: _MockShape(shape_type="Solid", volume=100)
_mock_cad_helpers.make_arc_handle = lambda *a, **kw: _MockShape(shape_type="Solid", volume=100)
_mock_cad_helpers.ensure_doc = lambda name=None: _fc_mock.ActiveDocument or _fc_mock.newDocument("Mock")
_mock_cad_helpers.cq_show = lambda *a, **kw: None
sys.modules["agent.cad_helpers"] = _mock_cad_helpers

# Now load cq.py
_spec = importlib.util.spec_from_file_location(
    "cq", os.path.join(os.path.dirname(__file__), "..", "agent", "cq.py"),
)
_cq_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cq_mod)

Workplane = _cq_mod.Workplane
_resolve_extrude = _cq_mod._resolve_extrude
_fc_vec = _cq_mod._fc_vec
Vector = _cq_mod.Vector


# ==========================================================================
# Tests
# ==========================================================================


# ---- Constructor ----

def test_workplane_constructor_defaults():
    wp = Workplane()
    assert wp._plane == "XY"
    assert wp._origin == (0, 0, 0)
    assert wp._shapes == []
    assert wp._pending == []


def test_workplane_constructor_custom_plane():
    wp = Workplane(plane="XZ")
    assert wp._plane == "XZ"
    wp2 = Workplane(plane="yz")
    assert wp2._plane == "YZ"


# ---- Primitives ----

def test_box_creates_shape():
    wp = Workplane("XY").box(10, 20, 30)
    assert len(wp._shapes) == 1
    shape = wp._shapes[0]
    assert shape.ShapeType == "Solid"


def test_box_rejects_negative():
    try:
        Workplane("XY").box(-1, 20, 30)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_cylinder_creates_shape():
    wp = Workplane("XY").cylinder(80, 40)
    assert len(wp._shapes) == 1
    assert wp._shapes[0].ShapeType == "Solid"


def test_cylinder_rejects_negative():
    try:
        Workplane("XY").cylinder(-80, 40)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_cone_creates_shape():
    wp = Workplane("XY").cone(50, 30, 80)
    assert len(wp._shapes) == 1


def test_sphere_creates_shape():
    wp = Workplane("XY").sphere(25)
    assert len(wp._shapes) == 1


def test_torus_creates_shape():
    wp = Workplane("XY").torus(20, 5)
    assert len(wp._shapes) == 1


# ---- 2D sketch accumulation ----

def test_circle_pending():
    wp = Workplane("XY").circle(40)
    assert len(wp._pending) == 1
    assert wp._pending[0] == ("circle", 40)
    # Not for construction
    wp2 = Workplane("XY").circle(40, forConstruction=True)
    assert len(wp2._pending) == 0


def test_two_circles_pending():
    wp = Workplane("XY").circle(40).circle(35)
    assert len(wp._pending) == 2
    assert wp._pending[0] == ("circle", 40)
    assert wp._pending[1] == ("circle", 35)


def test_rect_pending():
    wp = Workplane("XY").rect(10, 20)
    assert len(wp._pending) == 1
    assert wp._pending[0] == ("rect", 10, 20, True)


def test_polygon_pending():
    wp = Workplane("XY").polygon(6, 30)
    assert len(wp._pending) == 1
    assert wp._pending[0] == ("polygon", 6, 30, True)


# ---- Extrude ----

def test_extrude_single_circle():
    wp = Workplane("XY").circle(40).extrude(80)
    assert len(wp._pending) == 0  # consumed
    assert len(wp._shapes) == 1


def test_extrude_hollow_cylinder():
    wp = Workplane("XY").circle(40).circle(35).extrude(80)
    assert len(wp._shapes) == 1
    assert wp._shapes[0].ShapeType == "Solid"


def test_extrude_rect():
    wp = Workplane("XY").rect(10, 20).extrude(5)
    assert len(wp._shapes) == 1


def test_extrude_polygon():
    wp = Workplane("XY").polygon(6, 30).extrude(10)
    assert len(wp._shapes) == 1


def test_extrude_empty_pending_raises():
    try:
        Workplane("XY").extrude(10)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No pending" in str(e)


def test_extrude_negative_height_raises():
    try:
        Workplane("XY").circle(10).extrude(-5)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_extrude_hollow_reverses_radii():
    """Two circles with R1 < R2 should work (max becomes outer)."""
    wp = Workplane("XY").circle(35).circle(40).extrude(80)
    assert len(wp._shapes) == 1


# ---- Boolean operations ----

def test_cut_returns_new_wp():
    body = Workplane("XY").box(100, 100, 100)
    hole = Workplane("XY").cylinder(50, 20)
    result = body.cut(hole)
    assert result is not body
    assert len(result._shapes) == 1
    # Original unchanged
    assert len(body._shapes) == 1


def test_union_returns_new_wp():
    a = Workplane("XY").box(10, 10, 10)
    b = Workplane("XY").box(5, 5, 5)
    result = a.union(b)
    assert result is not a
    assert result is not b
    assert len(result._shapes) == 1


def test_intersect_returns_new_wp():
    a = Workplane("XY").box(10, 10, 10)
    b = Workplane("XY").box(5, 5, 5)
    result = a.intersect(b)
    assert result is not a
    assert len(result._shapes) == 1


# ---- Transforms ----

def test_translate_returns_new_wp():
    wp = Workplane("XY").box(10, 10, 10)
    moved = wp.translate((5, 0, 0))
    assert moved is not wp
    assert len(moved._shapes) == 1
    # Original still has its shape
    assert len(wp._shapes) == 1


def test_rotate_returns_new_wp():
    wp = Workplane("XY").cylinder(10, 5)
    rotated = wp.rotate((0, 0, 0), (0, 0, 1), 45)
    assert rotated is not wp
    assert len(rotated._shapes) == 1


def test_mirror_xy():
    wp = Workplane("XY").box(10, 10, 10)
    mirrored = wp.mirror("XY")
    assert mirrored is not wp


def test_mirror_invalid_plane_raises():
    wp = Workplane("XY").box(10, 10, 10)
    try:
        wp.mirror("AB")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown mirror plane" in str(e)


# ---- solid() / val() ----

def test_solid_returns_shape():
    wp = Workplane("XY").box(10, 10, 10)
    s = wp.solid()
    assert s is not None
    assert s.ShapeType == "Solid"


def test_solid_empty_raises():
    try:
        Workplane("XY").solid()
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "no shapes" in str(e)


def test_val_returns_shape():
    wp = Workplane("XY").box(10, 10, 10)
    assert wp.val() is not None


def test_val_empty_raises():
    try:
        Workplane("XY").val()
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---- workplane offset ----

def test_workplane_offset():
    wp = Workplane("XY")
    wp2 = wp.workplane(offset=10)
    assert wp2._origin == (0, 0, 10)


def test_workplane_offset_xz():
    wp = Workplane("XZ")
    wp2 = wp.workplane(offset=5)
    assert wp2._origin == (0, 5, 0)


def test_workplane_offset_zero():
    wp = Workplane("XY")
    wp2 = wp.workplane(offset=0)
    assert wp2._origin == (0, 0, 0)
    assert wp2._plane == "XY"


# ---- Chaining ----

def test_chain_multiple_operations():
    """Full chain: box → cut → translate → union."""
    body = Workplane("XY").box(100, 100, 10)
    hole = Workplane("XY").cylinder(5, 20)
    body = body.cut(hole)
    body = body.translate((0, 0, 5))
    cap = Workplane("XY").box(100, 100, 2)
    body = body.union(cap)
    assert len(body._shapes) == 1


# ---- Vector helper ----

def test_vector():
    v = Vector(1, 2, 3)
    assert v.x == 1
    assert v.y == 2
    assert v.z == 3


# ---- repr ----

def test_repr():
    wp = Workplane("XY").box(10, 10, 10)
    r = repr(wp)
    assert "Workplane" in r
    assert "XY" in r
    assert "shapes=1" in r


def test_repr_empty():
    wp = Workplane("XZ")
    r = repr(wp)
    assert "shapes=0" in r


# ---- _resolve_extrude directly ----

def test_resolve_extrude_hollow_both():
    shape = _resolve_extrude(
        [("circle", 40), ("circle", 35)], height=80, both=True
    )
    assert shape.ShapeType == "Solid"


def test_resolve_extrude_hollow_invalid_equal_radii():
    try:
        _resolve_extrude([("circle", 40), ("circle", 40)], height=80, both=False)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_resolve_extrude_negative_height():
    try:
        _resolve_extrude([("circle", 10)], height=-5, both=False)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Teardown: restore original sys.modules so other test files get clean state
# ---------------------------------------------------------------------------

def teardown_module():
    for key, orig in _ORIG_MODULES.items():
        if orig is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = orig
