"""LLM API client — all HTTP calls to the LLM service."""
from __future__ import annotations

import json
import urllib.request

from core.config import API_BASE_URL, API_KEY, MODEL_NAME, strip_markdown
from agent.prompts import (
    SYSTEM_PROMPT_NEW, SYSTEM_PROMPT_MODIFY,
    SYSTEM_PROMPT_DERIVE, SYSTEM_PROMPT_VARIANT,
)


def call_llm_with_tools(messages: list[dict],
                        tools: list[dict] | None = None,
                        temperature: float = 0.1) -> dict:
    """Call SiliconFlow API with optional tool definitions. Returns raw JSON."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        API_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate_freecad_code(user_description: str,
                          mode: str = "new",
                          context: str = "") -> str:
    """调用 LLM API 并返回可直接 exec() 的 Python 代码字符串。

    Args:
        user_description: 用户的自然语言描述（如 "法兰筒体 OD 200mm"）
        mode: 设计模式 — "new" 全新创建 | "modify" 修改现有 | "derive" 派生配合件 | "variant" 参数变体
        context: doc_analyzer 提取的文档几何文本（modify/derive/variant 模式必须提供）
    """
    prompt_map = {
        "new": SYSTEM_PROMPT_NEW,
        "modify": SYSTEM_PROMPT_MODIFY,
        "derive": SYSTEM_PROMPT_DERIVE,
        "variant": SYSTEM_PROMPT_VARIANT,
    }
    system_prompt = prompt_map.get(mode, SYSTEM_PROMPT_NEW)
    # modify/derive/variant 的 Prompt 含 {context} 占位符，替换为实际几何信息
    if "{context}" in system_prompt:
        system_prompt = system_prompt.format(context=context or "(No document context)")

    # temperature 设为 0.1：代码生成需要确定性输出，高 temperature 会导致 API 名称拼写错误
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_description},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode("utf-8")

    # 使用 urllib（标准库）而非 requests，因为 FreeCAD 内置 Python 不保证安装了第三方包
    req = urllib.request.Request(
        API_BASE_URL.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data["choices"][0]["message"]["content"]
    code = strip_markdown(content)
    if not code:
        raise ValueError("LLM returned empty response")
    return code


def call_llm_streaming(messages: list[dict],
                       tools: list[dict] | None = None,
                       temperature: float = 0.1):
    """Yield SSE data chunks from the streaming API.

    Each yielded value is a parsed JSON dict from one SSE ``data:`` line.
    The generator ends when ``data: [DONE]`` is received or the connection closes.
    """
    payload: dict = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        API_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                return
            try:
                yield json.loads(data_str)
            except json.JSONDecodeError:
                continue
