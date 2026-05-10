"""Workbench planning graph (Phase 1 + Phase 2 + Phase 3).

Phase 1: Linear deterministic graph, REST-only approval.
Phase 2: Adds durable checkpointer and interrupt() at request_workbench_approval.
Phase 3: Clarification loop via interrupt() at prepare_clarification; refreshes
         rover pose/scene on resume before draft generation.

Node order:
    capture_request
    retrieve_current_context
    parse_intent
    prepare_clarification       (Phase 3: only when intent has missing_information and no prior clarification)
    resolve_target              (only when intent has a spatial target)
    generate_mission_draft
    validate_draft
    store_draft
    request_workbench_approval  (Phase 2: interrupt(); Phase 1 fallback: REST-only)
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
    from gcs_server.ai.graph_runtime import WorkbenchGraphRuntime
    from gcs_server.ai.graph_state import WorkbenchGraphState
    from gcs_server.ai.mission_draft_service import validate_draft_payload
    from gcs_server.ai.provider_registry import resolve_intent_provider, resolve_provider
except ModuleNotFoundError:
    from ai.graph_runtime import WorkbenchGraphRuntime
    from ai.graph_state import WorkbenchGraphState
    from ai.mission_draft_service import validate_draft_payload
    from ai.provider_registry import resolve_intent_provider, resolve_provider


# ── Constants ─────────────────────────────────────────────────────────────────

_PLANNING_INTENT_TYPES = frozenset({"navigate_to_object", "inspect_area", "search_area"})

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


def _json_line(data: dict) -> str:
    return json.dumps(data, separators=(",", ":")) + "\n"


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


def _build_data_access_manifest(runtime: WorkbenchGraphRuntime) -> dict:
    tool_names = [d.name for d in runtime.tool_registry.definitions()]
    return {
        "data_surfaces": [
            {
                "name": "current_rover_state",
                "description": "Latest telemetry snapshot and freshness metadata.",
                "access": "tool",
                "tool_names": ["get_current_rover_state"],
                "initial_context": "summary",
            },
            {
                "name": "terrain_scene",
                "description": "Terrain/map objects and deterministic spatial geometry.",
                "access": "tool",
                "tool_names": [n for n in tool_names if any(k in n for k in ("object", "spatial", "scene"))],
                "initial_context": "scene_summary_only",
            },
            {
                "name": "replay_sessions",
                "description": "Recorded sessions, telemetry, events, paths, and metrics.",
                "access": "tool",
                "tool_names": [n for n in tool_names if "replay" in n],
                "initial_context": "active_session_summary_only",
            },
            {
                "name": "ai_chat_history",
                "description": "Saved AI chat sessions and messages.",
                "access": "planned_tool",
                "tool_names": ["list_ai_sessions", "search_ai_messages", "get_ai_session_messages"],
                "initial_context": "current_session_metadata_only",
            },
            {
                "name": "video_perception",
                "description": "Future sampled video frames and object detections.",
                "access": "future_tool",
                "tool_names": ["sample_video_frame", "detect_video_objects"],
                "initial_context": "video_metadata_only",
            },
        ]
    }


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

    return {
        "source_message_id": source_message_id,
        "classified_scope": "rover_task",
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
        )
    except Exception as exc:
        return {
            "context_metadata": {"error": str(exc), "context_text": ""},
            "data_access_manifest": _build_data_access_manifest(rt),
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

    return {
        "context_metadata": compact_meta,
        "data_access_manifest": _build_data_access_manifest(rt),
        "rover_state": full_ctx.get("rover") or {},
        "scene_summary": full_ctx.get("scene") or {},
        "runtime_summary": full_ctx.get("runtime") or {},
        "replay_summary": (full_ctx.get("details") or {}).get("current_replay") or {},
        "settings_summary": full_ctx.get("settings") or {},
        "llm_summary": full_ctx.get("llm") or {},
        "node_trace": [_node_entry("retrieve_current_context", ok=True)],
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

    return {
        "draft_id": stored.get("id", ""),
        "approval_status": stored.get("status", ""),
        "node_trace": [_node_entry(
            "store_draft", ok=True,
            draft_id=stored.get("id", ""),
            status=stored.get("status", ""),
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
        candidates = state.get("target_candidates") or []
        if candidates:
            parts.append(f"Resolved {len(candidates)} spatial target candidate(s).")
    else:
        parts.append("Could not generate a mission draft for this request.")
        fatal = [e for e in errors if e.get("severity") in ("error", "fatal")]
        if fatal:
            parts.append(f"Reason: {fatal[-1].get('message', 'unknown error')}.")

    content = " ".join(parts)
    meta = {
        "run_mode": "workbench",
        "intent": intent,
        "draft_id": draft_id,
        "approval_status": approval_status,
        "validation_status": validation.get("status", ""),
        "tool_trace": state.get("tool_trace") or [],
        "node_count": len(state.get("node_trace") or []),
    }
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
        "goal": draft.get("goal", ""),
        "risks": draft.get("risks") or [],
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
        rt.draft_service.approve_draft(draft_id, note=note)
    except Exception as exc:
        return {
            "approval_status": "approved",
            "errors": [{
                "node": "record_approval", "code": "service_error",
                "severity": "warning", "message": str(exc), "recoverable": True,
            }],
            "node_trace": [_node_entry("record_approval", ok=False, reason=str(exc))],
        }
    return {
        "approval_status": "approved",
        "node_trace": [_node_entry("record_approval", ok=True, draft_id=draft_id)],
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
    return {
        "approval_status": "rejected",
        "node_trace": [_node_entry("record_rejection", ok=True, draft_id=draft_id)],
    }


# ── Phase 3 nodes ─────────────────────────────────────────────────────────────

async def prepare_clarification(state: WorkbenchGraphState, config: RunnableConfig) -> dict:
    """Interrupt to collect missing information from the operator, then refresh context.

    Phase 3 constraint: rover pose and scene are re-fetched after the operator answers
    so the subsequent draft uses the freshest available state.
    """
    rt = _runtime(config)
    intent = state.get("intent") or {}
    missing = intent.get("missing_information") or []

    clarification_payload = {
        "type": "clarification_request",
        "questions": missing,
        "intent_summary": intent.get("summary", ""),
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
    graph.add_edge("retrieve_current_context", "parse_intent")
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
