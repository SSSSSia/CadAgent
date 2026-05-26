"""Tests for agent/code_fixes.py — pre-validation, auto-fix, error hints."""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_spec = importlib.util.spec_from_file_location(
    "code_fixes",
    os.path.join(os.path.dirname(__file__), "..", "agent", "code_fixes.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
pre_validate_code = _mod.pre_validate_code
auto_fix_code = _mod.auto_fix_code
error_hint = _mod.error_hint


# ---- pre_validate_code ----

def test_valid_code():
    ok, msg = pre_validate_code("x = 1\ny = 2")
    assert ok
    assert msg == ""


def test_syntax_error_missing_colon():
    ok, msg = pre_validate_code("if True\n  pass")
    assert not ok
    assert "SyntaxError" in msg


def test_syntax_error_unmatched_bracket():
    ok, msg = pre_validate_code("x = [1, 2")
    assert not ok
    assert "SyntaxError" in msg


def test_syntax_error_bad_indent():
    ok, msg = pre_validate_code("if True:\n  x = 1\n y = 2")
    assert not ok
    assert "SyntaxError" in msg


# ---- auto_fix_code ----

def test_no_fix_needed():
    code = "body = body.cut(hole)\nshape.translate(Vector(1,2,3))"
    fixed, fixes = auto_fix_code(code)
    assert fixed == code
    assert fixes == []


def test_fix_translate_assignment():
    code = "shape = shape.translate(Vector(0, 0, 10))"
    fixed, fixes = auto_fix_code(code)
    assert fixed == "shape.translate(Vector(0, 0, 10))"
    assert len(fixes) == 1
    assert "translate" in fixes[0]


def test_fix_boolean_no_assign():
    code = "body.cut(hole)"
    fixed, fixes = auto_fix_code(code)
    assert fixed == "body = body.cut(hole)"
    assert len(fixes) == 1
    assert "boolean" in fixes[0].lower()


def test_fix_missing_recompute():
    code = "obj = doc.addObject('Part::Feature', 'Box')\nobj.Shape = box"
    fixed, fixes = auto_fix_code(code)
    assert "doc.recompute()" in fixed
    assert len(fixes) == 1
    assert "recompute" in fixes[0]


def test_no_recompute_fix_when_present():
    code = "obj = doc.addObject('Part::Feature', 'Box')\nobj.Shape = box\ndoc.recompute()"
    fixed, fixes = auto_fix_code(code)
    assert fixed == code
    # recompute fix should NOT trigger


def test_multiple_fixes():
    code = "body.cut(hole)\nshape = shape.translate(Vector(1,2,3))\nobj = doc.addObject('Part::Feature', 'X')\nobj.Shape = body"
    fixed, fixes = auto_fix_code(code)
    assert len(fixes) == 3
    assert "body = body.cut(hole)" in fixed
    assert "shape.translate" in fixed
    assert "doc.recompute()" in fixed


# ---- error_hint ----

def test_name_error_hint():
    err = NameError("name 'doc' is not defined")
    hint, fixed = error_hint(err, "doc.recompute()")
    assert "Pre-imported" in hint
    assert "doc" in hint
    assert fixed is None


def test_name_error_bare_makebox_auto_fix():
    err = NameError("name 'makeBox' is not defined")
    hint, fixed = error_hint(err, "box = makeBox(100, 50, 30)")
    assert "Part.makeBox" in hint
    assert fixed is not None
    assert "Part.makeBox" in fixed
    assert "makeBox" not in fixed.replace("Part.makeBox", "")


def test_attribute_error_none_translate():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    hint, fixed = error_hint(err, "shape = shape.translate(Vector(1,2,3))")
    assert "translate" in hint
    assert fixed is not None
    assert "shape = shape.translate" not in fixed
    assert "shape.translate" in fixed


def test_attribute_error_none_boolean():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    hint, fixed = error_hint(err, "body.cut(hole)\nprint(body)")
    assert fixed is not None
    assert "body = body.cut(hole)" in fixed


def test_attribute_error_vector_case():
    err = AttributeError("'module' object has no attribute 'vector'")
    hint, fixed = error_hint(err, "v = FreeCAD.vector(1, 2, 3)")
    assert "Vector" in hint
    assert fixed is not None
    assert "FreeCAD.Vector" in fixed


def test_type_error_translate():
    err = TypeError("translate() takes 1 positional argument but 3 were given")
    hint, fixed = error_hint(err, "shape.translate(1, 2, 3)")
    assert "Vector" in hint
    assert fixed is not None
    assert "FreeCAD.Vector(1, 2, 3)" in fixed


def test_type_error_translate_no_auto_fix():
    err = TypeError("translate() takes 1 positional argument but 3 were given")
    hint, fixed = error_hint(err, "shape.translate(FreeCAD.Vector(1, 2, 3))")
    assert "Vector" in hint
    assert fixed is None


def test_occ_error_hint():
    class OCCError(Exception):
        pass
    err = OCCError("BRep_API: command terminated")
    hint, fixed = error_hint(err, "body = body.cut(hole)")
    assert "Boolean" in hint or "overlap" in hint
    assert fixed is None


def test_no_hint_for_unknown():
    err = ValueError("something unexpected")
    hint, fixed = error_hint(err, "x = 1")
    assert hint == ""
    assert fixed is None


# ---- auto_fix_code: new patterns (Fix 4-9) ----

def test_fix4_bare_makebox():
    code = "box = makeBox(100, 50, 30)"
    fixed, fixes = auto_fix_code(code)
    assert "Part.makeBox" in fixed
    assert any("Part." in f for f in fixes)


def test_fix4_bare_makecylinder():
    code = "cyl = makeCylinder(10, 50)"
    fixed, fixes = auto_fix_code(code)
    assert "Part.makeCylinder" in fixed


def test_fix4_no_fix_when_prefixed():
    code = "box = Part.makeBox(100, 50, 30)"
    fixed, fixes = auto_fix_code(code)
    assert fixed == code


def test_fix5_freecad_vector_case():
    code = "v = FreeCAD.vector(1, 2, 3)"
    fixed, fixes = auto_fix_code(code)
    assert "FreeCAD.Vector" in fixed
    assert any("case" in f.lower() or "Vector" in f for f in fixes)


def test_fix5_no_fix_when_correct_case():
    code = "v = FreeCAD.Vector(1, 2, 3)"
    fixed, fixes = auto_fix_code(code)
    assert fixed == code


def test_fix6_addobject_no_assign():
    code = 'doc.addObject("Part::Feature", "Box")'
    fixed, fixes = auto_fix_code(code)
    assert "_obj_" in fixed
    assert "=" in fixed


def test_fix6_no_fix_when_assigned():
    code = 'obj = doc.addObject("Part::Feature", "Box")\nobj.Shape = box\ndoc.recompute()'
    fixed, fixes = auto_fix_code(code)
    assert fixed == code


def test_fix8_multi_arg_boolean():
    code = "result = body.cut(a, b)"
    fixed, fixes = auto_fix_code(code)
    assert "body.cut(a).cut(b)" in fixed
    assert any("Split" in f or "chained" in f for f in fixes)


def test_fix8_multi_arg_fuse():
    code = "result = outer.fuse(x, y)"
    fixed, fixes = auto_fix_code(code)
    assert "outer.fuse(x).fuse(y)" in fixed


def test_fix9_placement_assignment():
    # FreeCAD.Placement assignments are now kept (valid for DocumentObjects)
    code = "shape.Placement = FreeCAD.Placement(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,0,1), 45)"
    fixed, fixes = auto_fix_code(code)
    # Should NOT remove — contains FreeCAD.Placement which is intentional
    assert "Placement" in fixed
    assert len(fixes) == 0


def test_fix9_no_fix_no_placement():
    code = "shape.translate(FreeCAD.Vector(1, 2, 3))"
    fixed, fixes = auto_fix_code(code)
    assert fixed == code


def test_combined_fix4_and_fix2():
    code = "box = makeBox(100, 50, 30)\nbody.cut(box)"
    fixed, fixes = auto_fix_code(code)
    assert "Part.makeBox" in fixed
    assert "body = body.cut(box)" in fixed


# ---- error_hint: makePipe ----

def test_makepipe_error_hint_with_autofix():
    err = AttributeError("'Part.Edge' object has no attribute 'makePipe'")
    hint, fixed = error_hint(err, "handle = arc_edge.makePipe(profile)")
    assert "Wire" in hint
    assert "NOT" in hint
    assert fixed is not None
    assert "Part.Wire([arc_edge]).makePipe(profile)" in fixed


def test_makepipe_error_hint_no_match_in_code():
    err = AttributeError("'Part.Edge' object has no attribute 'makePipe'")
    hint, fixed = error_hint(err, "x = 1\ny = 2")
    assert "Wire" in hint
    assert fixed is None


def test_improved_generic_attribute_error():
    err = AttributeError("'Part.Edge' object has no attribute 'makeLoft'")
    hint, fixed = error_hint(err, "x = edge.makeLoft(wires)")
    assert "makeLoft" in hint
    assert "Edge" in hint
    assert "Wire" in hint
