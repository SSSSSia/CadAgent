"""CadQuery-style chain API — runtime translation layer over FreeCAD Part API.

Provides a lightweight `Workplane` class that wraps FreeCAD's Part module with
CadQuery-fluent chaining.  LLMs generate CQ-style code; each method body
calls the equivalent FreeCAD API, so code executes directly in the sandbox
without any AST transformation or external dependencies.

Usage in execute_code sandbox (pre-injected):
    import cq
    body = cq.Workplane("XY").circle(40).circle(35).extrude(90)
    handle = cq.Workplane("XY").torus(25, 6)
    body = body.union(handle)
    cq_show(body, "Mug")
"""
from __future__ import annotations

import copy
import math
import types as _types

import FreeCAD
import Part

from agent.cad_helpers import (
    extract_solid, safe_fuse, safe_cut, make_hollow_cylinder,
)

# ---------------------------------------------------------------------------
# Helper: create a tiny 'cq' module-like namespace for sandbox injection
# ---------------------------------------------------------------------------

_cq_module = _types.ModuleType("cq")


def _fc_vec(x: float, y: float, z: float) -> FreeCAD.Vector:
    """Shortcut: construct a FreeCAD.Vector."""
    return FreeCAD.Vector(x, y, z)


def _center_offset(dims: list[float], centered: tuple[bool, ...]) -> FreeCAD.Vector:
    """Calculate FreeCAD.Vector offset so that a shape appears centered.

    ``dims`` is the raw (L, W, H) from ``Part.makeBox`` or the equivalent
    dimensions that FreeCAD builds from the origin corner.

    ``centered`` is a bool tuple per axis.  ``True`` means the shape should
    appear centered on that axis, so we shift by *-dim/2*.
    """
    dx = -dims[0] / 2 if len(centered) > 0 and centered[0] else 0
    dy = -dims[1] / 2 if len(centered) > 1 and centered[1] else 0
    dz = -dims[2] / 2 if len(centered) > 2 and centered[2] else 0
    return _fc_vec(dx, dy, dz)


# ---------------------------------------------------------------------------
# Workplane class
# ---------------------------------------------------------------------------

