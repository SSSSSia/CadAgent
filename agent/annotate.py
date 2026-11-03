"""Format a FreeCAD selection as a [mark] the agent can read."""
from __future__ import annotations


def format_mark(label: str, name: str, subname: str = "", point=None) -> str:
    """One click. *point* is ``(x, y, z)`` or None."""
    if point is None:
        where = "no picked point"
    else:
        where = f"({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f})"
    face = f" face {subname}" if subname else ""
    return f"[mark] {label} ({name}){face} at {where}"


def format_marks(items) -> str:
    """*items* is an iterable of ``(label, name, subname, point)``."""
    return "\n".join(
        format_mark(label, name, subname, point)
        for label, name, subname, point in items
    )


def _point_tuple(point):
    if point is None:
        return None
    return (float(point.x), float(point.y), float(point.z))


def marks_from_selection(selection) -> str:
    """*selection* is FreeCAD's ``getSelectionEx()`` list, or a similar stub."""
    items = []
    for item in selection or []:
        obj = item.Object
        label = getattr(obj, "Label", "") or getattr(obj, "Name", "")
        name = getattr(obj, "Name", "") or label
        subs = list(getattr(item, "SubElementNames", []) or [])
        points = list(getattr(item, "PickedPoints", []) or [])
        count = max(len(subs), len(points), 1)
        for index in range(count):
            sub = subs[index] if index < len(subs) else ""
            point = points[index] if index < len(points) else None
            items.append((label, name, sub, _point_tuple(point)))
    return format_marks(items)


def read_selection_marks() -> str:
    """Read the current 3D selection. Empty when nothing is selected."""
    import FreeCADGui
    try:
        selection = FreeCADGui.Selection.getSelectionEx()
    except Exception:
        return ""
    return marks_from_selection(selection)
