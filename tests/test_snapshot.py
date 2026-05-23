"""Tests for core/snapshot.py — SnapshotManager class and module-level API."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load snapshot module without FreeCAD dependency.
# The module-level convenience functions delegate to a default SnapshotManager.
_spec = importlib.util.spec_from_file_location(
    "snapshot",
    os.path.join(os.path.dirname(__file__), "..", "core", "snapshot.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SnapshotManager = _mod.SnapshotManager


# ---- Fresh manager state ----

def test_new_manager_has_no_snapshots():
    m = SnapshotManager()
    assert not m.has_snapshot()
    assert m.count() == 0


def test_pop_empty_returns_none():
    m = SnapshotManager()
    assert m.pop() is None


def test_cleanup_all_on_empty_is_noop():
    m = SnapshotManager()
    m.cleanup_all()  # should not raise
    assert m.count() == 0


def test_counter_starts_at_zero():
    m = SnapshotManager()
    assert m._counter == 0


def test_orphan_cleaned_starts_false():
    m = SnapshotManager()
    assert not m._orphan_cleaned


def test_max_snapshots_default():
    m = SnapshotManager()
    import core.config as cfg
    assert m._max_snapshots == cfg.MAX_SNAPSHOTS


def test_max_snapshots_custom():
    m = SnapshotManager(max_snapshots=3)
    assert m._max_snapshots == 3


# ---- take() without FreeCAD ----

def test_take_no_freecad_returns_none():
    m = SnapshotManager()
    assert m.take() is None


def test_take_no_freecad_does_not_change_counter():
    m = SnapshotManager()
    m.take()
    assert m._counter == 0


# ---- restore_latest edge cases ----

def test_restore_latest_empty_returns_error():
    m = SnapshotManager()
    # Requires FreeCAD import but will fail before that on empty stack
    result = m.restore_latest()
    assert result.startswith("ERROR")


# ---- _cleanup_old enforces limit ----

def test_cleanup_old_enforces_limit():
    m = SnapshotManager(max_snapshots=3)
    # Create temp files and add entries manually
    tmpdir = tempfile.mkdtemp()
    files = []
    for i in range(5):
        path = os.path.join(tmpdir, f"snap_{i}.FCStd")
        with open(path, "w") as f:
            f.write(f"snapshot {i}")
        m._stack.append({
            "path": path,
            "doc_name": "test_doc",
            "original_path": "",
            "time": float(i),
        })
        files.append(path)

    assert m.count() == 5
    m._cleanup_old()
    assert m.count() == 3

    # Oldest 2 files should be deleted
    assert not os.path.isfile(files[0])
    assert not os.path.isfile(files[1])
    # Remaining 3 should exist
    assert os.path.isfile(files[2])
    assert os.path.isfile(files[3])
    assert os.path.isfile(files[4])

    # Cleanup
    for f in files[2:]:
        os.remove(f)
    os.rmdir(tmpdir)


# ---- cleanup_all clears everything ----

def test_cleanup_all_clears_stack():
    m = SnapshotManager(max_snapshots=10)
    tmpdir = tempfile.mkdtemp()
    for i in range(3):
        path = os.path.join(tmpdir, f"snap_{i}.FCStd")
        with open(path, "w") as f:
            f.write(f"snapshot {i}")
        m._stack.append({
            "path": path,
            "doc_name": "test_doc",
            "original_path": "",
            "time": float(i),
        })

    assert m.count() == 3
    m.cleanup_all()
    assert m.count() == 0
    assert m._counter == 0

    # Files should be deleted
    for i in range(3):
        assert not os.path.isfile(os.path.join(tmpdir, f"snap_{i}.FCStd"))
    os.rmdir(tmpdir)


# ---- Module-level API delegates to default manager ----

def test_module_level_functions_exist():
    assert callable(_mod.take_snapshot)
    assert callable(_mod.has_snapshot)
    assert callable(_mod.snapshot_count)
    assert callable(_mod.pop_snapshot)
    assert callable(_mod.restore_latest_snapshot)
    assert callable(_mod.cleanup_all_snapshots)


def test_default_manager_is_snapshot_manager():
    assert isinstance(_mod._default_manager, SnapshotManager)


def test_module_has_snapshot_empty():
    assert not _mod.has_snapshot()


def test_module_snapshot_count():
    assert _mod.snapshot_count() == 0
