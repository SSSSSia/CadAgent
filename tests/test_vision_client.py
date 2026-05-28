"""Tests for core/vision_client.py — vision API client and image utilities."""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _reload_vision_client(monkeypatch=None):
    """Reload vision_client module with optional env overrides."""
    import importlib
    import core.config
    import core.vision_client
    if monkeypatch is not None:
        monkeypatch.delenv("VISION_API_BASE_URL", raising=False)
        monkeypatch.delenv("VISION_API_KEY", raising=False)
        monkeypatch.delenv("VISION_MODEL_NAME", raising=False)
    importlib.reload(core.config)
    importlib.reload(core.vision_client)
    return core.vision_client


class TestAnalyzeImageNotConfigured:
    def test_returns_error_when_empty(self, monkeypatch):
        mod = _reload_vision_client(monkeypatch)
        result = mod.analyze_image("fake_base64", "describe this")
        assert result.startswith("ERROR:")
        assert "not configured" in result

    def test_returns_error_when_partial(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.delenv("VISION_API_KEY", raising=False)
        monkeypatch.delenv("VISION_MODEL_NAME", raising=False)
        mod = _reload_vision_client()
        result = mod.analyze_image("fake_base64", "describe this")
        assert result.startswith("ERROR:")


class TestAnalyzeImageRequest:
    def test_request_payload_format(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-test-key")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        mod = _reload_vision_client()

        captured_req = {}

        class FakeResp:
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "A blue box."}}]
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def fake_urlopen(req, timeout=None):
            captured_req["url"] = req.full_url
            captured_req["data"] = json.loads(req.data.decode("utf-8"))
            captured_req["auth"] = req.get_header("Authorization")
            captured_req["content_type"] = req.get_header("Content-type")
            captured_req["timeout"] = timeout
            return FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        result = mod.analyze_image("aGVsbG8=", "What is this?", mime_type="image/jpeg")

        assert result == "A blue box."
        assert captured_req["url"] == "https://api.example.com/v1/chat/completions"
        assert captured_req["auth"] == "Bearer sk-test-key"
        assert captured_req["content_type"] == "application/json"
        assert captured_req["timeout"] == 60

        payload = captured_req["data"]
        assert payload["model"] == "gpt-4o"
        assert payload["max_tokens"] == 2048
        assert payload["temperature"] == 0.3

        msg = payload["messages"][0]
        assert msg["role"] == "user"
        content = msg["content"]
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,aGVsbG8="

    def test_success_response(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        mod = _reload_vision_client()

        class FakeResp:
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "It's a cube."}}]
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        monkeypatch.setattr("urllib.request.urlopen",
                            lambda req, timeout=None: FakeResp())

        result = mod.analyze_image("AAAA", "describe")
        assert result == "It's a cube."


class TestAnalyzeImageErrors:
    def test_http_error(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        mod = _reload_vision_client()

        def raise_http_error(req, timeout=None):
            raise urllib.error.HTTPError(
                "https://api.example.com/v1/chat/completions",
                401, "Unauthorized", {}, None
            )

        monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

        result = mod.analyze_image("AAAA", "describe")
        assert result.startswith("ERROR:")
        assert "HTTP 401" in result

    def test_generic_error(self, monkeypatch):
        monkeypatch.setenv("VISION_API_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("VISION_API_KEY", "sk-test")
        monkeypatch.setenv("VISION_MODEL_NAME", "gpt-4o")
        mod = _reload_vision_client()

        monkeypatch.setattr("urllib.request.urlopen",
                            lambda req, timeout=None: (_ for _ in ()).throw(TimeoutError("timed out")))

        result = mod.analyze_image("AAAA", "describe")
        assert result.startswith("ERROR:")
        assert "TimeoutError" in result


class TestImageFileToBase64:
    def test_png_file(self, tmp_path):
        mod = _reload_vision_client()
        png_file = tmp_path / "test.png"
        # Minimal valid PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        png_file.write_bytes(png_data)

        b64, mime = mod.image_file_to_base64(str(png_file))
        assert mime == "image/png"
        assert base64.b64decode(b64) == png_data

    def test_jpg_file(self, tmp_path):
        mod = _reload_vision_client()
        jpg_file = tmp_path / "photo.jpg"
        jpg_file.write_bytes(b"\xff\xd8\xff\xe0test_data")

        b64, mime = mod.image_file_to_base64(str(jpg_file))
        assert mime == "image/jpeg"
        assert base64.b64decode(b64) == b"\xff\xd8\xff\xe0test_data"

    def test_jpeg_extension(self, tmp_path):
        mod = _reload_vision_client()
        jpeg_file = tmp_path / "photo.jpeg"
        jpeg_file.write_bytes(b"\xff\xd8\xff\xe0data")

        b64, mime = mod.image_file_to_base64(str(jpeg_file))
        assert mime == "image/jpeg"

    def test_bmp_file(self, tmp_path):
        mod = _reload_vision_client()
        bmp_file = tmp_path / "image.bmp"
        bmp_file.write_bytes(b"BM\x00\x00test")

        b64, mime = mod.image_file_to_base64(str(bmp_file))
        assert mime == "image/bmp"
        assert base64.b64decode(b64) == b"BM\x00\x00test"

    def test_unsupported_format(self, tmp_path):
        mod = _reload_vision_client()
        gif_file = tmp_path / "anim.gif"
        gif_file.write_bytes(b"GIF89a")

        try:
            mod.image_file_to_base64(str(gif_file))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unsupported" in str(e)
            assert ".gif" in str(e)

    def test_case_insensitive_extension(self, tmp_path):
        mod = _reload_vision_client()
        png_file = tmp_path / "TEST.PNG"
        png_file.write_bytes(b"\x89PNG\r\ndata")

        b64, mime = mod.image_file_to_base64(str(png_file))
        assert mime == "image/png"

    def test_file_not_found(self):
        mod = _reload_vision_client()
        try:
            mod.image_file_to_base64("/nonexistent/path/image.png")
            assert False, "Should have raised FileNotFoundError"
        except (FileNotFoundError, OSError):
            pass
