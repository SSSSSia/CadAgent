"""Tests for core/paths.py — data root resolution and one-time migration (S4)."""
from __future__ import annotations

import os
import sys

import core.paths as paths


class TestDataRoot:
    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CADAGENT_DATA_DIR", str(tmp_path))
        assert paths.data_root() == str(tmp_path)

    def test_fallback_home_without_freecad(self, monkeypatch):
        monkeypatch.delenv("CADAGENT_DATA_DIR", raising=False)
        # No FreeCAD in the test interpreter
        root = paths.data_root()
        assert root.endswith(".cadagent") or "CadAgent" in root

    def test_subdir_creates_directory(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CADAGENT_DATA_DIR", str(tmp_path))
        sub = paths.subdir("sessions")
        assert sub == str(tmp_path / "sessions")
        assert os.path.isdir(sub)


class TestMigration:
    def _setup(self, monkeypatch, tmp_path):
        """Point the install root at a fake tree and reset the one-shot flag."""
        monkeypatch.setenv("CADAGENT_DATA_DIR", str(tmp_path / "data"))
        fake_install = tmp_path / "install"
        for name in ("sessions", "snapshots", "log"):
            d = fake_install / name
            d.mkdir(parents=True)
            (d / f"old_{name}.file").write_text("data")
        monkeypatch.setattr(paths, "_install_root", lambda: str(fake_install))
        monkeypatch.setattr(paths, "_MIGRATION_DONE", False, raising=False)

    def test_migrates_once_into_empty_destination(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        paths.subdir("sessions")  # triggers migration
        assert (tmp_path / "data" / "sessions" / "old_sessions.file").exists()
        assert (tmp_path / "data" / "snapshots" / "old_snapshots.file").exists()
        assert (tmp_path / "data" / "log" / "old_log.file").exists()

    def test_migration_runs_only_once(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        paths.subdir("sessions")
        # Add a NEW file to the fake install dir after the first migration
        (tmp_path / "install" / "sessions" / "late.file").write_text("x")
        paths.subdir("sessions")  # second call — migration must not re-run
        assert not (tmp_path / "data" / "sessions" / "late.file").exists()

    def test_non_empty_destination_not_touched(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        # Destination already has data — no mixing
        (tmp_path / "data" / "sessions").mkdir(parents=True)
        (tmp_path / "data" / "sessions" / "existing.file").write_text("mine")
        paths.subdir("sessions")
        assert (tmp_path / "data" / "sessions" / "existing.file").exists()
        assert not (tmp_path / "data" / "sessions" / "old_sessions.file").exists()

    def test_source_never_modified(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        paths.subdir("sessions")
        assert (tmp_path / "install" / "sessions" / "old_sessions.file").exists()


class TestDataRootMockGuard:
    """S7: a mocked FreeCAD (MagicMock) must fall back to ~/.cadagent —
    its __fspath__ satisfies os.path.join and makedirs used to build junk
    directories (MagicMock/mock.getUserAppDataDir()) in the CWD."""

    def test_mock_freecad_falls_back_to_home(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        monkeypatch.delenv("CADAGENT_DATA_DIR", raising=False)
        saved = sys.modules.get("FreeCAD")
        sys.modules["FreeCAD"] = MagicMock()
        try:
            root = paths.data_root()
            assert root == os.path.join(os.path.expanduser("~"), ".cadagent")
            # And subdir must never create directories in the CWD
            before = set(os.listdir(os.getcwd()))
            paths.subdir("log")
            assert set(os.listdir(os.getcwd())) == before
        finally:
            if saved is None:
                sys.modules.pop("FreeCAD", None)
            else:
                sys.modules["FreeCAD"] = saved
