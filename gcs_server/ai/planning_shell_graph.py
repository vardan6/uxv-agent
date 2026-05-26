"""Planning-shell graph for durable mission-planning approval (Phases 1-6).

Phase 6: legacy deterministic-DAG middle removed. Planner loop
(Phase 5 / planner_loop_node) is now the sole default path.
prepare_clarification remains for HITL clarification interrupt,
routing back to planner_loop_node on resume.

Node order:
    capture_request
    retrieve_current_context
    planner_loop_node           AgentLoopRuntime with planner tools
    [prepare_clarification]     only when planner requests clarification
    validate_draft
    store_draft
    request_planning_shell_approval  interrupt() durable HITL
    record_approval | record_rejection
    finalize_response

Error path: capture_request -> finalize_error (fatal input errors only).

Constraints:
- No command staging, no MQTT publishing, no controller lock writes.
- execution_allowed is always False on any generated draft.
"""

from __future__ import annotations

import json
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
    from gcs_server.ai.graph_runtime import PlanningShellGraphRuntime
    from gcs_server.ai.graph_state import PlanningShellGraphState
    from gcs_server.ai.mission_export_service import MissionExportService
    from gcs_server.ai.mission_repository import validate_mission_json
    from gcs_server.ai.provider_registry import resolve_provider
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
    from ai.graph_runtime import PlanningShellGraphRuntime
    from ai.graph_state import PlanningShellGraphState
    from ai.mission_export_service import MissionExportService
    from ai.mission_repository import validate_mission_json
    from ai.provider_registry import resolve_provider
    from ai.retrieval import (
        build_loaded_data_refs,
        build_retrieval_citations,
        build_retrieved_sources,
        normalize_retrieval_request,
    )
    from ai.session_store import normalize_source_controls
    from ai.tool_registry import allowed_tool_names_for_source_controls, normalize_mission_draft_payload


# ── Constants ─────────────────────────────────────────────────────────────────

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
    "- If the context reports an active revision with 'ai+edited' waypoints and the operator's request "
    "is ambiguous about whether to replace or extend the mission, call request_clarification before "
    "calling propose_mission_draft. Never silently discard operator-edited waypoints.\n"
    "- When your proposal refines or extends the current mission (operator confirmed, or intent is "
    "clearly a refinement), pass the active mission's operation_id as parent_operation_id to "
    "propose_mission_draft so the new revision appears under the same operation group. "
    "When the operator asks for a wholly new mission unrelated to the current one, omit parent_operation_id.\n"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _runtime(config: RunnableConfig) -> PlanningShellGraphRuntime:
    return (config.get("configurable") or {})["runtime"]


def _node_entry(name: str, **extra: Any) -> dict:
    return {"node": name, "ts": time.time(), **extra}


def _tool_entry(name: str, args: dict, result: Any) -> dict:
    return {"tool": name, "args": args, "result": result, "ts": time.time()}


def _provider_snapshot(provider: dict[str, Any] | None) -> dict[str, Any]:
    source = provider if isinstance(provider, dict) else {}
    return {
        "id": str(source.get("id") or "").strip(),
        "display_name": str(source.get("display_name") or "").strip(),
        "provider_type": str(source.get("provider_type") or "").strip(),
        "model_id": str(source.get("model_id") or "").strip(),
        "context_window": source.get("context_window"),
    }


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


def _build_active_mission_context(mission_execution: Any, session_id: str) -> dict[str, Any]:
    """Return a compact provenance summary for the active revision of the current session.

    Used by the planner to detect operator-edited waypoints before proposing a new mission.
    Returns an empty dict when no active revision exists or the service is unavailable.
    """
    if mission_execution is None or not session_id:
        return {}
    try:
        revision = mission_execution.get_current_revision(session_id=session_id)
    except Exception:
        return {}
    if not revision:
        return {}

    provenance: dict[str, str] = revision.get("provenance") or {}
    mission = revision.get("mission") or {}

    ai_count = sum(1 for v in provenance.values() if v == "ai")
    edited_count = sum(1 for v in provenance.values() if v == "ai+edited")
    user_count = sum(1 for v in provenance.values() if v == "user")
    total_tracked = ai_count + edited_count + user_count

    waypoint_count = 0
    for artifact in (mission.get("route_artifacts") or []):
        if isinstance(artifact, dict):
            waypoint_count += int(artifact.get("waypoint_count") or len(artifact.get("waypoints") or []))
    if not waypoint_count and isinstance(mission.get("waypoints"), list):
        waypoint_count = len(mission["waypoints"])

    return {
        "has_active_revision": True,
        "revision_id": str(revision.get("id") or ""),
        "revision_status": str(revision.get("status") or revision.get("operation_status") or ""),
        "operation_id": str(revision.get("operation_id") or ""),
        "goal": str(mission.get("goal") or ""),
        "waypoint_count": waypoint_count,
        "provenance_ai": ai_count,
        "provenance_ai_edited": edited_count,
        "provenance_user": user_count,
        "has_operator_edits": edited_count > 0,
        "is_operator_authored": total_tracked > 0 and edited_count == 0 and ai_count == 0,
    }


