"""Tests for core/llm_client.py — retry semantics and SSE parsing (S2-B5/B6)."""
from __future__ import annotations

import io
import urllib.error

import core.llm_client as llm


def _http_error(code, headers=None):
    return urllib.error.HTTPError("https://x/y", code, "boom", headers or {}, None)


class TestRetrySemantics:

    def test_429_honors_retry_after_and_closes_response(self, monkeypatch):
        sleeps, closed, calls = [], [], []
        monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
        orig_close = urllib.error.HTTPError.close

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            err = _http_error(429, {"Retry-After": "7"})
            err.close = lambda: closed.append(429)
            raise err

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        try:
            llm._urlopen_with_retry(object(), timeout=5)
            raise AssertionError("should have raised")
        except urllib.error.HTTPError as e:
            assert e.code == 429
        assert len(calls) == llm._MAX_RETRIES + 1
        assert closed == [429, 429]      # socket closed before each retry
        assert sleeps == [7, 7]          # Retry-After beats backoff

    def test_500_without_header_uses_backoff(self, monkeypatch):
        sleeps, calls = [], []
        monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise _http_error(500)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        try:
            llm._urlopen_with_retry(object(), timeout=5)
            raise AssertionError("should have raised")
        except urllib.error.HTTPError:
            pass
        assert sleeps == [2.0, 4.0]

    def test_retry_after_capped_at_max_sleep(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(
                _http_error(429, {"Retry-After": "120"})
            ),
        )
        try:
            llm._urlopen_with_retry(object(), timeout=5)
            raise AssertionError("should have raised")
        except urllib.error.HTTPError:
            pass
        assert sleeps == [llm._RETRY_MAX_SLEEP, llm._RETRY_MAX_SLEEP]

    def test_404_raises_immediately_no_retry(self, monkeypatch):
        calls = []
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise _http_error(404)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        try:
            llm._urlopen_with_retry(object(), timeout=5)
            raise AssertionError("should have raised")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(calls) == 1  # non-retryable: never retried

    def test_transient_then_success(self, monkeypatch):
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
        marker = object()
        attempts = []

        def fake_urlopen(req, timeout=None):
            attempts.append(1)
            if len(attempts) < 2:
                raise _http_error(503)
            return marker

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        assert llm._urlopen_with_retry(object(), timeout=5) is marker
        assert len(attempts) == 2


class TestSseParsing:

    def _collect(self, lines, monkeypatch):
        body = b"\n".join(lines) + b"\n"
        monkeypatch.setattr(llm, "_make_request", lambda payload: object())
        monkeypatch.setattr(
            llm, "_urlopen_with_retry", lambda req, timeout: io.BytesIO(body)
        )
        return list(llm.call_llm_streaming([{"role": "user", "content": "x"}]))

    def test_no_space_data_and_no_space_done(self, monkeypatch):
        out = self._collect([b'data:{"a": 1}', b'', b'data:[DONE]'], monkeypatch)
        assert out == [{"a": 1}]

    def test_spaced_forms_still_work(self, monkeypatch):
        out = self._collect(
            [b'data: {"a": 1}', b'data: {"b": 2}', b'data: [DONE]'], monkeypatch
        )
        assert out == [{"a": 1}, {"b": 2}]

    def test_non_data_lines_skipped(self, monkeypatch):
        out = self._collect(
            [b'event: message', b': keepalive', b'data:{"ok": true}', b'data: [DONE]'],
            monkeypatch,
        )
        assert out == [{"ok": True}]
