"""Central data-directory resolution for CadAgent user data (S4-C8/C9).

All user-generated data (sessions, snapshots, uploads, logs) lives under
ONE data root, resolved in priority order:

    1. $CADAGENT_DATA_DIR                     — tests / portable installs
    2. <FreeCAD user app data>/CadAgent       — normal FreeCAD installs
    3. ~/.cadagent                            — environments without FreeCAD

Older releases stored this data inside the install directory
(Mod/CadAgent/{sessions,snapshots,uploads,log}), which breaks read-only
and multi-user installs. migrate_from_install_dir() copies it to the
data root once per process (only into empty destination subdirs, never
deleting the source).
"""
from __future__ import annotations

import os
import shutil

_DATA_SUBDIRS = ("sessions", "snapshots", "uploads", "log")
_MIGRATION_DONE = False


def _install_root() -> str:
    """The CadAgent install directory (core/paths.py -> repo root)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_root() -> str:
    env = os.environ.get("CADAGENT_DATA_DIR")
    if env:
        return env
    try:
        import FreeCAD
        return os.path.join(FreeCAD.getUserAppDataDir(), "CadAgent")
    except (ImportError, AttributeError):
        pass
    return os.path.join(os.path.expanduser("~"), ".cadagent")


def subdir(name: str) -> str:
    """Return <data_root>/<name>, creating it. Never raises (OSError
    swallowed — callers like logger have their own fallbacks)."""
    migrate_from_install_dir()
    path = os.path.join(data_root(), name)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def migrate_from_install_dir() -> None:
    """One-time copy of install-dir data into the data root (S4-C8).

    Copies only when the destination subdir is empty; never deletes or
    modifies anything in the install directory. Runs at most once per
    process.
    """
    global _MIGRATION_DONE
    if _MIGRATION_DONE:
        return
    _MIGRATION_DONE = True
    install = _install_root()
    for name in _DATA_SUBDIRS:
        src = os.path.join(install, name)
        dst = os.path.join(data_root(), name)
        if not os.path.isdir(src):
            continue
        try:
            if os.path.isdir(dst) and os.listdir(dst):
                continue  # destination already has data — never mix
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(src):
                src_file = os.path.join(src, f)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, os.path.join(dst, f))
        except OSError:
            continue
