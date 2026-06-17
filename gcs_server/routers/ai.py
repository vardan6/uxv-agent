from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gcs_server.ai.agent_traces import AgentTraceStore
from gcs_server.ai.chat_service import AIChatService, AI_CONTEXT_MESSAGE_LIMIT
from gcs_server.ai.context_service import AIContextService
from gcs_server.ai.data_access import build_data_access_manifest
from gcs_server.ai.retrieval import (
    build_loaded_data_refs,
    build_retrieval_citations,
    build_retrieved_sources,
    normalize_retrieval_request,
)
from gcs_server.ai.session_store import normalize_source_controls
from gcs_server.ai.tool_registry import ToolRegistry, allowed_tool_names_for_source_controls
from gcs_server.ai.vehicle_profile import KNOWN_PROFILES, get_active_profile
from gcs_server.routers.llm import _redact_secret_text
from gcs_server.runtime import AppRuntime

router = APIRouter()


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace nan/inf float values with None so JSONResponse doesn't crash.

    MAVLink mission items use nan for unused params (e.g. yaw on a ground rover).
    Python's json.dumps allows nan by default but Starlette's JSONResponse does not.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj

_AI_SOURCE_CONTROL_LABELS = {
    "project_docs": "Project docs",
    "mission_history": "Mission history",
    "replay_reports": "Replay reports",
    "ai_chat_history": "AI chat history",
    "settings_config": "Settings/config",
    "sensor_context": "Sensor context",
    "web_research": "Web research",
}

_AI_CONTEXT_PROVIDER_LABELS = {
    "get_current_rover_state": "Current rover state snapshot",
    "get_runtime_context": "Runtime status and environment context",
    "get_settings_context": "Settings/config summary",
    "get_llm_context": "LLM provider and routing context",
    "get_current_mission_state": "Current mission state",
    "get_scene_summary": "Scene/map summary",
    "query_objects_in_front": "Objects in front of the rover",
    "query_objects_near": "Objects near the rover",
    "query_objects_by_kind": "Objects filtered by kind",
    "get_current_replay_summary": "Current replay summary",
    "get_recent_telemetry": "Recent telemetry window",
    "resolve_replay_sessions": "Replay session lookup",
    "get_recent_ai_chat_history": "Recent AI chat history",
}


class _AIStreamRun:
    def __init__(self, run_id: str, session_id: str) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self._lines: list[str] = []
        self._done = False
        self._condition = threading.Condition()
        self._cancel = threading.Event()

    def append(self, line: str) -> None:
        with self._condition:
            self._lines.append(line)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._done = True
            self._condition.notify_all()

    def stream(self) -> Any:
        index = 0
        try:
            while True:
                with self._condition:
                    while index >= len(self._lines) and not self._done:
                        self._condition.wait(timeout=0.25)
                    if index < len(self._lines):
                        line = self._lines[index]
                        index += 1
                    elif self._done:
                        break
                    else:
                        continue
                yield line
        except GeneratorExit:
            self._cancel.set()
            raise


class AIInflightStreamManager:
    def __init__(self) -> None:
        self._runs: dict[str, _AIStreamRun] = {}
        self._lock = threading.Lock()

    def start(self, runtime: AppRuntime, session_id: str, stream_factory: Any) -> _AIStreamRun:
        with self._lock:
            current = self._runs.get(session_id)
            if current is not None:
                raise ValueError("A response is already in progress for this session.")
            run = _AIStreamRun(run_id=f"ai-run-{uuid.uuid4().hex[:12]}", session_id=session_id)
            self._runs[session_id] = run

        def _worker() -> None:
            try:
                stream = stream_factory()
                for line in _stream_ai_events(stream):
                    if run._cancel.is_set():
                        break
                    run.append(line)
            finally:
                run.close()
                with self._lock:
                    active = self._runs.get(session_id)
                    if active is run:
                        self._runs.pop(session_id, None)

        runtime.ai_executor.submit(_worker)
        return run

    def get(self, session_id: str) -> _AIStreamRun | None:
        with self._lock:
            return self._runs.get(session_id)


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _ai_inflight_streams(request: Request) -> AIInflightStreamManager:
    return request.app.state.ai_inflight_streams


def _ai_chat_service(request: Request) -> AIChatService:
    return request.app.state.ai_chat_service


def _tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.tool_registry


def _agent_trace_store(request: Request) -> AgentTraceStore:
    return request.app.state.agent_trace_store


