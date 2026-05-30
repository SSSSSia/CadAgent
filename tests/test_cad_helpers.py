"""Tests for agent/cad_helpers.py — CAD helper functions.

Uses mock FreeCAD/Part objects since cad_helpers.py imports them at module level.
Tests the pure logic of each helper function.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Mock FreeCAD and Part before importing cad_helpers
# ---------------------------------------------------------------------------


class _MockShape:
    """Mock FreeCAD shape with configurable behavior."""

    def __init__(self, shape_type="Solid", solids=None, is_null=False, volume=100.0):
        self.ShapeType = shape_type
        self._solids = solids if solids is not None else []
        self._is_null = is_null
        self.Volume = volume
        self._translated = None

    def isNull(self):
        return self._is_null

    @property
    def Solids(self):
        return self._solids

    def fuse(self, other):
        return _MockShape("Compound", solids=[self, other])

    def cut(self, other):
        return _MockShape("Solid", solids=[], volume=self.Volume - other.Volume)

    def translate(self, vector):
        self._translated = (vector.x, vector.y, vector.z)

    def rotate(self, center, axis, angle):
        self._rotated = (center, axis, angle)


class _MockVector:
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z


class _MockDocument:
    def __init__(self, name="TestDoc"):
        self.Name = name


def _setup_mocks():
    """Set up mock FreeCAD and Part modules in sys.modules."""
    mock_freecad = MagicMock()
    mock_freecad.Vector = _MockVector
    mock_freecad.ActiveDocument = _MockDocument("Active")
    mock_freecad.getDocument = lambda n: _MockDocument(n) if n == "exists" else None
    mock_freecad.newDocument = lambda n: _MockDocument(n)

    mock_part = MagicMock()

    def make_cylinder(r, h):
        return _MockShape("Solid", volume=3.14159 * r * r * h)

    def make_box(x, y, z, origin=None):
        return _MockShape("Solid", volume=x * y * z)

    def make_torus(r1, r2):
        return _MockShape("Solid", volume=2 * 3.14159 * r1 * 3.14159 * r2 * r2)

    mock_part.makeCylinder = make_cylinder
    mock_part.makeBox = make_box
    mock_part.makeTorus = make_torus

    sys.modules["FreeCAD"] = mock_freecad
    sys.modules["Part"] = mock_part
    return mock_freecad, mock_part


def _load_cad_helpers():
    """Load cad_helpers module with mocked FreeCAD/Part.

    Restores original sys.modules after loading so other tests aren't affected.
    """
    # Save original modules (may not exist outside FreeCAD)
    saved = {}
    for key in ("FreeCAD", "Part"):
        saved[key] = sys.modules.get(key)

    _setup_mocks()

    file_path = os.path.join(
        os.path.dirname(__file__), "..", "agent", "cad_helpers.py"
    )
    file_path = os.path.normpath(file_path)

    spec = importlib.util.spec_from_file_location("cad_helpers", file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Restore original sys.modules so other tests aren't polluted
    for key, orig in saved.items():
        if orig is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = orig

    return mod


# Load module once for all tests
_mod = _load_cad_helpers()
extract_solid = _mod.extract_solid
safe_fuse = _mod.safe_fuse
safe_cut = _mod.safe_cut
make_hollow_cylinder = _mod.make_hollow_cylinder
make_ring = _mod.make_ring
make_box_handle = _mod.make_box_handle
make_arc_handle = _mod.make_arc_handle
ensure_doc = _mod.ensure_doc


# ===========================================================================
# extract_solid tests
# ===========================================================================


class TestExtractSolid:

    def test_none_raises(self):
        with pytest.raises(ValueError, match="shape is None"):
            extract_solid(None)

    def test_null_shape_raises(self):
        shape = _MockShape(is_null=True)
        with pytest.raises(ValueError, match="isNull"):
            extract_solid(shape)

    def test_solid_type_returns_directly(self):
        shape = _MockShape(shape_type="Solid")
        result = extract_solid(shape)
        assert result is shape

    def test_compound_one_solid_extracts(self):
        inner = _MockShape(shape_type="Solid")
        shape = _MockShape(shape_type="Compound", solids=[inner])
        assert extract_solid(shape) is inner

    def test_no_solids_raises(self):
        shape = _MockShape(shape_type="Shell", solids=[])
        with pytest.raises(ValueError, match="No solid components"):
            extract_solid(shape)

    def test_multi_solids_raises(self):
        shape = _MockShape(
            shape_type="Compound",
            solids=[_MockShape(), _MockShape()],
        )
        with pytest.raises(ValueError, match="Expected 1 solid, got 2"):
            extract_solid(shape)


# ===========================================================================
# safe_fuse / safe_cut tests
# ===========================================================================


class TestSafeFuse:

    def test_fuse_two_solids_success(self):
        a = MagicMock()
        b = MagicMock()
        a.fuse.return_value = _MockShape(shape_type="Solid")
        result = safe_fuse(a, b)
        assert isinstance(result, _MockShape)

    def test_fuse_non_overlapping_raises(self):
        a = _MockShape(shape_type="Solid")
        b = _MockShape(shape_type="Solid")
        # Mock fuse returns Compound with 2 solids (non-overlapping)
        with pytest.raises(ValueError, match="Expected 1 solid, got 2"):
            safe_fuse(a, b)


class TestSafeCut:

    def test_cut_calls_cut_method(self):
        a = MagicMock()
        b = MagicMock()
        a.cut.return_value = _MockShape(shape_type="Solid")
        safe_cut(a, b)
        a.cut.assert_called_once_with(b)


# ===========================================================================
# make_hollow_cylinder tests
# ===========================================================================


class TestMakeHollowCylinder:

    def test_basic_creates_shape(self):
        result = make_hollow_cylinder(40, 35, 90)
        assert isinstance(result, _MockShape)

    def test_with_bottom(self):
        result = make_hollow_cylinder(40, 35, 90, bottom=5)
        assert isinstance(result, _MockShape)

    def test_outer_not_greater_than_inner_raises(self):
        with pytest.raises(ValueError, match="outer_r.*must be greater"):
            make_hollow_cylinder(30, 40, 90)

    def test_equal_radii_raises(self):
        with pytest.raises(ValueError, match="outer_r.*must be greater"):
            make_hollow_cylinder(35, 35, 90)

    def test_negative_height_raises(self):
        with pytest.raises(ValueError, match="height.*must be positive"):
            make_hollow_cylinder(40, 35, -10)

    def test_zero_height_raises(self):
        with pytest.raises(ValueError, match="height.*must be positive"):
            make_hollow_cylinder(40, 35, 0)

    def test_negative_bottom_raises(self):
        with pytest.raises(ValueError, match="bottom.*must be non-negative"):
            make_hollow_cylinder(40, 35, 90, bottom=-1)


# ===========================================================================
# make_ring tests
# ===========================================================================


class TestMakeRing:

    def test_basic_creates_shape(self):
        result = make_ring(50, 40, 5)
        assert isinstance(result, _MockShape)

    def test_invalid_radii_raises(self):
        with pytest.raises(ValueError, match="outer_r.*must be greater"):
            make_ring(30, 40, 5)

    def test_negative_height_raises(self):
        with pytest.raises(ValueError, match="height.*must be positive"):
            make_ring(50, 40, -1)


# ===========================================================================
# make_box_handle tests
# ===========================================================================


class TestMakeBoxHandle:

    def test_basic_creates_shape(self):
        result = make_box_handle(40, 12, 45, 55, 22)
        assert isinstance(result, _MockShape)

    def test_positioning(self):
        """Verify handle is positioned with 2mm overlap into cup wall."""
        cup_radius = 40
        width = 12
        depth = 45
        height = 55
        z = 22

        result = make_box_handle(cup_radius, width, depth, height, z)
        # The mock shape should have been translated
        assert result._translated == (cup_radius - 2.0, -width / 2, z)

    def test_negative_width_raises(self):
        with pytest.raises(ValueError, match="width.*must be positive"):
            make_box_handle(40, -1, 45, 55, 22)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth.*must be positive"):
            make_box_handle(40, 12, -1, 55, 22)

    def test_negative_height_raises(self):
        with pytest.raises(ValueError, match="height.*must be positive"):
            make_box_handle(40, 12, 45, -1, 22)


# ===========================================================================
# make_arc_handle tests
# ===========================================================================


class TestMakeArcHandle:

    def test_basic_creates_shape(self):
        result = make_arc_handle(40, 6, 25, 50)
        assert isinstance(result, _MockShape)

    def test_positioning(self):
        """Verify handle is translated with 2mm overlap into cup wall."""
        result = make_arc_handle(40, 6, 25, 50)
        assert result._translated == (38.0, 0, 50)

    def test_rotations_applied(self):
        """Verify two rotations are applied to orient the arc in XZ plane."""
        result = make_arc_handle(40, 6, 25, 50)
        assert hasattr(result, "_rotated")

    def test_negative_handle_r_raises(self):
        with pytest.raises(ValueError, match="handle_r.*must be positive"):
            make_arc_handle(40, -1, 25, 50)

    def test_zero_handle_r_raises(self):
        with pytest.raises(ValueError, match="handle_r.*must be positive"):
            make_arc_handle(40, 0, 25, 50)

    def test_arc_r_not_greater_than_handle_r_raises(self):
        with pytest.raises(ValueError, match="arc_r.*must be greater"):
            make_arc_handle(40, 10, 5, 50)

    def test_arc_r_equals_handle_r_raises(self):
        with pytest.raises(ValueError, match="arc_r.*must be greater"):
            make_arc_handle(40, 10, 10, 50)


# ===========================================================================
# Overlap regression tests — catch the "handle doesn't overlap cup" bug class
# ===========================================================================


class TestHandleOverlap:
    """Verify both handle functions penetrate the cup wall for safe_fuse.

    These are regression tests: if someone changes the overlap formula,
    these tests will catch it before it reaches production.
    """

    def test_box_handle_penetrates_cup_wall(self):
        cup_r = 40
        result = make_box_handle(cup_r, 12, 45, 55, 22)
        handle_x = result._translated[0]
        assert handle_x < cup_r, (
            f"Box handle at x={handle_x} doesn't penetrate cup wall at x={cup_r}"
        )
        assert cup_r - handle_x >= 1.5, (
            f"Overlap only {cup_r - handle_x}mm, need at least 1.5mm"
        )

    def test_arc_handle_penetrates_cup_wall(self):
        cup_r = 40
        result = make_arc_handle(cup_r, 6, 25, 50)
        handle_x = result._translated[0]
        assert handle_x < cup_r, (
            f"Arc handle at x={handle_x} doesn't penetrate cup wall at x={cup_r}"
        )
        assert cup_r - handle_x >= 1.5, (
            f"Overlap only {cup_r - handle_x}mm, need at least 1.5mm"
        )

    def test_both_handles_use_same_overlap(self):
        """make_arc_handle and make_box_handle must use consistent overlap."""
        cup_r = 40
        box = make_box_handle(cup_r, 12, 45, 55, 22)
        arc = make_arc_handle(cup_r, 6, 25, 50)
        assert box._translated[0] == arc._translated[0], (
            f"Inconsistent overlap: box_x={box._translated[0]}, arc_x={arc._translated[0]}"
        )

    @pytest.mark.parametrize("cup_r", [10, 25, 40, 80, 150])
    def test_arc_handle_overlap_scales_with_cup_radius(self, cup_r):
        """Overlap must work for any cup radius."""
        result = make_arc_handle(cup_r, 6, 25, 50)
        handle_x = result._translated[0]
        assert handle_x < cup_r


# ===========================================================================
# ensure_doc tests
# ===========================================================================


class TestEnsureDoc:

    @pytest.fixture(autouse=True)
    def _patch_module_freecad(self):
        """Patch the FreeCAD reference inside the loaded cad_helpers module."""
        mock_fc, _ = _setup_mocks()
        # Point the loaded module's FreeCAD to our mock
        original_fc = _mod.FreeCAD
        _mod.FreeCAD = mock_fc
        yield
        _mod.FreeCAD = original_fc
        sys.modules.pop("FreeCAD", None)
        sys.modules.pop("Part", None)

    def test_name_exists_returns_existing(self):
        doc = ensure_doc("exists")
        assert doc.Name == "exists"

    def test_name_not_exists_creates_new(self):
        doc = ensure_doc("NewDoc")
        assert doc.Name == "NewDoc"

    def test_none_with_active_doc_returns_active(self):
        doc = ensure_doc(None)
        assert doc.Name == "Active"

    def test_none_without_active_creates_default(self):
        _mod.FreeCAD.ActiveDocument = None
        doc = ensure_doc(None)
        assert doc.Name == "CadAgentModel"


# ===========================================================================
# _BUILTIN_NAMES coverage test (cross-module check)
# ===========================================================================


class TestBuiltinNamesCoverage:
    """Ensure agent/tools.py _BUILTIN_NAMES covers all injected helper names."""

    def test_builtin_names_includes_helpers(self):
        """Verify _BUILTIN_NAMES in tools.py includes all helper function names.

        Can't import tools.py directly (requires FreeCAD), so read the source.
        """
        tools_path = os.path.join(
            os.path.dirname(__file__), "..", "agent", "tools.py"
        )
        with open(tools_path, encoding="utf-8") as f:
            source = f.read()
        expected = {
            "extract_solid", "safe_fuse", "safe_cut",
            "make_hollow_cylinder", "make_ring", "make_box_handle",
            "make_arc_handle", "ensure_doc",
        }
        for name in expected:
            assert f'"{name}"' in source, (
                f"'{name}' not found in agent/tools.py — "
                "LLM could overwrite this helper in subsequent execute_code calls"
            )
