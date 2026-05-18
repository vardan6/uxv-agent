"""Workbench planning graph (Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5).

Phase 1: Linear deterministic graph, REST-only approval.
Phase 2: Adds durable checkpointer and interrupt() at request_workbench_approval.
Phase 3: Clarification loop via interrupt() at prepare_clarification; refreshes
         rover pose/scene on resume before draft generation.
Phase 4: classify_request_scope node + lazy data branch nodes
         (retrieve_replay_context, retrieve_application_memory,
          retrieve_settings_context, retrieve_sensor_context);
         conditional routing driven by request_scope and source-control flags.
Phase 5: planner_loop_node added behind ai_use_planner_loop=false flag.
         When enabled, replaces the Phase 4 middle DAG with a single
         AgentLoopRuntime node that calls parse_rover_intent,
         resolve_spatial_target, lazy-load tools, and propose_mission_draft
         as agent tools. Legacy path remains available when flag is off.

Node order (legacy path, ai_use_planner_loop=false):
    capture_request
    retrieve_current_context
    classify_request_scope      (Phase 4)
    retrieve_replay_context     (Phase 4: only when replay branch active)
    retrieve_application_memory (Phase 4: only when memory branch active)
    retrieve_settings_context   (Phase 4: only when settings branch active)
    retrieve_sensor_context     (Phase 4: only when sensor branch active)
    parse_intent
    prepare_clarification       (Phase 3: only when intent has missing_information and no prior clarification)
    resolve_target              (only when intent has a spatial target)
    generate_mission_draft
    validate_draft
    store_draft
    request_workbench_approval  (Phase 2: interrupt(); Phase 1 fallback: REST-only)
    record_approval | record_rejection
    finalize_response

Node order (planner loop path, ai_use_planner_loop=true):
    capture_request
    retrieve_current_context
    planner_loop_node           (Phase 5: AgentLoopRuntime with planner tools)
    validate_draft
    store_draft
    request_workbench_approval
    record_approval | record_rejection
    finalize_response

Error path: capture_request -> finalize_error (fatal input errors only).

Constraints:
- No command staging, no MQTT publishing, no controller lock writes.
- execution_allowed is always False on any generated draft.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, AsyncIterator

try:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:
    raise RuntimeError(
        "LangGraph is not installed. Run: pip install langgraph"
    ) from exc

# Phase 2: interrupt() and Command for durable HITL approval
try:
    from langgraph.types import Command, interrupt as lg_interrupt  # type: ignore[attr-defined]
    _INTERRUPT_AVAILABLE = True
except ImportError:
    _INTERRUPT_AVAILABLE = False

try:
    from gcs_server.ai.agent_loop import AgentLoopRuntime, AgentInvokeResult
    from gcs_server.ai.data_access import build_data_access_manifest
    from gcs_server.ai.graph_runtime import WorkbenchGraphRuntime
    from gcs_server.ai.graph_state import WorkbenchGraphState
    from gcs_server.ai.mission_export_service import MissionExportService
    from gcs_server.ai.mission_draft_service import validate_draft_payload
    from gcs_server.ai.provider_registry import resolve_intent_provider, resolve_provider
    from gcs_server.ai.retrieval import (
        build_loaded_data_refs,
        build_retrieval_citations,
        build_retrieved_sources,
        normalize_retrieval_request,
    )
    from gcs_server.ai.session_store import normalize_source_controls
    from gcs_server.ai.tool_registry import allowed_tool_names_for_source_controls, normalize_mission_draft_payload
except ModuleNotFoundError:
    from ai.agent_loop import AgentLoopRuntime, AgentInvokeResult
    from ai.data_access import build_data_access_manifest
    from ai.graph_runtime import WorkbenchGraphRuntime
    from ai.graph_state import WorkbenchGraphState
    from ai.mission_export_service import MissionExportService
    from ai.mission_draft_service import validate_draft_payload
    from ai.provider_registry import resolve_intent_provider, resolve_provider
    from ai.retrieval import (
        build_loaded_data_refs,
        build_retrieval_citations,
        build_retrieved_sources,
        normalize_retrieval_request,
    )
    from ai.session_store import normalize_source_controls
    from ai.tool_registry import allowed_tool_names_for_source_controls, normalize_mission_draft_payload


# ── Constants ─────────────────────────────────────────────────────────────────

_PLANNING_INTENT_TYPES = frozenset({"navigate_to_object", "inspect_area", "search_area"})

_PLANNER_TOOL_NAMES = frozenset({
    "parse_rover_intent",
    "lazy_load_replay",
    "lazy_load_ai_memory",
    "lazy_load_settings",
    "lazy_load_sensor",
    "request_clarification",
    "resolve_spatial_target",
    "get_current_rover_state",
    "get_scene_summary",
    "plan_route_around_group",
    "plan_route_between",
    "propose_mission_draft",
})

_PLANNER_SYSTEM_PROMPT = (
    "You are a rover mission planning agent for Remote Rover GCS.\n\n"
    "Your task is to plan a mission draft from the operator's request.\n\n"
    "Workflow:\n"
    "1. Call parse_rover_intent to extract structured intent from the user prompt.\n"
    "2. If the intent has a spatial target, call resolve_spatial_target.\n"
    "3. If missing_information is non-empty and critical, call request_clarification once.\n"
    "4. Call propose_mission_draft with the intent and resolved target to finalize the plan.\n\n"
    "Hard rules:\n"
    "- Never call propose_mission_draft without first calling parse_rover_intent.\n"
    "- Never generate motion commands, MQTT payloads, or control values.\n"
    "- execution_allowed must always remain false in any draft.\n"
    "- required_operator_approval must always be true.\n"
    "- If the intent is not a rover planning task (navigate, inspect, search), "
    "call propose_mission_draft with a minimal draft explaining why the request is out of scope.\n"
)

_DRAFT_SYSTEM_PROMPT = (
    "You are a mission planning assistant for a remote rover GCS.\n"
    "Generate a structured mission draft from the provided rover intent and resolved target.\n\n"
    "Hard rules:\n"
    "- required_operator_approval MUST be true\n"
    "- execution_allowed MUST be false\n"
    "- Do NOT include MQTT topics, motor values, command payloads, or control fields\n"
    "- Step types must be one of: navigate, inspect, search, report\n"
    "- Return ONLY a valid JSON object with no markdown or extra text\n\n"
    "Required JSON schema:\n"
    '{\n'
    '  "goal": "clear mission goal",\n'
    '  "target": {},\n'
    '  "steps": [\n'
    '    {"type": "navigate|inspect|search|report", "description": "...", "target": {}, "success_condition": "..."}\n'
    '  ],\n'
    '  "constraints": ["string"],\n'
    '  "assumptions": ["string"],\n'
    '  "risks": ["string"],\n'
    '  "required_operator_approval": true,\n'
    '  "execution_allowed": false\n'
    '}'
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _runtime(config: RunnableConfig) -> WorkbenchGraphRuntime:
    return (config.get("configurable") or {})["runtime"]


def _node_entry(name: str, **extra: Any) -> dict:
    return {"node": name, "ts": time.time(), **extra}


def _tool_entry(name: str, args: dict, result: Any) -> dict:
    return {"tool": name, "args": args, "result": result, "ts": time.time()}


def _route_summary_for_approval(draft: dict[str, Any]) -> dict[str, Any]:
    waypoint_count = 0
    total_distance_m = 0.0
    artifact_count = 0
    route_hashes: list[str] = []

    if isinstance(draft.get("waypoints"), list):
        waypoint_count += len(draft["waypoints"])
        return {
            "artifact_count": 0,
            "waypoint_count": waypoint_count,
            "total_distance_m": 0.0,
            "route_hashes": route_hashes,
        }

    for artifact in draft.get("route_artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        artifact_count += 1
        artifact_waypoints = artifact.get("waypoints")
        if isinstance(artifact_waypoints, list):
            waypoint_count += len(artifact_waypoints)
        else:
            waypoint_count += int(artifact.get("waypoint_count") or 0)
        total_distance_m += float(artifact.get("total_distance_m") or 0.0)
        route_hash = str(artifact.get("route_hash") or "").strip()
        if route_hash:
            route_hashes.append(route_hash)
    if waypoint_count:
        return {
            "artifact_count": artifact_count,
            "waypoint_count": waypoint_count,
            "total_distance_m": round(total_distance_m, 1),
            "route_hashes": route_hashes,
        }

    for step in draft.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("waypoints"), list):
            waypoint_count += len(step["waypoints"])
        summary = step.get("route_summary")
        if isinstance(summary, dict):
            total_distance_m += float(summary.get("total_distance_m") or 0.0)

    return {
        "artifact_count": artifact_count,
        "waypoint_count": waypoint_count,
        "total_distance_m": round(total_distance_m, 1),
        "route_hashes": route_hashes,
    }


def _home_position_from_rover_state(rover_state: dict[str, Any]) -> dict[str, float] | None:
    gps = rover_state.get("gps") if isinstance(rover_state, dict) else None
    if not isinstance(gps, dict) or gps.get("lat") is None or gps.get("lon") is None:
        return None
    try:
        return {
            "latitude": float(gps["lat"]),
            "longitude": float(gps["lon"]),
            "altitude": float(gps.get("alt") or 0.0),
        }
    except (TypeError, ValueError):
        return None


def _json_line(data: dict) -> str:
    return json.dumps(data, separators=(",", ":")) + "\n"


def _usage_metadata(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", {}) or {}
    return usage if isinstance(usage, dict) else {}


def _response_metadata(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "response_metadata", {}) or {}
    return metadata if isinstance(metadata, dict) else {}


def _merge_usage_metadata(*items: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    numeric_keys = ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens")
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key in numeric_keys and isinstance(value, (int, float)):
                merged[key] = int(merged.get(key, 0)) + int(value)
            elif key not in merged:
                merged[key] = value
    return merged


def _merge_response_metadata(*items: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        merged.update(item)
    return merged


def _has_spatial_target(intent: dict) -> bool:
    target = intent.get("target") or {}
    if not isinstance(target, dict):
        return False
    return any(
        target.get(k) not in (None, "")
        for k in ("description", "kind", "side", "relative_bearing_deg")
    )


def _build_tool_context(state: WorkbenchGraphState) -> dict:
    """Build a context_snapshot dict compatible with ToolRegistry.invoke().

    ToolRegistry._snapshot_context() extracts context_snapshot["meta"]["context_snapshot"],
    then handlers read "rover", "scene", "mission" from that inner dict.
    """
    return {
        "meta": {
            "context_snapshot": {
                "rover": state.get("rover_state") or {},
                "scene": state.get("scene_summary") or {},
                "mission": {},
                "runtime": state.get("runtime_summary") or {},
            }
        }
    }


def _build_data_access_manifest(runtime: WorkbenchGraphRuntime, source_controls: dict[str, Any] | None = None) -> dict:
    return build_data_access_manifest(
        runtime.tool_registry.definitions(),
        allowed_tool_names=allowed_tool_names_for_source_controls(source_controls),
    )


def _build_draft_user_prompt(
    intent: dict,
    target_resolution: dict,
    rover_state: dict,
    clarification_response: dict | None = None,
) -> str:
    parts: list[str] = [
        f"Intent type: {intent.get('intent_type', 'unknown')}",
        f"Summary: {intent.get('summary', '')}",
    ]
    target = intent.get("target") or {}
    if any(target.get(k) for k in ("description", "kind", "side")):
        parts.append(f"Requested target: {json.dumps(target)}")
    if target_resolution.get("ok"):
        candidates = target_resolution.get("candidates") or target_resolution.get("objects") or []
        if candidates:
            parts.append(f"Resolved target candidates (top 3): {json.dumps(candidates[:3])}")
    actions = intent.get("requested_actions") or []
    if actions:
        parts.append(f"Requested actions: {', '.join(str(a) for a in actions)}")
    constraints = intent.get("constraints") or []
    if constraints:
        parts.append(f"Constraints: {', '.join(str(c) for c in constraints)}")
    if clarification_response and clarification_response.get("answer"):
        parts.append(f"Operator clarification: {clarification_response['answer']}")
    else:
        missing = intent.get("missing_information") or []
        if missing:
            parts.append(f"Missing information (flag as assumption): {', '.join(str(m) for m in missing)}")
    pos = (rover_state.get("position") or {})
    if pos:
        parts.append(f"Current rover position: {json.dumps(pos)}")
    return "\n".join(parts)


def _parse_draft_json(text: str) -> dict:
    clean = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _normalize_retrieval_request(value: Any, *, user_prompt: str = "", session_id: str = "") -> dict[str, Any]:
    return normalize_retrieval_request(value, user_prompt=user_prompt, session_id=session_id)


# ── Planner loop helpers (Phase 5) ────────────────────────────────────────────

def _planner_system_prompt_for_mode(run_mode: str) -> str:
    return _PLANNER_SYSTEM_PROMPT


def _planner_prompt_builder(
    context_snapshot: dict | None,
    run_mode: str,
    tool_calls: list,
    tools: list | None = None,
    data_access_manifest: dict | None = None,
) -> str:
    ctx = (context_snapshot or {}).get("meta", {}).get("context_snapshot") or {}
    context_text = (context_snapshot or {}).get("meta", {}).get("context_text", "")
    lines = [
        "You are planning a rover mission. Use the tools in sequence: "
        "parse_rover_intent → (resolve_spatial_target) → propose_mission_draft.",
    ]
    if context_text:
        lines.append(f"Current rover context:\n{context_text}")
    rover = ctx.get("rover") or {}
    if rover.get("position"):
        lines.append(f"Rover position: {json.dumps(rover['position'])}")
    return "\n".join(lines)


def _planner_allowed_tool_names(context_snapshot: dict | None) -> set[str] | None:
    allowed = set(_PLANNER_TOOL_NAMES)
    meta = (context_snapshot or {}).get("meta") or {}
    source_controls = normalize_source_controls(meta.get("source_controls"))
    if not source_controls.get("replay_reports", True):
        allowed.discard("lazy_load_replay")
    if not source_controls.get("ai_chat_history", False):
        allowed.discard("lazy_load_ai_memory")
    if not source_controls.get("settings_config", False):
        allowed.discard("lazy_load_settings")
    if not source_controls.get("sensor_context", False):
        allowed.discard("lazy_load_sensor")
    return allowed


def _is_tool_calling_unsupported_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "tool" in msg and ("unsupported" in msg or "not support" in msg or "bind_tools" in msg)


def _build_planner_context_snapshot(state: WorkbenchGraphState) -> dict:
    """Build a context_snapshot suitable for the planner AgentLoopRuntime.

    Includes all retrieved data (replay, memory, settings) so lazy-load tools
    can return it without needing extra service calls. Source controls are carried
    into meta so _snapshot_source_controls and lazy tool handlers enforce them.
    """
    source_controls = normalize_source_controls(
        (state.get("retrieval_request") or {}).get("source_controls")
    )
    return {
        "meta": {
            "context_snapshot": {
                "rover": state.get("rover_state") or {},
                "scene": state.get("scene_summary") or {},
                "mission": {},
                "runtime": state.get("runtime_summary") or {},
                "details": {
                    "current_replay": state.get("replay_summary") or {},
                    "ai_chat_history": state.get("chat_history_summary") or {},
                },
                "settings": state.get("settings_summary") or {},
                "llm": state.get("llm_summary") or {},
            },
            "context_text": (state.get("context_metadata") or {}).get("context_text", ""),
            "source_controls": source_controls,
        }
    }


def _extract_planner_tool_result(
    tool_calls: list[dict],
    tool_name: str,
    result_key: str = "",
) -> Any:
    """Return the result (or result[result_key]) from the last call to tool_name."""
    for call in reversed(tool_calls):
        if call.get("name") == tool_name:
            result = call.get("result") or {}
            if not isinstance(result, dict) or not result.get("ok"):
                return None
            if result_key:
                return result.get(result_key)
            return result
    return None


def _build_retrieved_sources(state: WorkbenchGraphState) -> list[dict[str, Any]]:
    return build_retrieved_sources(
        retrieval_request=_normalize_retrieval_request(
            state.get("retrieval_request") or {},
            user_prompt=str(state.get("user_prompt") or ""),
            session_id=str(state.get("session_id") or ""),
        ),
        session_id=str(state.get("session_id", "") or ""),
        replay_summary=state.get("replay_summary") or {},
        chat_history_summary=state.get("chat_history_summary") or {},
        settings_summary=state.get("settings_summary") or {},
        sensor_summary={
            "telemetry_fresh": ((state.get("rover_state") or {}).get("telemetry_fresh")),
            "camera_fresh": ((state.get("rover_state") or {}).get("camera_fresh")),
            "video_delivery": ((state.get("runtime_summary") or {}).get("video")),
        },
    )


# ── Nodes ─────────────────────────────────────────────────────────────────────

def capture_request(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Validate inputs, ensure a user message exists, initialize trace."""
    rt = _runtime(config)
    session_id = state.get("session_id", "")
    user_prompt = (state.get("user_prompt") or "").strip()

    errors: list[dict] = []
    if not session_id:
        errors.append({
            "node": "capture_request", "code": "missing_session_id",
            "severity": "fatal", "message": "session_id is required",
        })
    if not user_prompt:
        errors.append({
            "node": "capture_request", "code": "empty_prompt",
            "severity": "fatal", "message": "user_prompt must not be empty",
        })

    source_message_id = state.get("source_message_id", "")
    if not source_message_id and session_id and user_prompt:
        try:
            msg = rt.ai_session_store.add_message(
                session_id,
                role="user",
                content=user_prompt,
                meta={"run_mode": "workbench"},
            )
            source_message_id = msg.get("id", "")
        except Exception as exc:
            errors.append({
                "node": "capture_request", "code": "session_store_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            })

    use_planner_loop = bool(getattr(rt.app_runtime.config, "ai_use_planner_loop", False))
    return {
        "source_message_id": source_message_id,
        "use_planner_loop": use_planner_loop,
        "retrieval_request": _normalize_retrieval_request(
            state.get("retrieval_request") or {},
            user_prompt=user_prompt,
            session_id=session_id,
        ),
        "node_trace": [_node_entry("capture_request", fatal_errors=sum(1 for e in errors if e.get("severity") == "fatal"))],
        "errors": errors,
    }


async def retrieve_current_context(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Build one compact context snapshot for the entire graph run."""
    rt = _runtime(config)
    try:
        snapshot = await rt.context_service.build_compact_context(
            user_message=state.get("user_prompt", ""),
            session_id=state.get("session_id", ""),
            timezone_name=state.get("operator_timezone", ""),
            run_mode="agent",
            source_controls=normalize_source_controls((state.get("retrieval_request") or {}).get("source_controls")),
        )
    except Exception as exc:
        source_controls = normalize_source_controls((state.get("retrieval_request") or {}).get("source_controls"))
        return {
            "context_metadata": {"error": str(exc), "context_text": ""},
            "data_access_manifest": _build_data_access_manifest(rt, source_controls),
            "errors": [{
                "node": "retrieve_current_context", "code": "context_build_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            }],
            "node_trace": [_node_entry("retrieve_current_context", ok=False)],
        }

    full_ctx = snapshot.meta.get("context_snapshot") or {}
    # Store compact metadata only — not the full snapshot blob
    compact_meta = {k: v for k, v in snapshot.meta.items() if k != "context_snapshot"}
    compact_meta["context_text"] = snapshot.prompt

    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    sensor_summary = {
        "telemetry_fresh": ((full_ctx.get("rover") or {}).get("telemetry_fresh")),
        "camera_fresh": ((full_ctx.get("rover") or {}).get("camera_fresh")),
        "video_delivery": ((full_ctx.get("runtime") or {}).get("video")),
    }
    chat_history_summary = (full_ctx.get("details") or {}).get("ai_chat_history") or {}
    retrieved_sources = _build_retrieved_sources({
        **state,
        "retrieval_request": retrieval_request,
        "replay_summary": (full_ctx.get("details") or {}).get("current_replay") or {},
        "chat_history_summary": chat_history_summary,
        "settings_summary": full_ctx.get("settings") or {},
        "rover_state": full_ctx.get("rover") or {},
        "runtime_summary": full_ctx.get("runtime") or {},
    })
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=(full_ctx.get("details") or {}).get("current_replay") or {},
        chat_history_summary=chat_history_summary,
        settings_summary=full_ctx.get("settings") or {},
        sensor_summary=sensor_summary,
    )
    retrieval_citations = build_retrieval_citations(retrieved_sources, loaded_data_refs)

    return {
        "context_metadata": compact_meta,
        "data_access_manifest": _build_data_access_manifest(rt, retrieval_request.get("source_controls")),
        "rover_state": full_ctx.get("rover") or {},
        "scene_summary": full_ctx.get("scene") or {},
        "runtime_summary": full_ctx.get("runtime") or {},
        "replay_summary": (full_ctx.get("details") or {}).get("current_replay") or {},
        "chat_history_summary": chat_history_summary,
        "settings_summary": full_ctx.get("settings") or {},
        "llm_summary": full_ctx.get("llm") or {},
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": retrieval_citations,
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_current_context", ok=True)],
    }


def classify_request_scope(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    return {
        "classified_scope": str(retrieval_request.get("request_scope") or "rover_task"),
        "retrieval_request": retrieval_request,
        "node_trace": [_node_entry(
            "classify_request_scope",
            scope=str(retrieval_request.get("request_scope") or "rover_task"),
            lazy_branches=len(retrieval_request.get("lazy_branches") or []),
        )],
    }


def retrieve_replay_context(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    retrieved_sources = _build_retrieved_sources(state)
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=state.get("replay_summary") or {},
        chat_history_summary=state.get("chat_history_summary") or {},
        settings_summary=state.get("settings_summary") or {},
    )
    return {
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": build_retrieval_citations(retrieved_sources, loaded_data_refs),
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_replay_context", available=bool(state.get("replay_summary") or {}))],
    }


def retrieve_application_memory(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    retrieved_sources = _build_retrieved_sources(state)
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=state.get("replay_summary") or {},
        chat_history_summary=state.get("chat_history_summary") or {},
        settings_summary=state.get("settings_summary") or {},
    )
    return {
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": build_retrieval_citations(retrieved_sources, loaded_data_refs),
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_application_memory", session_id=str(state.get("session_id") or ""))],
    }


def retrieve_settings_context(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    retrieved_sources = _build_retrieved_sources(state)
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=state.get("replay_summary") or {},
        chat_history_summary=state.get("chat_history_summary") or {},
        settings_summary=state.get("settings_summary") or {},
    )
    return {
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": build_retrieval_citations(retrieved_sources, loaded_data_refs),
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_settings_context", available=bool(state.get("settings_summary") or {}))],
    }


def retrieve_sensor_context(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    retrieved_sources = _build_retrieved_sources(state)
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=state.get("replay_summary") or {},
        chat_history_summary=state.get("chat_history_summary") or {},
        settings_summary=state.get("settings_summary") or {},
        sensor_summary={
            "telemetry_fresh": ((state.get("rover_state") or {}).get("telemetry_fresh")),
            "camera_fresh": ((state.get("rover_state") or {}).get("camera_fresh")),
        },
    )
    return {
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": build_retrieval_citations(retrieved_sources, loaded_data_refs),
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_sensor_context", available=bool(state.get("rover_state") or {}))],
    }


def parse_intent(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Parse user prompt into a structured RoverIntent via IntentService."""
    rt = _runtime(config)
    try:
        resolved = resolve_intent_provider(
            rt.app_runtime.config,
            secret_resolver=rt.secret_resolver,
        )
    except Exception as exc:
        return {
            "intent": {"intent_type": "unknown", "summary": str(exc), "requires_rover_motion": False},
            "intent_provider": {},
            "intent_errors": [{"error": f"provider resolution failed: {exc}"}],
            "errors": [{
                "node": "parse_intent", "code": "provider_error",
                "severity": "warning", "message": str(exc), "recoverable": False,
            }],
            "node_trace": [_node_entry("parse_intent", ok=False, reason="provider_error")],
        }

    context_text = (state.get("context_metadata") or {}).get("context_text", "")
    try:
        result = rt.intent_service.parse(
            state.get("user_prompt", ""),
            model=resolved.model,
            context_summary=context_text,
            timezone_name=state.get("operator_timezone", ""),
        )
    except Exception as exc:
        return {
            "intent": {"intent_type": "unknown", "summary": str(exc), "requires_rover_motion": False},
            "intent_provider": {},
            "intent_errors": [{"error": str(exc)}],
            "errors": [{
                "node": "parse_intent", "code": "parse_error",
                "severity": "warning", "message": str(exc), "recoverable": False,
            }],
            "node_trace": [_node_entry("parse_intent", ok=False, reason="parse_exception")],
        }

    intent = result["intent"]
    return {
        "intent": intent,
        "intent_provider": {
            "provider_id": str(resolved.provider.get("id", "")),
            "model_id": str(resolved.provider.get("model_id", "")),
            "latency_ms": result.get("latency_ms", 0),
        },
        "intent_errors": [{"error": e} for e in result.get("parse_errors", [])],
        "intent_usage_metadata": result.get("usage_metadata") or {},
        "intent_response_metadata": result.get("response_metadata") or {},
        "node_trace": [_node_entry(
            "parse_intent", ok=True,
            intent_type=intent.get("intent_type", "unknown"),
            confidence=intent.get("confidence", 0.0),
        )],
    }


def _route_after_intent(state: WorkbenchGraphState) -> str:
    intent = state.get("intent") or {}
    intent_type = str(intent.get("intent_type", "unknown"))
    if intent_type not in _PLANNING_INTENT_TYPES:
        return "finalize_response"
    # Phase 3: ask for missing information once before drafting
    missing = intent.get("missing_information") or []
    if missing and not state.get("clarification_response"):
        return "prepare_clarification"
    if _has_spatial_target(intent):
        return "resolve_target"
    return "generate_mission_draft"


def resolve_target(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Deterministically resolve a spatial target description via ToolRegistry."""
    rt = _runtime(config)
    intent = state.get("intent") or {}
    target = intent.get("target") or {}
    tool_ctx = _build_tool_context(state)

    result = rt.tool_registry.invoke(
        "resolve_spatial_target",
        args={"target": target},
        runtime=rt.app_runtime,
        context_snapshot=tool_ctx,
        timezone_name=state.get("operator_timezone", ""),
    )
    candidates = result.get("candidates") or result.get("objects") or []

    return {
        "target_resolution": result,
        "target_candidates": candidates,
        "tool_trace": [_tool_entry("resolve_spatial_target", {"target": target}, result)],
        "node_trace": [_node_entry(
            "resolve_target",
            ok=bool(result.get("ok")),
            candidates=len(candidates),
        )],
    }


def generate_mission_draft(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Call the mission planner LLM to generate a structured draft payload."""
    rt = _runtime(config)
    intent = state.get("intent") or {}
    target_resolution = state.get("target_resolution") or {}

    # Try mission_planner purpose first, fall back to general_chat
    resolved = None
    for purpose in ("mission_planner", "general_chat"):
        try:
            resolved = resolve_provider(
                rt.app_runtime.config,
                purpose=purpose,
                secret_resolver=rt.secret_resolver,
            )
            break
        except Exception:
            continue

    if resolved is None:
        return {
            "draft": {},
            "errors": [{
                "node": "generate_mission_draft", "code": "no_provider",
                "severity": "warning", "message": "no LLM provider available for draft generation",
                "recoverable": False,
            }],
            "node_trace": [_node_entry("generate_mission_draft", ok=False, reason="no_provider")],
        }

    prompt = _build_draft_user_prompt(
        intent,
        target_resolution,
        state.get("rover_state") or {},
        clarification_response=state.get("clarification_response") or {},
    )
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        lc_messages = [SystemMessage(content=_DRAFT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        response = resolved.model.invoke(lc_messages)
        raw_text = str(getattr(response, "content", response) or "")
        draft = _parse_draft_json(raw_text)
    except Exception as exc:
        return {
            "draft": {},
            "errors": [{
                "node": "generate_mission_draft", "code": "generation_error",
                "severity": "warning", "message": str(exc), "recoverable": False,
            }],
            "node_trace": [_node_entry("generate_mission_draft", ok=False, reason="llm_error")],
        }

    # Enforce invariants regardless of model output
    draft["execution_allowed"] = False
    draft["required_operator_approval"] = True

    return {
        "draft": draft,
        "draft_usage_metadata": _usage_metadata(response),
        "draft_response_metadata": _response_metadata(response),
        "node_trace": [_node_entry(
            "generate_mission_draft", ok=True,
            provider_id=str(resolved.provider.get("id", "")),
            steps=len(draft.get("steps") or []),
        )],
    }


def validate_draft(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Run deterministic validation rules on the draft payload."""
    intent = state.get("intent") or {}
    target_resolution = state.get("target_resolution") or {}
    draft = state.get("draft") or {}
    rover_state = state.get("rover_state") or None

    validation = validate_draft_payload(intent, target_resolution, draft, rover_state)

    new_errors: list[dict] = []
    for blocker in validation.get("blockers") or []:
        new_errors.append({
            "node": "validate_draft", "code": "validation_blocker",
            "severity": "error", "message": blocker, "recoverable": False,
        })
    for warning in validation.get("warnings") or []:
        new_errors.append({
            "node": "validate_draft", "code": "validation_warning",
            "severity": "warning", "message": warning, "recoverable": True,
        })

    return {
        "validation": validation,
        "errors": new_errors,
        "node_trace": [_node_entry("validate_draft", status=validation.get("status", "unknown"))],
    }


def store_draft(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Persist the draft and validation to the mission draft store."""
    rt = _runtime(config)
    draft = state.get("draft") or {}
    intent = state.get("intent") or {}

    if not draft or not intent:
        return {
            "draft_id": "",
            "approval_status": "validation_failed",
            "node_trace": [_node_entry("store_draft", ok=False, reason="empty_draft_or_intent")],
        }

    try:
        stored = rt.draft_service.create_draft(
            session_id=state.get("session_id", ""),
            source_message_id=state.get("source_message_id", ""),
            intent=intent,
            target_resolution=state.get("target_resolution") or {},
            draft_payload=draft,
            rover_state=state.get("rover_state") or None,
        )
    except Exception as exc:
        return {
            "draft_id": "",
            "approval_status": "validation_failed",
            "errors": [{
                "node": "store_draft", "code": "store_error",
                "severity": "error", "message": str(exc), "recoverable": False,
            }],
            "node_trace": [_node_entry("store_draft", ok=False, reason="store_exception")],
        }

    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    mission_operation_id = ""
    mission_revision_id = ""
    mission_errors: list[dict[str, Any]] = []
    if mission_execution is not None:
        try:
            revision = mission_execution.create_proposal(
                session_id=state.get("session_id", ""),
                source_message_id=state.get("source_message_id", ""),
                draft_id=stored.get("id", ""),
                intent=intent,
                target_resolution=state.get("target_resolution") or {},
                draft_payload=stored.get("draft") or draft,
                validation=stored.get("validation") or state.get("validation") or {},
                draft_status=stored.get("status", ""),
                review_context={
                    "goal": (stored.get("draft") or draft).get("goal", ""),
                    "risks": (stored.get("draft") or draft).get("risks") or [],
                    "approval_scope": "planning_artifact_only",
                },
            )
            mission_operation_id = str(revision.get("operation_id") or "")
            mission_revision_id = str(revision.get("id") or "")
        except Exception as exc:
            mission_errors.append({
                "node": "store_draft",
                "code": "mission_execution_store_error",
                "severity": "warning",
                "message": str(exc),
                "recoverable": True,
            })

    return {
        "draft_id": stored.get("id", ""),
        "mission_operation_id": mission_operation_id,
        "mission_revision_id": mission_revision_id,
        "approval_status": stored.get("status", ""),
        "errors": mission_errors,
        "node_trace": [_node_entry(
            "store_draft", ok=True,
            draft_id=stored.get("id", ""),
            status=stored.get("status", ""),
            mission_operation_id=mission_operation_id or None,
            mission_revision_id=mission_revision_id or None,
        )],
    }


def finalize_response(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Compose and store the final assistant message, then end the graph."""
    rt = _runtime(config)
    session_id = state.get("session_id", "")
    intent = state.get("intent") or {}
    draft_id = state.get("draft_id", "")
    approval_status = state.get("approval_status", "")
    validation = state.get("validation") or {}
    errors = state.get("errors") or []
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(session_id or ""),
    )
    retrieved_sources = state.get("retrieved_sources") or []

    intent_type = intent.get("intent_type", "unknown")

    parts: list[str] = []
    if intent_type not in _PLANNING_INTENT_TYPES:
        summary = (intent.get("summary") or "").strip()
        if summary:
            parts.append(f"Request understood: {summary}.")
        parts.append(
            "The workbench graph handles rover planning tasks (navigate, inspect, search). "
            "Use the General Chat session for status questions, replay analysis, or other queries."
        )
    elif draft_id:
        parts.append(f"Mission draft created (ID: {draft_id}).")
        parts.append(f"Status: {approval_status}.")
        for blocker in validation.get("blockers") or []:
            parts.append(f"Blocker: {blocker}")
        for warning in validation.get("warnings") or []:
            parts.append(f"Warning: {warning}")
        if approval_status == "awaiting_approval":
            parts.append("Use POST /api/ai/mission-drafts/{draft_id}/approve to approve this draft.")
        elif approval_status == "approved":
            note = state.get("approval_note", "")
            parts.append("Mission draft approved as a planning artifact.")
            mission_export = state.get("mission_export") or {}
            if mission_export.get("file_path"):
                parts.append(f"Mission exported: {mission_export.get('file_path')}.")
            if note:
                parts.append(f"Operator note: {note}")
        elif approval_status == "rejected":
            note = state.get("approval_note", "")
            parts.append("Mission draft rejected.")
            if note:
                parts.append(f"Operator note: {note}")
        elif approval_status == "validation_failed":
            parts.append("Validation failed. Refine your request and try again.")
        elif approval_status == "needs_clarification":
            parts.append("Additional information is needed before this draft can proceed.")
    clarification_response = state.get("clarification_response") or {}
    if clarification_response.get("cancelled") and not draft_id:
        parts.append("Mission planning cancelled during clarification.")
    elif not draft_id and intent_type in _PLANNING_INTENT_TYPES:
        parts.append("Could not generate a mission draft for this request.")
        fatal = [e for e in errors if e.get("severity") in ("error", "fatal")]
        if fatal:
            parts.append(f"Reason: {fatal[-1].get('message', 'unknown error')}.")
    if retrieved_sources:
        enabled = retrieval_request.get("enabled_sources") or []
        parts.append(f"Enabled source controls: {', '.join(str(item) for item in enabled)}.")

    content = " ".join(parts)
    meta = {
        "run_mode": "workbench",
        "intent": intent,
        "draft_id": draft_id,
        "approval_status": approval_status,
        "validation_status": validation.get("status", ""),
        "mission_export": state.get("mission_export") or {},
        "tool_trace": state.get("tool_trace") or [],
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": state.get("retrieval_citations") or [],
        "loaded_data_refs": state.get("loaded_data_refs") or [],
        "node_count": len(state.get("node_trace") or []),
        "planner_loop_enabled": bool(state.get("use_planner_loop")),
    }
    if state.get("use_planner_loop"):
        meta["planner_agent_stop_reason"] = str(state.get("planner_agent_stop_reason") or "")
        meta["planner_agent_iterations"] = int(state.get("planner_agent_iterations") or 0)
        meta["planner_agent_trace_id"] = str(state.get("planner_agent_trace_id") or "")
        if state.get("planner_loop_fallback"):
            meta["planner_loop_fallback"] = True
    usage_metadata = _merge_usage_metadata(
        state.get("intent_usage_metadata") or {},
        state.get("draft_usage_metadata") or {},
    )
    if usage_metadata:
        meta["usage_metadata"] = usage_metadata
    response_metadata = _merge_response_metadata(
        state.get("intent_response_metadata") or {},
        state.get("draft_response_metadata") or {},
    )
    if response_metadata:
        meta["response_metadata"] = response_metadata
    if session_id and content:
        try:
            rt.ai_session_store.add_message(
                session_id,
                role="assistant",
                content=content,
                meta=meta,
            )
        except Exception:
            pass

    return {
        "node_trace": [_node_entry(
            "finalize_response",
            draft_id=draft_id,
            approval_status=approval_status,
        )],
    }


def finalize_error(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Store a controlled error response and end the graph."""
    rt = _runtime(config)
    session_id = state.get("session_id", "")
    errors = state.get("errors") or []
    fatal = [e for e in errors if e.get("severity") == "fatal"]
    message = fatal[0]["message"] if fatal else "An unexpected error occurred in the workbench graph."

    if session_id:
        try:
            rt.ai_session_store.add_message(
                session_id,
                role="assistant",
                content=f"Workbench error: {message}",
                meta={"run_mode": "workbench", "errors": errors},
            )
        except Exception:
            pass

    return {
        "node_trace": [_node_entry("finalize_error", message=message)],
    }


def _route_after_capture(state: WorkbenchGraphState) -> str:
    errors = state.get("errors") or []
    if any(e.get("severity") == "fatal" for e in errors):
        return "finalize_error"
    return "retrieve_current_context"


def _route_after_scope(state: WorkbenchGraphState) -> str:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    lazy_branches = retrieval_request.get("lazy_branches") or []
    for branch in (
        "retrieve_replay_context",
        "retrieve_application_memory",
        "retrieve_settings_context",
        "retrieve_sensor_context",
    ):
        if branch in lazy_branches:
            return branch
    return "parse_intent"


def _route_after_lazy_branch(state: WorkbenchGraphState, current_branch: str) -> str:
    retrieval_request = _normalize_retrieval_request(
        state.get("retrieval_request") or {},
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    lazy_branches = retrieval_request.get("lazy_branches") or []
    ordered = [
        "retrieve_replay_context",
        "retrieve_application_memory",
        "retrieve_settings_context",
        "retrieve_sensor_context",
    ]
    try:
        start = ordered.index(current_branch) + 1
    except ValueError:
        start = 0
    for branch in ordered[start:]:
        if branch in lazy_branches:
            return branch
    return "parse_intent"


def _route_after_replay_branch(state: WorkbenchGraphState) -> str:
    return _route_after_lazy_branch(state, "retrieve_replay_context")


def _route_after_memory_branch(state: WorkbenchGraphState) -> str:
    return _route_after_lazy_branch(state, "retrieve_application_memory")


def _route_after_settings_branch(state: WorkbenchGraphState) -> str:
    return _route_after_lazy_branch(state, "retrieve_settings_context")


# ── Phase 5 nodes ─────────────────────────────────────────────────────────────

def planner_loop_node(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Run AgentLoopRuntime as a single planner node (Phase 5, behind ai_use_planner_loop flag).

    Replaces the classify_request_scope → lazy branches → parse_intent →
    prepare_clarification → resolve_target → generate_mission_draft DAG with a
    single agentic loop that calls those operations as tools.
    """
    rt = _runtime(config)

    resolved = None
    for purpose in ("mission_planner", "general_chat"):
        try:
            resolved = resolve_provider(
                rt.app_runtime.config,
                purpose=purpose,
                secret_resolver=rt.secret_resolver,
            )
            break
        except Exception:
            continue

    if resolved is None:
        return {
            "planner_loop_fallback": True,
            "errors": [{
                "node": "planner_loop_node", "code": "no_provider",
                "severity": "warning",
                "message": "no LLM provider available for planner loop; falling back to legacy path",
                "recoverable": True,
            }],
            "node_trace": [_node_entry("planner_loop_node", ok=False, reason="no_provider", fallback=True)],
        }

    agent_loop = AgentLoopRuntime(
        tool_registry=rt.tool_registry,
        prompt_builder=_planner_prompt_builder,
        system_prompt_for_mode=_planner_system_prompt_for_mode,
        allowed_tool_names=_planner_allowed_tool_names,
        response_content=lambda r: str(getattr(r, "content", r) or ""),
        usage_metadata=lambda r: (getattr(r, "usage_metadata", {}) or {}),
        tool_calling_unsupported=_is_tool_calling_unsupported_error,
        trace_store=rt.trace_store,
    )

    context_snapshot = _build_planner_context_snapshot(state)
    messages = [{"role": "user", "content": state.get("user_prompt", "")}]

    result: AgentInvokeResult | None = agent_loop.invoke_with_tools(
        resolved.model,
        messages=messages,
        context_snapshot=context_snapshot,
        prompt_tool_calls=[],
        tool_context={
            "runtime": rt.app_runtime,
            "timezone_name": state.get("operator_timezone", ""),
        },
        run_mode="planner",
    )

    if result is None:
        return {
            "planner_loop_fallback": True,
            "errors": [{
                "node": "planner_loop_node", "code": "tool_calling_unsupported",
                "severity": "warning",
                "message": "planner model does not support tool calling; falling back to legacy path",
                "recoverable": True,
            }],
            "node_trace": [_node_entry("planner_loop_node", ok=False, reason="tool_calling_unsupported", fallback=True)],
        }

    intent = _extract_planner_tool_result(result.tool_calls, "parse_rover_intent", "intent") or {}
    target_result = _extract_planner_tool_result(result.tool_calls, "resolve_spatial_target") or {}
    draft_raw = _extract_planner_tool_result(result.tool_calls, "propose_mission_draft", "draft") or {}

    # Collect route artifacts from any route-planning tool calls so they survive draft storage.
    route_artifacts: list[dict[str, Any]] = []
    for tc in result.tool_calls:
        if tc.get("name") in ("plan_route_around_group", "plan_route_between"):
            res = tc.get("result") or {}
            if isinstance(res, dict) and res.get("ok"):
                waypoints = res.get("waypoints") or []
                route_artifacts.append({
                    "tool": tc["name"],
                    "args": tc.get("args") or {},
                    "route_hash": res.get("route_hash", ""),
                    "waypoint_count": res.get("waypoint_count", len(waypoints)),
                    "total_distance_m": res.get("total_distance_m", 0.0),
                    "waypoints": waypoints,
                    "summary": {k: v for k, v in res.items() if k not in ("waypoints", "ok", "known_groups")},
                })

    draft_repairs: list[str] = []
    if draft_raw:
        if route_artifacts and "route_artifacts" not in draft_raw:
            draft_raw["route_artifacts"] = route_artifacts
        draft_raw, draft_repairs = normalize_mission_draft_payload(draft_raw)

    tool_trace_entries = [
        _tool_entry(tc["name"], tc.get("args") or {}, tc.get("result") or {})
        for tc in result.tool_calls
    ]

    node_update: dict = {
        "planner_agent_stop_reason": result.stop_reason,
        "planner_agent_iterations": result.iterations,
        "planner_agent_trace_id": result.trace_id,
        "tool_trace": tool_trace_entries,
        "node_trace": [_node_entry(
            "planner_loop_node",
            ok=result.stop_reason in ("draft_proposed", "clarification_requested", "final_answer"),
            stop_reason=result.stop_reason,
            iterations=result.iterations,
            trace_id=result.trace_id,
            has_intent=bool(intent),
            has_draft=bool(draft_raw),
            route_artifact_count=len(route_artifacts),
            draft_repairs=draft_repairs if draft_repairs else None,
        )],
    }
    if intent:
        node_update["intent"] = intent
        node_update["intent_usage_metadata"] = result.usage_metadata
        node_update["intent_response_metadata"] = result.response_metadata
    if target_result:
        node_update["target_resolution"] = target_result
        node_update["target_candidates"] = target_result.get("candidates") or []
    if draft_raw:
        node_update["draft"] = draft_raw
        node_update["draft_usage_metadata"] = result.usage_metadata
        node_update["draft_response_metadata"] = result.response_metadata

    # Clarification handoff: extract questions from the request_clarification tool result
    # and set clarification_request in state so _route_after_planner_loop routes to
    # prepare_clarification, which surfaces the card and bridges to legacy draft generation.
    if result.stop_reason == "clarification_requested":
        clar_result = _extract_planner_tool_result(result.tool_calls, "request_clarification") or {}
        handoff = (clar_result.get("handoff") or {}) if isinstance(clar_result, dict) else {}
        node_update["clarification_request"] = {
            "type": "clarification_request",
            "questions": list(handoff.get("questions") or []),
            "intent_summary": str(handoff.get("intent_summary") or intent.get("summary", "")),
        }

    return node_update


def _route_after_context(state: WorkbenchGraphState) -> str:
    if state.get("use_planner_loop"):
        return "planner_loop_node"
    return "classify_request_scope"


def _route_after_planner_loop(state: WorkbenchGraphState) -> str:
    # Setup/runtime failure: fall back to legacy classify → parse_intent → generate path.
    if state.get("planner_loop_fallback"):
        return "classify_request_scope"
    # Clarification needed: bridge to prepare_clarification (legacy path handles resume).
    if state.get("clarification_request") and not state.get("clarification_response"):
        return "prepare_clarification"
    if state.get("draft"):
        return "validate_draft"
    return "finalize_response"


# ── Phase 2 nodes ─────────────────────────────────────────────────────────────

def request_workbench_approval(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Pause for operator approval of the planning draft.

    Phase 2: calls interrupt() when a checkpointer is available.
    Fallback: returns operator_decision='pending_rest' so the REST approve/reject
    APIs continue working without a running graph thread.
    """
    rt = _runtime(config)
    draft = state.get("draft") or {}
    draft_id = state.get("draft_id", "")

    approval_payload = {
        "type": "workbench_draft_approval",
        "draft_id": draft_id,
        "mission_operation_id": state.get("mission_operation_id", ""),
        "mission_revision_id": state.get("mission_revision_id", ""),
        "goal": draft.get("goal", ""),
        "risks": draft.get("risks") or [],
        "route_summary": _route_summary_for_approval(draft),
        "execution_allowed": False,
        "approval_scope": "planning_artifact_only",
    }

    if _INTERRUPT_AVAILABLE and rt.checkpointer is not None:
        decision = lg_interrupt(approval_payload)
        decision_str = str((decision or {}).get("decision", "approve"))
        note = str((decision or {}).get("note", ""))
        return {
            "operator_decision": decision_str,
            "approval_note": note,
            "node_trace": [_node_entry("request_workbench_approval", mode="interrupt", decision=decision_str)],
        }

    # REST fallback — graph finishes normally; approval via separate API calls
    return {
        "operator_decision": "pending_rest",
        "node_trace": [_node_entry("request_workbench_approval", mode="rest_fallback")],
    }


def record_approval(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Record operator approval on the stored draft."""
    rt = _runtime(config)
    draft_id = state.get("draft_id", "")
    note = state.get("approval_note", "")
    try:
        approved = rt.draft_service.approve_draft(draft_id, note=note)
    except Exception as exc:
        return {
            "approval_status": "approved",
            "errors": [{
                "node": "record_approval", "code": "service_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            }],
            "node_trace": [_node_entry("record_approval", ok=False, reason=str(exc))],
        }
    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    mission_errors: list[dict[str, Any]] = []
    if mission_execution is not None:
        try:
            mission_execution.approve_revision_for_draft(draft_id, note=note)
        except Exception as exc:
            mission_errors.append({
                "node": "record_approval",
                "code": "mission_execution_approval_error",
                "severity": "warning",
                "message": str(exc),
                "recoverable": True,
            })
    mission_export: dict[str, Any] = {}
    export_error = ""
    if approved and _route_summary_for_approval(approved.get("draft") or {}).get("waypoint_count"):
        try:
            result = MissionExportService().export(
                approved,
                home_position=_home_position_from_rover_state(state.get("rover_state") or {}),
            )
            if result.get("ok"):
                updated = rt.draft_service.mark_exported(draft_id, export_result=result)
                mission_export = (updated or {}).get("draft", {}).get("mission_export") or {
                    "file_path": result.get("file_path", ""),
                    "waypoint_count": result.get("waypoint_count", 0),
                    "vehicle_type": result.get("vehicle_type", 0),
                }
                if mission_execution is not None:
                    try:
                        mission_execution.mark_revision_exported(draft_id, export_result=result)
                    except Exception as exc:
                        mission_errors.append({
                            "node": "record_approval",
                            "code": "mission_execution_export_sync_error",
                            "severity": "warning",
                            "message": str(exc),
                            "recoverable": True,
                        })
            else:
                export_error = str(result.get("error") or "mission export failed")
        except Exception as exc:
            export_error = str(exc)
    errors = mission_errors
    if export_error:
        errors.append({
            "node": "record_approval",
            "code": "mission_export_failed",
            "severity": "warning",
            "message": export_error,
            "recoverable": True,
        })
    return {
        "approval_status": "approved",
        "mission_export": mission_export,
        "errors": errors,
        "node_trace": [_node_entry(
            "record_approval",
            ok=not export_error,
            draft_id=draft_id,
            mission_export=mission_export,
            export_error=export_error or None,
        )],
    }


def record_rejection(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Record operator rejection on the stored draft."""
    rt = _runtime(config)
    draft_id = state.get("draft_id", "")
    note = state.get("approval_note", "")
    try:
        rt.draft_service.reject_draft(draft_id, note=note)
    except Exception as exc:
        return {
            "approval_status": "rejected",
            "errors": [{
                "node": "record_rejection", "code": "service_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            }],
            "node_trace": [_node_entry("record_rejection", ok=False, reason=str(exc))],
        }
    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    mission_errors: list[dict[str, Any]] = []
    if mission_execution is not None:
        try:
            mission_execution.reject_revision_for_draft(draft_id, note=note)
        except Exception as exc:
            mission_errors.append({
                "node": "record_rejection",
                "code": "mission_execution_rejection_error",
                "severity": "warning",
                "message": str(exc),
                "recoverable": True,
            })
    return {
        "approval_status": "rejected",
        "errors": mission_errors,
        "node_trace": [_node_entry("record_rejection", ok=True, draft_id=draft_id)],
    }


# ── Phase 3 nodes ─────────────────────────────────────────────────────────────

async def prepare_clarification(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Interrupt to collect missing information from the operator, then refresh context.

    Phase 3 constraint: rover pose and scene are re-fetched after the operator answers
    so the subsequent draft uses the freshest available state.

    Phase 5 bridge: when called from the planner-loop path, prefer questions and
    intent_summary from the clarification_request set by planner_loop_node over
    intent.missing_information, since the planner may refine the question list.
    """
    rt = _runtime(config)
    intent = state.get("intent") or {}
    # Prefer clarification_request set by planner_loop_node (planner path) when present.
    existing_clar = state.get("clarification_request") or {}
    questions = list(existing_clar.get("questions") or intent.get("missing_information") or [])
    intent_summary = str(existing_clar.get("intent_summary") or intent.get("summary", ""))

    clarification_payload = {
        "type": "clarification_request",
        "questions": questions,
        "intent_summary": intent_summary,
    }

    if _INTERRUPT_AVAILABLE and rt.checkpointer is not None:
        response = lg_interrupt(clarification_payload)
        if isinstance(response, dict):
            answer = str(response.get("note", ""))
            cancelled = str(response.get("decision", "continue")) == "cancel"
        else:
            answer = str(response or "")
            cancelled = False

        # Refresh rover pose/scene on resume (Phase 3 constraint)
        refreshed_rover: dict = state.get("rover_state") or {}
        refreshed_scene: dict = state.get("scene_summary") or {}
        try:
            snapshot = await rt.context_service.build_compact_context(
                user_message=state.get("user_prompt", ""),
                session_id=state.get("session_id", ""),
                timezone_name=state.get("operator_timezone", ""),
                run_mode="agent",
            )
            full_ctx = snapshot.meta.get("context_snapshot") or {}
            if full_ctx.get("rover"):
                refreshed_rover = full_ctx["rover"]
            if full_ctx.get("scene"):
                refreshed_scene = full_ctx["scene"]
        except Exception:
            pass

        return {
            "clarification_request": clarification_payload,
            "clarification_response": {"answer": answer, "cancelled": cancelled, "ts": time.time()},
            "rover_state": refreshed_rover,
            "scene_summary": refreshed_scene,
            "node_trace": [_node_entry(
                "prepare_clarification",
                mode="interrupt",
                questions=len(missing),
                answered=bool(answer),
                cancelled=cancelled,
            )],
        }

    # REST fallback: skip clarification, proceed with missing info as assumptions
    return {
        "clarification_request": clarification_payload,
        "clarification_response": {},
        "node_trace": [_node_entry("prepare_clarification", mode="rest_fallback", questions=len(missing))],
    }


def _route_after_clarification(state: WorkbenchGraphState) -> str:
    clarification_response = state.get("clarification_response") or {}
    if clarification_response.get("cancelled"):
        return "finalize_response"
    intent = state.get("intent") or {}
    if _has_spatial_target(intent):
        return "resolve_target"
    return "generate_mission_draft"


def _route_after_store_draft(state: WorkbenchGraphState) -> str:
    status = state.get("approval_status", "")
    if status == "awaiting_approval":
        return "request_workbench_approval"
    return "finalize_response"


def _route_after_approval(state: WorkbenchGraphState) -> str:
    decision = state.get("operator_decision", "")
    if decision == "reject":
        return "record_rejection"
    if decision == "approve":
        return "record_approval"
    # pending_rest or empty — go straight to finalize
    return "finalize_response"


# ── Graph construction ────────────────────────────────────────────────────────

def build_workbench_graph(checkpointer: Any = None):
    """Build and compile the workbench planning graph.

    Pass a LangGraph checkpointer to enable Phase 2 interrupt/resume approval.
    Without a checkpointer the graph falls back to REST-only approval.
    """
    graph: StateGraph = StateGraph(WorkbenchGraphState)

    graph.add_node("capture_request", capture_request)
    graph.add_node("retrieve_current_context", retrieve_current_context)
    graph.add_node("planner_loop_node", planner_loop_node)
    graph.add_node("classify_request_scope", classify_request_scope)
    graph.add_node("retrieve_replay_context", retrieve_replay_context)
    graph.add_node("retrieve_application_memory", retrieve_application_memory)
    graph.add_node("retrieve_settings_context", retrieve_settings_context)
    graph.add_node("retrieve_sensor_context", retrieve_sensor_context)
    graph.add_node("parse_intent", parse_intent)
    graph.add_node("prepare_clarification", prepare_clarification)
    graph.add_node("resolve_target", resolve_target)
    graph.add_node("generate_mission_draft", generate_mission_draft)
    graph.add_node("validate_draft", validate_draft)
    graph.add_node("store_draft", store_draft)
    graph.add_node("request_workbench_approval", request_workbench_approval)
    graph.add_node("record_approval", record_approval)
    graph.add_node("record_rejection", record_rejection)
    graph.add_node("finalize_response", finalize_response)
    graph.add_node("finalize_error", finalize_error)

    graph.add_edge(START, "capture_request")
    graph.add_conditional_edges(
        "capture_request",
        _route_after_capture,
        {"retrieve_current_context": "retrieve_current_context", "finalize_error": "finalize_error"},
    )
    graph.add_conditional_edges(
        "retrieve_current_context",
        _route_after_context,
        {"planner_loop_node": "planner_loop_node", "classify_request_scope": "classify_request_scope"},
    )
    graph.add_conditional_edges(
        "planner_loop_node",
        _route_after_planner_loop,
        {
            "classify_request_scope": "classify_request_scope",
            "prepare_clarification": "prepare_clarification",
            "validate_draft": "validate_draft",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_conditional_edges(
        "classify_request_scope",
        _route_after_scope,
        {
            "retrieve_replay_context": "retrieve_replay_context",
            "retrieve_application_memory": "retrieve_application_memory",
            "retrieve_settings_context": "retrieve_settings_context",
            "retrieve_sensor_context": "retrieve_sensor_context",
            "parse_intent": "parse_intent",
        },
    )
    graph.add_conditional_edges(
        "retrieve_replay_context",
        _route_after_replay_branch,
        {
            "retrieve_application_memory": "retrieve_application_memory",
            "retrieve_settings_context": "retrieve_settings_context",
            "retrieve_sensor_context": "retrieve_sensor_context",
            "parse_intent": "parse_intent",
        },
    )
    graph.add_conditional_edges(
        "retrieve_application_memory",
        _route_after_memory_branch,
        {
            "retrieve_settings_context": "retrieve_settings_context",
            "retrieve_sensor_context": "retrieve_sensor_context",
            "parse_intent": "parse_intent",
        },
    )
    graph.add_conditional_edges(
        "retrieve_settings_context",
        _route_after_settings_branch,
        {
            "retrieve_sensor_context": "retrieve_sensor_context",
            "parse_intent": "parse_intent",
        },
    )
    graph.add_edge("retrieve_sensor_context", "parse_intent")
    graph.add_conditional_edges(
        "parse_intent",
        _route_after_intent,
        {
            "prepare_clarification": "prepare_clarification",
            "resolve_target": "resolve_target",
            "generate_mission_draft": "generate_mission_draft",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_conditional_edges(
        "prepare_clarification",
        _route_after_clarification,
        {
            "resolve_target": "resolve_target",
            "generate_mission_draft": "generate_mission_draft",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_edge("resolve_target", "generate_mission_draft")
    graph.add_edge("generate_mission_draft", "validate_draft")
    graph.add_edge("validate_draft", "store_draft")
    graph.add_conditional_edges(
        "store_draft",
        _route_after_store_draft,
        {"request_workbench_approval": "request_workbench_approval", "finalize_response": "finalize_response"},
    )
    graph.add_conditional_edges(
        "request_workbench_approval",
        _route_after_approval,
        {
            "record_approval": "record_approval",
            "record_rejection": "record_rejection",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_edge("record_approval", "finalize_response")
    graph.add_edge("record_rejection", "finalize_response")
    graph.add_edge("finalize_response", END)
    graph.add_edge("finalize_error", END)

    return graph.compile(checkpointer=checkpointer)


# ── Streaming helpers ─────────────────────────────────────────────────────────

async def _emit_chunk_events(
    chunk: dict,
    *,
    run_id: str,
    current_state: dict,
):
    """Yield NDJSON lines for a single LangGraph astream chunk.

    Mutates current_state in place with each node's update dict.
    Yields strings. If the chunk contains __interrupt__, yields the sentinel
    string '__INTERRUPT__' and returns; callers should handle interrupt
    detection at the outer astream level before calling this helper.
    """
    if "__interrupt__" in chunk:
        # Interrupt detected — caller handles this; we just signal it
        yield "__INTERRUPT__"
        return

    for node_name, update in chunk.items():
        if not isinstance(update, dict):
            continue

        for entry in update.get("tool_trace") or []:
            yield _json_line({
                "type": "agent_tool_start",
                "tool": entry.get("tool", ""),
                "args": entry.get("args", {}),
                "node": node_name,
                "ts": entry.get("ts", time.time()),
            })
            yield _json_line({
                "type": "agent_tool_result",
                "tool": entry.get("tool", ""),
                "result": entry.get("result", {}),
                "node": node_name,
                "ts": entry.get("ts", time.time()),
            })

        visible_keys = [k for k in update if k not in ("tool_trace", "node_trace", "errors")]
        yield _json_line({
            "type": "graph_node_result",
            "node": node_name,
            "run_id": run_id,
            "update_keys": visible_keys,
            "ts": time.time(),
        })

        if update.get("draft_id"):
            yield _json_line({
                "type": "mission_draft_created",
                "draft_id": update["draft_id"],
                "approval_status": update.get("approval_status", ""),
                "ts": time.time(),
            })
        if update.get("validation"):
            yield _json_line({
                "type": "mission_draft_validation",
                "validation": update["validation"],
                "ts": time.time(),
            })
        if update.get("retrieved_sources") is not None:
            yield _json_line({
                "type": "graph_retrieval_result",
                "retrieval_request": update.get("retrieval_request", current_state.get("retrieval_request", {})),
                "retrieved_sources": update.get("retrieved_sources") or [],
                "retrieval_citations": update.get("retrieval_citations") or [],
                "ts": time.time(),
            })
        if update.get("approval_status") == "awaiting_approval":
            draft_id = update.get("draft_id") or current_state.get("draft_id", "")
            yield _json_line({
                "type": "mission_draft_approval_required",
                "draft_id": draft_id,
                "ts": time.time(),
            })
        if update.get("approval_status") in ("approved", "rejected"):
            yield _json_line({
                "type": "mission_draft_decision",
                "draft_id": update.get("draft_id") or current_state.get("draft_id", ""),
                "approval_status": update["approval_status"],
                "ts": time.time(),
            })

        current_state.update(update)


# ── Streaming runner ──────────────────────────────────────────────────────────

async def stream_workbench_graph(
    runtime: WorkbenchGraphRuntime,
    *,
    session_id: str,
    user_prompt: str,
    operator_timezone: str = "",
    session_mode: str = "workbench",
    source_message_id: str = "",
    source_controls: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Async generator that runs the graph and yields NDJSON event lines.

    Phase 2: when the graph hits interrupt() at request_workbench_approval,
    emits graph_interrupt with the thread_id and stops streaming. The client
    then calls the resume endpoint with the operator decision.
    """
    run_id = uuid.uuid4().hex[:12]
    thread_id = f"ai-session:{session_id}:run:{run_id}"
    graph = build_workbench_graph(checkpointer=runtime.checkpointer)

    initial_state: WorkbenchGraphState = {  # type: ignore[typeddict-item]
        "session_id": session_id,
        "thread_id": thread_id,
        "user_prompt": user_prompt,
        "operator_timezone": operator_timezone,
        "session_mode": session_mode,
        "source_message_id": source_message_id,
        "retrieval_request": _normalize_retrieval_request(
            {"source_controls": normalize_source_controls(source_controls)},
            user_prompt=user_prompt,
            session_id=session_id,
        ),
        "retrieved_sources": [],
        "retrieval_citations": [],
        "loaded_data_refs": [],
        "tool_trace": [],
        "node_trace": [],
        "errors": [],
    }
    lg_config = {"configurable": {"runtime": runtime, "run_id": run_id, "thread_id": thread_id}}

    yield _json_line({
        "type": "graph_run_start",
        "run_id": run_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "planner_loop_enabled": bool(getattr(runtime.app_runtime.config, "ai_use_planner_loop", False)),
        "ts": time.time(),
    })

    current_state: dict = dict(initial_state)
    interrupted = False
    try:
        async for chunk in graph.astream(initial_state, config=lg_config):
            if "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                intr_value: Any = {}
                if interrupts:
                    intr = interrupts[0]
                    intr_value = intr.value if hasattr(intr, "value") else intr
                    if not isinstance(intr_value, dict):
                        intr_value = {"raw": str(intr_value)}
                yield _json_line({
                    "type": "graph_interrupt",
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "interrupt_value": intr_value,
                    "ts": time.time(),
                })
                interrupted = True
                break

            async for line in _emit_chunk_events(chunk, run_id=run_id, current_state=current_state):
                if line != "__INTERRUPT__":
                    yield line

    except Exception as exc:
        yield _json_line({
            "type": "graph_run_error",
            "run_id": run_id,
            "thread_id": thread_id,
            "error": str(exc),
            "ts": time.time(),
        })

    if not interrupted:
        yield _json_line({
            "type": "graph_run_end",
            "run_id": run_id,
            "thread_id": thread_id,
            "session_id": session_id,
            "draft_id": current_state.get("draft_id", ""),
            "approval_status": current_state.get("approval_status", ""),
            "ts": time.time(),
        })


async def resume_workbench_graph(
    runtime: WorkbenchGraphRuntime,
    *,
    thread_id: str,
    decision: str,
    note: str = "",
) -> AsyncIterator[str]:
    """Resume a graph that is suspended at an interrupt() approval gate.

    Requires runtime.checkpointer to be set (Phase 2). Yields NDJSON events
    for the remaining graph nodes after the approval decision.
    """
    if not _INTERRUPT_AVAILABLE:
        yield _json_line({
            "type": "graph_run_error",
            "thread_id": thread_id,
            "error": "LangGraph interrupt/resume is not available in this installation.",
            "ts": time.time(),
        })
        return

    if runtime.checkpointer is None:
        yield _json_line({
            "type": "graph_run_error",
            "thread_id": thread_id,
            "error": "No checkpointer configured. Cannot resume an interrupted graph.",
            "ts": time.time(),
        })
        return

    run_id = thread_id.split(":")[-1] if ":" in thread_id else thread_id
    graph = build_workbench_graph(checkpointer=runtime.checkpointer)
    lg_config = {"configurable": {"runtime": runtime, "thread_id": thread_id}}

    yield _json_line({
        "type": "graph_resume_start",
        "run_id": run_id,
        "thread_id": thread_id,
        "decision": decision,
        "ts": time.time(),
    })

    current_state: dict = {}
    try:
        async for chunk in graph.astream(
            Command(resume={"decision": decision, "note": note}),
            config=lg_config,
        ):
            if "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                intr_value: Any = {}
                if interrupts:
                    intr = interrupts[0]
                    intr_value = intr.value if hasattr(intr, "value") else intr
                    if not isinstance(intr_value, dict):
                        intr_value = {"raw": str(intr_value)}
                yield _json_line({
                    "type": "graph_interrupt",
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "interrupt_value": intr_value,
                    "ts": time.time(),
                })
                break

            async for line in _emit_chunk_events(chunk, run_id=run_id, current_state=current_state):
                if line != "__INTERRUPT__":
                    yield line

    except Exception as exc:
        yield _json_line({
            "type": "graph_run_error",
            "run_id": run_id,
            "thread_id": thread_id,
            "error": str(exc),
            "ts": time.time(),
        })

    yield _json_line({
        "type": "graph_run_end",
        "run_id": run_id,
        "thread_id": thread_id,
        "draft_id": current_state.get("draft_id", ""),
        "approval_status": current_state.get("approval_status", ""),
        "ts": time.time(),
    })
