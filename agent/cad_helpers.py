"""Stable CAD helper functions injected into execute_code namespace.

These helpers wrap common FreeCAD/OCC patterns that LLMs frequently get wrong:
- Boolean ops producing Compound instead of Solid
- Multi-solid results from fuse on non-overlapping shapes
- Manual Solids[0] extraction after every boolean op

All helpers raise clear ValueError on invalid geometry instead of returning
bad shapes silently.
"""
from __future__ import annotations

import FreeCAD
import Part


def extract_solid(shape):
    """Extract single solid from a shape after boolean operations.

    Returns the solid directly if shape is already a Solid.
    Returns shape.Solids[0] if exactly one solid exists inside a Compound.
    Raises ValueError for null shapes, no solids, or multiple solids.
    """
    if shape is None:
        raise ValueError("Null shape: shape is None")
    if shape.isNull():
        raise ValueError("Null shape: shape.isNull() is True")
    if shape.ShapeType == "Solid":
        return shape
    solids = shape.Solids
    if len(solids) == 0:
        raise ValueError(
            f"No solid components in shape (type={shape.ShapeType})"
        )
    if len(solids) > 1:
        raise ValueError(
            f"Expected 1 solid, got {len(solids)}. "
            "Shapes must physically overlap for fuse to merge into one solid."
        )
    return solids[0]


def safe_fuse(a, b):
    """Fuse two shapes and extract a single solid result.

    Use this instead of raw a.fuse(b) to guarantee a clean single solid.
    Raises ValueError if fuse produces null/compound/multi-solid result.
    """
    result = a.fuse(b)
    return extract_solid(result)


def safe_cut(a, b):
    """Cut b from a and extract solid result(s).

    Use this instead of raw a.cut(b).  Cut operations naturally produce
    multiple fragments, so this returns a Compound containing all resulting
    solids when more than one is present.  This is different from safe_fuse
    which requires exactly one solid (overlapping shapes should merge).
    """
    result = a.cut(b)
    if result is None or (hasattr(result, "isNull") and result.isNull()):
        raise ValueError("Cut operation produced null shape")
    # Already a single Solid — return directly
    if hasattr(result, "ShapeType") and result.ShapeType == "Solid":
        return result
    solids = result.Solids if hasattr(result, "Solids") else []
    if len(solids) == 0:
        raise ValueError("Cut removed all geometry — no solid remains")
    if len(solids) == 1:
        return solids[0]
    # Multiple fragments — return as Compound (valid for further boolean ops)
    compound = Part.makeCompound(solids)
    return compound


def make_hollow_cylinder(outer_r, inner_r, height, bottom=0):
    """Create a hollow cylinder (cup body) with optional bottom thickness.

    Args:
        outer_r: Outer radius in mm.
        inner_r: Inner radius in mm.
        height: Total height in mm.
        bottom: Bottom thickness in mm (0 = open bottom).
    """
    if outer_r <= inner_r:
        raise ValueError(
            f"outer_r ({outer_r}) must be greater than inner_r ({inner_r})"
        )
    if height <= 0:
        raise ValueError(f"height ({height}) must be positive")
    if bottom < 0:
        raise ValueError(f"bottom ({bottom}) must be non-negative")

    outer = Part.makeCylinder(outer_r, height)
    inner_h = max(height - bottom, 0.1)
    inner = Part.makeCylinder(inner_r, inner_h)
    if bottom > 0:
        inner.translate(FreeCAD.Vector(0, 0, bottom))
    return safe_cut(outer, inner)


def make_ring(outer_r, inner_r, height):
    """Create a ring/rim shape (flat annular cylinder).

    Args:
        outer_r: Outer radius in mm.
        inner_r: Inner radius in mm.
        height: Ring thickness in mm.
    """
    if outer_r <= inner_r:
        raise ValueError(
            f"outer_r ({outer_r}) must be greater than inner_r ({inner_r})"
        )
    if height <= 0:
        raise ValueError(f"height ({height}) must be positive")

    outer = Part.makeCylinder(outer_r, height)
    inner = Part.makeCylinder(inner_r, height)
    return safe_cut(outer, inner)


def make_box_handle(cup_radius, width, depth, height, z):
    """Create a rectangular box handle positioned to overlap with a cup body.

    The handle starts 2mm inside the cup wall to guarantee fuse overlap.

    Args:
        cup_radius: Outer radius of the cup body (mm).
        width: Handle width in Y direction (mm).
        depth: Handle depth in X direction (mm).
        height: Handle height in Z direction (mm).
        z: Z position of handle bottom (mm).
    """
    if width <= 0:
        raise ValueError(f"width ({width}) must be positive")
    if depth <= 0:
        raise ValueError(f"depth ({depth}) must be positive")
    if height <= 0:
        raise ValueError(f"height ({height}) must be positive")

    handle = Part.makeBox(depth, width, height)
    handle.translate(FreeCAD.Vector(cup_radius - 2.0, -width / 2, z))
    return extract_solid(handle)


