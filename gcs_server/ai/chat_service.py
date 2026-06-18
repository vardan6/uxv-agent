from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator

from .agent_loop import AgentInvokeResult, AgentLoopRuntime, AgentToolRuntime
from .provider_registry import resolve_intent_provider, resolve_provider
from .session_store import AISessionStore
from .tool_registry import allowed_tool_names_for_source_controls


SYSTEM_PROMPT = """You are the AI chat assistant inside Remote Rover GCS.
Answer operator questions clearly and concisely.
Do not claim to control the rover, publish commands, or start missions.
If the operator asks to create a route, mission, or waypoint plan (including requests like "go around X" or "fly to Y"), tell them to switch to Agent mode using the mode toggle above the input — Agent mode has map and mission-authoring tools that can resolve object names and create missions directly. Do not ask for coordinates or details you cannot use; redirect to Agent mode instead.
If the operator asks for direct rover motion (move now, fly now, execute) without mission planning, explain that chat is read-only for live commands."""

AGENT_SYSTEM_PROMPT = """You are the operator-facing AI agent in Remote Rover GCS.
Use tools and provided context as authoritative; do not invent rover state, telemetry, or map data.
You are given a compact summary of current rover pose, mission state, and scene as authoritative facts. Detailed map objects, replay history, telemetry samples, settings, and runtime/broker config are not pre-loaded — call the matching read-only tool when the operator's question needs them.
Travel distance = path_length_m. Furthest from home/start = max_distance_from_start_m.
Prefer live rover telemetry when fresh; otherwise use last_known_replay_state and say live is unavailable.
For underspecified replay/telemetry requests, auto-resolve via tools (e.g. resolve_replay_sessions -> metrics/path/compare/aggregate) before asking for IDs.
For follow-up references like "that session" or "the first one", reuse session_ids already present in recent history before resolving a new selector.
resolve_spatial_target: pass plain-language text or a minimal target object; never an empty payload.
Operator-provided coordinates or heading are valid inputs, not unavailable telemetry.
If a tool returns {"ok": false, "error": "..."}, report it plainly; do not fabricate data.
If a failed tool result includes a `hint` or `fallback_tool` field, follow it (try the suggested tool/strategy) before asking the operator for clarification.
Mission-authoring requests must use a terminal mission-creation tool; prose alone does not create a Mission.
When the operator supplies explicit route coordinates, extract them into structured {x, y, z} waypoints and call create_mission_from_waypoints instead of refusing or treating route_hash as a draft_id.
A successful mission-creation tool call creates a durable Mission visible on the map and in the mission sidebar, while your normal text response remains visible in chat.
Creating or editing a Mission is a planning action, not rover motion. Never claim a Mission was created unless the tool result includes a mission_id.
Do not publish raw commands or bypass approval/policy. Start or stop rover motion only through execution tools that are explicitly available in the current execution mode."""

AI_CONTEXT_MESSAGE_LIMIT = 40
AI_CONTEXT_HISTORY_CHAR_BUDGET = 16000
AI_CONTEXT_SINGLE_MESSAGE_CHAR_LIMIT = 4000


