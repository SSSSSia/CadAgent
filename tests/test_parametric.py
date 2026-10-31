"""Tests for parametric design features — parameter extraction and session storage.

S0-E2: TestExtractParameters and TestPersistentVarsFilter run against the
REAL agent/tools.py functions (loaded once with mocked FreeCAD), replacing
the former hand-copied replicas that could silently drift from production.
"""
from __future__ import annotations

from tests.helpers import load_tools_module

TOOLS, _FC_MOCK, _FCGUI_MOCK = load_tools_module()

_extract_parameters = TOOLS._extract_parameters


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
        assert s.code_history == []
        assert not hasattr(s, "parametric_code")  # placeholder removed (P12.2)

    def test_serialization_round_trip(self):
        from core.session import ChatSession
        s = ChatSession()
        s.parameters = {"OD": 200, "HEIGHT": 360}
        s.code_history = [("Model", "OD = 200" + chr(10) + "body = cq.Workplane('XY')"),
                          ("Model", "body = body.cut(hole)")]
        s.set_system_prompt("sys")

        d = s.to_dict()
        assert d["parameters"] == {"OD": 200, "HEIGHT": 360}
        assert d["code_history"] == [
            ["Model", "OD = 200" + chr(10) + "body = cq.Workplane('XY')"],
            ["Model", "body = body.cut(hole)"],
        ]

        s2 = ChatSession.from_dict(d)
        assert s2.parameters == {"OD": 200, "HEIGHT": 360}
        assert s2.code_history == [("Model", "OD = 200" + chr(10) + "body = cq.Workplane('XY')"),
                                   ("Model", "body = body.cut(hole)")]

    def test_deserialize_missing_fields(self):
        from core.session import ChatSession
        d = {"session_id": "abc", "messages": []}
        s = ChatSession.from_dict(d)
        assert s.parameters == {}
        assert s.code_history == []

    def test_deserialize_old_parametric_code_key_ignored(self):
        from core.session import ChatSession
        d = {"session_id": "abc", "messages": [],
             "parametric_code": "OD = 200"}  # legacy field — simply ignored
        s = ChatSession.from_dict(d)
        assert s.code_history == []

    def test_deserialize_malformed_history_entries_skipped(self):
        from core.session import ChatSession
        d = {"session_id": "abc", "messages": [],
             "code_history": [["ok", "x=1"], "garbage", [1, 2, 3], None]}
        s = ChatSession.from_dict(d)
        assert s.code_history == [("ok", "x=1")]

    def test_clear_resets_parameters(self):
        from core.session import ChatSession
        s = ChatSession()
        s.parameters = {"OD": 200}
        s.code_history = [("Model", "OD = 200")]
        s.set_system_prompt("sys")
        s.clear()
        assert s.parameters == {}
        assert s.code_history == []

    def test_clear_preserves_system_prompt_with_params(self):
        from core.session import ChatSession
        s = ChatSession()
        s.set_system_prompt("sys")
        s.parameters = {"OD": 200}
        s.code_history = [("Model", "OD = 200")]
        s.clear()
        assert len(s.messages) == 1
        assert s.messages[0]["role"] == "system"


# ---------------------------------------------------------------------------
# Tests for loop-temporary filtering in get_persistent_vars
# (real agent/tools.py functions, loaded with mocked FreeCAD)
# ---------------------------------------------------------------------------


def _filter_persistent_vars(namespace: dict) -> dict:
    """Run the real get_persistent_vars filter against the given namespace."""
    TOOLS.set_persistent_vars(namespace)
    try:
        return TOOLS.get_persistent_vars()
    finally:
        TOOLS.clear_persistent_vars()


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
        ns = {k: 1 for k in TOOLS._LOOP_TEMPORARY_NAMES}
        assert _filter_persistent_vars(ns) == {}


class TestFormatParamsLabel:
    """S7-F2: status-bar formatting for the extracted parameter store."""

    def test_empty_returns_empty_string(self):
        assert TOOLS.format_params_label({}) == ""

    def test_single_param(self):
        assert TOOLS.format_params_label({"OD": 200}) == "Params: OD=200"

    def test_three_params_shown(self):
        result = TOOLS.format_params_label(
            {"OD": 200, "H": 90, "T": 2.5}
        )
        assert result == "Params: OD=200, H=90, T=2.5"

    def test_extra_params_truncated_with_count(self):
        result = TOOLS.format_params_label(
            {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        )
        assert result == "Params: A=1, B=2, C=3 (+2 more)"

    def test_float_formatting(self):
        assert TOOLS.format_params_label({"TOL": 0.1}) == "Params: TOL=0.1"

    def test_custom_max_items(self):
        result = TOOLS.format_params_label({"A": 1, "B": 2}, max_items=1)
        assert result == "Params: A=1 (+1 more)"