def _session_mission_snapshot(runtime: AppRuntime, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None or not str(session_id or "").strip():
        return (
            {"active": False, "status": "no_active_mission", "summary": "No backend-owned mission proposal is stored yet."},
            {"available": False, "status": "no_mission_overlay", "summary": "No mission overlay is available.", "features": [], "waypoint_count": 0, "bounds": None},
        )
    try:
        mission_state = mission_execution.get_current_mission_state(session_id=session_id)
    except Exception as exc:
        mission_state = {
            "active": False,
            "status": "mission_state_unavailable",
            "summary": f"Mission state unavailable: {exc}",
        }
    try:
        mission_overlay = mission_execution.get_revision_overlay(session_id=session_id)
    except Exception as exc:
        mission_overlay = {
            "available": False,
            "status": "mission_overlay_unavailable",
            "summary": f"Mission overlay unavailable: {exc}",
            "features": [],
            "waypoint_count": 0,
            "bounds": None,
        }
    return mission_state, mission_overlay


def _public_ai_session(
    runtime: AppRuntime,
    session: dict[str, Any],
    include_messages: bool = False,
    include_mission_overlay: bool = False,
) -> dict[str, Any]:
    out = dict(session)
    if not include_messages:
        out.pop("messages", None)
    out["source_controls"] = normalize_source_controls(out.get("source_controls"))
    session_id = str(out.get("id") or "")
    mission_state, mission_overlay = _session_mission_snapshot(runtime, session_id)
    out["mission_state"] = mission_state
    if include_mission_overlay:
        out["mission_overlay"] = mission_overlay
    return out


def _tool_permission_label(value: Any) -> str:
    labels = {
        "read_only": "read-only",
        "analysis": "analysis",
        "planning": "planning",
        "command_staging": "command staging",
        "execution": "execution",
    }
    key = str(value or "").strip().lower()
    return labels.get(key, key or "unknown")


def _format_retrieval_surfaces_markdown(session_id: str, source_controls: dict[str, bool]) -> str:
    retrieval_request = normalize_retrieval_request({"source_controls": source_controls}, session_id=session_id)
    sources = build_retrieved_sources(retrieval_request=retrieval_request, session_id=session_id)
    enabled_sources = [source for source in sources if source_controls.get(str(source.get("source", "")))]
    disabled_keys = [key for key, enabled in source_controls.items() if not enabled]

    lines = ["## Retrieval Surfaces", ""]
    if enabled_sources:
        lines.append("Enabled for this session:")
        for source in enabled_sources:
            label = str(source.get("source", "source")).replace("_", " ")
            status = str(source.get("status", "planned"))
            note = str(source.get("note", "")).strip()
            lines.append(f"- `{label}`: {status}")
            if note:
                lines.append(f"  {note}")
    else:
        lines.append("No retrieval surfaces are enabled for this session.")

    if disabled_keys:
        lines.extend(["", "Disabled for this session:"])
        for key in disabled_keys:
            lines.append(f"- `{key.replace('_', ' ')}`")
    return "\n".join(lines).strip()


def _format_tool_catalog_markdown_brief(
    tool_registry: ToolRegistry,
    *,
    source_controls: dict[str, Any] | None = None,
) -> str:
    allowed_tool_names = allowed_tool_names_for_source_controls(source_controls)
    definitions = [definition for definition in tool_registry.definitions() if definition.name in allowed_tool_names]
    count = len(definitions)
    noun = "tool" if count == 1 else "tools"
    lines = ["## Agent Tools", "", f"{count} {noun} available in agent mode.", ""]
    for definition in definitions:
        lines.append(f"- **`{definition.name}`**: {definition.description}")
    return "\n".join(lines).strip()


def _format_tool_catalog_markdown_full(
    tool_registry: ToolRegistry,
    *,
    source_controls: dict[str, Any] | None = None,
) -> str:
    allowed_tool_names = allowed_tool_names_for_source_controls(source_controls)
    definitions = [definition for definition in tool_registry.definitions() if definition.name in allowed_tool_names]
    lines = ["## Agent Tools", ""]
    count = len(definitions)
    noun = "tool" if count == 1 else "tools"
    lines.append(f"{count} {noun} available in agent mode.")
    for definition in definitions:
        permission = _tool_permission_label(definition.permission)
        lines.extend([
            "",
            f"### `{definition.name}`",
            f"- Permission: `{permission}`",
            f"- Tier: `{definition.tier}`",
            f"- Description: {definition.description}",
        ])
        contract = definition.contract if isinstance(definition.contract, dict) else {}
        inputs = contract.get("inputs")
        required = contract.get("required_inputs")
        upstream = contract.get("upstream_from_tools")
        returns = contract.get("returns")
        downstream = contract.get("next_tools")
        if isinstance(inputs, dict) and inputs:
            lines.append(f"- Inputs: {_format_contract_mapping(inputs)}")
        if isinstance(required, list) and required:
            lines.append(f"- Required inputs: `{', '.join(str(item) for item in required)}`")
        if definition.required_scopes:
            lines.append(f"- Required scopes: `{', '.join(sorted(definition.required_scopes))}`")
        if definition.side_effects:
            lines.append(f"- Side effects: `{', '.join(sorted(definition.side_effects))}`")
        if isinstance(upstream, list) and upstream:
            lines.append(f"- Upstream sources: `{', '.join(str(item) for item in upstream)}`")
        if isinstance(returns, dict) and returns:
            lines.append(f"- Returns: {_format_contract_mapping(returns)}")
        if isinstance(downstream, list) and downstream:
            lines.append(f"- Next tools: `{', '.join(str(item) for item in downstream)}`")
    return "\n".join(lines).strip()


def _format_contract_mapping(values: dict[str, Any]) -> str:
    return ", ".join(f"`{key}`: `{value}`" for key, value in values.items())


def _format_compact_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _latest_assistant_message(session: dict[str, Any]) -> dict[str, Any] | None:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role", "")) == "assistant":
            return message
    return None


def _format_agent_tool_activity_markdown(session: dict[str, Any]) -> str:
    messages = session.get("messages")
    if not isinstance(messages, list):
        return "## Agent Tool Activity\n\nNo message history is available for this session."
    for message in reversed(messages):
        if str(message.get("role", "")) != "assistant":
            continue
        meta = message.get("meta")
        if not isinstance(meta, dict):
            continue
        tool_calls = meta.get("agent_tool_progress")
        if not isinstance(tool_calls, list) or not tool_calls:
            tool_calls = meta.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            continue
        lines = ["## Agent Tool Activity", ""]
        created_at = message.get("created_at")
        if created_at is not None:
            lines.append(f"Latest assistant message: `{created_at}`")
            lines.append("")
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or call.get("tool") or "tool")
            status = str(call.get("status") or ("complete" if call.get("result") is not None else "recorded"))
            lines.append(f"- `{name}`: {status}")
        return "\n".join(lines).strip()
    return "## Agent Tool Activity\n\nNo agent tool activity has been recorded in this session yet."


def _format_context_markdown(session: dict[str, Any]) -> str:
    message = _latest_assistant_message(session)
    if message is None:
        return "## Context\n\nNo assistant message is available for this session yet."
    meta = message.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    provider_name = str(message.get("provider_id") or "unknown")
    model_id = str(message.get("model_id") or "").strip()
    source_controls = normalize_source_controls(session.get("source_controls"))
    providers = [item for item in meta.get("context_providers") or [] if item]
    retrieved_sources = [item for item in meta.get("retrieved_sources") or [] if isinstance(item, dict)]
    loaded_refs = [item for item in meta.get("loaded_data_refs") or [] if isinstance(item, dict)]
    dropped_sections = [item for item in meta.get("dropped_sections") or [] if item]
    input_tok = (meta.get("usage_metadata") or {}).get("input_tokens")
    if input_tok is None:
        rm = meta.get("response_metadata") or {}
        usage = rm.get("usage_metadata") or rm.get("token_usage") or rm.get("usage") or {}
        input_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("prompt_eval_count")
    context_window = message.get("context_window") or session.get("context_window") or 0
    estimated_chars = meta.get("estimated_chars")
    budget_chars = meta.get("budget_chars")

    lines = ["## Context", ""]
    created_at = message.get("created_at")
    if created_at is not None:
        lines.append(f"Latest assistant message: `{created_at}`")
        lines.append("")
    lines.append("Summary:")
    lines.append(f"- Provider: `{provider_name}`{f' · `{model_id}`' if model_id else ''}")
    try:
        input_tok_num = float(input_tok)
    except (TypeError, ValueError):
        input_tok_num = None
    try:
        ctx_max_num = float(context_window)
    except (TypeError, ValueError):
        ctx_max_num = 0.0
    if input_tok_num is not None and ctx_max_num > 0:
        pct = max(0, min(100, round((input_tok_num / ctx_max_num) * 100)))
        lines.append(f"- Prompt window use: `{_format_compact_number(input_tok_num)} / {_format_compact_number(ctx_max_num)} tok ({pct}%)`")
    elif input_tok_num is not None:
        lines.append(f"- Prompt window use: `{_format_compact_number(input_tok_num)} tok`")
    try:
        estimated_chars_num = float(estimated_chars)
        budget_chars_num = float(budget_chars)
    except (TypeError, ValueError):
        estimated_chars_num = None
        budget_chars_num = None
    if estimated_chars_num is not None and budget_chars_num is not None and budget_chars_num > 0:
        lines.append(
            f"- Compact-context size estimate: `{_format_compact_number(estimated_chars_num)} / {_format_compact_number(budget_chars_num)} chars`"
        )
    enabled_count = sum(1 for value in source_controls.values() if value)
    lines.append(f"- Session source controls enabled: `{enabled_count}/{len(source_controls)}`")
    if providers:
        lines.append(f"- Context providers used: `{len(providers)}`")
    if retrieved_sources:
        lines.append(f"- Retrieval sources recorded: `{len(retrieved_sources)}`")
    if loaded_refs:
        lines.append(f"- Loaded context blocks: `{len(loaded_refs)}`")
    if dropped_sections:
        lines.append(f"- Trimmed sections: `{len(dropped_sections)}`")

    if providers:
        lines.extend(["", "Context providers", "This is what the old `6 sources` count was referring to."])
        for name in providers:
            label = _AI_CONTEXT_PROVIDER_LABELS.get(str(name), str(name))
            lines.append(f"- `{name}`: {label}")

    if retrieved_sources:
        lines.extend(["", "Retrieval sources"])
        for source in retrieved_sources:
            key = str(source.get("source") or "")
            label = _AI_SOURCE_CONTROL_LABELS.get(key, key or "source")
            status = str(source.get("status") or "unknown")
            requested = "lazy-loaded in this turn" if source.get("requested") else "not loaded in this turn"
            note = str(source.get("note") or "").strip()
            line = f"- `{label}` (`{key}`): {status}; {requested}"
            if note:
                line += f"; {note}"
            lines.append(line)

    if loaded_refs:
        lines.extend(["", "Loaded context blocks"])
        for ref in loaded_refs:
            source_key = str(ref.get("source") or "")
            source_label = _AI_SOURCE_CONTROL_LABELS.get(source_key, source_key or "source")
            ref_name = str(ref.get("ref") or "unknown")
            status = str(ref.get("status") or "unknown")
            extras: list[str] = []
            if ref.get("branch"):
                extras.append(f"branch: `{ref['branch']}`")
            if ref.get("message_count") is not None:
                extras.append(f"messages: `{ref['message_count']}`")
            line = f"- `{source_label}`: `{ref_name}` ({status})"
            if extras:
                line += f"; {' · '.join(extras)}"
            lines.append(line)

    if dropped_sections:
        lines.extend(["", "Trimmed sections"])
        for section in dropped_sections:
            lines.append(f"- `{section}`")

    return "\n".join(lines).strip()