def make_arc_handle(cup_radius, handle_r, arc_r, z_center):
    """Create an arc-shaped (half-torus) handle for cup-shaped parts.

    Uses a half-torus to create a smooth curved handle.  The handle
    connects to the cup at two points (top/bottom) and curves outward.
    Vertical span ≈ 2 * arc_r;  outward depth ≈ arc_r.

    Connection points penetrate 2mm into the cup wall for reliable
    safe_fuse overlap.

    Args:
        cup_radius: Outer radius of the cup body (mm).
        handle_r: Cross-section radius of the handle rod (mm).
        arc_r: Arc radius — controls handle size.  Height ≈ 2*arc_r,
               depth ≈ arc_r (mm).
        z_center: Z position of handle vertical center (mm).
    """
    if handle_r <= 0:
        raise ValueError(f"handle_r ({handle_r}) must be positive")
    if arc_r <= handle_r:
        raise ValueError(
            f"arc_r ({arc_r}) must be greater than handle_r ({handle_r})"
        )

    # Half-torus (180° sweep) around Z axis in XY plane
    torus = Part.makeTorus(arc_r, handle_r)
    s = arc_r + handle_r + 1
    cutter = Part.makeBox(
        2 * s, s, 2 * (handle_r + 1),
        FreeCAD.Vector(-s, -s, -(handle_r + 1)),
    )
    handle = safe_cut(torus, cutter)

    # Rotate from XY plane into XZ plane, curving in +X direction
    handle.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), -90)
    handle.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0), 90)

    # Offset 2mm inward so connection points penetrate cup wall for fuse
    handle.translate(FreeCAD.Vector(cup_radius - 2.0, 0, z_center))
    return extract_solid(handle)


# Track labels of objects created by cq_show so we can clean up stale
# intermediates on the next call.  Keeps the document at exactly one
# cq_show-managed object for the common single-part agent workflow.
_CQ_SHOW_LABELS: set[str] = set()


def cq_show(result, label="Part", doc=None):
    """Add a Workplane or FreeCAD shape to the document and recompute.

    This is the CQ-style bridge to FreeCAD's document model.  Call it
    after building geometry to make the result visible in the viewport.

    Reuses an existing object with the same Label (updates Shape in-place)
    and removes stale objects from previous cq_show calls to keep the
    document clean for the single-part agent workflow.

    Args:
        result: A cq.Workplane or raw FreeCAD shape.
        label:  Document object label (default "Part").
        doc:    Target document (defaults to ActiveDocument).
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("CadAgentModel")
    shape = result.solid() if hasattr(result, "solid") else result

    # Reuse existing object with the same Label, or create a new one.
    existing = None
    if hasattr(doc, "Objects"):
        for obj in doc.Objects:
            if getattr(obj, "Label", None) == label:
                existing = obj
                break

    returned = existing
    if existing is not None and hasattr(existing, "Shape"):
        existing.Shape = shape
    else:
        obj = doc.addObject("Part::Feature", label)
        obj.Shape = shape
        returned = obj

    # Remove stale objects from previous cq_show calls (different labels).
    to_remove = []
    if hasattr(doc, "Objects"):
        for obj in doc.Objects:
            if getattr(obj, "TypeId", "") != "Part::Feature":
                continue
            if obj.Label in _CQ_SHOW_LABELS and obj.Label != label:
                to_remove.append(obj)
    for obj in to_remove:
        try:
            doc.removeObject(obj.Name)
            _CQ_SHOW_LABELS.discard(obj.Label)
        except Exception:
            pass

    _CQ_SHOW_LABELS.discard(label)
    _CQ_SHOW_LABELS.add(label)
    doc.recompute()
    return returned


def ensure_doc(name=None):
    """Get or create a FreeCAD document.

    If name is given and the document exists, returns it.
    If name is given but doesn't exist, creates a new document.
    If name is None, returns ActiveDocument or creates "CadAgentModel".
    """
    if name:
        try:
            doc = FreeCAD.getDocument(name)
            if doc is not None:
                return doc
        except (NameError, RuntimeError):
            pass
        return FreeCAD.newDocument(name)
    if FreeCAD.ActiveDocument is not None:
        return FreeCAD.ActiveDocument
    return FreeCAD.newDocument("CadAgentModel")
