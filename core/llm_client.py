"""LLM API client — all HTTP calls to the LLM service."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import core.config as _config

_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0
_RETRY_MAX_SLEEP = 30.0


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
                       temperature: float = None):
    """Yield SSE data chunks from the streaming API.

    Each yielded value is a parsed JSON dict from one SSE ``data:`` line.
    The generator ends when ``data: [DONE]`` is received or the connection closes.
    """
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

    with _urlopen_with_retry(_make_request(payload), timeout=_config.LLM_TIMEOUT) as resp:
        for raw_line in resp:
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
