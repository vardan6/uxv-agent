from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from .provider_registry import resolve_intent_provider, resolve_provider
from .session_store import AISessionStore
from .tool_registry import DEFAULT_PERMISSIONS


SYSTEM_PROMPT = """You are the AI chat assistant inside Remote Rover GCS.
Answer operator questions clearly and concisely.
Do not claim to control the rover, publish commands, or start missions.
If the operator asks for rover movement or mission execution, explain that this chat mode is read-only."""

AGENT_SYSTEM_PROMPT = """You are the read-only AI agent inside Remote Rover GCS.
Answer operator questions using conversation history plus available tool/context results.
You may inspect rover state, map summaries, object queries, telemetry, and replay summaries.
Do not claim to control the rover, publish commands, start missions, or mutate GCS state.
If required rover, map, or sensor data is unavailable, say it is unavailable instead of guessing.
If a tool returns {"ok": false, "error": "..."}, report the failure clearly to the operator. Do not invent data to fill the gap."""

AI_CONTEXT_MESSAGE_LIMIT = 40
AI_AGENT_MAX_TOOL_ITERATIONS = 6


@dataclass(slots=True)
class AgentInvokeResult:
    content: str
    tool_calls: list[dict[str, Any]]
    response_metadata: dict[str, Any]
    usage_metadata: dict[str, Any]


@dataclass(slots=True)
class AgentToolRuntime:
    bound_model: Any
    tool_map: dict[str, Any]
    langchain_messages: list[Any]
    tool_message_cls: Any


