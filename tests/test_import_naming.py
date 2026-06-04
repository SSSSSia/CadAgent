"""Tests for official FreeCAD naming convention — no aliases allowed.

Enforces that source files never use 'import FreeCADGui as Gui',
'import FreeCAD as App', or bare 'Vector' in prompt examples.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_PY_DIRS = ["agent", "core", "ui"]


def _all_py_files():
    """Yield all .py source files in the project (excluding tests)."""
    for d in _PY_DIRS:
        dirpath = os.path.join(_ROOT, d)
        if not os.path.isdir(dirpath):
            continue
        for fname in os.listdir(dirpath):
            if fname.endswith(".py"):
                yield os.path.join(dirpath, fname)
    for f in ["InitGui.py"]:
        path = os.path.join(_ROOT, f)
        if os.path.isfile(path):
            yield path


def _read_all_prompts():
    """Load the prompts module and return all prompt strings."""
    spec = importlib.util.spec_from_file_location(
        "prompts",
        os.path.join(_ROOT, "agent", "prompts.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {
        "AGENT_SYSTEM_PROMPT": mod.AGENT_SYSTEM_PROMPT,
        "REACT_SYSTEM_PROMPT": mod.REACT_SYSTEM_PROMPT,
        "SYSTEM_PROMPT_NEW": mod.SYSTEM_PROMPT_NEW,
        "SYSTEM_PROMPT_MODIFY": mod.SYSTEM_PROMPT_MODIFY,
        "SYSTEM_PROMPT_DERIVE": mod.SYSTEM_PROMPT_DERIVE,
        "SYSTEM_PROMPT_VARIANT": mod.SYSTEM_PROMPT_VARIANT,
    }


class TestNoImportAliases:
    """No .py source file may use aliased imports."""

    def test_no_freecadgui_as_gui(self):
        for path in _all_py_files():
            with open(path, encoding="utf-8") as f:
                source = f.read()
            assert "import FreeCADGui as" not in source, (
                f"{path} contains 'import FreeCADGui as ...' "
                "— use 'import FreeCADGui' instead"
            )

    def test_no_freecad_as_app(self):
        for path in _all_py_files():
            with open(path, encoding="utf-8") as f:
                source = f.read()
            assert "import FreeCAD as App" not in source, (
                f"{path} contains 'import FreeCAD as App' "
                "— use 'import FreeCAD' instead"
            )


class TestPromptsOfficialNames:
    """Prompts must use official names, never aliases."""

    @pytest.mark.parametrize("name,prompt", list(_read_all_prompts().items()))
    def test_no_bare_vector_in_code_examples(self, name, prompt):
        for i, line in enumerate(prompt.split("\n"), 1):
            if not line or not line[0].isspace():
                continue
            if "Vector(" in line and "FreeCAD.Vector(" not in line:
                pytest.fail(
                    f"{name} line {i} has bare Vector(): {line.strip()}"
                )

    @pytest.mark.parametrize("name,prompt", list(_read_all_prompts().items()))
    def test_no_gui_in_available_modules(self, name, prompt):
        assert ", Gui," not in prompt, (
            f"{name} still lists bare 'Gui' in available modules list"
        )

    @pytest.mark.parametrize("name,prompt", list(_read_all_prompts().items()))
    def test_no_never_use_freecadgui(self, name, prompt):
        assert "NEVER use 'FreeCADGui'" not in prompt, (
            f"{name} still says NEVER use FreeCADGui"
        )
        assert 'NEVER use "FreeCADGui"' not in prompt, (
            f"{name} still says NEVER use FreeCADGui"
        )

    @pytest.mark.parametrize("name,prompt", list(_read_all_prompts().items()))
    def test_mentions_freecadgui_or_cq(self, name, prompt):
        assert "FreeCADGui" in prompt or "cq.Workplane" in prompt, (
            f"{name} mentions neither 'FreeCADGui' nor 'cq.Workplane' — "
            "should reference an official API"
        )