class AIChatService:
    def __init__(
        self,
        store: AISessionStore,
        secret_resolver: Callable[[str], str] | None = None,
        tool_registry: Any | None = None,
        trace_store: Any | None = None,
    ):
        self._store = store
        self._secret_resolver = secret_resolver
        self._tool_registry = tool_registry
        self._agent_loop = AgentLoopRuntime(
            tool_registry=tool_registry,
            prompt_builder=_prompt_for_mode,
            system_prompt_for_mode=_system_prompt_for_run_mode,
            allowed_tool_names=_allowed_agent_tool_names,
            response_content=_response_content,
            usage_metadata=_usage_metadata,
            tool_calling_unsupported=_is_tool_calling_unsupported_error,
            trace_store=trace_store,
        )

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
        run_mode: str | None = None,
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
        clean_run_mode = _retry_run_mode(messages, run_mode)

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
        run_mode: str | None = None,
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
        clean_run_mode = _retry_run_mode(messages, run_mode)

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
        prompt_messages = _fit_messages_to_budget(messages)
        bypass_for_smalltalk = clean_run_mode == "agent" and _is_trivial_agent_smalltalk(prompt_messages)
        effective_context_snapshot = None if bypass_for_smalltalk else context_snapshot
        prompt_tool_calls: list[dict[str, Any]] = []
        agent_tooling_error: str | None = None
        should_try_tools = (
            not bypass_for_smalltalk
            and (clean_run_mode == "agent" or _should_use_read_only_tools(prompt_messages, context_snapshot))
        )
        if should_try_tools:
            started = time.perf_counter()
            agent_result = None
            try:
                for agent_event in self._stream_agent_with_tools_events(
                    model,
                    messages=prompt_messages,
                    context_snapshot=context_snapshot,
                    prompt_tool_calls=prompt_tool_calls,
                    tool_context=_tool_context_with_session(tool_context, session_id),
                    run_mode=clean_run_mode,
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
                    # The agent loop has already streamed this answer to the client as
                    # assistant_delta events while generating it; re-emitting the full
                    # content here would duplicate it (the client appends deltas). Any
                    # post-loop fallback content (e.g. repeated-tool-failure messages)
                    # still reaches the client via the assistant_message event below,
                    # which replaces the pending bubble wholesale.
                    _ctx_meta = _context_meta(context_snapshot)
                    _rag_cits = _rag_citations_from_tool_calls(agent_result.tool_calls)
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
                            "agent_trace": agent_result.trace_events,
                            "agent_trace_id": agent_result.trace_id,
                            "data_access_manifest": agent_result.data_access_manifest,
                            "prompt_context_tool_calls": prompt_tool_calls,
                            "agent_permissions": _agent_permissions(clean_run_mode),
                            "agent_stop_reason": agent_result.stop_reason,
                            "agent_iterations": agent_result.iterations,
                            "agent_smalltalk_bypass": bypass_for_smalltalk,
                            "agent_tool_fallback_error": agent_tooling_error,
                            "response_metadata": agent_result.response_metadata,
                            "usage_metadata": agent_result.usage_metadata,
                            **_ctx_meta,
                            "retrieval_citations": list(_ctx_meta.get("retrieval_citations") or []) + _rag_cits,
                        },
                    )
                    yield _json_line({"type": "assistant_message", "message": assistant_message})
                    return
        langchain_messages = _to_langchain_messages(
            prompt_messages,
            _prompt_for_mode(effective_context_snapshot, clean_run_mode, prompt_tool_calls),
            system_prompt=SYSTEM_PROMPT if bypass_for_smalltalk else (AGENT_SYSTEM_PROMPT if clean_run_mode == "agent" else SYSTEM_PROMPT),
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
            if content_out and not failed:
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
                        "tool_calls": [],
                        "prompt_context_tool_calls": prompt_tool_calls,
                        "agent_permissions": _agent_permissions(clean_run_mode),
                        "agent_smalltalk_bypass": bypass_for_smalltalk,
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
        prompt_messages = _fit_messages_to_budget(messages)
        bypass_for_smalltalk = clean_run_mode == "agent" and _is_trivial_agent_smalltalk(prompt_messages)
        effective_context_snapshot = None if bypass_for_smalltalk else context_snapshot
        prompt_tool_calls: list[dict[str, Any]] = []
        agent_tooling_error: str | None = None
        if (not bypass_for_smalltalk) and (clean_run_mode == "agent" or _should_use_read_only_tools(prompt_messages, context_snapshot)):
            started = time.perf_counter()
            try:
                agent_result = self._try_invoke_agent_with_tools(
                    model,
                    messages=prompt_messages,
                    context_snapshot=context_snapshot,
                    prompt_tool_calls=prompt_tool_calls,
                    tool_context=_tool_context_with_session(tool_context, session_id),
                    run_mode=clean_run_mode,
                )
            except Exception as exc:
                agent_result = None
                # Keep the request alive by falling back to plain invoke.
                agent_tooling_error = str(exc)
            if agent_result is not None:
                _ctx_meta = _context_meta(context_snapshot)
                _rag_cits = _rag_citations_from_tool_calls(agent_result.tool_calls)
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
                        "agent_trace": agent_result.trace_events,
                        "agent_trace_id": agent_result.trace_id,
                        "data_access_manifest": agent_result.data_access_manifest,
                        "prompt_context_tool_calls": prompt_tool_calls,
                        "agent_permissions": _agent_permissions(clean_run_mode),
                        "agent_stop_reason": agent_result.stop_reason,
                        "agent_iterations": agent_result.iterations,
                        "agent_smalltalk_bypass": bypass_for_smalltalk,
                        "agent_tool_fallback_error": agent_tooling_error,
                        "response_metadata": agent_result.response_metadata,
                        "usage_metadata": agent_result.usage_metadata,
                        **_ctx_meta,
                        "retrieval_citations": list(_ctx_meta.get("retrieval_citations") or []) + _rag_cits,
                    },
                )
        langchain_messages = _to_langchain_messages(
            prompt_messages,
            _prompt_for_mode(effective_context_snapshot, clean_run_mode, prompt_tool_calls),
            system_prompt=SYSTEM_PROMPT if bypass_for_smalltalk else (AGENT_SYSTEM_PROMPT if clean_run_mode == "agent" else SYSTEM_PROMPT),
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
                "tool_calls": [],
                "prompt_context_tool_calls": prompt_tool_calls,
                "data_access_manifest": _data_access_manifest(context_snapshot),
                "agent_permissions": _agent_permissions(clean_run_mode),
                "agent_smalltalk_bypass": bypass_for_smalltalk,
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
        run_mode: str = "agent",
    ) -> AgentInvokeResult | None:
        return self._agent_loop.invoke_with_tools(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
            run_mode=run_mode,
        )

    def _stream_agent_with_tools_events(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        run_mode: str = "agent",
    ) -> Iterator[dict[str, Any]]:
        yield from self._agent_loop.stream_tool_events(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
            run_mode=run_mode,
        )

    def _prepare_agent_tool_runtime(
        self,
        model: Any,
        *,
        messages: list[dict[str, Any]],
        context_snapshot: dict[str, Any] | None,
        prompt_tool_calls: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        run_mode: str = "agent",
    ) -> AgentToolRuntime | None:
        return self._agent_loop.prepare_tool_runtime(
            model,
            messages=messages,
            context_snapshot=context_snapshot,
            prompt_tool_calls=prompt_tool_calls,
            tool_context=tool_context,
            run_mode=run_mode,
        )