def _build_ai_session_command_response(
    runtime: AppRuntime,
    tool_registry: ToolRegistry,
    session_id: str,
    command: str,
) -> tuple[str, str]:
    normalized = str(command or "").strip().lower()
    include_messages = normalized in {"tool-activity", "context"}
    session = runtime.ai_store.get_session(session_id, include_messages=include_messages)
    if session is None:
        raise KeyError("AI session not found")
    source_controls = normalize_source_controls(session.get("source_controls"))
    if normalized == "retrieval-surfaces":
        return "/retrieval-surfaces", _format_retrieval_surfaces_markdown(session_id, source_controls)
    if normalized == "tool-activity":
        return "/tool-activity", _format_agent_tool_activity_markdown(session)
    if normalized == "context":
        return "/context", _format_context_markdown(session)
    if normalized == "capabilities brief":
        retrieval = _format_retrieval_surfaces_markdown(session_id, source_controls)
        tools = _format_tool_catalog_markdown_brief(tool_registry, source_controls=source_controls)
        return "/capabilities brief", f"{retrieval}\n\n{tools}"
    if normalized == "capabilities full":
        retrieval = _format_retrieval_surfaces_markdown(session_id, source_controls)
        tools = _format_tool_catalog_markdown_full(tool_registry, source_controls=source_controls)
        return "/capabilities full", f"{retrieval}\n\n{tools}"
    raise ValueError(f"unsupported command '{command}'")


def _request_timezone_name(request: Request, payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict):
        clean = str(payload.get("timezone", "")).strip()
        if clean:
            return clean
    return str(request.headers.get("x-operator-timezone", "")).strip()


async def _ai_context_snapshot(
    runtime: AppRuntime,
    tool_registry: ToolRegistry,
    user_message: str = "",
    session_id: str = "",
    timezone_name: str = "",
    run_mode: str = "chat",
) -> dict[str, Any]:
    session = runtime.ai_store.get_session(session_id, include_messages=False) if session_id else None
    source_controls = normalize_source_controls((session or {}).get("source_controls"))
    snapshot = await AIContextService(runtime).build_compact_context(
        user_message,
        session_id=session_id,
        timezone_name=timezone_name,
        run_mode=run_mode,
        source_controls=source_controls,
    )
    full_ctx = snapshot.meta.get("context_snapshot") if isinstance(snapshot.meta, dict) else {}
    details = (full_ctx or {}).get("details") if isinstance(full_ctx, dict) else {}
    replay_summary = details.get("current_replay") if isinstance(details, dict) else {}
    chat_history_summary = details.get("ai_chat_history") if isinstance(details, dict) else {}
    settings_summary = (full_ctx or {}).get("settings") if isinstance(full_ctx, dict) else {}
    rover_state = (full_ctx or {}).get("rover") if isinstance(full_ctx, dict) else {}
    runtime_summary = (full_ctx or {}).get("runtime") if isinstance(full_ctx, dict) else {}
    retrieval_request = normalize_retrieval_request(
        {"source_controls": source_controls},
        user_prompt=user_message,
        session_id=session_id,
    )
    sensor_summary = {
        "telemetry_fresh": (rover_state or {}).get("telemetry_fresh"),
        "camera_fresh": (rover_state or {}).get("camera_fresh"),
        "video_delivery": (runtime_summary or {}).get("video"),
    }
    retrieved_sources = build_retrieved_sources(
        retrieval_request=retrieval_request,
        session_id=session_id,
        replay_summary=replay_summary if isinstance(replay_summary, dict) else {},
        chat_history_summary=chat_history_summary if isinstance(chat_history_summary, dict) else {},
        settings_summary=settings_summary if isinstance(settings_summary, dict) else {},
        sensor_summary=sensor_summary,
    )
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=session_id,
        replay_summary=replay_summary if isinstance(replay_summary, dict) else {},
        chat_history_summary=chat_history_summary if isinstance(chat_history_summary, dict) else {},
        settings_summary=settings_summary if isinstance(settings_summary, dict) else {},
        sensor_summary=sensor_summary,
    )
    meta = dict(snapshot.meta)
    meta["retrieval_request"] = retrieval_request
    meta["retrieved_sources"] = retrieved_sources
    meta["loaded_data_refs"] = loaded_data_refs
    meta["retrieval_citations"] = build_retrieval_citations(retrieved_sources, loaded_data_refs)
    meta["data_access_manifest"] = build_data_access_manifest(
        tool_registry.definitions(),
        allowed_tool_names=allowed_tool_names_for_source_controls(source_controls),
    )
    return {"prompt": snapshot.prompt, "meta": meta}