class Workplane:
    """CadQuery-style workplane wrapping FreeCAD shapes.

    Internal state:
        _shapes  — list[FreeCAD TopoShape] (the actual geometry)
        _pending — list of 2-D sketch operations waiting for extrude()
        _plane   — reference plane name ("XY", "XZ", "YZ")
    """

    def __init__(
        self,
        plane: str = "XY",
        origin: tuple[float, float, float] = (0, 0, 0),
        shapes: list | None = None,
        pending: list | None = None,
    ):
        self._plane = plane.upper()
        self._origin = origin
        self._shapes: list = shapes if shapes is not None else []
        self._pending: list = pending if pending is not None else []

    # -- Clone helper -------------------------------------------------------

    def _copy(self, shapes: list | None = None) -> Workplane:
        """Return a new Workplane with the same plane/origin and new shapes."""
        return Workplane(
            plane=self._plane,
            origin=self._origin,
            shapes=shapes if shapes is not None else list(self._shapes),
            pending=list(self._pending),  # carry forward pending 2D ops
        )

    # -- Solid access -------------------------------------------------------

    def solid(self):
        """Return the single FreeCAD Solid (or the first shape).

        Raises ValueError if no shapes exist.
        """
        if not self._shapes:
            raise ValueError("Workplane contains no shapes. Build geometry first.")
        shape = self._shapes[-1]
        if hasattr(shape, "ShapeType") and shape.ShapeType == "Compound":
            return extract_solid(shape)
        return shape

    def val(self):
        """Return the underlying FreeCAD shape (may be Compound or Solid)."""
        if not self._shapes:
            raise ValueError("Workplane contains no shapes.")
        return self._shapes[-1]

    # -- 2D sketch operations (accumulate pending) --------------------------

    def circle(self, radius: float, forConstruction: bool = False) -> Workplane:
        """Add a circle to the pending sketch list."""
        if forConstruction:
            return self
        self._pending.append(("circle", radius))
        return self

    def rect(self, L: float, W: float, centered: bool = True) -> Workplane:
        """Add a rectangle to the pending sketch list."""
        self._pending.append(("rect", L, W, centered))
        return self

    def polygon(self, n: int, radius: float, centered: bool = True) -> Workplane:
        """Add a regular polygon to the pending sketch list."""
        self._pending.append(("polygon", n, radius, centered))
        return self

    # -- Unimplemented CadQuery sketch methods (clear error instead of AttributeError) --

    def moveTo(self, *args, **kwargs):
        raise NotImplementedError(
            "moveTo/lineTo/threePointArc sketch paths are not supported. "
            "Use circle(), rect(), polygon() + extrude() for 2D-to-3D, or "
            "combine primitive solids (box, cylinder, torus) with .union()/.cut()."
        )

    def lineTo(self, *args, **kwargs):
        raise NotImplementedError(
            "lineTo sketch paths are not supported. "
            "Use circle(), rect(), polygon() + extrude() for 2D-to-3D, or "
            "combine primitive solids (box, cylinder, torus) with .union()/.cut()."
        )

    def threePointArc(self, *args, **kwargs):
        raise NotImplementedError(
            "threePointArc sketch paths are not supported. "
            "Use torus() + .cut() for curved handles, or "
            "make_arc_handle(cup_radius, handle_r, arc_r, z_center)."
        )

    def close(self, *args, **kwargs):
        raise NotImplementedError(
            "close() sketch paths are not supported. "
            "Use circle(), rect(), polygon() + extrude() for closed profiles."
        )

    def newObject(self, *args, **kwargs):
        raise NotImplementedError(
            "newObject() is not available. Use .union()/.cut() to combine "
            "Workplane objects, or cq_show() to add results to the document."
        )

    # -- Extrude (consumes pending 2D ops) ----------------------------------

    def extrude(self, height: float, both: bool = False) -> Workplane:
        """Extrude the pending 2D sketch into a solid.

        Handles:
        - Single circle  → Part.makeCylinder (solid cylinder)
        - Two circles    → make_hollow_cylinder (concentric: first = outer)
        - Single rect    → Part.makeBox
        - Single polygon → revolved polygon (approximated)
        """
        if not self._pending:
            raise ValueError("No pending 2D operations to extrude. "
                             "Add circle(), rect(), or polygon() first.")

        pending = list(self._pending)
        self._pending = []  # consumed

        shape = _resolve_extrude(pending, height, both)
        return self._copy(shapes=[shape])

    # -- Primitive solids (direct 3D, no pending) ----------------------------

    def box(
        self,
        L: float,
        W: float,
        H: float,
        centered: tuple[bool, bool, bool] = (True, True, True),
    ) -> Workplane:
        """Create a box (parallelepiped)."""
        if L <= 0 or W <= 0 or H <= 0:
            raise ValueError(f"box dimensions must be positive: L={L}, W={W}, H={H}")
        shape = Part.makeBox(L, W, H)
        offset = _center_offset([L, W, H], centered)
        if offset.x != 0 or offset.y != 0 or offset.z != 0:
            shape.translate(offset)
        return self._copy(shapes=[shape])

    def cylinder(
        self,
        height: float,
        radius: float,
        centered: tuple[bool, bool, bool] = (True, True, False),
    ) -> Workplane:
        """Create a cylinder.

        **Note**: parameter order is (height, radius) following CadQuery
        convention — NOT (radius, height) like FreeCAD's Part.makeCylinder.
        """
        if height <= 0 or radius <= 0:
            raise ValueError(
                f"cylinder dimensions must be positive: height={height}, radius={radius}"
            )
        # FC API: Part.makeCylinder(radius, height)
        shape = Part.makeCylinder(radius, height)
        # FC builds from Z=0 upward; CadQuery centers by default on XY, not Z
        offset = _center_offset([2 * radius, 2 * radius, height], centered)
        if offset.x != 0 or offset.y != 0 or offset.z != 0:
            shape.translate(offset)
        return self._copy(shapes=[shape])

    def cone(
        self,
        r1: float,
        r2: float,
        height: float,
        centered: tuple[bool, bool, bool] = (True, True, False),
    ) -> Workplane:
        """Create a cone (frustum). r1=base radius, r2=top radius."""
        if height <= 0 or r1 < 0 or r2 < 0:
            raise ValueError(
                f"cone dimensions invalid: r1={r1}, r2={r2}, height={height}"
            )
        shape = Part.makeCone(r1, r2, height)
        offset = _center_offset([2 * max(r1, r2), 2 * max(r1, r2), height], centered)
        if offset.x != 0 or offset.y != 0 or offset.z != 0:
            shape.translate(offset)
        return self._copy(shapes=[shape])

    def sphere(self, radius: float) -> Workplane:
        """Create a sphere centered at the workplane origin."""
        if radius <= 0:
            raise ValueError(f"sphere radius must be positive: {radius}")
        shape = Part.makeSphere(radius)
        return self._copy(shapes=[shape])

    def torus(self, major_r: float, minor_r: float) -> Workplane:
        """Create a torus (ring shape). major_r=ring radius, minor_r=tube radius."""
        if major_r <= 0 or minor_r <= 0:
            raise ValueError(
                f"torus radii must be positive: major_r={major_r}, minor_r={minor_r}"
            )
        shape = Part.makeTorus(major_r, minor_r)
        return self._copy(shapes=[shape])

    # -- Boolean operations (chainable, return new Workplane) ----------------

    def cut(self, other) -> Workplane:
        """Subtract *other* (Workplane or FreeCAD shape) from this workplane."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = safe_cut(my_solid, other_solid)
        return self._copy(shapes=[result])

    def union(self, other) -> Workplane:
        """Merge *other* (Workplane or FreeCAD shape) with this workplane."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = safe_fuse(my_solid, other_solid)
        return self._copy(shapes=[result])

    def intersect(self, other) -> Workplane:
        """Boolean intersection of this workplane with *other*."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = my_solid.common(other_solid)
        return self._copy(shapes=[result])

    # -- Transformations (return new Workplane, original unchanged) ----------

    def translate(self, vec: tuple[float, float, float]) -> Workplane:
        """Translate by *vec* — returns a NEW workplane (does NOT modify in-place).

        This is different from FreeCAD's native translate() which modifies
        in-place and returns None.  The CQ-style always returns a new object.
        """
        new_shape = self.solid().copy()
        new_shape.translate(_fc_vec(vec[0], vec[1], vec[2]))
        return self._copy(shapes=[new_shape])

    def rotate(
        self,
        center: tuple[float, float, float],
        axis: tuple[float, float, float],
        angle_degrees: float,
    ) -> Workplane:
        """Rotate around *axis* through *center* by *angle_degrees*.

        Returns a new Workplane.
        """
        new_shape = self.solid().copy()
        new_shape.rotate(
            _fc_vec(*center),
            _fc_vec(*axis),
            angle_degrees,
        )
        return self._copy(shapes=[new_shape])

    def mirror(
        self,
        mirror_plane: str | tuple,
    ) -> Workplane:
        """Mirror the shape across a plane.

        *mirror_plane* can be:
        - "XY", "XZ", "YZ" — mirror across that coordinate plane
        - (base, normal) — a tuple of two (x,y,z) tuples
        """
        if isinstance(mirror_plane, str):
            mirror_plane = mirror_plane.upper()
            normals = {
                "XY": _fc_vec(0, 0, 1),
                "XZ": _fc_vec(0, 1, 0),
                "YZ": _fc_vec(1, 0, 0),
            }
            normal = normals.get(mirror_plane)
            if normal is None:
                raise ValueError(
                    f"Unknown mirror plane '{mirror_plane}'. Use 'XY', 'XZ', or 'YZ'."
                )
            base = _fc_vec(0, 0, 0)
        else:
            base = _fc_vec(*mirror_plane[0])
            normal = _fc_vec(*mirror_plane[1])

        new_shape = self.solid().copy()
        new_shape.mirror(base, normal)
        return self._copy(shapes=[new_shape])

    # -- Workplane offset ---------------------------------------------------

    def workplane(self, offset: float = 0) -> Workplane:
        """Create a new workplane offset from the current one.

        Carries forward the existing shapes so chain can continue.
        """
        if offset == 0:
            return self._copy()
        # Adjust Z origin based on plane orientation
        ox, oy, oz = self._origin
        if self._plane == "XY":
            oz += offset
        elif self._plane == "XZ":
            oy += offset
        elif self._plane == "YZ":
            ox += offset
        return Workplane(
            plane=self._plane,
            origin=(ox, oy, oz),
            shapes=list(self._shapes),
            pending=list(self._pending),
        )

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        n_shapes = len(self._shapes)
        n_pending = len(self._pending)
        return (f"<Workplane plane={self._plane!r} "
                f"shapes={n_shapes} pending={n_pending}>")


# ---------------------------------------------------------------------------
# Internal: resolve pending 2D operations into a FreeCAD solid
# ---------------------------------------------------------------------------

def _resolve_extrude(
    pending: list[tuple], height: float, both: bool
):
    """Convert accumulated pending 2D operations to a FreeCAD shape via extrude.

    Supported patterns:
    - [('circle', R)]              → solid cylinder
    - [('circle', R1), ('circle', R2)] → hollow cylinder (R1 > R2 = outer)
    - [('rect', L, W, centered)]   → box
    - [('polygon', n, R, centered)] → regular polygon extrusion
    """
    if height <= 0:
        raise ValueError(f"extrude height must be positive: {height}")

    # --- Hollow cylinder: two concentric circles ---
    if len(pending) == 2:
        op1, op2 = pending[0], pending[1]
        if (op1[0] == "circle" and op2[0] == "circle"):
            r1 = max(op1[1], op2[1])  # outer
            r2 = min(op1[1], op2[1])  # inner
            if r1 <= r2:
                raise ValueError(
                    f"Hollow cylinder requires R1 > R2, got R1={r1}, R2={r2}"
                )
            bottom = 0 if both else 0  # both → hollow cylinder (open both ends)
            if both:
                # Open at both ends: use two cylinders + cut
                outer = Part.makeCylinder(r1, height)
                inner = Part.makeCylinder(r2, height + 0.01)
                # Offset inner slightly to ensure clean boolean
                inner.translate(_fc_vec(0, 0, -0.005))
                shape = safe_cut(outer, inner)
            else:
                # Closed bottom
                shape = make_hollow_cylinder(r1, r2, height, bottom=0)
            # Center on XY
            shape.translate(_fc_vec(0, 0, -height / 2))
            return shape

    # --- Single circle → solid cylinder ---
    if len(pending) == 1:
        op = pending[0]
        if op[0] == "circle":
            R = op[1]
            if R <= 0:
                raise ValueError(f"Circle radius must be positive: {R}")
            shape = Part.makeCylinder(R, height)
            shape.translate(_fc_vec(0, 0, -height / 2))  # center on XY
            return shape

        if op[0] == "rect":
            _, L, W, centered = op
            if L <= 0 or W <= 0:
                raise ValueError(f"rect dimensions must be positive: L={L}, W={W}")
            shape = Part.makeBox(L, W, height)
            if centered:
                shape.translate(_fc_vec(-L / 2, -W / 2, -height / 2))
            else:
                shape.translate(_fc_vec(0, 0, -height / 2))
            return shape

        if op[0] == "polygon":
            _, n, R, centered = op
            if n < 3 or R <= 0:
                raise ValueError(f"polygon needs n>=3 and R>0, got n={n}, R={R}")
            # Build polygon wire from vertices
            edges = []
            for i in range(n):
                a = 2 * math.pi * i / n
                x = R * math.cos(a)
                y = R * math.sin(a)
                a2 = 2 * math.pi * ((i + 1) % n) / n
                x2 = R * math.cos(a2)
                y2 = R * math.sin(a2)
                edge = Part.makeLine(
                    _fc_vec(x, y, 0), _fc_vec(x2, y2, 0)
                )
                edges.append(edge)
            wire = Part.Wire(edges)
            face = Part.Face(wire)
            shape = face.extrude(_fc_vec(0, 0, height))
            if centered:
                shape.translate(_fc_vec(0, 0, -height / 2))
            return shape

    # --- Multiple rects / mixed — fallback: fuse individual extrusions ---
    shapes = []
    for op in pending:
        if op[0] == "circle":
            R = op[1]
            s = Part.makeCylinder(R, height)
            s.translate(_fc_vec(0, 0, -height / 2))
        elif op[0] == "rect":
            _, L, W, centered = op
            s = Part.makeBox(L, W, height)
            if centered:
                s.translate(_fc_vec(-L / 2, -W / 2, -height / 2))
            else:
                s.translate(_fc_vec(0, 0, -height / 2))
        else:
            raise ValueError(
                f"Unsupported pending operation in multi-op extrude: {op[0]}"
            )
        shapes.append(s)

    # Fuse all shapes together
    result = shapes[0]
    for s in shapes[1:]:
        result = safe_fuse(result, s)
    return result


# ---------------------------------------------------------------------------
# Module-level convenience for sandbox injection
# ---------------------------------------------------------------------------

Vector = _fc_vec  # cq.Vector(x, y, z) → FreeCAD.Vector


# Populate the cq module namespace for sandbox injection
_cq_module.Workplane = Workplane
_cq_module.Vector = Vector

# Export for tools.py injection
__all__ = ["Workplane", "Vector", "_cq_module"]
