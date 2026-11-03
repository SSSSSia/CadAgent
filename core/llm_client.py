"""LLM API client — all HTTP calls to the LLM service."""
from __future__ import annotations

import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request

import core.config as _config

_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0
_RETRY_MAX_SLEEP = 30.0
# urllib cannot abort a blocked read. A one-second socket timeout poisons
# the response: the next read raises "cannot read from timed out object".
# The body is read on a side thread; Stop closes the socket, which unblocks
# that read within about a second (S9-B).
_READ_SLICE_S = 1.0

# Shared by every in-flight chat call. The panel sets it from the Stop button.
_CANCEL = threading.Event()


class LlmCancelled(Exception):
    """The user stopped the call. Chunks already yielded stay with the caller."""


def request_llm_cancel() -> None:
    """Ask every in-flight LLM read to stop at the next timeout slice."""
    _CANCEL.set()


def clear_llm_cancel() -> None:
    """Allow the next turn to call the model."""
    _CANCEL.clear()


def llm_cancel_requested() -> bool:
    return _CANCEL.is_set()


def interrupted_result(content: str, tool_calls: list | None = None) -> dict:
    """Stream payload for a cancelled call. Partial text is kept."""
    msg: dict = {"content": content or ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg, "finish_reason": "interrupted"}],
        "interrupted": True,
    }


def _parse_retry_after(headers) -> float:
    """Parse a numeric Retry-After header (seconds). HTTP-date unsupported."""
    if not headers:
        return 0.0
    try:
        raw = headers.get("Retry-After")
    except Exception:
        return 0.0
    if not raw:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _urlopen_with_retry(request, timeout):
    """urlopen with retry, Retry-After support, and socket cleanup.

    Retryable failures (429/5xx/network) back off exponentially; a numeric
    server Retry-After takes precedence, capped at _RETRY_MAX_SLEEP. The
    failed response is closed before each retry sleep so sockets don't pile
    up (S2-B6). The final error is re-raised with its body still readable.
    """
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        retry_after = 0.0
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                retry_after = _parse_retry_after(e.headers)
                last_error = e
                if attempt < _MAX_RETRIES:
                    try:
                        e.close()
                    except Exception:
                        pass
            else:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            last_error = e
        if attempt < _MAX_RETRIES:
            time.sleep(min(
                max(retry_after, _RETRY_BACKOFF * (2 ** attempt)),
                _RETRY_MAX_SLEEP,
            ))
    if last_error is not None:
        raise last_error
    raise RuntimeError("urlopen failed without capturing an error")


def _cancel_is_set(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _interruptible_sleep(seconds: float, cancel_event) -> None:
    """Sleep in short steps so Stop does not wait out a retry backoff."""
    end = time.monotonic() + max(0.0, seconds)
    while True:
        if _cancel_is_set(cancel_event):
            raise LlmCancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(0.05, left))


def _open_cancellable(request, deadline: float, cancel_event):
    """Open the HTTP response without aborting a slow first byte.

    urllib's timeout covers the whole request. A one-second timeout here
    drops the connection while a reasoning model is still thinking, then
    the next loop opens a new request and the panel spins until
    LLM_TIMEOUT. The open therefore uses the remaining deadline. Stop
    during the body is handled by ``_iter_lines``, which shortens the
    socket timeout after the headers arrive. HTTP 429/5xx keep the
    existing retry budget.
    """
    last_error = None
    attempt = 0
    while True:
        if _cancel_is_set(cancel_event):
            raise LlmCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if last_error is not None:
                raise last_error
            raise TimeoutError("LLM request timed out")
        try:
            return urllib.request.urlopen(request, timeout=remaining)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last_error = e
            if attempt >= _MAX_RETRIES:
                raise
            retry_after = _parse_retry_after(e.headers)
            try:
                e.close()
            except Exception:
                pass
            delay = min(
                max(retry_after, _RETRY_BACKOFF * (2 ** attempt)),
                _RETRY_MAX_SLEEP,
            )
            attempt += 1
            _interruptible_sleep(delay, cancel_event)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(e, (TimeoutError, socket.timeout)) or isinstance(
                reason, (TimeoutError, socket.timeout)
            ):
                last_error = TimeoutError("LLM request timed out")
                continue
            last_error = e
            if attempt >= _MAX_RETRIES:
                raise
            delay = min(_RETRY_BACKOFF * (2 ** attempt), _RETRY_MAX_SLEEP)
            attempt += 1
            _interruptible_sleep(delay, cancel_event)