def _latest_user_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _latest_user_run_mode(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        meta = message.get("meta")
        if not isinstance(meta, dict):
            return "chat"
        clean = str(meta.get("run_mode") or "chat").strip().lower()
        return "agent" if clean == "agent" else "chat"
    return "chat"


def _payload_or_latest_user_run_mode(payload: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    if "run_mode" in payload:
        return _ai_run_mode(payload)
    return _latest_user_run_mode(messages)


def _ai_run_mode(payload: dict[str, Any]) -> str:
    clean = str(payload.get("run_mode", "chat")).strip().lower()
    if clean in {"", "chat", "general_chat", "intent", "rover_intent_test"}:
        return "chat"
    if clean in {"agent", "planning_shell"}:
        return "agent"
    raise HTTPException(status_code=400, detail="run_mode must be chat or agent")


async def _run_ai_call(runtime: AppRuntime, func, *args) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(runtime.ai_executor, func, *args)


def _llm_provider_http_exception(exc: Exception) -> HTTPException | None:
    try:
        import httpx
    except ImportError:
        httpx = None

    if httpx is not None:
        if isinstance(exc, httpx.TimeoutException):
            return HTTPException(status_code=504, detail="LLM provider request timed out.")
        if isinstance(exc, httpx.ConnectError):
            return HTTPException(status_code=503, detail="Could not connect to the LLM provider.")
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                return HTTPException(status_code=400, detail="LLM provider model or endpoint was not found. Check the model ID and base URL.")
            if status_code == 429:
                return HTTPException(status_code=429, detail="LLM provider rate limit or quota was reached.")
            return HTTPException(status_code=502, detail=f"LLM provider request failed with HTTP {status_code}.")

    try:
        import ollama
    except ImportError:
        ollama = None

    if ollama is not None:
        response_error = getattr(ollama, "ResponseError", None)
        if response_error and isinstance(exc, response_error):
            status_code = int(getattr(exc, "status_code", 0) or 0)
            message = str(getattr(exc, "error", "") or exc).strip() or "Ollama request failed."
            if status_code == 404:
                return HTTPException(status_code=400, detail=f"Ollama model was not found. Pull the model or check model_id. {message}")
            return HTTPException(status_code=502, detail=message)

    try:
        import openai
    except ImportError:
        return None

    authentication_error = getattr(openai, "AuthenticationError", None)
    permission_denied_error = getattr(openai, "PermissionDeniedError", None)
    not_found_error = getattr(openai, "NotFoundError", None)
    bad_request_error = getattr(openai, "BadRequestError", None)
    rate_limit_error = getattr(openai, "RateLimitError", None)
    timeout_error = getattr(openai, "APITimeoutError", None)
    connection_error = getattr(openai, "APIConnectionError", None)
    status_error = getattr(openai, "APIStatusError", None)

    if authentication_error and isinstance(exc, authentication_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider authentication failed. Check the configured API key.",
        )
    if permission_denied_error and isinstance(exc, permission_denied_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider permission denied. Check API key access for this model.",
        )
    if not_found_error and isinstance(exc, not_found_error):
        return HTTPException(
            status_code=400,
            detail="LLM provider model or endpoint was not found. Check the model ID and base URL.",
        )
    if bad_request_error and isinstance(exc, bad_request_error):
        return HTTPException(
            status_code=400,
            detail=_llm_provider_error_detail(exc, "LLM provider rejected the request."),
        )
    if rate_limit_error and isinstance(exc, rate_limit_error):
        return HTTPException(status_code=429, detail="LLM provider rate limit or quota was reached.")
    if timeout_error and isinstance(exc, timeout_error):
        return HTTPException(status_code=504, detail="LLM provider request timed out.")
    if connection_error and isinstance(exc, connection_error):
        return HTTPException(status_code=503, detail="Could not connect to the LLM provider.")
    if status_error and isinstance(exc, status_error):
        return HTTPException(
            status_code=502,
            detail=_llm_provider_error_detail(exc, "LLM provider request failed."),
        )
    return None


def _llm_provider_error_detail(exc: Exception, fallback: str) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        for key in ("detail", "message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return _redact_secret_text(value.strip())
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return _redact_secret_text(value["message"].strip())
    return _redact_secret_text(fallback)


def _ai_stream_error_line(detail: str) -> str:
    return f"{json.dumps({'type': 'error', 'detail': detail}, separators=(',', ':'))}\n"


def _llm_stream_error_detail(exc: Exception) -> str:
    provider_error = _llm_provider_http_exception(exc)
    if provider_error is not None:
        return str(provider_error.detail)
    return str(exc) or "Chat streaming failed."


def _stream_ai_events(stream: Any) -> Any:
    try:
        yield from stream
    except (KeyError, ValueError, RuntimeError) as exc:
        yield _ai_stream_error_line(str(exc))
    except Exception as exc:
        yield _ai_stream_error_line(_llm_stream_error_detail(exc))


def _mission_export_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "file_path": result.get("file_path", ""),
        "waypoint_count": result.get("waypoint_count", 0),
        "vehicle_type": result.get("vehicle_type", 0),
    }


@router.get("/api/ai/sessions")
async def list_ai_sessions(
    request: Request,
    include_archived: bool = False,
    archived_only: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    runtime = _runtime(request)
    sessions = runtime.ai_store.list_sessions(
        limit=limit,
        include_archived=include_archived,
        archived_only=archived_only,
    )
    return {"sessions": [_public_ai_session(runtime, session) for session in sessions]}


@router.get("/api/ai/missions")
async def list_missions(
    request: Request,
    user_id: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Flat Mission list for the sidebar (ADR 0021 §2): one row = one Mission.

    Single-user today, so `user_id` defaults to "" and matches MissionStore's
    per-user filtering; multi-user auth would source it from the request.
    """
    runtime = _runtime(request)
    missions = runtime.mission_store.list_missions(user_id=user_id, limit=limit)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is not None:
        for m in missions:
            active = sessions.get_for_mission(str(m.get("id") or ""))
            m["session_status"] = active.status if active is not None else ""
    return {"missions": missions}


@router.post("/api/ai/missions")
async def create_blank_mission(request: Request) -> JSONResponse:
    """Create a blank manual Mission with an empty revision ready for waypoint placement.

    Used by the map widget "➕ New mission" button. The resulting Mission has
    no waypoints; the operator places them by clicking on the map in add mode.
    """
    runtime = _runtime(request)
    mission_store = getattr(runtime, "mission_store", None)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_store is None or mission_execution is None:
        raise HTTPException(status_code=503, detail="mission services unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    name = str(payload.get("name", "") or "New mission").strip() or "New mission"
    user_id = str(payload.get("user_id", "") or "")
    waypoints_raw = payload.get("waypoints")
    waypoints = [wp for wp in waypoints_raw if isinstance(wp, dict)] if isinstance(waypoints_raw, list) else None

    op_result = mission_execution.create_blank_operation(name=name, waypoints=waypoints)
    if not op_result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": op_result.get("error", "failed to create operation")},
            status_code=500,
        )
    operation_id = str(op_result.get("operation_id") or "")

    try:
        mission = mission_store.create_mission(user_id=user_id, name=name, origin="manual")
        mission_id = str(mission.get("id") or "")
        if not mission_id:
            raise RuntimeError("failed to create mission")
    except Exception as exc:
        mission_execution.delete_operation(operation_id)
        return JSONResponse({"ok": False, "error": str(exc) or "failed to create mission"}, status_code=500)

    mission_store.set_active_operation(mission_id, operation_id=operation_id)

    return JSONResponse(
        {
            "ok": True,
            "mission_id": mission_id,
            "operation_id": operation_id,
            "revision_id": str(op_result.get("revision_id") or ""),
        },
        status_code=201,
    )


@router.post("/api/ai/missions/draw-pattern")
async def create_drawn_pattern_mission(request: Request) -> JSONResponse:
    """Operator-drawn pattern → new Mission (Phase 4 authoring UX).

    The map's basemap draw mode POSTs the sketched WGS84 vertices plus pattern
    params; the execution service converts them to the local frame, runs the
    corridor/survey generator, and persists the nav subtree as a new proposal.
    We then bridge that operation to a flat manual Mission so it appears in the
    sidebar (mirroring the planner's store_draft bridge).
    """
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    result = mission_execution.create_drawn_pattern_mission(
        session_id=str(payload.get("session_id", "") or ""),
        pattern=str(payload.get("pattern", "") or ""),
        points=payload.get("points") if isinstance(payload.get("points"), list) else [],
        params=payload.get("params") if isinstance(payload.get("params"), dict) else {},
        name=str(payload.get("name", "") or ""),
        constraints_store=getattr(runtime, "operational_constraints_store", None),
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)

    operation_id = str(result.get("operation_id") or "")
    mission_store = getattr(runtime, "mission_store", None)
    mission_id = ""
    if mission_store is not None and operation_id:
        try:
            existing = mission_store.get_by_operation_id(operation_id)
            if existing is not None:
                mission_id = str(existing.get("id") or "")
                mission_store.bump_client_version(mission_id)
            else:
                revision = result.get("revision") or {}
                created = mission_store.create_mission(
                    user_id=str(payload.get("user_id", "") or ""),
                    name=str((revision.get("mission") or {}).get("goal") or "")
                    or str(payload.get("name", "") or "")
                    or "Drawn pattern",
                    origin="manual",
                )
                mission_id = str(created.get("id") or "")
                if mission_id:
                    mission_store.set_active_operation(mission_id, operation_id=operation_id)
                    # Pin the Mission's ADR 0022 datum to the origin the draw path
                    # anchored on (first drawn vertex), so the row's coordinate
                    # frame matches the stored waypoints instead of scene fallback.
                    datum = result.get("origin_datum")
                    if isinstance(datum, dict):
                        try:
                            from ai.coordinate_frame import Origin
                        except ImportError:
                            from gcs_server.ai.coordinate_frame import Origin
                        mission_store.set_origin_datum(
                            mission_id, datum=Origin.from_dict(datum)
                        )
        except Exception as exc:
            result["mission_bridge_error"] = str(exc)

    result["mission_id"] = mission_id
    return JSONResponse(result)


@router.post("/api/ai/missions/{mission_id}/geofence")
async def set_mission_geofence(mission_id: str, request: Request) -> JSONResponse:
    """Operator-drawn geofence → fenced revision on an existing Mission (Phase 5).

    The basemap draw mode POSTs the sketched WGS84 polygon (and optional rally
    points / alt band); the execution service appends a revision carrying the
    fence inside mission content, which :func:`build_mission_executor` then
    enforces early and uploads to the FC. POST with ``{"clear": true}`` removes
    the fence.
    """
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    mission_store = getattr(runtime, "mission_store", None)
    if mission_execution is None or mission_store is None:
        raise HTTPException(status_code=503, detail="mission services unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    mission = mission_store.get_mission(str(mission_id or "").strip())
    if mission is None:
        raise HTTPException(status_code=404, detail=f"mission '{mission_id}' not found")
    operation_id = str(mission.get("active_operation_id") or "").strip()
    if not operation_id:
        return JSONResponse(
            {"ok": False, "error": f"mission '{mission_id}' has no active operation to fence"},
            status_code=400,
        )

    clear = bool(payload.get("clear"))
    geofence: dict[str, Any] | None = None
    if not clear:
        polygon = payload.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            return JSONResponse(
                {"ok": False, "error": "polygon must be a list of at least three {lat, lon} vertices (or pass clear=true)"},
                status_code=400,
            )
        geofence = {
            "polygon": polygon,
            "rally_points": payload.get("rally_points") if isinstance(payload.get("rally_points"), list) else [],
        }
        if payload.get("min_alt") is not None:
            geofence["min_alt"] = payload.get("min_alt")
        if payload.get("max_alt") is not None:
            geofence["max_alt"] = payload.get("max_alt")

    result = mission_execution.set_operation_geofence(
        session_id=str(payload.get("session_id", "") or ""),
        operation_id=operation_id,
        geofence=geofence,
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    try:
        mission_store.bump_client_version(str(mission_id or "").strip())
    except Exception as exc:
        result["mission_bump_error"] = str(exc)
    result["mission_id"] = str(mission_id or "").strip()
    return JSONResponse(result)


@router.delete("/api/ai/missions/{mission_id}")
async def delete_mission(mission_id: str, request: Request) -> JSONResponse:
    """Delete a flat Mission by id.

    Refuses while the Mission is executing or while a Confirm-mode run is armed
    / awaiting confirmation for that Mission.
    """
    runtime = _runtime(request)
    mission_store = getattr(runtime, "mission_store", None)
    if mission_store is None:
        raise HTTPException(status_code=503, detail="mission store unavailable")
    mid = str(mission_id or "").strip()
    mission = mission_store.get_mission(mid)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"mission '{mission_id}' not found")
    status = str((mission.get("activeRevisionStatus") or mission.get("active_revision_status") or "")).strip()
    if status == "executing":
        return JSONResponse({"ok": False, "error": "cannot delete a mission that is currently executing"}, status_code=409)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    active = sessions.get_for_mission(mid) if sessions is not None else None
    active_status = str(getattr(active, "status", "") or "").strip()
    if active_status in {"armed", "awaiting_confirm", "running"}:
        return JSONResponse(
            {
                "ok": False,
                "error": "cannot delete a mission that is armed, awaiting confirmation, or running",
                "execution_status": active_status,
            },
            status_code=409,
        )
    ok = mission_store.delete_mission(mid)
    if not ok:
        raise HTTPException(status_code=404, detail=f"mission '{mission_id}' not found")
    return JSONResponse({"ok": True, "mission_id": mid})


@router.patch("/api/ai/missions/{mission_id}")
async def rename_mission_endpoint(mission_id: str, request: Request) -> JSONResponse:
    """Update a flat Mission. PATCH with {name} to rename and/or {color} to set
    the persisted per-Mission colour override (empty string clears it)."""
    runtime = _runtime(request)
    mission_store = getattr(runtime, "mission_store", None)
    if mission_store is None:
        raise HTTPException(status_code=503, detail="mission store unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    has_name = "name" in payload
    has_color = "color" in payload
    if not has_name and not has_color:
        return JSONResponse({"ok": False, "error": "provide at least one of: name, color"}, status_code=400)
    mid = str(mission_id or "").strip()
    updated = None
    if has_name:
        name = str(payload.get("name", "") or "").strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name must be a non-empty string"}, status_code=400)
        updated = mission_store.rename_mission(mid, name=name)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"mission '{mission_id}' not found")
    if has_color:
        # Empty string is a valid value here: it clears the override.
        color = str(payload.get("color", "") or "").strip()
        updated = mission_store.set_color(mid, color=color)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"mission '{mission_id}' not found")
    return JSONResponse({"ok": True, "mission": updated})


@router.post("/api/ai/sessions")
async def create_ai_session(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="session payload must be an object")
    session = runtime.ai_store.create_session(
        title=str(payload.get("title", "New chat")),
        mode=str(payload.get("mode", "general_chat")),
        provider_id=str(payload.get("provider_id", "")),
        source_controls=payload.get("source_controls"),
    )
    return JSONResponse({"ok": True, "session": _public_ai_session(runtime, session)})


@router.get("/api/ai/sessions/{session_id}")
async def get_ai_session(session_id: str, request: Request, include_archived: bool = False) -> dict[str, Any]:
    runtime = _runtime(request)
    session = runtime.ai_store.get_session(session_id, include_messages=True)
    if session is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    if session.get("archived_at") is not None and not include_archived:
        raise HTTPException(status_code=404, detail="AI session not found")
    return {"session": _public_ai_session(runtime, session, include_messages=True, include_mission_overlay=True)}


@router.post("/api/ai/sessions/{session_id}/commands")
async def run_ai_session_command(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="command payload must be an object")
    try:
        raw_command, assistant_content = _build_ai_session_command_response(
            runtime,
            _tool_registry(request),
            session_id,
            str(payload.get("command", "")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_message = runtime.ai_store.add_message(
        session_id,
        role="user",
        content=raw_command,
        meta={"run_mode": "chat", "local_command": raw_command},
    )
    assistant_message = runtime.ai_store.add_message(
        session_id,
        role="assistant",
        content=assistant_content,
        meta={"run_mode": "chat", "local_command": raw_command},
    )
    return JSONResponse({
        "ok": True,
        "user_message": user_message,
        "assistant_message": assistant_message,
    })


@router.patch("/api/ai/sessions/{session_id}")
async def update_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="session payload must be an object")
    session = runtime.ai_store.update_session(
        session_id,
        title=str(payload["title"]) if "title" in payload else None,
        provider_id=str(payload["provider_id"]) if "provider_id" in payload else None,
        mode=str(payload["mode"]) if "mode" in payload else None,
        source_controls=payload["source_controls"] if "source_controls" in payload else None,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "session": _public_ai_session(runtime, session)})


@router.delete("/api/ai/sessions/{session_id}")
async def archive_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.archive_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "archived_session_id": session_id})


@router.post("/api/ai/sessions/{session_id}/restore")
async def restore_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.restore_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    session = runtime.ai_store.get_session(session_id, include_messages=False)
    return JSONResponse({"ok": True, "session": _public_ai_session(runtime, session or {})})


@router.delete("/api/ai/sessions/{session_id}/purge")
async def purge_ai_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    if not runtime.ai_store.purge_session(session_id):
        raise HTTPException(status_code=404, detail="AI session not found")
    return JSONResponse({"ok": True, "deleted_session_id": session_id})


@router.post("/api/ai/sessions/{session_id}/messages")
async def send_ai_message(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    content = str(payload.get("content", ""))
    run_mode = _ai_run_mode(payload)
    timezone_name = _request_timezone_name(request, payload)
    try:
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            content,
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        result = await _run_ai_call(
            runtime,
            _ai_chat_service(request).send_message,
            runtime.config,
            session_id,
            content,
            context_snapshot,
            run_mode,
            {"timezone_name": timezone_name, "runtime": runtime},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return JSONResponse({"ok": True, **result})


@router.post("/api/ai/sessions/{session_id}/messages/stream")
async def send_ai_message_stream(session_id: str, request: Request) -> StreamingResponse:
    inflight = _ai_inflight_streams(request)
    resume = request.query_params.get("resume", "").strip().lower() in {"1", "true", "yes"}
    if resume:
        run = inflight.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No in-progress response for this session.")
        return StreamingResponse(run.stream(), media_type="application/x-ndjson")

    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    content = str(payload.get("content", ""))
    run_mode = _ai_run_mode(payload)
    timezone_name = _request_timezone_name(request, payload)
    try:
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            content,
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        def _stream_factory() -> Any:
            return _ai_chat_service(request).stream_message_events(
                runtime.config,
                session_id,
                content,
                context_snapshot,
                run_mode,
                {"timezone_name": timezone_name, "runtime": runtime},
            )
        run = inflight.start(runtime, session_id, _stream_factory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return StreamingResponse(run.stream(), media_type="application/x-ndjson")


@router.post("/api/ai/sessions/{session_id}/retry")
async def retry_ai_message(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    timezone_name = _request_timezone_name(request, payload)
    try:
        messages = runtime.ai_store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        run_mode = _payload_or_latest_user_run_mode(payload, messages)
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            _latest_user_content(messages),
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        result = await _run_ai_call(
            runtime,
            _ai_chat_service(request).retry_last_response,
            runtime.config,
            session_id,
            context_snapshot,
            run_mode,
            {"timezone_name": timezone_name, "runtime": runtime},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return JSONResponse({"ok": True, **result})


@router.post("/api/ai/sessions/{session_id}/retry/stream")
async def retry_ai_message_stream(session_id: str, request: Request) -> StreamingResponse:
    inflight = _ai_inflight_streams(request)
    resume = request.query_params.get("resume", "").strip().lower() in {"1", "true", "yes"}
    if resume:
        run = inflight.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No in-progress response for this session.")
        return StreamingResponse(run.stream(), media_type="application/x-ndjson")

    runtime = _runtime(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="message payload must be an object")
    timezone_name = _request_timezone_name(request, payload)
    try:
        messages = runtime.ai_store.latest_messages(session_id, limit=AI_CONTEXT_MESSAGE_LIMIT)
        run_mode = _payload_or_latest_user_run_mode(payload, messages)
        context_snapshot = await _ai_context_snapshot(
            runtime,
            _tool_registry(request),
            _latest_user_content(messages),
            session_id=session_id,
            timezone_name=timezone_name,
            run_mode=run_mode,
        )
        def _stream_factory() -> Any:
            return _ai_chat_service(request).stream_retry_events(
                runtime.config,
                session_id,
                context_snapshot,
                run_mode,
                {"timezone_name": timezone_name, "runtime": runtime},
            )
        run = inflight.start(runtime, session_id, _stream_factory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        provider_error = _llm_provider_http_exception(exc)
        if provider_error is not None:
            raise provider_error from exc
        raise
    return StreamingResponse(run.stream(), media_type="application/x-ndjson")


@router.get("/api/ai/sessions/{session_id}/stream-status")
async def ai_session_stream_status(session_id: str, request: Request) -> dict[str, Any]:
    session = _runtime(request).ai_store.get_session(session_id, include_messages=False)
    if session is None or session.get("archived_at") is not None:
        raise HTTPException(status_code=404, detail="AI session not found")
    run = _ai_inflight_streams(request).get(session_id)
    return {"session_id": session_id, "in_progress": bool(run), "run_id": run.run_id if run else ""}


@router.get("/api/ai/traces")
async def list_ai_traces(request: Request, limit: int = 20, day: str = "") -> JSONResponse:
    trace_store = _agent_trace_store(request)
    clean_day = str(day or "").strip()
    if clean_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean_day):
        raise HTTPException(status_code=400, detail="day must use YYYY-MM-DD format")
    traces = trace_store.list(limit=max(1, min(200, limit)), day=clean_day)
    return JSONResponse({"ok": True, "traces": traces, "count": len(traces)})


@router.get("/api/ai/traces/{trace_id}")
async def get_ai_trace(trace_id: str, request: Request) -> JSONResponse:
    trace_store = _agent_trace_store(request)
    try:
        trace = trace_store.get(trace_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent trace not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "trace": trace})


@router.post("/api/ai/sessions/{session_id}/mission-draft")
async def create_mission_draft(session_id: str, request: Request) -> JSONResponse:
    _runtime(request)
    raise HTTPException(
        status_code=409,
        detail="legacy mission draft writes are disabled; use /api/ai/mission-revisions or normal agent mission tools",
    )


@router.get("/api/ai/mission-drafts")
async def list_mission_drafts(
    request: Request,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    runtime = _runtime(request)
    drafts = runtime.mission_draft_service.list_drafts(
        session_id=session_id,
        status_filter=status,
        limit=max(1, min(200, limit)),
    )
    return JSONResponse({"ok": True, "drafts": drafts, "count": len(drafts)})


@router.get("/api/ai/mission-drafts/{draft_id}")
async def get_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    draft = runtime.mission_draft_service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="mission draft not found")
    return JSONResponse({"ok": True, "draft": draft})


@router.get("/api/ai/mission-revisions")
async def list_mission_revisions(
    request: Request,
    session_id: str | None = None,
    operation_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    revisions = mission_execution.list_revisions(
        session_id=session_id,
        operation_id=operation_id,
        status_filter=status,
        limit=max(1, min(200, limit)),
    )
    return JSONResponse({"ok": True, "revisions": revisions, "count": len(revisions)})


@router.get("/api/ai/mission-revisions/current")
async def get_current_mission_revision(request: Request, session_id: str = "") -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    state = mission_execution.get_current_mission_state(session_id=session_id)
    revision_id = str(state.get("revision_id") or "").strip()
    revision = mission_execution.get_revision(revision_id) if revision_id else None
    overlay = mission_execution.get_revision_overlay(session_id=session_id)
    return JSONResponse({"ok": True, "mission_state": state, "revision": revision, "overlay": overlay})


@router.get("/api/ai/mission-revisions/{revision_id}")
async def get_mission_revision(revision_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    revision = mission_execution.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="mission revision not found")
    return JSONResponse({"ok": True, "revision": revision})


@router.get("/api/ai/mission-revisions/{revision_id}/overlay")
async def get_mission_revision_overlay(revision_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    revision = mission_execution.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="mission revision not found")
    return JSONResponse({"ok": True, "overlay": mission_execution.get_revision_overlay(revision_id=revision_id)})


@router.get("/api/ai/missions/{mission_id}/overlay")
async def get_mission_overlay(mission_id: str, request: Request) -> JSONResponse:
    """Mission-level overlay (ADR 0021 §2): resolve Mission -> active operation
    -> active revision, then reuse the per-revision overlay builder. This is the
    mission-keyed overlay source the sidebar/MapWidget cutover renders from,
    replacing the per-revision `/api/ai/mission-revisions/{id}/overlay` path.
    """
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    revision_id = runtime.mission_store.get_active_revision_id(mission_id)
    if revision_id is None:
        raise HTTPException(status_code=404, detail="mission not found")
    if not revision_id:
        return JSONResponse({"ok": True, "overlay": None})
    return JSONResponse({"ok": True, "overlay": mission_execution.get_revision_overlay(revision_id=revision_id)})


@router.get("/api/ai/mission-overlays/current")
async def get_current_mission_overlay(request: Request, session_id: str = "") -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    return JSONResponse({"ok": True, "overlay": mission_execution.get_revision_overlay(session_id=session_id)})


@router.post("/api/ai/mission-revisions")
async def create_client_mission_revision(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    operation_id = str(payload.get("operation_id") or "").strip()
    if not operation_id:
        raise HTTPException(status_code=400, detail="operation_id is required")
    waypoints = payload.get("waypoints")
    if not isinstance(waypoints, list):
        raise HTTPException(status_code=400, detail="waypoints must be a list")
    label = str(payload.get("label") or "")
    from_revision_id = str(payload.get("from_revision_id") or "")
    result = mission_execution.create_client_revision(
        operation_id=operation_id,
        waypoints=waypoints,
        label=label,
        from_revision_id=from_revision_id,
    )
    return JSONResponse(result, status_code=201 if result.get("ok") else 409)


@router.patch("/api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}")
async def update_mission_waypoint(revision_id: str, waypoint_index: int, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    point = payload.get("point")
    if not isinstance(point, dict):
        raise HTTPException(status_code=400, detail="point is required and must be an object")
    expected_version_raw = payload.get("expected_version")
    if expected_version_raw is None:
        raise HTTPException(status_code=400, detail="expected_version is required")
    try:
        expected_version = int(expected_version_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="expected_version must be an integer") from None
    result = mission_execution.update_waypoint(
        revision_id,
        waypoint_index,
        point=point,
        expected_version=expected_version,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/mission-revisions/{revision_id}/waypoints")
async def insert_mission_waypoint(revision_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="request body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    point = payload.get("point")
    if not isinstance(point, dict):
        raise HTTPException(status_code=400, detail="point is required and must be an object")
    expected_version_raw = payload.get("expected_version")
    if expected_version_raw is None:
        raise HTTPException(status_code=400, detail="expected_version is required")
    try:
        expected_version = int(expected_version_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="expected_version must be an integer") from None
    after_index_raw = payload.get("after_index", -1)
    try:
        after_index = int(after_index_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="after_index must be an integer") from None
    result = mission_execution.insert_waypoint(
        revision_id,
        after_index=after_index,
        point=point,
        expected_version=expected_version,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.delete("/api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}")
async def delete_mission_waypoint(
    revision_id: str,
    waypoint_index: int,
    request: Request,
) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    expected_version = 0
    if isinstance(payload, dict) and payload.get("expected_version") is not None:
        try:
            expected_version = int(payload["expected_version"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="expected_version must be an integer") from None
    result = mission_execution.delete_waypoint(
        revision_id,
        waypoint_index,
        expected_version=expected_version,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.get("/api/vehicle-profile/active")
async def get_active_vehicle_profile(request: Request) -> JSONResponse:
    _runtime(request)
    return JSONResponse({"ok": True, "profile": asdict(get_active_profile())})


@router.get("/api/vehicle-profiles")
async def list_vehicle_profiles(request: Request) -> JSONResponse:
    _runtime(request)
    return JSONResponse({
        "ok": True,
        "profiles": [asdict(profile) for profile in KNOWN_PROFILES.values()],
    })


@router.get("/api/ai/controller-mission")
async def get_controller_mission_state(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    return JSONResponse({"ok": True, "controller_state": mission_execution.get_controller_state()})


@router.get("/api/ai/controller-mission/health")
async def get_controller_mission_health(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    health = mission_execution.check_controller_health()
    return JSONResponse({"ok": bool(health.get("ok")), "health": health})


@router.post("/api/ai/controller-mission/clear")
async def clear_controller_mission(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    expected_controller_version_raw = payload.get("expected_controller_version") if isinstance(payload, dict) else None
    expected_controller_version = None
    if expected_controller_version_raw is not None:
        try:
            expected_controller_version = int(expected_controller_version_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="expected_controller_version must be an integer") from None
    result = mission_execution.clear_controller_mission(
        expected_controller_version=expected_controller_version,
    )
    runtime.replay_store.log_runtime_event(
        "mission_controller_clear",
        {
            "status": result.get("status", ""),
            "ok": bool(result.get("ok")),
            "attempt_id": result.get("attempt_id", ""),
            "expected_controller_version": expected_controller_version,
        },
    )
    return JSONResponse(_sanitize_for_json(result), status_code=200 if result.get("ok") else 409)


@router.get("/api/ai/execution/state")
async def get_execution_state(request: Request) -> JSONResponse:
    """Confirm-banner poll (ADR 0021 §1): the in-flight execution for a session,
    including the confirm-window countdown when one is awaiting confirmation."""
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    session_id = str(request.query_params.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    active = sessions.get(session_id)
    return JSONResponse({"ok": True, "execution": active.snapshot() if active else None})


@router.post("/api/ai/execution/confirm")
async def confirm_execution(request: Request) -> JSONResponse:
    """Operator `[Play]` on the confirm banner: start the armed run if still
    within its confirm window."""
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    session_id = str((payload.get("session_id") if isinstance(payload, dict) else "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    result = sessions.confirm(session_id)
    runtime.replay_store.log_runtime_event(
        "mission_execution_confirm",
        {"session_id": session_id, "ok": bool(result.get("ok")), "status": result.get("status", "")},
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/execution/cancel")
async def cancel_execution_endpoint(request: Request) -> JSONResponse:
    """Operator dismissed the confirm banner: drop the armed/awaiting run."""
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    session_id = str((payload.get("session_id") if isinstance(payload, dict) else "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    result = sessions.cancel(session_id)
    runtime.replay_store.log_runtime_event(
        "mission_execution_cancel",
        {"session_id": session_id, "ok": bool(result.get("ok")), "status": result.get("status", "")},
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


def _active_operation_id_for_mission(runtime: Any, mission_id: str) -> str:
    """Look up the active_operation_id for a flat Mission so sidebar pause/resume/stop
    can call the service (FC adapter + DB) as well as parking the executor thread."""
    store = getattr(runtime, "mission_store", None)
    if store is None:
        return ""
    mission = store.get_mission(str(mission_id or "").strip())
    if not isinstance(mission, dict):
        return ""
    return str(mission.get("active_operation_id") or "").strip()


@router.post("/api/ai/missions/{mission_id}/pause")
async def pause_mission_endpoint(mission_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    mid = str(mission_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="mission_id is required")
    result = sessions.pause_for_mission(mid)
    if result.get("ok"):
        svc = getattr(runtime, "mission_execution_service", None)
        op_id = _active_operation_id_for_mission(runtime, mid)
        if svc is not None and op_id:
            svc_result = svc.pause_mission(op_id)
            if not svc_result.get("ok"):
                sessions.resume_for_mission(mid)
                result = svc_result
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/missions/{mission_id}/resume")
async def resume_mission_endpoint(mission_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    mid = str(mission_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="mission_id is required")
    result = sessions.resume_for_mission(mid)
    if result.get("ok"):
        svc = getattr(runtime, "mission_execution_service", None)
        op_id = _active_operation_id_for_mission(runtime, mid)
        if svc is not None and op_id:
            svc_result = svc.resume_mission(op_id)
            if not svc_result.get("ok"):
                sessions.pause_for_mission(mid)
                result = svc_result
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/missions/{mission_id}/stop")
async def stop_mission_endpoint(mission_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    sessions = getattr(runtime, "mission_execution_sessions", None)
    if sessions is None:
        raise HTTPException(status_code=503, detail="execution sessions unavailable")
    mid = str(mission_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="mission_id is required")
    result = sessions.abort_for_mission(mid)
    if result.get("ok"):
        svc = getattr(runtime, "mission_execution_service", None)
        op_id = _active_operation_id_for_mission(runtime, mid)
        if svc is not None and op_id:
            svc_result = svc.abort_mission(op_id)
            if not svc_result.get("ok"):
                result = svc_result
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/mission-revisions/{revision_id}/execute")
async def execute_mission_revision(revision_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    expected_controller_version_raw = payload.get("expected_controller_version") if isinstance(payload, dict) else None
    expected_controller_version = None
    if expected_controller_version_raw is not None:
        try:
            expected_controller_version = int(expected_controller_version_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="expected_controller_version must be an integer") from None
    result = mission_execution.execute_revision(
        revision_id,
        expected_controller_version=expected_controller_version,
    )
    runtime.replay_store.log_runtime_event(
        "mission_execution_cutover",
        {
            "revision_id": revision_id,
            "status": result.get("status", ""),
            "ok": bool(result.get("ok")),
            "attempt_id": result.get("attempt_id", ""),
            "expected_controller_version": expected_controller_version,
        },
    )
    return JSONResponse(_sanitize_for_json(result), status_code=200 if result.get("ok") else 409)


@router.post("/api/ai/mission-revisions/{revision_id}/reject")
async def reject_mission_revision(revision_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    mission_execution = getattr(runtime, "mission_execution_service", None)
    if mission_execution is None:
        raise HTTPException(status_code=503, detail="mission execution service unavailable")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    note = str(payload.get("note", "") if isinstance(payload, dict) else "")
    revision = mission_execution.reject_revision(revision_id, note=note)
    if revision is None:
        raise HTTPException(
            status_code=409,
            detail="revision not found or not in a rejectable status",
        )
    return JSONResponse({"ok": True, "revision": revision})


@router.post("/api/ai/mission-drafts/{draft_id}/approve")
async def approve_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    _runtime(request)
    raise HTTPException(
        status_code=409,
        detail=(
            "legacy mission draft approve is disabled; use "
            "/api/ai/mission-revisions/{revision_id}/approve"
        ),
    )


@router.post("/api/ai/mission-drafts/{draft_id}/reject")
async def reject_mission_draft(draft_id: str, request: Request) -> JSONResponse:
    _runtime(request)
    raise HTTPException(
        status_code=409,
        detail=(
            "legacy mission draft reject is disabled; use "
            "/api/ai/mission-revisions/{revision_id}/reject"
        ),
    )
