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


# ---- Session ID support ----

def test_session_id_defaults_none():
    m = SnapshotManager()
    assert m._session_id is None


def test_set_session_id():
    m = SnapshotManager()
    m.set_session_id("abc123")
    assert m._session_id == "abc123"


def test_set_session_id_none_resets():
    m = SnapshotManager()
    m.set_session_id("abc123")
    m.set_session_id(None)
    assert m._session_id is None


def test_cleanup_for_session_removes_matching():
    m = SnapshotManager(max_snapshots=10)
    tmpdir = tempfile.mkdtemp()
    # Add entries for session "aaa"
    for i in range(3):
        path = os.path.join(tmpdir, f"snap_aaa_{i}.FCStd")
        with open(path, "w") as f:
            f.write(f"snapshot {i}")
        m._stack.append({
            "path": path,
            "doc_name": "test_doc",
            "original_path": "",
            "session_id": "aaa",
            "time": float(i),
        })
    # Add entry for session "bbb"
    path_b = os.path.join(tmpdir, f"snap_bbb_0.FCStd")
    with open(path_b, "w") as f:
        f.write("snapshot b")
    m._stack.append({
        "path": path_b,
        "doc_name": "test_doc",
        "original_path": "",
        "session_id": "bbb",
        "time": 10.0,
    })
    # Add legacy entry (no session_id)
    path_legacy = os.path.join(tmpdir, f"snap_legacy.FCStd")
    with open(path_legacy, "w") as f:
        f.write("legacy snapshot")
    m._stack.append({
        "path": path_legacy,
        "doc_name": "test_doc",
        "original_path": "",
        "session_id": None,
        "time": 0.0,
    })

    assert m.count() == 5
    removed = m.cleanup_for_session("aaa")
    assert removed == 3
    assert m.count() == 2

    # aaa files should be deleted
    for i in range(3):
        assert not os.path.isfile(os.path.join(tmpdir, f"snap_aaa_{i}.FCStd"))
    # bbb and legacy should survive
    assert os.path.isfile(path_b)
    assert os.path.isfile(path_legacy)

    # Cleanup
    for p in [path_b, path_legacy]:
        os.remove(p)
    os.rmdir(tmpdir)


def test_cleanup_for_session_preserves_no_id_entries():
    m = SnapshotManager(max_snapshots=10)
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "snap_old.FCStd")
    with open(path, "w") as f:
        f.write("old snapshot")
    m._stack.append({
        "path": path,
        "doc_name": "test_doc",
        "original_path": "",
        "session_id": None,
        "time": 0.0,
    })
    removed = m.cleanup_for_session("some_session")
    assert removed == 0
    assert m.count() == 1
    assert os.path.isfile(path)
    os.remove(path)
    os.rmdir(tmpdir)


def test_cleanup_for_session_nonexistent_id():
    m = SnapshotManager()
    removed = m.cleanup_for_session("nonexistent")
    assert removed == 0


# ---- Module-level session functions ----

def test_module_set_snapshot_session_id():
    _mod.set_snapshot_session_id("test123")
    assert _mod._default_manager._session_id == "test123"
    _mod.set_snapshot_session_id(None)  # reset


def test_module_cleanup_session_snapshots():
    assert callable(_mod.cleanup_session_snapshots)


# ---- Orphan cleanup threshold ----

def test_cleanup_orphans_default_1h():
    m = SnapshotManager()
    tmpdir = tempfile.mkdtemp()
    # Create a file "older" than 1 hour by backdating mtime
    import time as _time
    old_path = os.path.join(tmpdir, "old_orphan.FCStd")
    with open(old_path, "w") as f:
        f.write("old")
    # Set mtime to 2 hours ago
    two_hours_ago = _time.time() - 7200
    os.utime(old_path, (two_hours_ago, two_hours_ago))

    # Create a recent file (should survive)
    recent_path = os.path.join(tmpdir, "recent_orphan.FCStd")
    with open(recent_path, "w") as f:
        f.write("recent")

    # Override get_snapshot_dir to use tmpdir
    m.get_snapshot_dir = lambda: tmpdir
    m.cleanup_orphans()

    assert not os.path.isfile(old_path)   # >1h old, removed
    assert os.path.isfile(recent_path)     # recent, kept

    os.remove(recent_path)
    os.rmdir(tmpdir)