def _tool_context_with_session(tool_context: dict[str, Any] | None, session_id: str) -> dict[str, Any]:
    """Augment tool_context with session_id so the agent loop can scope its tool-result cache."""
    base = dict(tool_context) if isinstance(tool_context, dict) else {}
    if session_id and not base.get("session_id"):
        base["session_id"] = session_id
    return base


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
    if clean in {"general_chat", "chat", "intent", "rover_intent_test"}:
        return "chat"
    if clean in {"agent", "planning_shell"}:
        return "agent"
    raise ValueError("run_mode must be chat or agent")


def _retry_run_mode(messages: list[dict[str, Any]], requested_run_mode: str | None = None) -> str:
    if requested_run_mode is not None:
        return _normalize_run_mode(requested_run_mode)
    if not messages or messages[-1]["role"] != "user":
        raise ValueError("Retry requires the latest remaining message to be from the user.")
    return _message_run_mode(messages[-1])


def _fit_messages_to_budget(
    messages: list[dict[str, Any]],
    *,
    total_char_budget: int = AI_CONTEXT_HISTORY_CHAR_BUDGET,
    per_message_char_limit: int = AI_CONTEXT_SINGLE_MESSAGE_CHAR_LIMIT,
) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        return []
    kept: list[dict[str, Any]] = []
    used = 0
    for message in reversed(messages):
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if len(content) > per_message_char_limit:
            content = f"{content[:per_message_char_limit]}\n[earlier message truncated for context budget]"
        projected = used + len(content)
        if kept and projected > total_char_budget:
            continue
        next_message = dict(message)
        next_message["role"] = role
        next_message["content"] = content
        kept.append(next_message)
        used = projected
    return list(reversed(kept))


