"""Tests for agent/code_fixes.py — pre-validation and error hints."""
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


# ---- error_hint ----

def test_name_error_hint():
    err = NameError("name 'doc' is not defined")
    hint, fixed = error_hint(err, "doc.recompute()")
    assert "FreeCADGui" in hint
    assert "doc" in hint
    assert fixed is None


def test_name_error_bare_gui_auto_fix():
    err = NameError("name 'Gui' is not defined")
    hint, fixed = error_hint(err, "Gui.updateGui()")
    assert "FreeCADGui" in hint
    assert fixed is not None
    assert "FreeCADGui.updateGui()" in fixed
    assert "Gui." not in fixed.replace("FreeCADGui.", "")


def test_name_error_bare_makebox_auto_fix():
    err = NameError("name 'makeBox' is not defined")
    hint, fixed = error_hint(err, "box = makeBox(100, 50, 30)")
    assert "Part.makeBox" in hint
    assert fixed is not None
    assert "Part.makeBox" in fixed
    assert "makeBox" not in fixed.replace("Part.makeBox", "")


def test_attribute_error_none_translate():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    hint, fixed = error_hint(err, "shape = shape.translate(FreeCAD.Vector(1,2,3))")
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


def test_makeellipse_error_hint():
    err = AttributeError("module 'Part' has no attribute 'makeEllipse'")
    hint, fixed = error_hint(err, "e = Part.makeEllipse(50, 30)")
    assert "Part.Ellipse()" in hint
    assert "MajorRadius" in hint
    assert fixed is None


def test_occ_error_collinear_hint():
    """OCCError with collinear points should give specific Arc hint."""
    class OCCError(Exception):
        pass
    err = OCCError("Three points are collinear")
    hint, fixed = error_hint(err, "arc = Part.Arc(p1, p2, p3)")
    assert "collinear" in hint.lower() or "three points" in hint.lower()
    assert "Part.Arc" in hint
    assert "mid-point" in hint
    assert fixed is None


def test_occ_error_null_shape_hint():
    """OCCError with Null shape should give specific hint."""
    class OCCError(Exception):
        pass
    err = OCCError("Null shape")
    hint, fixed = error_hint(err, "handle = path.makePipe(profile)")
    assert "null" in hint.lower()
    assert "overlap" in hint.lower() or "boolean" in hint.lower() or "makePipe" in hint
    assert fixed is None


def test_valueerror_null_shape_hint():
    """ValueError: Null shape (the most common real-world case) must produce a hint."""
    err = ValueError("Null shape")
    hint, fixed = error_hint(err, "body = body.cut(hole)")
    assert "null" in hint.lower()
    assert "boolean" in hint.lower() or "overlap" in hint.lower()
    assert fixed is None


def test_occ_command_not_done_revolve_hint():
    """BRep_API: command not done with revolve() should give revolve-specific hint."""
    class OCCError(Exception):
        pass
    err = OCCError("BRep_API: command not done")
    code = "mouse_body = wire.revolve(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,1,0), 180)"
    hint, fixed = error_hint(err, code)
    assert "revolve" in hint.lower()
    assert "CLOSED" in hint or "closed" in hint
    assert fixed is None


def test_occ_argument_signature_hint():
    """OCCError: Argument list signature incorrect should hint Wire vs Edge."""
    class OCCError(Exception):
        pass
    err = OCCError("Argument list signature is incorrect.\n\nSupported signatures:\n(face)\n(wire)")
    hint, fixed = error_hint(err, "face = Part.Face(wire)")
    assert "Wire" in hint
    assert "Edge" in hint
    assert fixed is None


def test_sweep_not_exist_hint():
    """AttributeError: 'sweep' should suggest makePipe."""
    err = AttributeError("'Part.Edge' object has no attribute 'sweep'")
    hint, fixed = error_hint(err, "mouse_body = wire_arc.sweep(path_wire, True)")
    assert "sweep" in hint
    assert "makePipe" in hint or "makeLoft" in hint
    assert fixed is None


# ===========================================================================
# Phase 5: Auto-retry eligibility boundary tests
# ===========================================================================

# --- Eligible: error_hint returns fixed_code → auto-retry should trigger ---

def test_auto_retry_eligible_bare_gui():
    err = NameError("name 'Gui' is not defined")
    _, fixed = error_hint(err, "Gui.SendMsgToActiveView('Enter')")
    assert fixed is not None


def test_auto_retry_eligible_misspelled_freecadgui():
    err = NameError("name 'FreecadGUI' is not defined")
    _, fixed = error_hint(err, "FreecadGUI.SendMsgToActiveView('Enter')")
    assert fixed is not None
    assert "FreeCADGui" in fixed


def test_auto_retry_eligible_bare_makebox():
    err = NameError("name 'makeBox' is not defined")
    _, fixed = error_hint(err, "box = makeBox(10, 20, 30)")
    assert fixed is not None
    assert "Part.makeBox" in fixed


def test_auto_retry_eligible_translate_assignment():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    _, fixed = error_hint(err, "shape = shape.translate(FreeCAD.Vector(1,2,3))")
    assert fixed is not None
    assert "shape = shape.translate" not in fixed


def test_auto_retry_eligible_boolean_no_assign():
    err = AttributeError("'NoneType' object has no attribute 'Shape'")
    _, fixed = error_hint(err, "body.cut(hole)")
    assert fixed is not None
    assert "body = body.cut(hole)" in fixed


def test_auto_retry_eligible_vector_case():
    err = AttributeError("'module' object has no attribute 'vector'")
    _, fixed = error_hint(err, "v = FreeCAD.vector(1, 2, 3)")
    assert fixed is not None
    assert "FreeCAD.Vector" in fixed


def test_auto_retry_eligible_makepipe_edge():
    err = AttributeError("'Part.Edge' object has no attribute 'makePipe'")
    _, fixed = error_hint(err, "pipe = arc_edge.makePipe(profile)")
    assert fixed is not None


def test_auto_retry_eligible_translate_args():
    err = TypeError("translate() takes 1 positional argument but 3 were given")
    _, fixed = error_hint(err, "shape.translate(1, 2, 3)")
    assert fixed is not None
    assert "FreeCAD.Vector(1, 2, 3)" in fixed


# --- NOT eligible: error_hint returns None → no auto-retry ---

def test_auto_retry_not_eligible_null_shape():
    err = ValueError("Null shape")
    _, fixed = error_hint(err, "body = body.cut(hole)")
    assert fixed is None


def test_auto_retry_not_eligible_occ_error():
    class OCCError(Exception):
        pass
    err = OCCError("BRep_API: command terminated")
    _, fixed = error_hint(err, "body = body.cut(hole)")
    assert fixed is None


def test_auto_retry_not_eligible_makeellipse():
    err = AttributeError("module 'Part' has no attribute 'makeEllipse'")
    _, fixed = error_hint(err, "e = Part.makeEllipse(50, 30)")
    assert fixed is None


def test_auto_retry_not_eligible_sweep():
    err = AttributeError("'Part.Edge' object has no attribute 'sweep'")
    _, fixed = error_hint(err, "body = wire.sweep(path)")
    assert fixed is None


def test_auto_retry_not_eligible_doc_is_none():
    err = AttributeError("'NoneType' object has no attribute 'addObject'")
    _, fixed = error_hint(err, "obj = doc.addObject('Part::Feature', 'Box')")
    assert fixed is None


def test_auto_retry_not_eligible_unknown_error():
    err = ValueError("something unexpected")
    _, fixed = error_hint(err, "x = 1")
    assert fixed is None
