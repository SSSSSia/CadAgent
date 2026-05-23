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
    hint = error_hint(err, "doc.recompute()")
    assert "Pre-imported" in hint
    assert "doc" in hint


def test_attribute_error_none():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    hint = error_hint(err, "shape = shape.translate(Vector(1,2,3))")
    assert "None" in hint or "translate" in hint


def test_type_error_translate():
    err = TypeError("translate() takes 1 positional argument but 3 were given")
    hint = error_hint(err, "shape.translate(1, 2, 3)")
    assert "Vector" in hint


def test_no_hint_for_unknown():
    err = ValueError("something unexpected")
    hint = error_hint(err, "x = 1")
    assert hint == ""
