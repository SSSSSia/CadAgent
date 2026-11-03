"""Selection marks, without a FreeCAD GUI."""
from __future__ import annotations

from agent.annotate import format_mark, marks_from_selection


class _Point:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Obj:
    def __init__(self, name, label):
        self.Name = name
        self.Label = label


class _Sel:
    def __init__(self, obj, subs=None, points=None):
        self.Object = obj
        self.SubElementNames = subs or []
        self.PickedPoints = points or []


def test_format_mark_with_and_without_a_point():
    assert format_mark("Rim", "cqobj_Rim") == "[mark] Rim (cqobj_Rim) at no picked point"
    text = format_mark("Rim", "cqobj_Rim", "Face3", (1, 2, 3.5))
    assert text == "[mark] Rim (cqobj_Rim) face Face3 at (1.000, 2.000, 3.500)"


def test_marks_from_selection_pairs_faces_and_points():
    text = marks_from_selection([
        _Sel(_Obj("Block", "Body"), ["Face1"], [_Point(0, 0, 10)]),
        _Sel(_Obj("Pin", "Pin")),
    ])
    assert "[mark] Body (Block) face Face1 at (0.000, 0.000, 10.000)" in text
    assert "[mark] Pin (Pin) at no picked point" in text
    assert marks_from_selection([]) == ""
