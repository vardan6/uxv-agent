from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .provider_registry import resolve_provider
from .session_store import AISessionStore


SYSTEM_PROMPT = """You are the AI chat assistant inside Remote Rover GCS.
Answer operator questions clearly and concisely.
Do not claim to control the rover, publish commands, or start missions.
If the operator asks for rover movement or mission execution, explain that this chat mode is read-only."""

AGENT_SYSTEM_PROMPT = """You are the read-only AI agent inside Remote Rover GCS.
Answer operator questions using conversation history plus available tool/context results.
You may inspect rover state, map summaries, object queries, telemetry, and replay summaries.
Do not claim to control the rover, publish commands, start missions, or mutate GCS state.
If required rover, map, or sensor data is unavailable, say it is unavailable instead of guessing."""


@dataclass(slots=True)
class AgentInvokeResult:
    content: str
    tool_calls: list[dict[str, Any]]
    response_metadata: dict[str, Any]


class AIChatService:
    def __init__(
        self,
        store: AISessionStore,
        secret_resolver: Callable[[str], str] | None = None,
        agent_toolset: Any | None = None,
    ):
        self._store = store
        self._secret_resolver = secret_resolver
        self._agent_toolset = agent_toolset

    def send_message(
        self,
        config: Any,
        session_id: str,
        content: str,
        context_snapshot: dict[str, Any] | None = None,
        run_mode: str = "chat",
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("message content is required")
        clean_run_mode = _normalize_run_mode(run_mode)

        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        provider_id_override = str(session.get("provider_id") or "")
        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=provider_id_override,
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        provider_id = str(provider.get("id", ""))
        model_id = str(provider.get("model_id", ""))

        user_message = self._store.add_message(
            session_id,
            role="user",
            content=clean_content,
            provider_id=provider_id,
            model_id=model_id,
            meta={"run_mode": clean_run_mode},
        )
        self._store.maybe_auto_title(session_id, clean_content)
        messages = self._store.latest_messages(session_id, limit=40)
        assistant_message = self._invoke_and_store(
            resolved.model,
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            messages=messages,
            context_snapshot=context_snapshot,
            run_mode=clean_run_mode,
            tool_context=tool_context,
        )
        return {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "session": self._store.get_session(session_id, include_messages=False),
        }

    def retry_last_response(
        self,
        config: Any,
        session_id: str,
        context_snapshot: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        messages = self._store.latest_messages(session_id, limit=40)
        if not messages:
            raise ValueError("No message is available to retry.")
        if messages[-1]["role"] == "assistant":
            self._store.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Retry requires the latest remaining message to be from the user.")
        clean_run_mode = _message_run_mode(messages[-1])

        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=str(session.get("provider_id") or ""),
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        assistant_message = self._invoke_and_store(
            resolved.model,
            session_id=session_id,
            provider_id=str(provider.get("id", "")),
            model_id=str(provider.get("model_id", "")),
            messages=messages,
            context_snapshot=context_snapshot,
            run_mode=clean_run_mode,
            tool_context=tool_context,
        )
        return {
            "assistant_message": assistant_message,
            "session": self._store.get_session(session_id, include_messages=False),
        }

    def stream_retry_events(
        self,
        config: Any,
        session_id: str,
        context_snapshot: dict[str, Any] | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        messages = self._store.latest_messages(session_id, limit=40)
        if not messages:
            raise ValueError("No message is available to retry.")
        if messages[-1]["role"] == "assistant":
            self._store.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Retry requires the latest remaining message to be from the user.")
        clean_run_mode = _message_run_mode(messages[-1])

        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=str(session.get("provider_id") or ""),
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        yield from self._stream_assistant_events(
            resolved.model,
            session_id=session_id,
            provider_id=str(provider.get("id", "")),
            model_id=str(provider.get("model_id", "")),
            messages=messages,
            context_snapshot=context_snapshot,
            run_mode=clean_run_mode,
            tool_context=tool_context,
        )

    def stream_message_events(
        self,
        config: Any,
        session_id: str,
        content: str,
        context_snapshot: dict[str, Any] | None = None,
        run_mode: str = "chat",
        tool_context: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("message content is required")
        clean_run_mode = _normalize_run_mode(run_mode)

        session = self._store.get_session(session_id, include_messages=False)
        if session is None or session.get("archived_at") is not None:
            raise KeyError("AI session not found")

        provider_id_override = str(session.get("provider_id") or "")
        resolved = resolve_provider(
            config,
            purpose="general_chat",
            provider_id=provider_id_override,
            secret_resolver=self._secret_resolver,
        )
        provider = resolved.provider
        provider_id = str(provider.get("id", ""))
        model_id = str(provider.get("model_id", ""))

        user_message = self._store.add_message(
            session_id,
            role="user",
            content=clean_content,
            provider_id=provider_id,
            model_id=model_id,
            meta={"run_mode": clean_run_mode},
        )
        self._store.maybe_auto_title(session_id, clean_content)
        yield _json_line({"type": "user_message", "message": user_message})

        messages = self._store.latest_messages(session_id, limit=40)
        yield from self._stream_assistant_events(
            resolved.model,
            session_id=session_id,
            provider_id=provider_id,
            model_id=model_id,
            messages=messages,
            context_snapshot=context_snapshot,
            run_mode=clean_run_mode,
            tool_context=tool_context,
        )

    def _stream_assistant_events(
        self,
        model: Any,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None = None,
        run_mode: str = "chat",
        tool_context: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        clean_run_mode = _normalize_run_mode(run_mode)
        prompt_tool_calls = _tool_calls(context_snapshot) if clean_run_mode == "agent" else []
        if clean_run_mode == "agent":
            started = time.perf_counter()
            agent_result = self._try_invoke_agent_with_tools(
                model,
                messages=messages,
                context_snapshot=context_snapshot,
                prompt_tool_calls=prompt_tool_calls,
                tool_context=tool_context,
            )
            if agent_result is not None:
                content_out = agent_result.content.strip()
                if content_out:
                    yield _json_line({"type": "assistant_delta", "delta": content_out})
                    assistant_message = self._store.add_message(
                        session_id,
                        role="assistant",
                        content=content_out,
                        provider_id=provider_id,
                        model_id=model_id,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        meta={
                            "run_mode": clean_run_mode,
                            "tool_calls": agent_result.tool_calls,
                            "prompt_context_tool_calls": prompt_tool_calls,
                            "agent_permissions": _agent_permissions(clean_run_mode),
                            "response_metadata": agent_result.response_metadata,
                            **_context_meta(context_snapshot),
                        },
                    )
                    yield _json_line({"type": "assistant_message", "message": assistant_message})
                return
        langchain_messages = _to_langchain_messages(
            messages,
            _prompt_for_mode(context_snapshot, clean_run_mode, prompt_tool_calls),
            system_prompt=AGENT_SYSTEM_PROMPT if clean_run_mode == "agent" else SYSTEM_PROMPT,
        )
        started = time.perf_counter()
        parts: list[str] = []
        interrupted = False
        failed = False
        try:
            stream = getattr(model, "stream", None)
            if callable(stream):
                for chunk in stream(langchain_messages):
                    delta = _response_content(chunk)
                    if not delta:
                        continue
                    parts.append(delta)
                    yield _json_line({"type": "assistant_delta", "delta": delta})
            else:
                response = model.invoke(langchain_messages)
                delta = _response_content(response)
                if delta:
                    parts.append(delta)
                    yield _json_line({"type": "assistant_delta", "delta": delta})
        except GeneratorExit:
            interrupted = True
            raise
        except Exception:
            failed = True
            raise
        finally:
            content_out = "".join(parts).strip()
            if content_out:
                latency_ms = int((time.perf_counter() - started) * 1000)
                assistant_message = self._store.add_message(
                    session_id,
                    role="assistant",
                    content=content_out,
                    provider_id=provider_id,
                    model_id=model_id,
                    latency_ms=latency_ms,
                    meta={
                        "run_mode": clean_run_mode,
                        "tool_calls": prompt_tool_calls,
                        "agent_permissions": _agent_permissions(clean_run_mode),
                        "interrupted": interrupted or failed,
                        **_context_meta(context_snapshot),
                    },
                )
                if not interrupted and not failed:
                    yield _json_line({"type": "assistant_message", "message": assistant_message})

    def _invoke_and_store(
        self,
        model: Any,
        *,
        session_id: str,
        provider_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None = None,
        run_mode: str = "chat",
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_run_mode = _normalize_run_mode(run_mode)
        prompt_tool_calls = _tool_calls(context_snapshot) if clean_run_mode == "agent" else []
        if clean_run_mode == "agent":
            started = time.perf_counter()
            agent_result = self._try_invoke_agent_with_tools(
                model,
                messages=messages,
                context_snapshot=context_snapshot,
                prompt_tool_calls=prompt_tool_calls,
                tool_context=tool_context,
            )
            if agent_result is not None:
                return self._store.add_message(
                    session_id,
                    role="assistant",
                    content=agent_result.content,
                    provider_id=provider_id,
                    model_id=model_id,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    meta={
                        "run_mode": clean_run_mode,
                        "tool_calls": agent_result.tool_calls,
                        "prompt_context_tool_calls": prompt_tool_calls,
                        "agent_permissions": _agent_permissions(clean_run_mode),
                        "response_metadata": agent_result.response_metadata,
                        **_context_meta(context_snapshot),
                    },
                )
        langchain_messages = _to_langchain_messages(
            messages,
            _prompt_for_mode(context_snapshot, clean_run_mode, prompt_tool_calls),
            system_prompt=AGENT_SYSTEM_PROMPT if clean_run_mode == "agent" else SYSTEM_PROMPT,
        )
        started = time.perf_counter()
        response = model.invoke(langchain_messages)
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = _response_content(response)
        return self._store.add_message(
            session_id,
            role="assistant",
            content=content,
            provider_id=provider_id,
            model_id=model_id,
            latency_ms=latency_ms,
            meta={
                "run_mode": clean_run_mode,
                "tool_calls": prompt_tool_calls,
                "agent_permissions": _agent_permissions(clean_run_mode),
                "response_metadata": getattr(response, "response_metadata", {}) or {},
                **_context_meta(context_snapshot),
            },
        )

    def _try_invoke_agent_with_tools(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
    ) -> AgentInvokeResult | None:
        if self._agent_toolset is None:
            return None
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            return None

        try:
            from langchain_core.messages import ToolMessage
        except ImportError as exc:
            raise RuntimeError("LangChain core is not installed. Install gcs_server/requirements-gcs.txt.") from exc

        tools = self._agent_toolset.build_langchain_tools(
            timezone_name=str((tool_context or {}).get("timezone_name") or "").strip(),
        )
        if not tools:
            return None

        bound_model = bind_tools(tools)
        tool_map = {str(tool.name): tool for tool in tools}
        langchain_messages = _to_langchain_messages(
            messages,
            _prompt_for_mode(context_snapshot, "agent", prompt_tool_calls),
            system_prompt=AGENT_SYSTEM_PROMPT,
        )
        executed_tool_calls: list[dict[str, Any]] = []
        final_response = None

        for _ in range(6):
            final_response = bound_model.invoke(langchain_messages)
            langchain_messages.append(final_response)
            response_tool_calls = getattr(final_response, "tool_calls", None) or []
            if not response_tool_calls:
                break
            for call in response_tool_calls:
                tool_name = str(call.get("name") or "").strip()
                tool_args = call.get("args") if isinstance(call.get("args"), dict) else {}
                tool = tool_map.get(tool_name)
                if tool is None:
                    tool_result: Any = {"ok": False, "error": f"tool '{tool_name}' is not available"}
                else:
                    try:
                        tool_result = tool.invoke(tool_args)
                    except Exception as exc:
                        tool_result = {"ok": False, "error": str(exc)}
                executed_tool_calls.append(
                    {
                        "id": str(call.get("id") or ""),
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                    }
                )
                langchain_messages.append(
                    ToolMessage(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=str(call.get("id") or tool_name),
                        name=tool_name,
                    )
                )

        if final_response is None:
            return None
        return AgentInvokeResult(
            content=_response_content(final_response),
            tool_calls=executed_tool_calls,
            response_metadata=getattr(final_response, "response_metadata", {}) or {},
        )


def _to_langchain_messages(
    messages: list[dict[str, Any]],
    context_prompt: str = "",
    *,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[Any]:
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    except ImportError as exc:
        raise RuntimeError("LangChain core is not installed. Install gcs_server/requirements-gcs.txt.") from exc

    out: list[Any] = [SystemMessage(content=system_prompt)]
    if context_prompt:
        out.append(SystemMessage(content=context_prompt))
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _normalize_run_mode(run_mode: str) -> str:
    clean = str(run_mode or "chat").strip().lower()
    if clean in {"general_chat", "chat"}:
        return "chat"
    if clean == "agent":
        return "agent"
    raise ValueError("run_mode must be chat or agent")


def _message_run_mode(message: dict[str, Any]) -> str:
    meta = message.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    return _normalize_run_mode(str(meta.get("run_mode") or "chat"))


def _prompt_for_mode(
    context_snapshot: dict[str, Any] | None,
    run_mode: str,
    tool_calls: list[dict[str, Any]],
) -> str:
    base_prompt = _context_prompt(context_snapshot)
    if run_mode != "agent":
        return base_prompt
    return (
        "Agent mode is enabled for this message. Use the read-only tool/context results below as current facts. "
        "If a requested tool result is unavailable or empty, say so directly. Do not invent map objects, rover pose, "
        "or telemetry values.\n"
        f"Read-only tool calls: {json.dumps(tool_calls, separators=(',', ':'), sort_keys=True)}\n"
        f"{base_prompt}"
    )


def _tool_calls(context_snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    meta = _context_meta(context_snapshot)
    snapshot = meta.get("context_snapshot")
    providers = meta.get("context_providers")
    if not isinstance(snapshot, dict) or not isinstance(providers, list):
        return []

    details = snapshot.get("details") if isinstance(snapshot.get("details"), dict) else {}
    calls: list[dict[str, Any]] = []
    provider_to_result = {
        "get_current_rover_state": snapshot.get("rover"),
        "get_scene_map_summary": snapshot.get("scene"),
        "find_objects_in_front": details.get("objects_in_front"),
        "find_objects_near_rover": details.get("objects_near_rover"),
        "find_objects_by_kind": details.get("objects_by_kind"),
        "get_current_replay_summary": details.get("current_replay"),
        "get_recent_telemetry": details.get("recent_telemetry"),
        "get_replay_session_context": details.get("replay_sessions"),
    }
    for name in providers:
        result = provider_to_result.get(str(name))
        if result is None:
            continue
        calls.append({"name": str(name), "result": result})
    return calls


def _agent_permissions(run_mode: str) -> dict[str, Any]:
    return {
        "mode": run_mode,
        "read_only": True,
        "may_publish_commands": False,
        "may_start_missions": False,
        "may_mutate_state": False,
    }


def _context_prompt(context_snapshot: dict[str, Any] | None) -> str:
    if not isinstance(context_snapshot, dict):
        return ""
    return str(context_snapshot.get("prompt") or "")


def _context_meta(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    return meta if isinstance(meta, dict) else {}


def _response_content(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _json_line(data: dict[str, Any]) -> str:
    return f"{json.dumps(data, separators=(',', ':'))}\n"
