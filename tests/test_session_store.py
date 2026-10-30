"""Tests for core/session_store.py — save/load/list/delete + B22 id validation.

First test coverage for the store (S6-B22); uses CADAGENT_DATA_DIR to point
the data root at a tmp dir (S4 paths design for test injection).
"""
from __future__ import annotations

import json
import os

from tests.helpers import load_module

_mod = load_module("session_store", "core", "session_store.py")
SessionStore = _mod.SessionStore

from core.session import ChatSession  # noqa: E402 — pure stdlib module


def _make_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CADAGENT_DATA_DIR", str(tmp_path))
    return SessionStore()


def _session_with_message(sid=None, msg="hello"):
    s = ChatSession()
    if sid:
        s.session_id = sid
    s.messages.append({"role": "user", "content": msg})
    return s


class TestRoundTrip:

    def test_save_and_load(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        s = _session_with_message(msg="design a flange")
        path = store.save(s)
        assert path and os.path.isfile(path)

        loaded = store.load(s.session_id)
        assert loaded is not None
        assert loaded.session_id == s.session_id
        assert loaded.messages[-1]["content"] == "design a flange"

    def test_save_empty_session_id_returns_path(self, tmp_path, monkeypatch):
        """save() is called by our own code with generated ids — just pin
        that a 12-hex id round-trips through save (no format gate on save)."""
        store = _make_store(tmp_path, monkeypatch)
        s = _session_with_message(sid="0123456789ab")
        assert store.save(s)
        assert store.load("0123456789ab") is not None


class TestSessionIdValidation:
    """B22: load/delete reject ids that don't match the generated format
    before touching the filesystem (blocks path traversal)."""

    BAD_IDS = [
        "",
        "abc",                       # too short
        "aaaaaaaaaaaaa",             # 13 chars
        "AAAAAAAAAAAA",              # uppercase (uuid4().hex is lowercase)
        "../evil",                   # traversal
        "..\\evil",                  # traversal (windows)
        "aaaa.aaaa",                 # extension injection
        "zzzzzzzzzzzz",              # non-hex
        None,
    ]

    def test_load_rejects_bad_ids(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        for bad in self.BAD_IDS:
            assert store.load(bad) is None, f"load({bad!r}) should be None"

    def test_delete_rejects_bad_ids(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        for bad in self.BAD_IDS:
            assert store.delete(bad) is False, f"delete({bad!r}) should be False"

    def test_traversal_creates_no_files(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        store.load("../evil")
        store.delete("../evil")
        assert os.listdir(str(tmp_path)) == ["sessions"]

    def test_valid_but_missing_id_returns_none(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        assert store.load("0123456789ab") is None


class TestListAndDelete:

    def _write_session_file(self, store, sid, created_at, summary=""):
        data = {
            "session_id": sid,
            "created_at": created_at,
            "summary": summary,
            "messages": [{"role": "user", "content": "x"}],
        }
        path = os.path.join(store._dir, f"{sid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_list_sorted_descending(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        self._write_session_file(store, "aaaaaaaaaaaa", "2026-01-01T10:00:00")
        self._write_session_file(store, "bbbbbbbbbbbb", "2026-01-02T10:00:00")
        ids = [s["session_id"] for s in store.list_sessions()]
        assert ids == ["bbbbbbbbbbbb", "aaaaaaaaaaaa"]

    def test_list_corrupt_timestamp_sorts_oldest(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        self._write_session_file(store, "aaaaaaaaaaaa", "2026-01-01T10:00:00")
        self._write_session_file(store, "bbbbbbbbbbbb", "not-a-timestamp")
        ids = [s["session_id"] for s in store.list_sessions()]
        # Corrupt timestamp degrades to "" (oldest) — stable, never interleaved
        assert ids == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]

    def test_list_skips_corrupt_json(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        self._write_session_file(store, "aaaaaaaaaaaa", "2026-01-01T10:00:00")
        with open(os.path.join(store._dir, "broken.json"), "w") as f:
            f.write("{not json")
        ids = [s["session_id"] for s in store.list_sessions()]
        assert ids == ["aaaaaaaaaaaa"]

    def test_load_corrupt_json_returns_none(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        with open(os.path.join(store._dir, "aaaaaaaaaaaa.json"), "w") as f:
            f.write("{not json")
        assert store.load("aaaaaaaaaaaa") is None

    def test_delete_existing_then_missing(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        path = self._write_session_file(store, "aaaaaaaaaaaa", "2026-01-01T10:00:00")
        assert store.delete("aaaaaaaaaaaa") is True
        assert not os.path.exists(path)
        assert store.delete("aaaaaaaaaaaa") is False


class TestSaveIfNotEmpty:

    def test_skips_session_without_user_message(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        s = ChatSession()
        s.messages.append({"role": "assistant", "content": "hi"})
        assert store.save_if_not_empty(s) == ""
        assert os.listdir(store._dir) == []

    def test_saves_session_with_user_message(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        s = _session_with_message()
        assert store.save_if_not_empty(s)
        assert store.load(s.session_id) is not None
