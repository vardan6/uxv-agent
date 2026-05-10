from __future__ import annotations

import sys
import types

from ai.chat_service import AIChatService


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


def test_agent_tool_binding_disables_strict_mode_for_optional_tool_args() -> None:
    service = AIChatService(store=None, tool_registry=_FakeRegistry())
    model = _FakeModel()
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
        runtime = service._prepare_agent_tool_runtime(
            model,
            messages=[{"role": "user", "content": "what is ahead"}],
            context_snapshot=None,
            prompt_tool_calls=[],
            tool_context=None,
        )
    finally:
        if original_messages is None:
            sys.modules.pop("langchain_core.messages", None)
        else:
            sys.modules["langchain_core.messages"] = original_messages
        if original_langchain_core is None:
            sys.modules.pop("langchain_core", None)
        else:
            sys.modules["langchain_core"] = original_langchain_core

    assert runtime is not None
    assert len(model.bind_calls) == 1
    assert model.bind_calls[0]["kwargs"] == {"strict": False}
    assert [tool.name for tool in model.bind_calls[0]["tools"]] == ["query_objects_in_front"]
