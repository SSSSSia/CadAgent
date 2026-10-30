"""Tests for core/session.py — ChatSession class."""
from __future__ import annotations

from core.session import ChatSession


class TestChatSessionInit:
    def test_new_session(self):
        s = ChatSession()
        assert len(s.session_id) == 12
        assert s.created_at
        assert s.messages == []
        assert s.summary == ""
        assert s.document_state == ""


class TestAddMessages:
    def test_add_user_message(self):
        s = ChatSession()
        s.add_user_message("hello")
        assert len(s.messages) == 1
        assert s.messages[0]["role"] == "user"
        assert s.messages[0]["content"] == "hello"

    def test_add_assistant_message(self):
        s = ChatSession()
        s.add_assistant_message({"content": "hi", "role": "assistant"})
        assert s.messages[0]["role"] == "assistant"
        assert s.messages[0]["content"] == "hi"

    def test_add_assistant_ensures_role(self):
        s = ChatSession()
        s.add_assistant_message({"content": "hi"})
        assert s.messages[0]["role"] == "assistant"

    def test_add_tool_result(self):
        s = ChatSession()
        s.add_tool_result("call_123", "result text")
        assert s.messages[0]["role"] == "tool"
        assert s.messages[0]["tool_call_id"] == "call_123"
        assert s.messages[0]["content"] == "result text"


class TestSystemPrompt:
    def test_set_system_prompt_inserts(self):
        s = ChatSession()
        s.add_user_message("hi")
        s.set_system_prompt("you are helpful")
        assert s.messages[0]["role"] == "system"
        assert s.messages[0]["content"] == "you are helpful"

    def test_set_system_prompt_replaces(self):
        s = ChatSession()
        s.set_system_prompt("first")
        s.set_system_prompt("second")
        assert s.messages[0]["content"] == "second"
        assert len([m for m in s.messages if m["role"] == "system"]) == 1


class TestGetMessages:
    def test_returns_copy(self):
        s = ChatSession()
        s.add_user_message("hi")
        msgs = s.get_messages()
        msgs.append({"role": "user", "content": "extra"})
        assert len(s.messages) == 1


class TestGetLastAssistantText:
    def test_returns_last(self):
        s = ChatSession()
        s.add_assistant_message({"content": "first"})
        s.add_user_message("ok")
        s.add_assistant_message({"content": "second"})
        assert s.get_last_assistant_text() == "second"

    def test_empty_session(self):
        s = ChatSession()
        assert s.get_last_assistant_text() == ""

    def test_no_assistant_messages(self):
        s = ChatSession()
        s.add_user_message("hi")
        assert s.get_last_assistant_text() == ""


class TestCounters:
    def test_message_count(self):
        s = ChatSession()
        s.add_user_message("hi")
        s.add_assistant_message({"content": "hello"})
        assert s.message_count() == 2

    def test_user_turn_count(self):
        s = ChatSession()
        s.add_user_message("hi")
        s.add_assistant_message({"content": "hello"})
        s.add_user_message("bye")
        assert s.user_turn_count() == 2


class TestClear:
    def test_clear_preserves_system_prompt(self):
        s = ChatSession()
        s.set_system_prompt("sys")
        s.add_user_message("hi")
        s.clear()
        assert len(s.messages) == 1
        assert s.messages[0]["role"] == "system"
        assert s.summary == ""

    def test_clear_without_system_prompt(self):
        s = ChatSession()
        s.add_user_message("hi")
        s.clear()
        assert len(s.messages) == 0


class TestSerialization:
    def test_to_dict(self):
        s = ChatSession()
        s.add_user_message("hi")
        d = s.to_dict()
        assert "session_id" in d
        assert "created_at" in d
        assert "messages" in d
        assert len(d["messages"]) == 1

    def test_round_trip(self):
        s = ChatSession()
        s.set_system_prompt("sys prompt")
        s.add_user_message("create a box")
        s.add_assistant_message({"content": "done"})
        s.update_summary("box created")

        d = s.to_dict()
        s2 = ChatSession.from_dict(d)

        assert s2.session_id == s.session_id
        assert s2.summary == "box created"
        assert len(s2.messages) == 3
        assert s2.messages[0]["role"] == "system"
        assert s2.messages[1]["content"] == "create a box"

    def test_from_dict_missing_fields(self):
        s = ChatSession.from_dict({})
        assert len(s.session_id) == 12
        assert s.messages == []
        assert s.summary == ""

    def test_from_dict_preserves_system_prompt(self):
        d = {
            "session_id": "abc123",
            "messages": [{"role": "system", "content": "my prompt"}],
        }
        s = ChatSession.from_dict(d)
        assert s._system_prompt == "my prompt"


class TestSchemaTolerance:
    """S6: the dead _version mechanism was removed — old files carrying a
    "version" key must still load (unknown keys are ignored)."""

    def test_from_dict_ignores_unknown_version_key(self):
        d = {"version": 99, "session_id": "abc123", "messages": []}
        s = ChatSession.from_dict(d)
        assert s.session_id == "abc123"
        assert not hasattr(s, "_version")

    def test_to_dict_has_no_version_key(self):
        d = ChatSession().to_dict()
        assert "version" not in d

    def test_clear_does_not_change_session_id(self):
        s = ChatSession()
        original_id = s.session_id
        s.add_user_message("hi")
        s.clear()
        assert s.session_id == original_id


# ---- S2-B12: from_dict must not adopt a non-system first message ----

class TestFromDictSystemPromptRole:

    def test_user_first_message_not_adopted_as_system(self):
        from core.session import ChatSession
        d = {
            "session_id": "abc123def456",
            "messages": [
                {"role": "user", "content": "make me a bracket"},
                {"role": "assistant", "content": "done"},
            ],
        }
        s = ChatSession.from_dict(d)
        assert s._system_prompt == ""
        # clear() must not re-inject the user text as a system message
        s.clear()
        assert s.messages == []

    def test_system_first_message_still_adopted(self):
        from core.session import ChatSession
        d = {
            "session_id": "abc123def456",
            "messages": [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "hi"},
            ],
        }
        s = ChatSession.from_dict(d)
        assert s._system_prompt == "SYS"
        s.clear()
        assert s.messages == [{"role": "system", "content": "SYS"}]


# ---- S3-D12: find_tool_name ----

class TestFindToolName:

    def _messages(self):
        return [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "execute_code", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": "OK"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_2", "function": {"name": "undo_last", "arguments": "{}"}},
                {"id": "tc_3", "function": {"name": "export_step", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_3", "content": "SUCCESS"},
        ]

    def test_finds_name_despite_newer_unrelated_calls(self):
        """tc_1 is older than tc_2/tc_3 — the old scan mislabeled it."""
        from core.session import ChatSession
        assert ChatSession.find_tool_name(self._messages(), "tc_1") == "execute_code"
        assert ChatSession.find_tool_name(self._messages(), "tc_3") == "export_step"

    def test_unknown_id_falls_back(self):
        from core.session import ChatSession
        assert ChatSession.find_tool_name(self._messages(), "nope") == "tool_result"

    def test_empty_history(self):
        from core.session import ChatSession
        assert ChatSession.find_tool_name([], "x") == "tool_result"


# ---- S2-B17 (done in S3): lock-guarded concurrent appends ----

class TestThreadSafety:
    def test_concurrent_appends_all_lands(self):
        import threading
        from core.session import ChatSession
        s = ChatSession()
        errors = []

        def worker(n):
            try:
                for i in range(100):
                    s.add_user_message(f"w{n}-{i}")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert s.message_count() == 400