def _message_run_mode(message: dict[str, Any]) -> str:
    meta = message.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    return _normalize_run_mode(str(meta.get("run_mode") or "chat"))


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    if not isinstance(messages, list):
        return ""
    latest_user = next((message for message in reversed(messages) if message.get("role") == "user"), None)
    if not isinstance(latest_user, dict):
        return ""
    return str(latest_user.get("content") or "").strip().lower()


def _is_trivial_agent_smalltalk(messages: list[dict[str, Any]]) -> bool:
    content = _latest_user_content(messages)
    if not content:
        return False
    if len(content) > 40:
        return False
    simple = {
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "hiya",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how are you?",
    }
    return content in simple


def _system_prompt_for_run_mode(run_mode: str) -> str:
    return AGENT_SYSTEM_PROMPT if run_mode == "agent" else SYSTEM_PROMPT


def _prompt_for_mode(
    context_snapshot: dict[str, Any] | None,
    run_mode: str,
    tool_calls: list[dict[str, Any]],
    tools: list[Any] | None = None,
    data_access_manifest: dict[str, Any] | None = None,
) -> str:
    base_prompt = _context_prompt(context_snapshot)
    tool_guidance = _tool_catalog_prompt(tools)
    manifest_guidance = _data_access_manifest_prompt(data_access_manifest)
    if run_mode != "agent" and not tool_calls and not tool_guidance:
        return base_prompt
    if run_mode != "agent":
        return (
            "This chat message may use read-only rover and replay tools when needed. Use tool/context results as current facts. "
            "If live telemetry is stale, prefer the last known replay-backed state when available.\n"
            f"{tool_guidance}"
            f"{manifest_guidance}"
            f"Read-only tool/context results: {json.dumps(tool_calls, separators=(',', ':'), sort_keys=True)}\n"
            f"{base_prompt}"
        )
    context_sentence = "Use the read-only tool/context results below as current facts. " if tool_calls else ""
    tool_calls_line = f"Read-only tool calls: {json.dumps(tool_calls, separators=(',', ':'), sort_keys=True)}\n" if tool_calls else ""
    return (
        f"Agent mode is enabled for this message. {context_sentence}"
        "When the operator asks about nearby, nearest, left, right, ahead, object kinds, sessions, duration, path length, "
        "travel distance, furthest distance, settings, model routing, earlier chats, or available data surfaces, call the matching tools instead of answering from memory. "
        "Treat travel distance as path_length_m. Treat furthest from home/start as max_distance_from_start_m. "
        "For follow-up references like 'the first one in each set', prefer session_ids already named in recent conversation history. "
        "For underspecified replay requests, auto-resolve a selector (for example 'latest session with telemetry') and continue with tool calls before asking the operator for IDs. "
        "Never call resolve_spatial_target with an empty payload; pass either plain text or a minimal target object. "
        "If the operator explicitly supplies coordinates or heading for a hypothetical rover pose, pass them to object-query tools instead of treating them as unavailable telemetry. "
        "If a requested tool result is unavailable or empty, say so directly. Do not invent map objects, rover pose, "
        "or telemetry values beyond what the operator explicitly supplied.\n"
        f"{tool_guidance}"
        f"{manifest_guidance}"
        f"{tool_calls_line}"
        f"{base_prompt}"
    )


