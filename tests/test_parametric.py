"""Tests for parametric design features — parameter extraction and session storage."""
from __future__ import annotations

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# Replicate the function under test directly to avoid FreeCAD import chain
_PARAM_PATTERN = re.compile(r'^([A-Z][A-Z0-9_]*)\s*=\s*([-+]?[\d.]+)\s*$')


def _extract_parameters(code: str) -> dict:
    params = {}
    for line in code.strip().split('\n'):
        m = _PARAM_PATTERN.match(line.strip())
        if m:
            val = float(m.group(2)) if '.' in m.group(2) else int(m.group(2))
            params[m.group(1)] = val
        elif line.strip() and not line.strip().startswith('#'):
            break
    return params


class TestExtractParameters:
    def test_basic_params(self):
        code = "OD = 200\nHEIGHT = 360\nFLANGE_R = 125\nbody = Part.makeCylinder(OD/2, HEIGHT)"
        params = _extract_parameters(code)
        assert params == {"OD": 200, "HEIGHT": 360, "FLANGE_R": 125}

    def test_float_params(self):
        code = "TOLERANCE = 0.1\nANGLE = 45.5\nresult = TOLERANCE * 2"
        params = _extract_parameters(code)
        assert params == {"TOLERANCE": 0.1, "ANGLE": 45.5}

    def test_int_param(self):
        code = "NUM_HOLES = 8\nresult = []"
        params = _extract_parameters(code)
        assert params == {"NUM_HOLES": 8}
        assert isinstance(params["NUM_HOLES"], int)

    def test_stops_at_non_param(self):
        code = "OD = 200\nbody = Part.makeCylinder(OD/2, 100)\nHEIGHT = 360"
        params = _extract_parameters(code)
        assert params == {"OD": 200}

    def test_comment_lines_skipped(self):
        code = "# Design parameters\nOD = 200\n# Second comment\nHEIGHT = 360\nbody = Part.makeBox(OD, HEIGHT, 10)"
        params = _extract_parameters(code)
        assert params == {"OD": 200, "HEIGHT": 360}

    def test_no_params(self):
        code = "body = Part.makeCylinder(100, 360)\nprint(body)"
        params = _extract_parameters(code)
        assert params == {}

    def test_empty_code(self):
        assert _extract_parameters("") == {}

    def test_only_comments(self):
        code = "# Just comments\n# No actual code"
        assert _extract_parameters(code) == {}

    def test_lowercase_not_matched(self):
        code = "od = 200\nheight = 360"
        params = _extract_parameters(code)
        assert params == {}

    def test_mixed_case_only_upper(self):
        code = "OD = 200\ninner_r = 50\nWALL_T = 12"
        params = _extract_parameters(code)
        assert params == {"OD": 200}

    def test_negative_value(self):
        code = "OFFSET = -10\nresult = OFFSET + 20"
        params = _extract_parameters(code)
        assert params == {"OFFSET": -10}

    def test_underscore_in_name(self):
        code = "FLANGE_RADIUS = 125\nNUM_BOLT_HOLES = 8\nresult = FLANGE_RADIUS"
        params = _extract_parameters(code)
        assert params == {"FLANGE_RADIUS": 125, "NUM_BOLT_HOLES": 8}

    def test_param_with_expression_not_matched(self):
        code = "OD = 100 + 50\nresult = OD"
        params = _extract_parameters(code)
        assert params == {}


class TestSessionParameters:
    def test_init_has_parameters(self):
        from core.session import ChatSession
        s = ChatSession()
        assert s.parameters == {}
        assert s.parametric_code == ""

    def test_serialization_round_trip(self):
        from core.session import ChatSession
        s = ChatSession()
        s.parameters = {"OD": 200, "HEIGHT": 360}
        s.parametric_code = "OD = 200\nHEIGHT = 360\nbody = Part.makeCylinder(OD/2, HEIGHT)"
        s.set_system_prompt("sys")

        d = s.to_dict()
        assert d["parameters"] == {"OD": 200, "HEIGHT": 360}
        assert d["parametric_code"] == "OD = 200\nHEIGHT = 360\nbody = Part.makeCylinder(OD/2, HEIGHT)"

        s2 = ChatSession.from_dict(d)
        assert s2.parameters == {"OD": 200, "HEIGHT": 360}
        assert s2.parametric_code == "OD = 200\nHEIGHT = 360\nbody = Part.makeCylinder(OD/2, HEIGHT)"

    def test_deserialize_missing_fields(self):
        from core.session import ChatSession
        d = {"session_id": "abc", "messages": []}
        s = ChatSession.from_dict(d)
        assert s.parameters == {}
        assert s.parametric_code == ""

    def test_clear_resets_parameters(self):
        from core.session import ChatSession
        s = ChatSession()
        s.parameters = {"OD": 200}
        s.parametric_code = "OD = 200"
        s.set_system_prompt("sys")
        s.clear()
        assert s.parameters == {}
        assert s.parametric_code == ""

    def test_clear_preserves_system_prompt_with_params(self):
        from core.session import ChatSession
        s = ChatSession()
        s.set_system_prompt("sys")
        s.parameters = {"OD": 200}
        s.parametric_code = "OD = 200"
        s.clear()
        assert len(s.messages) == 1
        assert s.messages[0]["role"] == "system"


# ---------------------------------------------------------------------------
# Tests for loop-temporary filtering in get_persistent_vars
# Replicate the pure logic here to avoid importing agent/tools.py (FreeCAD).
# ---------------------------------------------------------------------------

_LOOP_TEMPORARY_NAMES = frozenset({
    "i", "j", "k", "n", "idx", "count",
    "x", "y", "z", "dx", "dy", "dz",
    "r", "t", "angle", "s",
})

_PERSISTABLE_TYPES = (int, float, str, bool, type(None))


def _filter_persistent_vars(namespace: dict) -> dict:
    """Replica of get_persistent_vars filtering logic."""
    return {
        k: v for k, v in namespace.items()
        if isinstance(v, _PERSISTABLE_TYPES) and k not in _LOOP_TEMPORARY_NAMES
    }


class TestPersistentVarsFilter:
    def test_excludes_loop_temporaries(self):
        ns = {"i": 1, "x": 2.0, "angle": 45, "t": 0.5, "r": 10}
        result = _filter_persistent_vars(ns)
        assert result == {}

    def test_includes_named_vars(self):
        ns = {"outer_radius": 40.0, "cup_height": 100, "wall_thickness": 2.5}
        result = _filter_persistent_vars(ns)
        assert result == ns

    def test_mixed_vars_filters_only_temporaries(self):
        ns = {
            "outer_radius": 40.0,
            "i": 3,
            "height": 100,
            "angle": 1.57,
            "base_thickness": 5,
            "z": 10.0,
        }
        result = _filter_persistent_vars(ns)
        assert result == {"outer_radius": 40.0, "height": 100, "base_thickness": 5}

    def test_excludes_non_persistable_types(self):
        ns = {"outer_radius": 40.0, "shape": object(), "data": [1, 2, 3]}
        result = _filter_persistent_vars(ns)
        assert result == {"outer_radius": 40.0}

    def test_empty_namespace(self):
        assert _filter_persistent_vars({}) == {}

    def test_all_temporaries_filtered(self):
        ns = {k: 1 for k in _LOOP_TEMPORARY_NAMES}
        assert _filter_persistent_vars(ns) == {}
