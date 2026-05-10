from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest

from ai.chat_service import AIChatService, AgentInvokeResult


class _Message:
    def __init__(self, content: str = "", **kwargs):
        self.content = content
        self.kwargs = kwargs


class _ToolMessage(_Message):
    pass


class _FakeTool:
    def __init__(self, name: str):
        self.name = name


class _FakeRegistry:
    def build_langchain_tools(self, runtime, context_snapshot, *, timezone_name="", permissions=None):
        return [_FakeTool("query_objects_in_front")]


class _FakeBoundModel:
    pass


class _FakeModel:
    def __init__(self):
        self.bind_calls: list[dict] = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append({"tools": tools, "kwargs": kwargs})
        return _FakeBoundModel()


class _FakeStreamModel:
    def __init__(self, chunks, error: Exception | None = None):
        self._chunks = chunks
        self._error = error

    def stream(self, _messages):
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


class _FakeStore:
    def __init__(self):
        self.calls: list[dict] = []

    def add_message(self, session_id: str, **kwargs):
        message = {"id": f"m{len(self.calls) + 1}", "session_id": session_id, **kwargs}
        self.calls.append(message)
        return message


@contextmanager
def _fake_langchain_messages():
    fake_messages_module = types.SimpleNamespace(
        AIMessage=_Message,
        HumanMessage=_Message,
        SystemMessage=_Message,
        ToolMessage=_ToolMessage,
    )
    original_messages = sys.modules.get("langchain_core.messages")
    original_langchain_core = sys.modules.get("langchain_core")
    sys.modules["langchain_core"] = types.SimpleNamespace(messages=fake_messages_module)
    sys.modules["langchain_core.messages"] = fake_messages_module
    try:
        yield
    finally:
        if original_messages is None:
            sys.modules.pop("langchain_core.messages", None)
        else:
            sys.modules["langchain_core.messages"] = original_messages
        if original_langchain_core is None:
            sys.modules.pop("langchain_core", None)
        else:
            sys.modules["langchain_core"] = original_langchain_core


def test_agent_tool_binding_disables_strict_mode_for_optional_tool_args() -> None:
    service = AIChatService(store=None, tool_registry=_FakeRegistry())
    model = _FakeModel()
    with _fake_langchain_messages():
        runtime = service._prepare_agent_tool_runtime(
            model,
            messages=[{"role": "user", "content": "what is ahead"}],
            context_snapshot=None,
            prompt_tool_calls=[],
            tool_context=None,
        )

    assert runtime is not None
    assert len(model.bind_calls) == 1
    assert model.bind_calls[0]["kwargs"] == {"strict": False}
    assert [tool.name for tool in model.bind_calls[0]["tools"]] == ["query_objects_in_front"]


def test_empty_agent_result_falls_back_to_plain_streaming() -> None:
    store = _FakeStore()
    service = AIChatService(store=store)
    model = _FakeStreamModel([_Message("fallback reply")])

    def _fake_agent_events(*_args, **_kwargs):
        yield {
            "type": "_agent_result",
            "result": AgentInvokeResult(
                content="   ",
                tool_calls=[],
                response_metadata={},
                usage_metadata={},
            ),
        }

    service._stream_agent_with_tools_events = _fake_agent_events  # type: ignore[method-assign]

    with _fake_langchain_messages():
        events = list(
            service._stream_assistant_events(
                model,
                session_id="s1",
                provider_id="p1",
                model_id="m1",
                messages=[{"role": "user", "content": "hi"}],
                run_mode="agent",
            )
        )

    assert any('"type":"assistant_delta","delta":"fallback reply"' in event for event in events)
    assert any('"type":"assistant_message"' in event for event in events)
    assert [call["content"] for call in store.calls] == ["fallback reply"]


def test_stream_failure_does_not_persist_partial_assistant_message() -> None:
    store = _FakeStore()
    service = AIChatService(store=store)
    model = _FakeStreamModel([_Message("partial")], error=RuntimeError("stream failed"))

    with _fake_langchain_messages():
        with pytest.raises(RuntimeError, match="stream failed"):
            list(
                service._stream_assistant_events(
                    model,
                    session_id="s1",
                    provider_id="p1",
                    model_id="m1",
                    messages=[{"role": "user", "content": "hi"}],
                    run_mode="chat",
                )
            )

    assert store.calls == []
