"""
Session manager — manages conversation history for multi-turn agent interactions.

Three-layer memory:
  - Short-term: messages[] during a single agent run
  - Mid-term: ChatSession persists across multiple user inputs within one FreeCAD session
  - Long-term: session_store.py saves to disk for cross-session persistence (Phase 2)
"""
from __future__ import annotations

import uuid
from datetime import datetime


class ChatSession:
    """一次完整的设计会话，包含多轮 Agent 交互。"""

    def __init__(self):
        self.session_id = uuid.uuid4().hex[:12]
        self.created_at = datetime.now().isoformat()
        self.messages: list[dict] = []
        self.summary: str = ""
        self.document_state: str = ""
        self.last_mode: str = "auto"
        self._system_prompt: str = ""

    def set_system_prompt(self, prompt: str):
        """设置 system prompt（只在第一次或新建会话时调用）。"""
        self._system_prompt = prompt
        # 如果 messages 中已有 system 消息则替换，否则插入
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def add_user_message(self, text: str):
        """添加用户消息。"""
        self.messages.append({"role": "user", "content": text})

    def add_assistant_message(self, msg: dict):
        """添加 assistant 消息（可能含 tool_calls）。"""
        # Ensure role is set
        entry = dict(msg)
        entry["role"] = "assistant"
        self.messages.append(entry)

    def add_tool_result(self, tool_call_id: str, result: str):
        """添加工具执行结果。"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })

    def get_messages(self) -> list[dict]:
        """获取完整对话历史。"""
        return list(self.messages)

    def get_last_assistant_text(self) -> str:
        """获取最后一条 assistant 纯文本消息（用于 UI 显示）。"""
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return ""

    def update_summary(self, text: str):
        """更新会话摘要（每次 Agent 完成时调用）。"""
        self.summary = text

    def update_document_state(self, state: str):
        """更新文档状态快照。"""
        self.document_state = state

    def message_count(self) -> int:
        """返回消息总数。"""
        return len(self.messages)

    def user_turn_count(self) -> int:
        """返回用户发送的消息数。"""
        return sum(1 for m in self.messages if m.get("role") == "user")

    def clear(self):
        """清空会话（保留 system prompt）。"""
        system = self._system_prompt
        self.messages.clear()
        self.summary = ""
        self.document_state = ""
        if system:
            self.messages.append({"role": "system", "content": system})

    def to_dict(self) -> dict:
        """序列化为字典（用于持久化）。"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "summary": self.summary,
            "document_state": self.document_state,
            "last_mode": self.last_mode,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChatSession:
        """从字典反序列化。"""
        session = cls.__new__(cls)
        session.session_id = data.get("session_id", uuid.uuid4().hex[:12])
        session.created_at = data.get("created_at", datetime.now().isoformat())
        session.messages = data.get("messages", [])
        session.summary = data.get("summary", "")
        session.document_state = data.get("document_state", "")
        session.last_mode = data.get("last_mode", "auto")
        session._system_prompt = session.messages[0].get("content", "") if session.messages else ""
        return session
