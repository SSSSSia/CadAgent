"""Tests for core/snapshot.py — SnapshotManager class and module-level API."""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from tests.helpers import install_sys_modules, load_module, restore_sys_modules

# Load snapshot module without FreeCAD dependency.
# The module-level convenience functions delegate to a default SnapshotManager.
_mod = load_module("snapshot", "core", "snapshot.py")

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


def test_orphan_flag_is_module_level():
    # S4-C5: the once-per-process flag lives on the module, not the manager
    assert hasattr(_mod, "_ORPHAN_CLEANED")


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
        m._stacks.setdefault("test_doc", []).append({
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
        m._stacks.setdefault("test_doc", []).append({
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
        m._stacks.setdefault("test_doc", []).append({
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
    m._stacks.setdefault("test_doc", []).append({
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
    m._stacks.setdefault("test_doc", []).append({
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
    m._stacks.setdefault("test_doc", []).append({
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


# ---- take() snapshot save semantics (S1-C1) ----

class TestTakeSaveSemantics:
    """take() must not disturb the live document (saveCopy preferred)."""

    def _make_doc(self):
        """Fake FreeCAD document emulating real saveAs side effects.

        saveAs rewrites FileName to the target and renames Label to the
        file basename (verified against FreeCAD 1.1.1); saveCopy leaves
        the document untouched.
        """
        from unittest.mock import MagicMock

        doc = MagicMock()
        doc.Name = "user_part"
        doc.Label = "My Bracket"
        doc.FileName = r"C:\work\user_part.FCStd"

        def _fake_save_as(path):
            doc.FileName = path
            doc.Label = os.path.splitext(os.path.basename(path))[0]

        doc.saveAs.side_effect = _fake_save_as
        return doc

    def _take(self, m, doc):
        """Run take(doc) with a FreeCAD mock installed and a temp snap dir."""
        from unittest.mock import MagicMock

        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": MagicMock()})
        try:
            path = m.take(doc)
        finally:
            restore_sys_modules(saved)
        return path, tmpdir

    def test_take_prefers_savecopy_and_leaves_doc_untouched(self):
        m = SnapshotManager()
        doc = self._make_doc()
        path, tmpdir = self._take(m, doc)

        doc.saveCopy.assert_called_once_with(path)
        doc.saveAs.assert_not_called()
        assert doc.FileName == r"C:\work\user_part.FCStd"
        assert doc.Label == "My Bracket"
        os.rmdir(tmpdir)  # saveCopy fake wrote nothing

    def test_take_fallback_restores_filename_and_label(self):
        m = SnapshotManager()
        doc = self._make_doc()
        del doc.saveCopy  # legacy FreeCAD without saveCopy
        path, tmpdir = self._take(m, doc)

        doc.saveAs.assert_called_once_with(path)
        # saveAs side effect fired, then take() restored both attributes
        assert doc.FileName == r"C:\work\user_part.FCStd"
        assert doc.Label == "My Bracket"
        os.rmdir(tmpdir)

    def test_take_entry_records_original_label(self):
        m = SnapshotManager()
        doc = self._make_doc()
        path, tmpdir = self._take(m, doc)

        entry = m._stacks["user_part"][-1]
        assert entry["original_path"] == r"C:\work\user_part.FCStd"
        assert entry["original_label"] == "My Bracket"
        assert entry["doc_name"] == "user_part"
        os.rmdir(tmpdir)


# ---- restore_latest() untitled-document save hijack (S1-C2) ----

class TestRestoreFileName:
    """restore_latest() must never leave FileName pointing at the snapshot."""

    def _run_restore(self, entry_extra):
        from unittest.mock import MagicMock

        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        snap_path = os.path.join(tmpdir, "user_part_0001_ab12cd_1748000000.FCStd")
        with open(snap_path, "w") as f:
            f.write("snap")

        # Emulate openDocument: names the doc after the snapshot basename
        # and points FileName at the snapshot file.
        restored = MagicMock()
        restored.Name = os.path.splitext(os.path.basename(snap_path))[0]
        restored.Label = restored.Name
        restored.FileName = snap_path

        fc = MagicMock()
        fc.ActiveDocument.Name = restored.Name
        fc.openDocument = MagicMock(return_value=restored)
        fcgui = MagicMock()
        fcgui.activeDocument.return_value = None

        m._stacks.setdefault("test_doc", []).append({
            "path": snap_path,
            "doc_name": restored.Name,
            "original_path": "",
            "original_label": "My Bracket",
            "session_id": None,
            "time": 0.0,
            **entry_extra,
        })
        saved = install_sys_modules({"FreeCAD": fc, "FreeCADGui": fcgui})
        try:
            result = m.restore_latest()
        finally:
            restore_sys_modules(saved)
        return result, restored, tmpdir

    def test_untitled_doc_restore_resets_filename(self):
        """Untitled doc: FileName must be reset to '' so Ctrl+S opens Save As."""
        result, restored, tmpdir = self._run_restore({})
        assert result.startswith("SUCCESS")
        assert restored.FileName == ""
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_titled_doc_restore_restores_filename(self):
        result, restored, tmpdir = self._run_restore(
            {"original_path": r"C:\work\user_part.FCStd"}
        )
        assert result.startswith("SUCCESS")
        assert restored.FileName == r"C:\work\user_part.FCStd"
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- restore_latest() Label restore + short session filename (S1-C3) ----

class TestRestoreLabelAndFilename:

    def test_restore_restores_original_label(self):
        """openDocument renames Label to the snapshot basename — restore it."""
        from unittest.mock import MagicMock

        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        snap_path = os.path.join(tmpdir, "user_part_0001_ab12cd_1748000000.FCStd")
        with open(snap_path, "w") as f:
            f.write("snap")

        restored = MagicMock()
        restored.Name = "user_part_0001_ab12cd_1748000000"
        restored.Label = restored.Name  # openDocument behavior
        restored.FileName = snap_path

        fc = MagicMock()
        fc.ActiveDocument.Name = restored.Name
        fc.openDocument = MagicMock(return_value=restored)
        fcgui = MagicMock()
        fcgui.activeDocument.return_value = None

        m._stacks.setdefault("test_doc", []).append({
            "path": snap_path,
            "doc_name": restored.Name,
            "original_path": "",
            "original_label": "My Bracket",
            "session_id": None,
            "time": 0.0,
        })
        saved = install_sys_modules({"FreeCAD": fc, "FreeCADGui": fcgui})
        try:
            result = m.restore_latest()
        finally:
            restore_sys_modules(saved)

        assert result.startswith("SUCCESS")
        assert restored.Label == "My Bracket"
        # Result string tells the LLM the new document identity
        assert "Name='user_part_0001_ab12cd_1748000000'" in result
        assert "Label='My Bracket'" in result
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_take_filename_uses_short_session_hash(self):
        """Session segment of the filename is capped at 6 hex chars."""
        from unittest.mock import MagicMock
        import re

        m = SnapshotManager()
        m.set_session_id("0c5b85877c95")  # 12 chars
        doc = MagicMock()
        doc.Name = "Model"
        doc.Label = "Model"
        doc.FileName = ""

        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": MagicMock()})
        try:
            path = m.take(doc)
        finally:
            restore_sys_modules(saved)

        fname = os.path.basename(path)
        expected_prefix = "Model_0001_" + "0c5b85877c95"[:6] + "_"
        assert fname.startswith(expected_prefix) and fname.endswith(".FCStd"), fname
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- S4: per-document stacks, unified lifecycle, disk cleanup ----

class _FakeFreeCAD:
    """FreeCAD stand-in with controllable open/close for restore tests."""

    def __init__(self):
        self.docs = {}
        self.opened_paths = []

    def listDocuments(self):
        return dict(self.docs)

    def openDocument(self, path):
        from unittest.mock import MagicMock
        doc = MagicMock()
        doc.Name = os.path.splitext(os.path.basename(path))[0]
        doc.Label = doc.Name
        doc.FileName = path
        self.docs[doc.Name] = doc
        self.opened_paths.append(path)
        return doc

    def closeDocument(self, name):
        self.docs.pop(name, None)


def _fake_doc(name):
    from unittest.mock import MagicMock
    doc = MagicMock()
    doc.Name = name
    doc.Label = name
    doc.FileName = ""
    doc.saveCopy.side_effect = lambda path: open(path, "wb").write(b"snap")
    return doc


def _install_fc(fake):
    from unittest.mock import MagicMock
    fcgui = MagicMock()
    fcgui.activeDocument.return_value = None
    return install_sys_modules({"FreeCAD": fake, "FreeCADGui": fcgui})


class TestPerDocumentStacks:

    def test_multi_doc_restore_order(self):
        fake = _FakeFreeCAD()
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": fake})
        try:
            p_a1 = m.take(_fake_doc("DocA"))
            p_b1 = m.take(_fake_doc("DocB"))
            p_a2 = m.take(_fake_doc("DocA"))
            assert m.count() == 3

            r1 = m.restore_latest()
            r2 = m.restore_latest()
            r3 = m.restore_latest()
        finally:
            restore_sys_modules(saved)
        assert r1.startswith("SUCCESS") and r2.startswith("SUCCESS") and r3.startswith("SUCCESS")
        # Newest first, per document: A2, B1, A1
        assert fake.opened_paths == [p_a2, p_b1, p_a1]
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_restore_deletes_file_on_success(self):
        fake = _FakeFreeCAD()
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": fake})
        try:
            path = m.take(_fake_doc("DocA"))
            assert os.path.isfile(path)
            result = m.restore_latest()
        finally:
            restore_sys_modules(saved)
        assert result.startswith("SUCCESS")
        assert not os.path.isfile(path)
        assert m.count() == 0
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_restore_missing_file_keeps_entry(self):
        fake = _FakeFreeCAD()
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": fake})
        try:
            path = m.take(_fake_doc("DocA"))
            os.remove(path)  # snapshot file vanished
            result = m.restore_latest()
        finally:
            restore_sys_modules(saved)
        assert result.startswith("ERROR")
        assert "not found" in result
        assert m.count() == 1  # entry kept, not silently dropped
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestLifecycleInvariants:

    def test_fifty_take_restore_cycles_leave_no_files(self):
        """S4 exit criteria: files on disk == entries in stacks."""
        fake = _FakeFreeCAD()
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": fake})
        try:
            for _ in range(50):
                m.take(_fake_doc("DocA"))
                m.take(_fake_doc("DocB"))
                assert m.restore_latest().startswith("SUCCESS")
                assert m.restore_latest().startswith("SUCCESS")
        finally:
            restore_sys_modules(saved)
        assert m.count() == 0
        files = [f for f in os.listdir(tmpdir) if f.endswith(".FCStd")]
        assert files == []
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cap_evicts_oldest_across_docs(self):
        fake = _FakeFreeCAD()
        m = SnapshotManager(max_snapshots=5)
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        saved = install_sys_modules({"FreeCAD": fake})
        try:
            for i in range(8):
                m.take(_fake_doc("DocA" if i % 2 else "DocB"))
        finally:
            restore_sys_modules(saved)
        assert m.count() == 5
        files = [f for f in os.listdir(tmpdir) if f.endswith(".FCStd")]
        assert len(files) == 5  # file presence == stack membership
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestSessionDiskCleanup:

    def test_disk_sweep_matches_hash_segment_only(self):
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        match = os.path.join(tmpdir, "DocA_0001_aaaabb_1000000000.FCStd")
        other = os.path.join(tmpdir, "DocA_0002_cccdef_1000000000.FCStd")
        legacy = os.path.join(tmpdir, "DocA_0003_1000000000.FCStd")
        for p in (match, other, legacy):
            with open(p, "w") as f:
                f.write("x")

        removed = m.cleanup_for_session("aaaabbbbcccc")

        assert removed == 1
        assert not os.path.isfile(match)
        assert os.path.isfile(other)      # other session preserved
        assert os.path.isfile(legacy)     # legacy (no session) preserved
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_empty_session_id_noop(self):
        m = SnapshotManager()
        assert m.cleanup_for_session("") == 0


class TestOrphanRetry:

    def test_failed_scan_retries_later(self):
        m = SnapshotManager()
        tmpdir = tempfile.mkdtemp()
        m.get_snapshot_dir = lambda: tmpdir
        old_path = os.path.join(tmpdir, "old_orphan.FCStd")
        with open(old_path, "w") as f:
            f.write("old")
        two_hours_ago = time.time() - 7200
        os.utime(old_path, (two_hours_ago, two_hours_ago))

        # Direct flag control (not monkeypatch): undo() would restore the
        # pre-test True from earlier tests in the same process.
        _mod._ORPHAN_CLEANED = False

        def failing_listdir(path):
            raise OSError("directory locked")
        real_listdir = os.listdir
        os.listdir = failing_listdir
        try:
            m.cleanup_orphans()
        finally:
            os.listdir = real_listdir
        assert _mod._ORPHAN_CLEANED is False   # flag set only after success
        assert os.path.isfile(old_path)

        m.cleanup_orphans()  # retry now succeeds
        assert _mod._ORPHAN_CLEANED is True
        assert not os.path.isfile(old_path)
        shutil.rmtree(tmpdir, ignore_errors=True)
