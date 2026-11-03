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


# CadQuery named planes. Local +X/+Y lie in the plane; local +Z is the
# extrude normal. The rotate entry must match _rotate_vec (right-handed).
#   XY: (x, y, z) -> (x, y, z)     normal +Z
#   XZ: (x, y, z) -> (x, -z, y)    normal -Y
#   YZ: (x, y, z) -> (z, x, y)     normal +X
_PLANE_NORMAL = {
    "XY": (0.0, 0.0, 1.0),
    "XZ": (0.0, -1.0, 0.0),
    "YZ": (1.0, 0.0, 0.0),
}
_PLANE_ROTATE = {
    "XY": None,
    "XZ": ((1.0, 0.0, 0.0), 90.0),
    "YZ": ((1.0, 1.0, 1.0), 120.0),
}


def _rotate_vec(x: float, y: float, z: float, plane: str) -> tuple[float, float, float]:
    """Map a local-frame vector into global axes. No origin shift."""
    if plane == "XY":
        return (x, y, z)
    if plane == "XZ":
        return (x, -z, y)
    if plane == "YZ":
        return (z, x, y)
    raise ValueError(f"Unknown workplane '{plane}'")


def _to_local(
    x: float, y: float, z: float, plane: str, origin: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Inverse of rotate-then-translate by *origin*."""
    x -= origin[0]
    y -= origin[1]
    z -= origin[2]
    if plane == "XY":
        return (x, y, z)
    if plane == "XZ":
        return (x, z, -y)
    if plane == "YZ":
        return (y, z, x)
    raise ValueError(f"Unknown workplane '{plane}'")


def _orient_shape(shape, plane: str, origin: tuple[float, float, float]):
    """Rotate a local-XY shape onto *plane*, then translate to *origin*."""
    spec = _PLANE_ROTATE[plane]
    if spec is not None:
        axis, angle = spec
        shape.rotate(_fc_vec(0, 0, 0), _fc_vec(*axis), angle)
    ox, oy, oz = origin
    if ox or oy or oz:
        shape.translate(_fc_vec(ox, oy, oz))
    return shape


class _AxisBox:
    """BoundBox stand-in so shell cutters can run in local coordinates."""

    def __init__(self, xmin, ymin, zmin, xmax, ymax, zmax):
        self.XMin = xmin
        self.YMin = ymin
        self.ZMin = zmin
        self.XMax = xmax
        self.YMax = ymax
        self.ZMax = zmax


def _local_bbox(shape, plane: str, origin: tuple[float, float, float]) -> _AxisBox:
    """Axis-aligned box of *shape* expressed in the workplane's local frame."""
    bb = shape.BoundBox
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for x in (bb.XMin, bb.XMax):
        for y in (bb.YMin, bb.YMax):
            for z in (bb.ZMin, bb.ZMax):
                lx, ly, lz = _to_local(x, y, z, plane, origin)
                xs.append(lx)
                ys.append(ly)
                zs.append(lz)
    return _AxisBox(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


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
        _plane   — "XY", "XZ", or "YZ" (CadQuery named planes)
        _origin  — global workplane origin; base geometry is created there
    """

    def __init__(
        self,
        plane: str = "XY",
        origin: tuple[float, float, float] = (0, 0, 0),
        shapes: list | None = None,
        pending: list | None = None,
        locations: list | None = None,
        profile: list | None = None,
        primitive: str | None = None,
    ):
        if not isinstance(plane, str):
            raise NotImplementedError(
                f"Workplane plane {plane!r} is not supported. "
                "Use 'XY', 'XZ', or 'YZ'."
            )
        name = plane.upper()
        if name not in _PLANE_NORMAL:
            raise NotImplementedError(
                f"Workplane plane '{plane}' is not supported. "
                "Use 'XY', 'XZ', or 'YZ'."
            )
        self._plane = name
        self._origin = tuple(origin) if origin else (0, 0, 0)
        self._shapes: list = shapes if shapes is not None else []
        self._pending: list = pending if pending is not None else []
        # (x, y, rotation_degrees) pending points from polarArray/rarray
        self._locations: list = list(locations) if locations is not None else []
        # line-profile ops for revolve(): move/line/arc/close
        self._profile: list = list(profile) if profile is not None else []
        # "box" / "cylinder" while the solid is still that plain primitive
        self._primitive: str | None = primitive
        self._edge_note: str = ""

    def _copy(self, shapes: list | None = None, keep_primitive: bool = True) -> Workplane:
        """Return a new Workplane with the same plane/origin and new shapes."""
        return Workplane(
            plane=self._plane,
            origin=self._origin,
            shapes=shapes if shapes is not None else list(self._shapes),
            pending=list(self._pending),
            locations=list(self._locations),
            profile=list(self._profile),
            primitive=self._primitive if keep_primitive else None,
        )

    def _place(self, shape):
        """Place a freshly built base shape at the workplane origin.

        Only called where NEW base geometry is created (primitives and
        extrude). Boolean/transform results already carry absolute
        coordinates and must not be shifted again.
        """
        return _orient_shape(shape, self._plane, self._origin)

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
        """Add a circle at each pending location (or the origin)."""
        cloned = self._copy()
        if forConstruction:
            return cloned
        if radius <= 0:
            raise ValueError(f"Circle radius must be positive: {radius}")
        cloned._stamp(("circle", radius))
        return cloned

    def rect(self, L: float, W: float, centered: bool = True) -> Workplane:
        """Add a rectangle at each pending location (or the origin)."""
        cloned = self._copy()
        if L <= 0 or W <= 0:
            raise ValueError(f"rect dimensions must be positive: L={L}, W={W}")
        cloned._stamp(("rect", L, W, centered))
        return cloned

    def polygon(self, n: int, radius: float, centered: bool = True) -> Workplane:
        """Add a regular polygon at each pending location (or the origin)."""
        cloned = self._copy()
        if n < 3 or radius <= 0:
            raise ValueError(f"polygon needs n>=3 and R>0, got n={n}, R={radius}")
        cloned._stamp(("polygon", n, radius, centered))
        return cloned

    def _stamp(self, op: tuple) -> None:
        """Append *op* once per location. Origin-only ops stay  unpositioned."""
        locs = self._locations or [(0.0, 0.0, 0.0)]
        for x, y, rot in locs:
            if x or y or rot:
                self._pending.append(op + (x, y, rot))
            else:
                self._pending.append(op)
        self._locations = []

    def polarArray(
        self,
        radius: float,
        startAngle: float,
        angle: float,
        count: int,
        fill: bool = True,
        rotate: bool = True,
    ) -> Workplane:
        """Record CadQuery-style polar locations for the next sketch or hole.

        *angle* is degrees. With fill=True a full 360 is split into *count*
        steps (the endpoint is not duplicated); a partial span includes both
        ends. fill=False steps by *angle* each time. rotate=True stores the
        local rotation so non-round profiles follow the radius.
        """
        if count <= 0:
            raise ValueError(f"polarArray count must be positive, got {count}")
        if radius < 0:
            raise ValueError(f"polarArray radius must be >= 0, got {radius}")
        cloned = self._copy()
        span = math.radians(angle)
        start = math.radians(startAngle)
        if fill:
            if abs(abs(span) - 2 * math.pi) < 1e-9:
                step = span / count
            else:
                step = span / (count - 1) if count > 1 else 0.0
        else:
            step = span
        locs = []
        for i in range(count):
            a = start + step * i
            rot = math.degrees(a) if rotate else 0.0
            locs.append((radius * math.cos(a), radius * math.sin(a), rot))
        cloned._locations = locs
        return cloned

    def rarray(
        self,
        xSpacing: float,
        ySpacing: float,
        xCount: int,
        yCount: int,
        center: bool = True,
    ) -> Workplane:
        """Record a rectangular grid of locations (CadQuery rarray)."""
        if xCount < 1 or yCount < 1:
            raise ValueError(
                f"rarray counts must be >= 1, got xCount={xCount}, yCount={yCount}"
            )
        cloned = self._copy()
        pts = []
        for i in range(xCount):
            for j in range(yCount):
                pts.append((i * xSpacing, j * ySpacing, 0.0))
        if center:
            ox = (xCount - 1) * xSpacing / 2.0
            oy = (yCount - 1) * ySpacing / 2.0
            pts = [(x - ox, y - oy, rot) for x, y, rot in pts]
        cloned._locations = pts
        return cloned

    def moveTo(self, x: float, y: float) -> Workplane:
        """Start a revolve profile at (x, y) on the XY plane."""
        cloned = self._copy()
        cloned._profile.append(("move", float(x), float(y)))
        return cloned

    def lineTo(self, x: float, y: float) -> Workplane:
        """Add a straight segment of the revolve profile."""
        if not self._profile:
            raise ValueError("lineTo() needs moveTo() first.")
        cloned = self._copy()
        cloned._profile.append(("line", float(x), float(y)))
        return cloned

    def threePointArc(self, point1, point2) -> Workplane:
        """Arc from the current point through point1 to point2."""
        if not self._profile:
            raise ValueError("threePointArc() needs moveTo() first.")
        cloned = self._copy()
        x1, y1 = point1
        x2, y2 = point2
        cloned._profile.append(("arc", float(x1), float(y1), float(x2), float(y2)))
        return cloned

    def close(self) -> Workplane:
        """Close the revolve profile back to the last moveTo."""
        if not self._profile:
            raise ValueError("close() needs a profile. Call moveTo() first.")
        cloned = self._copy()
        cloned._profile.append(("close",))
        return cloned

    def newObject(self, *args, **kwargs):
        raise NotImplementedError(
            "newObject() is not available. Use .union()/.cut() to combine "
            "Workplane objects, or cq_show() to add results to the document."
        )

    # -- Extrude (consumes pending 2D ops) ----------------------------------

    def extrude(self, height: float, both: bool = False) -> Workplane:
        """Extrude the pending 2D sketch into a solid.

        CadQuery semantics (S5-A4):
        - extrude(H) rises from the workplane along +Z: z = 0 → +H
        - extrude(H, both=True) extrudes the full height in BOTH
          directions: z = -H → +H (total height 2H)

        Handles:
        - Single circle  → Part.makeCylinder (solid cylinder)
        - Two circles    → hollow cylinder (concentric: larger = outer)
        - Single rect    → Part.makeBox
        - Single polygon → extruded regular polygon
        """
        if self._profile:
            raise ValueError(
                "A line profile is pending. Use revolve(), not extrude()."
            )
        if not self._pending:
            raise ValueError("No pending 2D operations to extrude. "
                             "Add circle(), rect(), or polygon() first.")

        pending = list(self._pending)
        self._pending = []  # consumed

        shape = _resolve_extrude(pending, height, both)
        result = self._copy(shapes=[self._place(shape)], keep_primitive=False)
        result._pending = []
        result._primitive = _extrude_primitive(pending)
        return result

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
        result = self._copy(shapes=[self._place(shape)])
        result._primitive = "box"
        return result

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
        result = self._copy(shapes=[self._place(shape)])
        result._primitive = "cylinder"
        return result

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
        return self._copy(shapes=[self._place(shape)])

    def sphere(self, radius: float) -> Workplane:
        """Create a sphere centered at the workplane origin."""
        if radius <= 0:
            raise ValueError(f"sphere radius must be positive: {radius}")
        shape = Part.makeSphere(radius)
        return self._copy(shapes=[self._place(shape)])

    def torus(self, major_r: float, minor_r: float) -> Workplane:
        """Create a torus (ring shape). major_r=ring radius, minor_r=tube radius."""
        if major_r <= 0 or minor_r <= 0:
            raise ValueError(
                f"torus radii must be positive: major_r={major_r}, minor_r={minor_r}"
            )
        shape = Part.makeTorus(major_r, minor_r)
        return self._copy(shapes=[self._place(shape)])

    # -- Boolean operations (chainable, return new Workplane) ----------------

    def cut(self, other) -> Workplane:
        """Subtract *other* (Workplane or FreeCAD shape) from this workplane."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = safe_cut(my_solid, other_solid)
        return self._copy(shapes=[result], keep_primitive=False)

    def union(self, other) -> Workplane:
        """Merge *other* (Workplane or FreeCAD shape) with this workplane."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = safe_fuse(my_solid, other_solid)
        return self._copy(shapes=[result], keep_primitive=False)

    def intersect(self, other) -> Workplane:
        """Boolean intersection of this workplane with *other*."""
        other_solid = other.solid() if isinstance(other, Workplane) else other
        my_solid = self.solid()
        result = my_solid.common(other_solid)
        return self._copy(shapes=[result], keep_primitive=False)

    # -- Transformations (return new Workplane, original unchanged) ----------

    def translate(self, vec: tuple[float, float, float]) -> Workplane:
        """Translate by *vec* — returns a NEW workplane (does NOT modify in-place).

        This is different from FreeCAD's native translate() which modifies
        in-place and returns None.  The CQ-style always returns a new object.
        """
        new_shape = self.solid().copy()
        new_shape.translate(_fc_vec(vec[0], vec[1], vec[2]))
        return self._copy(shapes=[new_shape], keep_primitive=False)

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
        return self._copy(shapes=[new_shape], keep_primitive=False)

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
        return self._copy(shapes=[new_shape], keep_primitive=False)

    # -- Holes, shell, edge dress, revolve (S8) -----------------------------

    def hole(self, diameter: float, depth: float | None = None) -> Workplane:
        """Drill a round hole at each pending location (or the origin).

        depth=None cuts through the solid along the plane normal. A finite
        depth drills along -normal from the workplane.
        """
        if diameter <= 0:
            raise ValueError(f"hole diameter must be positive: {diameter}")
        return self._drill(diameter / 2.0, depth, None, None)

    def cboreHole(
        self,
        diameter: float,
        cboreDiameter: float,
        cboreDepth: float,
        depth: float | None = None,
    ) -> Workplane:
        """Drill a counterbored hole at each pending location."""
        if diameter <= 0 or cboreDiameter <= 0 or cboreDepth <= 0:
            raise ValueError(
                "cboreHole sizes must be positive: "
                f"diameter={diameter}, cboreDiameter={cboreDiameter}, "
                f"cboreDepth={cboreDepth}"
            )
        if cboreDiameter <= diameter:
            raise ValueError(
                "cboreDiameter must be larger than diameter: "
                f"{cboreDiameter} <= {diameter}"
            )
        return self._drill(diameter / 2.0, depth, cboreDiameter / 2.0, cboreDepth)

    def _drill(self, radius, depth, cbore_radius, cbore_depth) -> Workplane:
        host = self.solid()
        locs = list(self._locations) or [(0.0, 0.0, 0.0)]
        result = host
        for x, y, _rot in locs:
            cutter = _make_drill(
                host, radius, depth, x, y, self._plane, self._origin,
            )
            result = safe_cut(result, cutter)
            if cbore_radius is not None:
                cbore = _make_drill(
                    host, cbore_radius, cbore_depth, x, y,
                    self._plane, self._origin, finite=True,
                )
                result = safe_cut(result, cbore)
        out = self._copy(shapes=[result], keep_primitive=False)
        out._locations = []
        return out

    def shell(self, thickness: float, open: str | None = None) -> Workplane:
        """Hollow a plain box or cylinder by subtracting an inner cutter.

        open=None keeps a closed cavity. "top" / "bottom" let the cutter
        cross that face. Other solids are rejected.
        """
        if thickness <= 0:
            raise ValueError(f"shell thickness must be positive: {thickness}")
        if open not in (None, "top", "bottom"):
            raise ValueError("shell open must be None, 'top', or 'bottom'")
        if self._primitive not in ("box", "cylinder"):
            raise ValueError(
                "shell() only supports a plain box or cylinder. "
                "Holes, booleans, and other solids are not shelled."
            )
        solid = self.solid()
        local_bb = _local_bbox(solid, self._plane, self._origin)
        if self._primitive == "box":
            cutter = _box_shell_cutter(local_bb, thickness, open)
        else:
            cutter = _cylinder_shell_cutter(local_bb, thickness, open)
        _orient_shape(cutter, self._plane, self._origin)
        out = self._copy(shapes=[safe_cut(solid, cutter)], keep_primitive=False)
        return out

    def fillet(self, radius: float, edges="all") -> Workplane:
        """Round edges one at a time. Failures are skipped and counted."""
        return self._dress_edges("fillet", radius, edges)

    def chamfer(self, length: float, edges="all") -> Workplane:
        """Chamfer edges one at a time. Failures are skipped and counted."""
        return self._dress_edges("chamfer", length, edges)

    def _dress_edges(self, kind: str, size: float, edges) -> Workplane:
        if size <= 0:
            raise ValueError(f"{kind} size must be positive: {size}")
        shape = self.solid().copy()
        targets = _select_edges(shape, edges, _PLANE_NORMAL[self._plane])
        if not targets:
            raise ValueError(f"No edges matched selector {edges!r}.")
        applied = 0
        skipped = 0
        mids = [_edge_midpoint(edge) for edge in targets]
        for mid in mids:
            edge = _closest_edge(shape, mid)
            if edge is None:
                skipped += 1
                continue
            try:
                if kind == "fillet":
                    shape = shape.makeFillet(size, [edge])
                else:
                    shape = shape.makeChamfer(size, [edge])
                applied += 1
            except Exception:
                skipped += 1
        if applied == 0:
            raise ValueError(
                f"{kind} applied to 0 edges (skipped {skipped}). "
                "Try a smaller size or a narrower edge selector."
            )
        out = self._copy(shapes=[shape], keep_primitive=False)
        out._edge_note = f"{kind} applied={applied} skipped={skipped}"
        return out

    def revolve(
        self,
        angleDegrees: float = 360,
        axisStart=None,
        axisEnd=None,
        axis: str = "Y",
    ) -> Workplane:
        """Revolve a closed line profile, or one circle(), around an axis.

        Default axis is Y through the workplane origin. Pass axisStart and
        axisEnd together to revolve around an arbitrary segment. A pending
        circle is already closed; a line profile still needs close().
        """
        if not angleDegrees:
            raise ValueError("revolve angle must be non-zero")
        if self._pending and not _profile_has_edges(self._profile):
            return self._revolve_circle(angleDegrees, axisStart, axisEnd, axis)
        if not self._profile:
            raise ValueError(
                "revolve() needs a profile. Call moveTo(), lineTo(), and close(), "
                "or circle() then revolve()."
            )
        if not any(op[0] == "close" for op in self._profile):
            raise ValueError("Profile is not closed. Call close() before revolve().")
        wire = _profile_wire(self._profile, (0.0, 0.0, 0.0))
        return self._revolve_wire(wire, angleDegrees, axisStart, axisEnd, axis)

    def _revolve_circle(self, angleDegrees, axisStart, axisEnd, axis) -> Workplane:
        if len(self._pending) != 1 or self._pending[0][0] != "circle":
            raise ValueError(
                "revolve() accepts one circle() or a closed line profile. "
                "rect(), polygon(), and several sketches cannot be revolved."
            )
        op = self._pending[0]
        radius = float(op[1])
        cx = float(op[3]) if len(op) > 3 else 0.0
        cy = float(op[4]) if len(op) > 4 else 0.0
        edge = Part.makeCircle(radius, _fc_vec(cx, cy, 0.0), _fc_vec(0.0, 0.0, 1.0))
        wire = Part.Wire([edge])
        return self._revolve_wire(wire, angleDegrees, axisStart, axisEnd, axis)

    def _revolve_wire(self, wire, angleDegrees, axisStart, axisEnd, axis) -> Workplane:
        _orient_shape(wire, self._plane, self._origin)
        base, direction = _revolve_axis(
            axisStart, axisEnd, axis, self._origin, self._plane,
        )
        shape = wire.revolve(base, direction, float(angleDegrees))
        if shape is None or getattr(shape, "isNull", lambda: False)():
            raise ValueError(
                "revolve() produced an empty solid. Keep the profile on one "
                "side of the axis; a circle spun about its own center is empty."
            )
        out = self._copy(shapes=[shape], keep_primitive=False)
        out._profile = []
        out._pending = []
        return out

    # -- Workplane offset ---------------------------------------------------

    def workplane(self, offset: float = 0, origin=None) -> Workplane:
        """Create a new workplane on the same named plane.

        offset moves along the plane normal: XY +Z, XZ -Y, YZ +X.
        origin=(x, y, z) sets that global point. origin=(x, y) shifts
        inside the plane and keeps the current offset. Existing shapes
        and pending sketches are carried forward unchanged.
        """
        ox, oy, oz = self._origin
        if origin is not None:
            coords = _xyz(origin)
            if len(coords) == 2:
                dx, dy, dz = _rotate_vec(coords[0], coords[1], 0.0, self._plane)
                ox, oy, oz = ox + dx, oy + dy, oz + dz
            else:
                ox, oy, oz = coords
        if offset:
            nx, ny, nz = _PLANE_NORMAL[self._plane]
            ox += nx * float(offset)
            oy += ny * float(offset)
            oz += nz * float(offset)
        if origin is None and not offset:
            return self._copy()
        return Workplane(
            plane=self._plane,
            origin=(ox, oy, oz),
            shapes=list(self._shapes),
            pending=list(self._pending),
            locations=list(self._locations),
            profile=list(self._profile),
            primitive=self._primitive,
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

def _extrude_pending_op(op: tuple, height: float, both: bool):
    """Extrude a single pending 2D op with CadQuery semantics.

    z spans 0 → +H normally, or -H → +H when both=True (total 2H).
    """
    total_h = 2 * height if both else height
    z0 = -height if both else 0

    if op[0] == "circle":
        R = op[1]
        x, y, _rot = _pose(op, 2)
        if R <= 0:
            raise ValueError(f"Circle radius must be positive: {R}")
        shape = Part.makeCylinder(R, total_h)
        shape.translate(_fc_vec(x, y, z0))
        return shape

    if op[0] == "rect":
        _, L, W, centered = op[:4]
        x, y, rot = _pose(op, 4)
        if L <= 0 or W <= 0:
            raise ValueError(f"rect dimensions must be positive: L={L}, W={W}")
        shape = Part.makeBox(L, W, total_h)
        dx, dy = (-L / 2, -W / 2) if centered else (0.0, 0.0)
        shape.translate(_fc_vec(dx, dy, 0))
        if rot:
            shape.rotate(_fc_vec(0, 0, 0), _fc_vec(0, 0, 1), rot)
        shape.translate(_fc_vec(x, y, z0))
        return shape

    if op[0] == "polygon":
        _, n, R, _centered = op[:4]
        x, y, rot = _pose(op, 4)
        if n < 3 or R <= 0:
            raise ValueError(f"polygon needs n>=3 and R>0, got n={n}, R={R}")
        # Vertices sit on a circle of radius R around the origin, so the
        # polygon is always XY-centered (the centered flag only exists for
        # API symmetry with rect).
        edges = []
        for i in range(n):
            a = 2 * math.pi * i / n
            a2 = 2 * math.pi * ((i + 1) % n) / n
            edge = Part.makeLine(
                _fc_vec(R * math.cos(a), R * math.sin(a), 0),
                _fc_vec(R * math.cos(a2), R * math.sin(a2), 0),
            )
            edges.append(edge)
        face = Part.Face(Part.Wire(edges))
        shape = face.extrude(_fc_vec(0, 0, total_h))
        if rot:
            shape.rotate(_fc_vec(0, 0, 0), _fc_vec(0, 0, 1), rot)
        shape.translate(_fc_vec(x, y, z0))
        return shape

    raise ValueError(f"Unsupported pending 2D operation: {op[0]}")


def _resolve_extrude(
    pending: list[tuple], height: float, both: bool
):
    """Convert accumulated pending 2D operations to a FreeCAD shape via extrude.

    CadQuery semantics (S5-A4): rises from the workplane (z=0 → +H);
    both=True spans z=-H → +H (total 2H).

    Supported patterns:
    - [('circle', R)]              → solid cylinder
    - [('circle', R1), ('circle', R2)] → hollow cylinder (outer = max radius)
    - [('rect', L, W, centered)]   → box
    - [('polygon', n, R, centered)] → regular polygon extrusion
    """
    if height <= 0:
        raise ValueError(f"extrude height must be positive: {height}")

    # --- Hollow cylinder: two circles that share a center ---
    if len(pending) == 2:
        op1, op2 = pending[0], pending[1]
        if op1[0] == "circle" and op2[0] == "circle":
            c1, c2 = _circle_xy(op1), _circle_xy(op2)
            if _same_xy(c1, c2):
                r1 = max(op1[1], op2[1])  # outer
                r2 = min(op1[1], op2[1])  # inner
                if r1 <= r2:
                    raise ValueError(
                        f"Hollow cylinder requires R1 > R2, got R1={r1}, R2={r2}"
                    )
                if both:
                    # Open tube spanning -H..+H
                    outer = Part.makeCylinder(r1, 2 * height)
                    outer.translate(_fc_vec(0, 0, -height))
                    inner = Part.makeCylinder(r2, 2 * height + 0.01)
                    inner.translate(_fc_vec(0, 0, -(height + 0.005)))
                    shape = safe_cut(outer, inner)
                else:
                    # Open tube spanning 0..H
                    shape = make_hollow_cylinder(r1, r2, height, bottom=0)
                if c1[0] or c1[1]:
                    shape.translate(_fc_vec(c1[0], c1[1], 0))
                return shape

    # --- Single op (circle / rect / polygon) ---
    if len(pending) == 1:
        return _extrude_pending_op(pending[0], height, both)

    # --- Multiple ops — extrude each, then fuse ---
    shapes = [_extrude_pending_op(op, height, both) for op in pending]
    result = shapes[0]
    for s in shapes[1:]:
        result = safe_fuse(result, s)
    return result


def _extrude_primitive(pending: list[tuple]) -> str | None:
    """Tag a single circle/rect extrusion so shell() can accept it."""
    if len(pending) != 1:
        return None
    kind = pending[0][0]
    if kind == "circle":
        return "cylinder"
    if kind == "rect":
        return "box"
    return None


def _pose(op: tuple, base_len: int) -> tuple[float, float, float]:
    """Return (x, y, rotation_degrees) stored after the base op fields."""
    extra = op[base_len:]
    x = float(extra[0]) if len(extra) >= 1 else 0.0
    y = float(extra[1]) if len(extra) >= 2 else 0.0
    rot = float(extra[2]) if len(extra) >= 3 else 0.0
    return x, y, rot


def _circle_xy(op: tuple) -> tuple[float, float]:
    x, y, _rot = _pose(op, 2)
    return x, y


def _same_xy(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


_DRILL_OVERLAP = 0.05


def _make_drill(host, radius, depth, x, y, plane, origin, finite=False):
    """Cylinder cutter along the plane normal, through *host* or to *depth*."""
    if depth is None and not finite:
        local = _local_bbox(host, plane, origin)
        z0 = local.ZMin - _DRILL_OVERLAP
        height = (local.ZMax - local.ZMin) + 2 * _DRILL_OVERLAP
    else:
        if depth is None or depth <= 0:
            raise ValueError(f"hole depth must be positive: {depth}")
        z0 = -float(depth)
        height = float(depth)
    shape = Part.makeCylinder(radius, height)
    shape.translate(_fc_vec(x, y, z0))
    return _orient_shape(shape, plane, origin)


_SHELL_OVERLAP = 0.05


def _box_shell_cutter(bb, thickness, open_side):
    dx = bb.XMax - bb.XMin
    dy = bb.YMax - bb.YMin
    dz = bb.ZMax - bb.ZMin
    if dx <= 2 * thickness or dy <= 2 * thickness or dz <= thickness:
        raise ValueError(
            f"shell thickness {thickness} does not fit this box "
            f"({dx:.4g} x {dy:.4g} x {dz:.4g})"
        )
    if open_side is None and dz <= 2 * thickness:
        raise ValueError(
            f"closed shell thickness {thickness} does not fit box height {dz:.4g}"
        )
    ix = dx - 2 * thickness
    iy = dy - 2 * thickness
    x0 = bb.XMin + thickness
    y0 = bb.YMin + thickness
    if open_side is None:
        iz = dz - 2 * thickness
        z0 = bb.ZMin + thickness
    elif open_side == "top":
        iz = dz - thickness + _SHELL_OVERLAP
        z0 = bb.ZMin + thickness
    else:
        iz = dz - thickness + _SHELL_OVERLAP
        z0 = bb.ZMin - _SHELL_OVERLAP
    shape = Part.makeBox(ix, iy, iz)
    shape.translate(_fc_vec(x0, y0, z0))
    return shape


def _cylinder_shell_cutter(bb, thickness, open_side):
    radius = min(bb.XMax - bb.XMin, bb.YMax - bb.YMin) / 2.0
    height = bb.ZMax - bb.ZMin
    if radius <= thickness or height <= thickness:
        raise ValueError(
            f"shell thickness {thickness} does not fit this cylinder "
            f"(R={radius:.4g}, H={height:.4g})"
        )
    if open_side is None and height <= 2 * thickness:
        raise ValueError(
            f"closed shell thickness {thickness} does not fit cylinder height {height:.4g}"
        )
    inner_r = radius - thickness
    cx = (bb.XMin + bb.XMax) / 2.0
    cy = (bb.YMin + bb.YMax) / 2.0
    if open_side is None:
        iz = height - 2 * thickness
        z0 = bb.ZMin + thickness
    elif open_side == "top":
        iz = height - thickness + _SHELL_OVERLAP
        z0 = bb.ZMin + thickness
    else:
        iz = height - thickness + _SHELL_OVERLAP
        z0 = bb.ZMin - _SHELL_OVERLAP
    shape = Part.makeCylinder(inner_r, iz)
    # makeCylinder's axis is Z through the origin; shift it to the solid's axis.
    shape.translate(_fc_vec(cx, cy, z0))
    return shape


def _edge_span(edge):
    bb = edge.BoundBox
    return (
        abs(bb.XMax - bb.XMin),
        abs(bb.YMax - bb.YMin),
        abs(bb.ZMax - bb.ZMin),
    )


def _edge_class(edge, normal=(0.0, 0.0, 1.0)) -> str:
    """'vertical' is parallel to the plane normal; on XY that is global Z."""
    dx, dy, dz = _edge_span(edge)
    nx, ny, nz = normal
    if abs(ny) > 0.5:
        along, a, b = dy, dx, dz
    elif abs(nx) > 0.5:
        along, a, b = dx, dy, dz
    else:
        along, a, b = dz, dx, dy
    if along > a and along > b:
        return "vertical"
    if along <= 0.25 * max(a, b):
        return "horizontal"
    return "other"


def _edge_midpoint(edge):
    bb = edge.BoundBox
    return (
        (bb.XMin + bb.XMax) / 2.0,
        (bb.YMin + bb.YMax) / 2.0,
        (bb.ZMin + bb.ZMax) / 2.0,
    )


def _select_edges(shape, selector, normal=(0.0, 0.0, 1.0)):
    all_edges = list(getattr(shape, "Edges", []) or [])
    if selector == "all":
        return all_edges
    if selector == "vertical":
        return [edge for edge in all_edges if _edge_class(edge, normal) == "vertical"]
    if selector == "horizontal":
        return [
            edge for edge in all_edges if _edge_class(edge, normal) == "horizontal"
        ]
    if isinstance(selector, (list, tuple)):
        chosen = []
        for index in selector:
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError(f"edge index must be an int, got {index!r}")
            if index < 0 or index >= len(all_edges):
                raise ValueError(
                    f"edge index {index} out of range (0..{len(all_edges) - 1})"
                )
            chosen.append(all_edges[index])
        return chosen
    raise ValueError(
        "edges must be 'all', 'vertical', 'horizontal', or a list of indices"
    )


def _closest_edge(shape, mid):
    best = None
    best_d = None
    for edge in getattr(shape, "Edges", []) or []:
        ex, ey, ez = _edge_midpoint(edge)
        dist = (ex - mid[0]) ** 2 + (ey - mid[1]) ** 2 + (ez - mid[2]) ** 2
        if best_d is None or dist < best_d:
            best = edge
            best_d = dist
    return best


def _xyz(value):
    """2 or 3 coordinates from a tuple or a vector-like object."""
    if hasattr(value, "x") and hasattr(value, "y"):
        return (float(value.x), float(value.y), float(getattr(value, "z", 0.0)))
    try:
        coords = tuple(float(item) for item in value)
    except TypeError as exc:
        raise ValueError(
            "workplane origin must be a 2-tuple or a 3-tuple"
        ) from exc
    if len(coords) not in (2, 3):
        raise ValueError("workplane origin must be a 2-tuple or a 3-tuple")
    return coords


def _profile_has_edges(profile) -> bool:
    """True when the line profile has a segment, not only moveTo points."""
    return any(op[0] in ("line", "arc") for op in profile)


def _profile_wire(profile, origin):
    ox, oy, oz = origin
    start = None
    current = None
    edges = []
    for op in profile:
        kind = op[0]
        if kind == "move":
            current = (ox + op[1], oy + op[2], oz)
            start = current
        elif kind == "line":
            if current is None:
                raise ValueError("lineTo() needs moveTo() first.")
            nxt = (ox + op[1], oy + op[2], oz)
            edges.append(Part.makeLine(_fc_vec(*current), _fc_vec(*nxt)))
            current = nxt
        elif kind == "arc":
            if current is None:
                raise ValueError("threePointArc() needs moveTo() first.")
            mid = (ox + op[1], oy + op[2], oz)
            end = (ox + op[3], oy + op[4], oz)
            edges.append(Part.Arc(
                _fc_vec(*current), _fc_vec(*mid), _fc_vec(*end),
            ).toShape())
            current = end
        elif kind == "close":
            if current is None or start is None:
                raise ValueError("close() needs a profile.")
            if (abs(current[0] - start[0]) > 1e-9
                    or abs(current[1] - start[1]) > 1e-9
                    or abs(current[2] - start[2]) > 1e-9):
                edges.append(Part.makeLine(_fc_vec(*current), _fc_vec(*start)))
            current = start
        else:
            raise ValueError(f"Unknown profile operation: {kind}")
    if not edges:
        raise ValueError("Profile has no edges.")
    return Part.Wire(edges)


def _revolve_axis(axis_start, axis_end, axis, origin, plane="XY"):
    if axis_start is not None or axis_end is not None:
        if axis_start is None or axis_end is None:
            raise ValueError("axisStart and axisEnd must be given together.")
        sx, sy, sz = axis_start
        ex, ey, ez = axis_end
        if abs(ex - sx) + abs(ey - sy) + abs(ez - sz) < 1e-12:
            raise ValueError("revolve axis has zero length")
        return _fc_vec(sx, sy, sz), _fc_vec(ex - sx, ey - sy, ez - sz)
    name = (axis or "Y").upper()
    dirs = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
    if name not in dirs:
        raise ValueError("revolve axis must be 'X', 'Y', or 'Z'")
    dx, dy, dz = _rotate_vec(*dirs[name], plane)
    return _fc_vec(*origin), _fc_vec(dx, dy, dz)


# ---------------------------------------------------------------------------
# Module-level convenience for sandbox injection
# ---------------------------------------------------------------------------

Vector = _fc_vec  # cq.Vector(x, y, z) → FreeCAD.Vector


# Populate the cq module namespace for sandbox injection
_cq_module.Workplane = Workplane
_cq_module.Vector = Vector

# Export for tools.py injection
__all__ = ["Workplane", "Vector", "_cq_module"]