def _response_socket(resp):
    """Find the socket behind urllib's addinfourl / HTTPResponse wrappers.

    A one-level ``fp.raw._sock`` lookup misses the real chain
    (addinfourl.fp is an HTTPResponse, whose fp is a makefile). Without
    the socket, the body read keeps the long open timeout and Stop cannot
    land between chunks.
    """
    obj = resp
    seen: set[int] = set()
    while obj is not None and id(obj) not in seen:
        seen.add(id(obj))
        sock = getattr(obj, "_sock", None) or getattr(obj, "sock", None)
        if sock is not None and hasattr(sock, "settimeout"):
            return sock
        nxt = getattr(obj, "raw", None)
        if nxt is None:
            nxt = getattr(obj, "fp", None)
        obj = nxt
    return None


def _close_quietly(resp) -> None:
    sock = _response_socket(resp)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
    try:
        resp.close()
    except Exception:
        pass


def _iter_lines(resp, deadline: float, cancel_event):
    """Yield response lines. Stop closes the socket instead of timing it out.

    SocketIO remembers the first timeout and then raises
    ``OSError: cannot read from timed out object`` on every later read.
    A model pause longer than one second used to hit that. The socket
    timeout stays at the deadline; a side thread blocks in readline, and
    Stop or the deadline closes the response to wake it.
    """
    lines: queue.Queue = queue.Queue()

    def _reader():
        try:
            while True:
                line = resp.readline()
                lines.put(line)
                if not line:
                    return
        except Exception as exc:
            lines.put(exc)

    threading.Thread(target=_reader, name="cadagent-llm-read", daemon=True).start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _close_quietly(resp)
            raise TimeoutError("LLM request timed out")
        try:
            item = lines.get(timeout=min(_READ_SLICE_S, remaining))
        except queue.Empty:
            if _cancel_is_set(cancel_event):
                _close_quietly(resp)
                raise LlmCancelled()
            continue
        if isinstance(item, BaseException):
            if _cancel_is_set(cancel_event):
                raise LlmCancelled()
            raise item
        if not item:
            if _cancel_is_set(cancel_event):
                raise LlmCancelled()
            return
        yield item
        if _cancel_is_set(cancel_event):
            _close_quietly(resp)
            raise LlmCancelled()


def _make_request(payload: dict) -> urllib.request.Request:
    """Build a standard POST request for the LLM chat/completions endpoint."""
    return urllib.request.Request(
        _config.API_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_config.API_KEY}",
        },
    )


def call_llm_streaming(messages: list[dict],
                       tools: list[dict] | None = None,
                       temperature: float = None,
                       cancel_event: threading.Event | None = None):
    """Yield SSE data chunks from the streaming API.

    Each yielded value is a parsed JSON dict from one SSE ``data:`` line.
    The generator ends when ``data: [DONE]`` is received or the connection closes.
    ``cancel_event`` defaults to the process-wide stop flag. A set flag raises
    ``LlmCancelled`` at the next read slice; chunks already yielded are kept.
    """
    if cancel_event is None:
        cancel_event = _CANCEL
    if _cancel_is_set(cancel_event):
        raise LlmCancelled()
    payload: dict = {
        "model": _config.MODEL_NAME,
        "messages": messages,
        "temperature": temperature if temperature is not None else _config.TEMPERATURE,
        "max_tokens": _config.MAX_TOKENS,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    deadline = time.monotonic() + float(_config.LLM_TIMEOUT)
    resp = _open_cancellable(_make_request(payload), deadline, cancel_event)
    try:
        for raw_line in _iter_lines(resp, deadline, cancel_event):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            # SSE allows "data:" with or without a following space (S2-B5)
            if not line.startswith("data:"):
                continue
            data_str = line[5:].lstrip(" ")
            if data_str == "[DONE]":
                return
            try:
                yield json.loads(data_str)
            except json.JSONDecodeError:
                continue
    finally:
        try:
            resp.close()
        except Exception:
            pass
