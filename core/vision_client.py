"""Vision model API client — sends images to a vision LLM for analysis.

Uses OpenAI-compatible chat completions API with image_url content blocks.
No third-party dependencies — pure urllib.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

import core.config as _config
from core.logger import log_info, log_error


def analyze_image(image_base64: str, prompt: str, mime_type: str = "image/png") -> str:
    """Send a base64-encoded image to the vision model with a text prompt.

    Args:
        image_base64: Base64-encoded image data (no data URI prefix).
        prompt: Text prompt for the vision model.
        mime_type: MIME type of the image (default image/png).

    Returns:
        Vision model's text response, or "ERROR: ..." string on failure.
    """
    if not (_config.VISION_API_BASE_URL and _config.VISION_API_KEY
            and _config.VISION_MODEL_NAME):
        return ("ERROR: Vision model not configured. "
                "Set Vision API URL, Key, and Model in Settings.")

    endpoint = _config.VISION_API_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": _config.VISION_MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": _config.VISION_MAX_TOKENS,
        "temperature": _config.VISION_TEMPERATURE,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_config.VISION_API_KEY}",
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )

    log_info(f"Vision API call: model={_config.VISION_MODEL_NAME}, "
             f"prompt_len={len(prompt)}, img_b64_len={len(image_base64)}")

    try:
        with urllib.request.urlopen(req, timeout=_config.VISION_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        log_info(f"Vision API response: {len(content)} chars")
        return content
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        err = f"Vision API HTTP {e.code}: {body}"
        log_error(err)
        return f"ERROR: {err}"
    except Exception as e:
        err = f"Vision API failed: {type(e).__name__}: {e}"
        log_error(err)
        return f"ERROR: {err}"


def image_file_to_base64(file_path: str) -> tuple[str, str]:
    """Read an image file and return (base64_data, mime_type).

    Supports PNG, JPEG, BMP. Raises ValueError for unsupported formats.
    """
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
    }
    if ext not in mime_map:
        raise ValueError(
            f"Unsupported image format: {ext}. "
            f"Supported: {', '.join(mime_map.keys())}"
        )

    with open(file_path, "rb") as f:
        data = f.read()

    return base64.b64encode(data).decode("ascii"), mime_map[ext]