def _tool_calls(context_snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    meta = _context_meta(context_snapshot)
    snapshot = meta.get("context_snapshot")
    providers = meta.get("context_providers")
    if not isinstance(snapshot, dict) or not isinstance(providers, list):
        return []
    source_controls = meta.get("retrieval_request", {}).get("source_controls") if isinstance(meta.get("retrieval_request"), dict) else {}
    allow_replay = source_controls.get("replay_reports", True) if isinstance(source_controls, dict) else True

    details = snapshot.get("details") if isinstance(snapshot.get("details"), dict) else {}
    calls: list[dict[str, Any]] = []
    provider_to_result = {
        "get_current_rover_state": snapshot.get("rover"),
        "get_scene_summary": snapshot.get("scene"),
        "query_objects_in_front": details.get("objects_in_front"),
        "query_objects_near": details.get("objects_near_rover"),
        "query_objects_by_kind": details.get("objects_by_kind"),
        "get_current_replay_summary": details.get("current_replay") if allow_replay else None,
        "get_recent_telemetry": details.get("recent_telemetry") if allow_replay else None,
        "resolve_replay_sessions": details.get("replay_sessions") if allow_replay else None,
        "get_recent_ai_chat_history": details.get("ai_chat_history"),
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


def _allowed_agent_tool_names(context_snapshot: dict[str, Any] | None) -> set[str] | None:
    meta = _context_meta(context_snapshot)
    retrieval_request = meta.get("retrieval_request")
    source_controls = retrieval_request.get("source_controls") if isinstance(retrieval_request, dict) else {}
    if not isinstance(source_controls, dict):
        return None
    return allowed_tool_names_for_source_controls(source_controls)


def _should_use_read_only_tools(messages: list[dict[str, Any]], context_snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(messages, list) or not messages:
        return False
    latest_user = next((message for message in reversed(messages) if message.get("role") == "user"), None)
    if not isinstance(latest_user, dict):
        return False
    content = str(latest_user.get("content") or "").strip().lower()
    if not content:
        return False
    if not _allowed_agent_tool_names(context_snapshot):
        return False
    return any(
        token in content
        for token in (
            "replay",
            "session",
            "chat history",
            "previous chat",
            "earlier",
            "before",
            "settings",
            "config",
            "configuration",
            "provider",
            "routing",
            "surface",
            "source",
            "sensor",
            "camera",
            "video",
            "telemetry",
            "duration",
            "travel distance",
            "path length",
            "distance from home",
            "distance from start",
            "furthest",
            "longest",
            "current state of rover",
            "current rover state",
            "last known",
        )
    )


def _tool_catalog_prompt(tools: list[Any] | None) -> str:
    if not isinstance(tools, list) or not tools:
        return ""
    names = [
        str(getattr(tool, "name", "")).strip()
        for tool in tools
        if str(getattr(tool, "name", "")).strip()
    ]
    if not names:
        return ""
    return f"Available read-only tools: {', '.join(names)}.\n"


def _data_access_manifest_prompt(data_access_manifest: dict[str, Any] | None) -> str:
    if not isinstance(data_access_manifest, dict):
        return ""
    surfaces = data_access_manifest.get("data_surfaces")
    if not isinstance(surfaces, list):
        return ""
    parts: list[str] = []
    for surface in surfaces:
        if not isinstance(surface, dict) or not surface.get("enabled"):
            continue
        name = str(surface.get("name") or "").strip()
        enabled_tools = surface.get("enabled_tool_names")
        tool_names = enabled_tools if isinstance(enabled_tools, list) and enabled_tools else surface.get("tool_names")
        if not name or not isinstance(tool_names, list) or not tool_names:
            continue
        parts.append(f"{name}: {', '.join(str(item) for item in tool_names)}")
    if not parts:
        return ""
    return f"Available data surfaces: {'; '.join(parts)}.\n"


def _context_prompt(context_snapshot: dict[str, Any] | None) -> str:
    if not isinstance(context_snapshot, dict):
        return ""
    return str(context_snapshot.get("prompt") or "")


def _context_meta(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    return meta if isinstance(meta, dict) else {}


def _rag_citations_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for call in tool_calls:
        if str(call.get("name") or "") == "search_project_docs":
            result = call.get("result") or {}
            if isinstance(result, dict):
                for c in result.get("citations") or []:
                    if isinstance(c, dict):
                        citations.append(c)
    return citations


def _data_access_manifest(context_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    meta = _context_meta(context_snapshot)
    manifest = meta.get("data_access_manifest")
    return manifest if isinstance(manifest, dict) else None


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