def _build_data_access_manifest(runtime: PlanningShellGraphRuntime, source_controls: dict[str, Any] | None = None) -> dict:
    return build_data_access_manifest(
        runtime.tool_registry.definitions(),
        allowed_tool_names=allowed_tool_names_for_source_controls(source_controls),
    )


def _normalize_retrieval_request(value: Any, *, user_prompt: str = "", session_id: str = "") -> dict[str, Any]:
    return normalize_retrieval_request(value, user_prompt=user_prompt, session_id=session_id)


def _coerce_scene_point(value: Any, *, fallback_id: str = "") -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        point = {
            "x": float(value.get("x")),
            "y": float(value.get("y")),
            "z": float(value.get("z", 0.0) or 0.0),
        }
    except (TypeError, ValueError):
        return None
    point["id"] = str(value.get("id") or fallback_id or "")
    point["label"] = str(value.get("label") or "")
    point["kind"] = str(value.get("kind") or "")
    return point


def _collect_waypoints(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("waypoints"), list):
        direct = [
            _coerce_scene_point(wp, fallback_id=f"wp-{index}")
            for index, wp in enumerate(payload["waypoints"], start=1)
        ]
        direct_points = [wp for wp in direct if wp is not None]
        if direct_points:
            return direct_points

    route_waypoints: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(payload.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        for waypoint_index, waypoint in enumerate(artifact.get("waypoints") or [], start=1):
            point = _coerce_scene_point(
                waypoint,
                fallback_id=f"route-{artifact_index}-wp-{waypoint_index}",
            )
            if point is not None:
                route_waypoints.append(point)
    if route_waypoints:
        return route_waypoints

    step_waypoints: list[dict[str, Any]] = []
    for step_index, step in enumerate(payload.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        for waypoint_index, waypoint in enumerate(step.get("waypoints") or [], start=1):
            point = _coerce_scene_point(
                waypoint,
                fallback_id=f"step-{step_index}-wp-{waypoint_index}",
            )
            if point is not None:
                step_waypoints.append(point)
    return step_waypoints


def _is_explicit_replace_confirmation(answer: str) -> bool:
    text = str(answer or "").strip().lower()
    if not text:
        return False
    phrases = (
        "replace",
        "overwrite",
        "supersede",
        "regenerate",
        "start over",
        "discard the edits",
        "discard edits",
        "ignore the edits",
        "ignore edits",
    )
    return any(phrase in text for phrase in phrases)


def _build_provenance_conflict(state: PlanningShellGraphState, rt: PlanningShellGraphRuntime) -> dict[str, Any]:
    draft = state.get("draft") or {}
    mission = state.get("active_mission_context") or {}
    parent_operation_id = str(state.get("parent_operation_id") or "").strip()
    current_operation_id = str(mission.get("operation_id") or "").strip()
    if not draft or not parent_operation_id or parent_operation_id != current_operation_id:
        return {}
    if not mission.get("has_operator_edits"):
        return {}
    answer = str((state.get("clarification_response") or {}).get("answer") or "")
    if _is_explicit_replace_confirmation(answer):
        return {}

    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    if mission_execution is None:
        return {}
    current_revision = mission_execution.get_current_revision(session_id=str(state.get("session_id") or ""))
    if not current_revision:
        return {}

    provenance = current_revision.get("provenance") if isinstance(current_revision.get("provenance"), dict) else {}
    current_waypoints = _collect_waypoints(current_revision.get("mission") or {})
    edited_waypoints = [
        {
            "id": str(point.get("id") or f"mission-wp-{index}"),
            "label": str(point.get("label") or f"Waypoint {index}"),
            "index": index,
        }
        for index, point in enumerate(current_waypoints, start=1)
        if provenance.get(str(point.get("id") or f"mission-wp-{index}")) == "ai+edited"
    ]
    if not edited_waypoints:
        return {}

    proposed_waypoints = _collect_waypoints(draft)
    if not proposed_waypoints:
        return {}

    summary = (
        f"The active mission revision has {len(edited_waypoints)} operator-edited waypoint(s). "
        "Creating a new AI proposal linked to this mission would supersede those edits."
    )
    edited_labels = ", ".join(item["label"] for item in edited_waypoints[:3])
    if len(edited_waypoints) > 3:
        edited_labels = f"{edited_labels}, and {len(edited_waypoints) - 3} more"
    question = (
        "Reply with 'replace' if you want the AI to supersede those edited waypoints, "
        "or describe how the mission should preserve or extend them instead."
    )
    return {
        "type": "provenance_conflict",
        "intent_summary": summary,
        "questions": [question],
        "summary": summary,
        "edited_waypoints": edited_waypoints,
        "edited_waypoint_labels": edited_labels,
        "current_revision_id": str(current_revision.get("id") or ""),
        "current_waypoint_count": len(current_waypoints),
        "proposed_waypoint_count": len(proposed_waypoints),
    }


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
    clarification_answer = (context_snapshot or {}).get("meta", {}).get("clarification_answer")
    if clarification_answer:
        lines.append(f"Operator answered your clarification question: {clarification_answer}")
        lines.append("Continue from where you left off using this answer to complete the mission draft.")
    rover = ctx.get("rover") or {}
    if rover.get("position"):
        lines.append(f"Rover position: {json.dumps(rover['position'])}")
    mission = ctx.get("mission") or {}
    if mission.get("has_active_revision"):
        edited = int(mission.get("provenance_ai_edited") or 0)
        user = int(mission.get("provenance_user") or 0)
        total = int(mission.get("waypoint_count") or 0)
        goal = str(mission.get("goal") or "")
        status = str(mission.get("revision_status") or "")
        parts = [f"There is an active mission revision (status: {status}"]
        if goal:
            parts.append(f', goal: "{goal}"')
        parts.append(f", {total} waypoint(s)).")
        if edited > 0:
            parts.append(
                f" {edited} waypoint(s) carry 'ai+edited' provenance — the operator manually "
                "repositioned them after the AI proposed the route. "
                "Your new proposal will supersede those edits. "
                "If the operator's request is to refine or extend the existing mission rather than replace it, "
                "ask a clarification question before proposing."
            )
        elif user > 0:
            parts.append(
                f" {user} waypoint(s) are fully operator-authored (provenance: user). "
                "Your proposal will create a new revision; the operator's waypoints will not be carried forward automatically."
            )
        op_id = str(mission.get("operation_id") or "")
        if op_id:
            parts.append(
                f" Use parent_operation_id=\"{op_id}\" in propose_mission_draft if your proposal "
                "refines or extends this mission."
            )
        lines.append("".join(parts))
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


def _build_planner_context_snapshot(state: PlanningShellGraphState) -> dict:
    """Build a context_snapshot suitable for the planner AgentLoopRuntime.

    Source controls are carried into meta so lazy tool handlers can enforce them.
    Larger retrieval surfaces stay out of the planner context until tools load them.
    """
    source_controls = normalize_source_controls(
        (state.get("retrieval_request") or {}).get("source_controls")
    )
    snapshot = {
        "meta": {
            "context_snapshot": {
                "rover": state.get("rover_state") or {},
                "scene": state.get("scene_summary") or {},
                "mission": state.get("active_mission_context") or {},
                "runtime": state.get("runtime_summary") or {},
                "details": {},
                "settings": {},
                "llm": state.get("llm_summary") or {},
            },
            "context_text": (state.get("context_metadata") or {}).get("context_text", ""),
            "source_controls": source_controls,
        }
    }
    clar = state.get("clarification_response") or {}
    if clar and clar.get("answer"):
        snapshot["meta"]["clarification_answer"] = clar["answer"]
    return snapshot


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


def _build_retrieved_sources(state: PlanningShellGraphState) -> list[dict[str, Any]]:
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


def _retrieval_update_from_tool_calls(
    state: PlanningShellGraphState,
    tool_calls: list[dict],
) -> dict[str, Any]:
    branch_by_tool = {
        "lazy_load_replay": "retrieve_replay_context",
        "lazy_load_ai_memory": "retrieve_application_memory",
        "lazy_load_settings": "retrieve_settings_context",
        "lazy_load_sensor": "retrieve_sensor_context",
    }
    lazy_branches: list[str] = []
    replay_summary: dict[str, Any] = {}
    chat_history_summary: dict[str, Any] = {}
    settings_summary: dict[str, Any] = {}
    sensor_summary: dict[str, Any] = {}

    for call in tool_calls:
        name = str(call.get("name") or "")
        branch = branch_by_tool.get(name)
        if branch and branch not in lazy_branches:
            lazy_branches.append(branch)
        result = call.get("result") or {}
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        if name == "lazy_load_replay":
            replay_summary = result.get("replay_summary") or {}
        elif name == "lazy_load_ai_memory":
            chat_history_summary = result.get("chat_history_summary") or {}
        elif name == "lazy_load_settings":
            settings_summary = result.get("settings_summary") or {}
        elif name == "lazy_load_sensor":
            sensor_summary = {
                "telemetry_fresh": result.get("telemetry_fresh"),
                "camera_fresh": result.get("camera_fresh"),
            }

    if not lazy_branches:
        return {}

    retrieval_request = _normalize_retrieval_request(
        {
            **(state.get("retrieval_request") or {}),
            "lazy_branches": lazy_branches,
        },
        user_prompt=str(state.get("user_prompt") or ""),
        session_id=str(state.get("session_id") or ""),
    )
    retrieved_sources = build_retrieved_sources(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=replay_summary,
        chat_history_summary=chat_history_summary,
        settings_summary=settings_summary,
        sensor_summary=sensor_summary,
    )
    loaded_data_refs = build_loaded_data_refs(
        retrieval_request=retrieval_request,
        session_id=str(state.get("session_id") or ""),
        replay_summary=replay_summary,
        chat_history_summary=chat_history_summary,
        settings_summary=settings_summary,
        sensor_summary=sensor_summary,
    )
    return {
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": build_retrieval_citations(retrieved_sources, loaded_data_refs),
        "loaded_data_refs": loaded_data_refs,
        "replay_summary": replay_summary,
        "chat_history_summary": chat_history_summary,
        "settings_summary": settings_summary,
    }


# ── Nodes ─────────────────────────────────────────────────────────────────────

def capture_request(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
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
                meta={"run_mode": "planning_shell"},
            )
            source_message_id = msg.get("id", "")
        except Exception as exc:
            errors.append({
                "node": "capture_request", "code": "session_store_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            })

    return {
        "source_message_id": source_message_id,
        "retrieval_request": _normalize_retrieval_request(
            state.get("retrieval_request") or {},
            user_prompt=user_prompt,
            session_id=session_id,
        ),
        "node_trace": [_node_entry("capture_request", fatal_errors=sum(1 for e in errors if e.get("severity") == "fatal"))],
        "errors": errors,
    }


async def retrieve_current_context(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
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

    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    active_mission_context = _build_active_mission_context(mission_execution, str(state.get("session_id") or ""))

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
        "active_mission_context": active_mission_context,
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": retrieval_citations,
        "loaded_data_refs": loaded_data_refs,
        "node_trace": [_node_entry("retrieve_current_context", ok=True)],
    }


def validate_draft(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Run deterministic validation rules on the draft payload."""
    rt = _runtime(config)
    intent = state.get("intent") or {}
    target_resolution = state.get("target_resolution") or {}
    draft = state.get("draft") or {}
    rover_state = state.get("rover_state") or None

    # ADR 0021 Slice 2b.2: repo-driven structural validation against the
    # mission_json shape persisted by MissionRepository / executed by
    # MissionExportService. The planner draft can wrap the mission payload as
    # `draft['draft']`, `draft['mission']`, or be the payload itself.
    mission_payload = draft.get("draft") if isinstance(draft.get("draft"), dict) else None
    if not isinstance(mission_payload, dict):
        mission_payload = draft.get("mission") if isinstance(draft.get("mission"), dict) else None
    if not isinstance(mission_payload, dict):
        mission_payload = draft if isinstance(draft, dict) else {}
    validation = validate_mission_json(mission_payload)

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

    provenance_conflict = _build_provenance_conflict(state, rt)
    if provenance_conflict:
        new_errors.append({
            "node": "validate_draft",
            "code": "provenance_conflict",
            "severity": "warning",
            "message": provenance_conflict.get("summary") or "operator-edited waypoints need confirmation before replacement",
            "recoverable": True,
        })

    return {
        "validation": validation,
        "clarification_request": provenance_conflict,
        "clarification_response": {} if provenance_conflict else (state.get("clarification_response") or {}),
        "provenance_conflict": provenance_conflict,
        "errors": new_errors,
        "node_trace": [_node_entry(
            "validate_draft",
            status=validation.get("status", "unknown"),
            provenance_conflict=bool(provenance_conflict),
        )],
    }


def store_draft(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Persist the draft with mission_execution as canonical storage.

    Planning-shell writes are mission-revision-first: this node allocates a
    stable draft_id and persists only through mission_execution.
    """
    rt = _runtime(config)
    draft = state.get("draft") or {}
    intent = state.get("intent") or {}

    if not draft or not intent:
        return {
            "draft_id": "",
            "approval_status": "validation_failed",
            "node_trace": [_node_entry("store_draft", ok=False, reason="empty_draft_or_intent")],
        }

    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    draft_id = str(state.get("draft_id") or "").strip() or f"ai-draft-{uuid.uuid4().hex[:12]}"
    draft_status = str(state.get("approval_status") or "awaiting_approval")
    validation = state.get("validation") or {}
    mission_operation_id = ""
    mission_revision_id = ""
    mission_errors: list[dict[str, Any]] = []
    if mission_execution is None:
        return {
            "draft_id": "",
            "approval_status": "validation_failed",
            "errors": [{
                "node": "store_draft",
                "code": "mission_execution_unavailable",
                "severity": "error",
                "message": "mission execution service unavailable",
                "recoverable": False,
            }],
            "node_trace": [_node_entry("store_draft", ok=False, reason="mission_execution_unavailable")],
        }

    try:
        revision = mission_execution.create_proposal(
            session_id=state.get("session_id", ""),
            source_message_id=state.get("source_message_id", ""),
            draft_id=draft_id,
            intent=intent,
            target_resolution=state.get("target_resolution") or {},
            draft_payload=draft,
            validation=validation,
            draft_status=draft_status,
            review_context={
                "goal": draft.get("goal", ""),
                "risks": draft.get("risks") or [],
                "approval_scope": "planning_artifact_only",
            },
            parent_operation_id=state.get("parent_operation_id", ""),
        )
        mission_operation_id = str(revision.get("operation_id") or "")
        mission_revision_id = str(revision.get("id") or "")
    except Exception as exc:
        return {
            "draft_id": "",
            "approval_status": "validation_failed",
            "errors": [{
                "node": "store_draft",
                "code": "mission_execution_store_error",
                "severity": "error",
                "message": str(exc),
                "recoverable": False,
            }],
            "node_trace": [_node_entry("store_draft", ok=False, reason="mission_execution_store_exception")],
        }

    return {
        "draft_id": draft_id,
        "mission_operation_id": mission_operation_id,
        "mission_revision_id": mission_revision_id,
        "approval_status": draft_status,
        "errors": mission_errors,
        "node_trace": [_node_entry(
            "store_draft", ok=True,
            draft_id=draft_id,
            status=draft_status,
            mission_operation_id=mission_operation_id or None,
            mission_revision_id=mission_revision_id or None,
        )],
    }


def finalize_response(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Compose and store the final assistant message, then end the graph."""
    rt = _runtime(config)
    session_id = state.get("session_id", "")
    intent = state.get("intent") or {}
    draft_id = state.get("draft_id", "")
    mission_revision_id = str(state.get("mission_revision_id") or "")
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

    _planning_intent_types = frozenset({"navigate_to_object", "inspect_area", "search_area"})
    parts: list[str] = []
    if intent_type not in _planning_intent_types and not draft_id:
        summary = (intent.get("summary") or "").strip()
        if summary:
            parts.append(f"Request understood: {summary}.")
        parts.append(
            "The planning shell handles rover planning tasks (navigate, inspect, search). "
            "Use the General Chat session for status questions, replay analysis, or other queries."
        )
    elif draft_id:
        parts.append(f"Mission draft created (ID: {draft_id}).")
        if mission_revision_id:
            parts.append(f"Mission revision ID: {mission_revision_id}.")
        parts.append(f"Status: {approval_status}.")
        for blocker in validation.get("blockers") or []:
            parts.append(f"Blocker: {blocker}")
        for warning in validation.get("warnings") or []:
            parts.append(f"Warning: {warning}")
        if approval_status == "awaiting_approval":
            if mission_revision_id:
                parts.append(
                    "Use POST /api/ai/mission-revisions/{revision_id}/approve to approve this mission revision."
                )
            else:
                parts.append("Mission revision link missing; retry planning to create a revision-backed draft.")
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
    elif not draft_id:
        parts.append("Could not generate a mission draft for this request.")
        relevant_errors = [e for e in errors if e.get("severity") in ("warning", "error", "fatal")]
        if relevant_errors:
            parts.append(f"Reason: {relevant_errors[-1].get('message', 'unknown error')}.")
    if retrieved_sources:
        enabled = retrieval_request.get("enabled_sources") or []
        parts.append(f"Enabled source controls: {', '.join(str(item) for item in enabled)}.")

    content = " ".join(parts)
    meta = {
        "run_mode": "planning_shell",
        "intent": intent,
        "draft_id": draft_id,
        "mission_revision_id": mission_revision_id,
        "approval_status": approval_status,
        "validation_status": validation.get("status", ""),
        "mission_export": state.get("mission_export") or {},
        "tool_trace": state.get("tool_trace") or [],
        "retrieval_request": retrieval_request,
        "retrieved_sources": retrieved_sources,
        "retrieval_citations": state.get("retrieval_citations") or [],
        "loaded_data_refs": state.get("loaded_data_refs") or [],
        "node_count": len(state.get("node_trace") or []),
        "planner_loop_enabled": True,
    }
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
    provider_snapshot = _provider_snapshot(state.get("intent_provider") or {})
    if provider_snapshot.get("id"):
        meta["provider_snapshot"] = provider_snapshot
    if session_id and content:
        try:
            rt.ai_session_store.add_message(
                session_id,
                role="assistant",
                content=content,
                provider_id=str(provider_snapshot.get("id") or ""),
                model_id=str(provider_snapshot.get("model_id") or ""),
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


def finalize_error(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Store a controlled error response and end the graph."""
    rt = _runtime(config)
    session_id = state.get("session_id", "")
    errors = state.get("errors") or []
    fatal = [e for e in errors if e.get("severity") == "fatal"]
    message = fatal[0]["message"] if fatal else "An unexpected error occurred in the planning shell."
    provider_snapshot = _provider_snapshot(state.get("intent_provider") or {})

    if session_id:
        try:
            rt.ai_session_store.add_message(
                session_id,
                role="assistant",
                content=f"Planning shell error: {message}",
                provider_id=str(provider_snapshot.get("id") or ""),
                model_id=str(provider_snapshot.get("model_id") or ""),
                meta={
                    "run_mode": "planning_shell",
                    "errors": errors,
                    "provider_snapshot": provider_snapshot if provider_snapshot.get("id") else {},
                },
            )
        except Exception:
            pass

    return {
        "node_trace": [_node_entry("finalize_error", message=message)],
    }


def _route_after_capture(state: PlanningShellGraphState) -> str:
    errors = state.get("errors") or []
    if any(e.get("severity") == "fatal" for e in errors):
        return "finalize_error"
    return "retrieve_current_context"


# ── Phase 5 nodes ─────────────────────────────────────────────────────────────

def planner_loop_node(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Run AgentLoopRuntime as the sole planner node (Phase 6).

    Calls parse_rover_intent, resolve_spatial_target, lazy-load tools,
    request_clarification, and propose_mission_draft as agent tools.
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
                "message": "no LLM provider available for planner loop",
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
            "intent_provider": _provider_snapshot(resolved.provider),
            "planner_loop_fallback": True,
            "errors": [{
                "node": "planner_loop_node", "code": "tool_calling_unsupported",
                "severity": "warning",
                "message": "planner model does not support tool calling",
                "recoverable": True,
            }],
            "node_trace": [_node_entry("planner_loop_node", ok=False, reason="tool_calling_unsupported", fallback=True)],
        }

    intent = _extract_planner_tool_result(result.tool_calls, "parse_rover_intent", "intent") or {}
    target_result = _extract_planner_tool_result(result.tool_calls, "resolve_spatial_target") or {}
    draft_raw = _extract_planner_tool_result(result.tool_calls, "propose_mission_draft", "draft") or {}
    parent_operation_id = str(
        _extract_planner_tool_result(result.tool_calls, "propose_mission_draft", "parent_operation_id") or ""
    ).strip()

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
        "intent_provider": _provider_snapshot(resolved.provider),
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
    node_update.update(_retrieval_update_from_tool_calls(state, result.tool_calls))
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
    if parent_operation_id:
        node_update["parent_operation_id"] = parent_operation_id

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


def _route_after_context(state: PlanningShellGraphState) -> str:
    return "planner_loop_node"


def _route_after_planner_loop(state: PlanningShellGraphState) -> str:
    if state.get("planner_loop_fallback"):
        return "finalize_response"
    if state.get("clarification_request") and not state.get("clarification_response"):
        return "prepare_clarification"
    if state.get("draft"):
        return "validate_draft"
    return "finalize_response"


# ── Phase 2 nodes ─────────────────────────────────────────────────────────────

def request_planning_shell_approval(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Pause for operator approval of the planning draft.

    Phase 2: calls interrupt() when a checkpointer is available.
    Fallback: returns operator_decision='pending_rest' so the REST approve/reject
    APIs continue working without a running graph thread.
    """
    rt = _runtime(config)
    draft = state.get("draft") or {}
    draft_id = state.get("draft_id", "")

    approval_payload = {
        "type": "planning_shell_draft_approval",
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
            "node_trace": [_node_entry("request_planning_shell_approval", mode="interrupt", decision=decision_str)],
        }

    # REST fallback — graph finishes normally; approval via separate API calls
    return {
        "operator_decision": "pending_rest",
        "node_trace": [_node_entry("request_planning_shell_approval", mode="rest_fallback")],
    }


def record_approval(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Record operator approval on the stored draft."""
    rt = _runtime(config)
    draft_id = state.get("draft_id", "")
    revision_id = str(state.get("mission_revision_id") or "").strip()
    note = state.get("approval_note", "")
    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    mission_errors: list[dict[str, Any]] = []
    approved: dict[str, Any] | None = None
    if mission_execution is not None and revision_id:
        try:
            approved = mission_execution.approve_revision(revision_id, note=note)
        except Exception as exc:
            mission_errors.append({
                "node": "record_approval",
                "code": "mission_execution_approval_error",
                "severity": "warning",
                "message": str(exc),
                "recoverable": True,
            })
    if approved is None:
        mission_errors.append({
            "node": "record_approval",
            "code": "revision_approval_missing",
            "severity": "warning",
            "message": "linked mission revision could not be approved",
            "recoverable": True,
        })
    mission_export: dict[str, Any] = {}
    export_error = ""
    if approved and _route_summary_for_approval(approved.get("mission") or approved.get("draft") or {}).get("waypoint_count"):
        try:
            result = MissionExportService().export(
                approved,
                home_position=_home_position_from_rover_state(state.get("rover_state") or {}),
            )
            if result.get("ok"):
                export_synced = None
                if mission_execution is not None and revision_id:
                    try:
                        export_synced = mission_execution.mark_revision_exported_by_revision_id(
                            revision_id,
                            export_result=result,
                        )
                    except Exception as exc:
                        mission_errors.append({
                            "node": "record_approval",
                            "code": "mission_execution_export_sync_error",
                            "severity": "warning",
                            "message": str(exc),
                            "recoverable": True,
                        })
                mission_export = (export_synced or {}).get("mission", {}).get("mission_export") or {
                    "file_path": result.get("file_path", ""),
                    "waypoint_count": result.get("waypoint_count", 0),
                    "vehicle_type": result.get("vehicle_type", 0),
                }
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


def record_rejection(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Record operator rejection on the stored draft."""
    rt = _runtime(config)
    draft_id = state.get("draft_id", "")
    revision_id = str(state.get("mission_revision_id") or "").strip()
    note = state.get("approval_note", "")
    mission_execution = getattr(rt.app_runtime, "mission_execution_service", None)
    mission_errors: list[dict[str, Any]] = []
    rejected = None
    if mission_execution is not None and revision_id:
        try:
            rejected = mission_execution.reject_revision(revision_id, note=note)
        except Exception as exc:
            mission_errors.append({
                "node": "record_rejection",
                "code": "mission_execution_rejection_error",
                "severity": "warning",
                "message": str(exc),
                "recoverable": True,
            })
    if rejected is None:
        mission_errors.append({
            "node": "record_rejection",
            "code": "revision_rejection_missing",
            "severity": "warning",
            "message": "linked mission revision could not be rejected",
            "recoverable": True,
        })
    return {
        "approval_status": "rejected",
        "errors": mission_errors,
        "node_trace": [_node_entry("record_rejection", ok=True, draft_id=draft_id)],
    }


# ── Phase 3 nodes ─────────────────────────────────────────────────────────────

async def prepare_clarification(state: PlanningShellGraphState, config: RunnableConfig) -> dict:
    """Interrupt to collect missing information from the operator, then refresh context.

    Rover pose and scene are re-fetched after the operator answers so the resumed
    planner_loop_node uses the freshest available state. Prefers questions and
    intent_summary from clarification_request set by planner_loop_node over
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
                questions=len(questions),
                answered=bool(answer),
                cancelled=cancelled,
            )],
        }

    # REST fallback: skip clarification, proceed with missing info as assumptions
    return {
        "clarification_request": clarification_payload,
        "clarification_response": {},
        "node_trace": [_node_entry("prepare_clarification", mode="rest_fallback", questions=len(questions))],
    }


def _route_after_clarification(state: PlanningShellGraphState) -> str:
    clarification_response = state.get("clarification_response") or {}
    if clarification_response.get("cancelled"):
        return "finalize_response"
    return "planner_loop_node"


def _route_after_validate_draft(state: PlanningShellGraphState) -> str:
    if state.get("clarification_request") and not state.get("clarification_response"):
        return "prepare_clarification"
    return "store_draft"


def _route_after_store_draft(state: PlanningShellGraphState) -> str:
    status = state.get("approval_status", "")
    if status == "awaiting_approval":
        return "request_planning_shell_approval"
    return "finalize_response"


def _route_after_approval(state: PlanningShellGraphState) -> str:
    decision = state.get("operator_decision", "")
    if decision == "reject":
        return "record_rejection"
    if decision == "approve":
        return "record_approval"
    # pending_rest or empty — go straight to finalize
    return "finalize_response"


# ── Graph construction ────────────────────────────────────────────────────────

def build_planning_shell_graph(checkpointer: Any = None):
    """Build and compile the planning-shell graph.

    Pass a LangGraph checkpointer to enable interrupt/resume approval.
    Without a checkpointer the graph falls back to REST-only approval.
    """
    graph: StateGraph = StateGraph(PlanningShellGraphState)

    graph.add_node("capture_request", capture_request)
    graph.add_node("retrieve_current_context", retrieve_current_context)
    graph.add_node("planner_loop_node", planner_loop_node)
    graph.add_node("prepare_clarification", prepare_clarification)
    graph.add_node("validate_draft", validate_draft)
    graph.add_node("store_draft", store_draft)
    graph.add_node("request_planning_shell_approval", request_planning_shell_approval)
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
    graph.add_edge("retrieve_current_context", "planner_loop_node")
    graph.add_conditional_edges(
        "planner_loop_node",
        _route_after_planner_loop,
        {
            "prepare_clarification": "prepare_clarification",
            "validate_draft": "validate_draft",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_conditional_edges(
        "prepare_clarification",
        _route_after_clarification,
        {
            "planner_loop_node": "planner_loop_node",
            "finalize_response": "finalize_response",
        },
    )
    graph.add_conditional_edges(
        "validate_draft",
        _route_after_validate_draft,
        {
            "prepare_clarification": "prepare_clarification",
            "store_draft": "store_draft",
        },
    )
    graph.add_conditional_edges(
        "store_draft",
        _route_after_store_draft,
        {"request_planning_shell_approval": "request_planning_shell_approval", "finalize_response": "finalize_response"},
    )
    graph.add_conditional_edges(
        "request_planning_shell_approval",
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

async def stream_planning_shell_graph(
    runtime: PlanningShellGraphRuntime,
    *,
    session_id: str,
    user_prompt: str,
    operator_timezone: str = "",
    session_mode: str = "planning_shell",
    source_message_id: str = "",
    source_controls: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Async generator that runs the graph and yields NDJSON event lines.

    Phase 2: when the graph hits interrupt() at request_planning_shell_approval,
    emits graph_interrupt with the thread_id and stops streaming. The client
    then calls the resume endpoint with the operator decision.
    """
    run_id = uuid.uuid4().hex[:12]
    thread_id = f"ai-session:{session_id}:run:{run_id}"
    graph = build_planning_shell_graph(checkpointer=runtime.checkpointer)

    initial_state: PlanningShellGraphState = {  # type: ignore[typeddict-item]
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
        "planner_loop_enabled": True,
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


async def resume_planning_shell_graph(
    runtime: PlanningShellGraphRuntime,
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
    graph = build_planning_shell_graph(checkpointer=runtime.checkpointer)
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