class AIChatService:
    def __init__(
        self,
        store: AISessionStore,
        secret_resolver: Callable[[str], str] | None = None,
        tool_registry: Any | None = None,
    ):
        self._store = store
        self._secret_resolver = secret_resolver
        self._tool_registry = tool_registry

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

        resolved = _resolve_provider_for_session(config, session, self._secret_resolver)
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
        messages = self._store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
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

        messages = self._store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        if not messages:
            raise ValueError("No message is available to retry.")
        if messages[-1]["role"] == "assistant":
            self._store.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Retry requires the latest remaining message to be from the user.")
        clean_run_mode = _message_run_mode(messages[-1])

        resolved = _resolve_provider_for_session(config, session, self._secret_resolver)
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

        messages = self._store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        if not messages:
            raise ValueError("No message is available to retry.")
        if messages[-1]["role"] == "assistant":
            self._store.delete_message(messages[-1]["id"])
            messages = messages[:-1]
        if not messages or messages[-1]["role"] != "user":
            raise ValueError("Retry requires the latest remaining message to be from the user.")
        clean_run_mode = _message_run_mode(messages[-1])

        resolved = _resolve_provider_for_session(config, session, self._secret_resolver)
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

        resolved = _resolve_provider_for_session(config, session, self._secret_resolver)
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

        messages = self._store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
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
        agent_tooling_error: str | None = None
        if clean_run_mode == "agent":
            started = time.perf_counter()
            agent_result = None
            try:
                for agent_event in self._stream_agent_with_tools_events(
                    model,
                    messages=messages,
                    context_snapshot=context_snapshot,
                    prompt_tool_calls=prompt_tool_calls,
                    tool_context=tool_context,
                ):
                    if agent_event.get("type") == "_agent_result":
                        agent_result = agent_event.get("result")
                        continue
                    yield _json_line(agent_event)
            except Exception as exc:
                # Provider/tool-schema mismatches should not hard-fail the whole reply.
                # Fall back to regular non-tool generation in agent mode.
                agent_tooling_error = str(exc)
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
                            "agent_tool_fallback_error": agent_tooling_error,
                            "response_metadata": agent_result.response_metadata,
                            "usage_metadata": agent_result.usage_metadata,
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
        last_chunk: Any = None
        stream_response_metadata: dict[str, Any] = {}
        stream_usage_metadata: dict[str, Any] = {}
        interrupted = False
        failed = False
        try:
            stream = getattr(model, "stream", None)
            if callable(stream):
                for chunk in stream(langchain_messages):
                    last_chunk = chunk
                    chunk_response_metadata = getattr(chunk, "response_metadata", {}) or {}
                    if isinstance(chunk_response_metadata, dict) and chunk_response_metadata:
                        stream_response_metadata.update(chunk_response_metadata)
                    chunk_usage_metadata = _usage_metadata(chunk)
                    if chunk_usage_metadata:
                        stream_usage_metadata.update(chunk_usage_metadata)
                    delta = _response_content(chunk)
                    if not delta:
                        continue
                    parts.append(delta)
                    yield _json_line({"type": "assistant_delta", "delta": delta})
            else:
                last_chunk = model.invoke(langchain_messages)
                delta = _response_content(last_chunk)
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
                response_metadata = stream_response_metadata or (getattr(last_chunk, "response_metadata", {}) or {})
                usage_metadata = stream_usage_metadata or _usage_metadata(last_chunk)
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
                        "agent_tool_fallback_error": agent_tooling_error,
                        "interrupted": interrupted or failed,
                        "response_metadata": response_metadata,
                        "usage_metadata": usage_metadata,
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
        agent_tooling_error: str | None = None
        if clean_run_mode == "agent":
            started = time.perf_counter()
            try:
                agent_result = self._try_invoke_agent_with_tools(
                    model,
                    messages=messages,
                    context_snapshot=context_snapshot,
                    prompt_tool_calls=prompt_tool_calls,
                    tool_context=tool_context,
                )
            except Exception as exc:
                agent_result = None
                # Keep the request alive by falling back to plain invoke.
                agent_tooling_error = str(exc)
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
                        "agent_tool_fallback_error": agent_tooling_error,
                        "response_metadata": agent_result.response_metadata,
                        "usage_metadata": agent_result.usage_metadata,
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
                "agent_tool_fallback_error": agent_tooling_error,
                "response_metadata": getattr(response, "response_metadata", {}) or {},
                "usage_metadata": _usage_metadata(response),
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
        runtime = self._prepare_agent_tool_runtime(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
        )
        if runtime is None:
            return None
        executed_tool_calls: list[dict[str, Any]] = []
        final_response = None

        for _ in range(AI_AGENT_MAX_TOOL_ITERATIONS):
            try:
                final_response = runtime.bound_model.invoke(runtime.langchain_messages)
            except Exception as exc:
                if _is_tool_calling_unsupported_error(exc):
                    return None
                raise
            runtime.langchain_messages.append(final_response)
            response_tool_calls = getattr(final_response, "tool_calls", None) or []
            if not response_tool_calls:
                break
            for call in response_tool_calls:
                tool_name = str(call.get("name") or "").strip()
                tool_args = call.get("args") if isinstance(call.get("args"), dict) else {}
                tool = runtime.tool_map.get(tool_name)
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
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
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
            usage_metadata=_usage_metadata(final_response),
        )

    def _stream_agent_with_tools_events(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        runtime = self._prepare_agent_tool_runtime(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
        )
        if runtime is None:
            yield {"type": "_agent_result", "result": None}
            return

        executed_tool_calls: list[dict[str, Any]] = []
        final_response = None

        for iteration in range(1, AI_AGENT_MAX_TOOL_ITERATIONS + 1):
            try:
                final_response = runtime.bound_model.invoke(runtime.langchain_messages)
            except Exception as exc:
                if _is_tool_calling_unsupported_error(exc):
                    yield {"type": "_agent_result", "result": None}
                    return
                raise
            runtime.langchain_messages.append(final_response)
            response_tool_calls = getattr(final_response, "tool_calls", None) or []
            if not response_tool_calls:
                break
            for call in response_tool_calls:
                tool_name = str(call.get("name") or "").strip()
                tool_args = call.get("args") if isinstance(call.get("args"), dict) else {}
                tool_call_id = str(call.get("id") or tool_name)
                started = time.perf_counter()
                yield {
                    "type": "agent_tool_start",
                    "tool_call": {
                        "id": tool_call_id,
                        "name": tool_name,
                        "args": tool_args,
                        "iteration": iteration,
                    },
                }
                tool = runtime.tool_map.get(tool_name)
                if tool is None:
                    tool_result: Any = {"ok": False, "error": f"tool '{tool_name}' is not available"}
                else:
                    try:
                        tool_result = tool.invoke(tool_args)
                    except Exception as exc:
                        tool_result = {"ok": False, "error": str(exc)}
                executed_tool_call = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                }
                executed_tool_calls.append(executed_tool_call)
                yield {
                    "type": "agent_tool_result",
                    "tool_call": {
                        **executed_tool_call,
                        "iteration": iteration,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                }
                runtime.langchain_messages.append(
                    runtime.tool_message_cls(
                        content=json.dumps(tool_result, separators=(",", ":"), sort_keys=True),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                )

        if final_response is None:
            yield {"type": "_agent_result", "result": None}
            return
        yield {
            "type": "_agent_result",
            "result": AgentInvokeResult(
                content=_response_content(final_response),
                tool_calls=executed_tool_calls,
                response_metadata=getattr(final_response, "response_metadata", {}) or {},
                usage_metadata=_usage_metadata(final_response),
            ),
        }

    def _prepare_agent_tool_runtime(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
    ) -> AgentToolRuntime | None:
        if self._tool_registry is None:
            return None
        bind_tools = getattr(model, "bind_tools", None)
        if not callable(bind_tools):
            return None

        try:
            from langchain_core.messages import ToolMessage
        except ImportError as exc:
            raise RuntimeError("LangChain core is not installed. Install gcs_server/requirements-gcs.txt.") from exc

        ctx = tool_context or {}
        runtime = ctx.get("runtime")
        timezone_name = str(ctx.get("timezone_name") or "").strip()
        tools = self._tool_registry.build_langchain_tools(
            runtime,
            context_snapshot or {},
            timezone_name=timezone_name,
            permissions=set(DEFAULT_PERMISSIONS),
        )
        if not tools:
            return None

        try:
            # OpenAI Responses normalizes omitted tool strictness into strict mode,
            # which breaks our optional tool arguments (for example max_distance_m).
            # Force best-effort tool calling so the existing schemas remain valid.
            bound_model = bind_tools(tools, strict=False)
        except Exception as exc:
            if _is_tool_calling_unsupported_error(exc):
                return None
            raise
        return AgentToolRuntime(
            bound_model=bound_model,
            tool_map={str(tool.name): tool for tool in tools},
            langchain_messages=_to_langchain_messages(
                messages,
                _prompt_for_mode(context_snapshot, "agent", prompt_tool_calls),
                system_prompt=AGENT_SYSTEM_PROMPT,
            ),
            tool_message_cls=ToolMessage,
        )


def _resolve_provider_for_session(
    config: Any,
    session: dict[str, Any],
    secret_resolver: Callable[[str], str] | None,
) -> Any:
    provider_id = str(session.get("provider_id") or "")
    mode = str(session.get("mode") or "general_chat").strip()
    if mode in ("rover_intent_test", "rover_mission_planning"):
        return resolve_intent_provider(config, provider_id=provider_id, secret_resolver=secret_resolver)
    return resolve_provider(config, purpose="general_chat", provider_id=provider_id, secret_resolver=secret_resolver)


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
    if clean in {"general_chat", "chat", "workbench", "intent", "rover_intent_test"}:
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


def _usage_metadata(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", {}) or {}
    return usage if isinstance(usage, dict) else {}


def _is_tool_calling_unsupported_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    if not message:
        return False
    return (
        "does not support tools" in message
        or "does not support tool calling" in message
        or "does not support function calling" in message
        or "tool calling is not supported" in message
        or "function calling is not supported" in message
    )
