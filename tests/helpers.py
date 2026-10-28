"""Shared test helpers — module loading, sys.modules mocking, config reload.

These deduplicate the bootstrap patterns that were previously copy-pasted
across the test files (S0-E1) and provide the .env-isolated config reload
used to decouple config tests from the developer's real .env (S0-E3).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every environment key core/config.py reads. Keep in sync with
# core/config.py `_CFG_DEFAULTS` plus the four int-only keys parsed in
# Config.refresh().
_CONFIG_ENV_KEYS = (
    "API_BASE_URL", "API_KEY", "MODEL_NAME", "MAX_TOKENS", "TEMPERATURE",
    "VISION_API_BASE_URL", "VISION_API_KEY", "VISION_MODEL_NAME",
    "VISION_MAX_TOKENS", "VISION_TEMPERATURE", "VISION_TIMEOUT",
    "MAX_ITERATIONS", "MAX_SNAPSHOTS", "MAX_CONTEXT_TOKENS", "LLM_TIMEOUT",
)


def load_module(name: str, *relparts: str):
    """Load a source file as an isolated module (pattern-B dedupe).

    Equivalent to the previous per-file spec_from_file_location blocks::

        mod = load_module("text_utils", "core", "text_utils.py")
    """
    path = os.path.normpath(os.path.join(PROJECT_ROOT, *relparts))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_sys_modules(mapping: dict) -> dict:
    """Install mock modules into sys.modules. Returns the saved originals."""
    saved = {k: sys.modules.get(k) for k in mapping}
    sys.modules.update(mapping)
    return saved


def restore_sys_modules(saved: dict) -> None:
    """Restore sys.modules entries saved by install_sys_modules.

    Preserves the original semantics: a key that did not exist before is
    popped, not set to None.
    """
    for key, orig in saved.items():
        if orig is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = orig


def load_tools_module():
    """Load agent/tools.py with FreeCAD/FreeCADGui/Part/PySide6 mocked.

    Installs MagicMock substitutes, spec-loads tools.py under the module
    name "tools" (its `from agent.cad_helpers import ...` then resolves
    against the mocked FreeCAD), and restores sys.modules immediately —
    the returned module keeps bound references to the mocks.

    Returns (tools_module, freecad_mock, freecadgui_mock).
    """
    from unittest.mock import MagicMock

    mock_freecad = MagicMock()
    mock_freecad.ActiveDocument = MagicMock()
    mock_freecad.ActiveDocument.Objects = []
    mock_freecad.newDocument = MagicMock(return_value=mock_freecad.ActiveDocument)

    mock_freecadgui = MagicMock()
    mock_freecadgui.activeDocument = MagicMock(return_value=None)

    mock_part = MagicMock()
    mock_pyside6 = MagicMock()

    saved = install_sys_modules({
        "FreeCAD": mock_freecad,
        "FreeCADGui": mock_freecadgui,
        "Part": mock_part,
        "PySide6": mock_pyside6,
    })
    try:
        mod = load_module("tools", "agent", "tools.py")
    finally:
        restore_sys_modules(saved)
    return mod, mock_freecad, mock_freecadgui


def reload_config(env: dict | None = None):
    """Reload core.config with the repo .env hidden and env vars controlled.

    Decouples config assertions from the developer's real .env (S0-E3):

    - env=None → all config keys are removed from os.environ before the
      reload, so module attributes reflect built-in defaults.
    - env=dict → exactly these keys are set (values str()-ed); all other
      config keys are removed.

    The repo-root .env is hidden from os.path.isfile for the duration of
    the reload (other paths delegate to the real isfile). os.environ is
    restored afterwards; the reloaded core.config module keeps the values
    it derived — same residual behavior as the previous per-test reloads.
    """
    import core.config as _cfg_mod

    dotenv = os.path.normpath(os.path.join(PROJECT_ROOT, ".env"))
    real_isfile = os.path.isfile

    def _hidden_isfile(path):
        if os.path.normpath(path) == dotenv:
            return False
        return real_isfile(path)

    saved_env = {k: os.environ.get(k) for k in _CONFIG_ENV_KEYS}
    try:
        for k in _CONFIG_ENV_KEYS:
            os.environ.pop(k, None)
        if env:
            for k, v in env.items():
                os.environ[k] = str(v)
        os.path.isfile = _hidden_isfile
        importlib.reload(_cfg_mod)
    finally:
        os.path.isfile = real_isfile
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return _cfg_mod
