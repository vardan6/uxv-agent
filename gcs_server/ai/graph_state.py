from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class PlanningShellGraphState(TypedDict, total=False):
    """State for the durable planning-shell graph.

    ``total=False`` makes all keys optional — each node returns only the keys
    it produces. The three trace lists are annotated with the ``add`` reducer
    so LangGraph concatenates new entries rather than replacing the whole list.
    """

    # ── Request identity ──────────────────────────────────────────────────────
    session_id: str
    user_id: str                # per-user Mission store scope (ADR 0021 §2/§5)
    thread_id: str              # Phase 2: stable LangGraph thread ID for checkpoint/resume
    source_message_id: str
    user_prompt: str
    operator_timezone: str
    session_mode: str
    classified_scope: str          # "rover_task" in Phase 1

    # ── Compact context — populated once by retrieve_current_context ──────────
    context_metadata: dict         # compact snapshot meta; no full context blob
    context_snapshot_ref: str      # future: key into external audit store
    data_access_manifest: dict     # tool/surface capability map
    rover_state: dict
    scene_summary: dict
    runtime_summary: dict
    replay_summary: dict
    chat_history_summary: dict
    settings_summary: dict
    llm_summary: dict
    active_mission_context: dict   # active revision provenance summary for conflict detection

    # ── Intent layer ──────────────────────────────────────────────────────────
    intent: dict
    intent_provider: dict          # {provider_id, model_id, latency_ms}
    intent_errors: list
    intent_usage_metadata: dict
    intent_response_metadata: dict

    # ── Retrieval layer — Phase 4 ─────────────────────────────────────────────
    classified_scope: str
    retrieval_request: dict
    retrieved_sources: list
    retrieval_citations: list
    loaded_data_refs: list

    # ── Target resolution ─────────────────────────────────────────────────────
    target_resolution: dict
    target_candidates: list
    clarification_request: dict    # Phase 3
    clarification_response: dict   # Phase 3
    operator_edit_payload: dict    # Phase 2
    provenance_conflict: dict      # planning-shell conflict gate for ai+edited waypoints

    # ── Draft layer ───────────────────────────────────────────────────────────
    draft: dict
    draft_id: str
    parent_operation_id: str     # non-empty when planner links proposal to an existing operation
    mission_edit_mode: str       # ADR 0021 §3: create | clone_and_edit | edit_in_place
    source_mission_id: str       # ADR 0021 §3: flat Mission the edit derives from
    mission_id: str              # flat Mission (ADR 0021 §2) this proposal bridges to
    mission_operation_id: str
    mission_revision_id: str
    validation: dict
    draft_usage_metadata: dict
    draft_response_metadata: dict
    approval_status: str           # proposed | rejected | validation_failed | needs_clarification
    approval_note: str
    operator_decision: str         # Phase 2: approve | reject | pending_rest

    # ── Planner loop — Phase 5 ────────────────────────────────────────────────
    planner_agent_stop_reason: str  # stop reason from AgentLoopRuntime run
    planner_agent_iterations: int   # iteration count from AgentLoopRuntime run
    planner_agent_trace_id: str     # durable AgentLoopRuntime JSONL trace ID
    planner_loop_fallback: bool     # True when planner loop could not produce a draft

    # ── Append-only traces — LangGraph concatenates via add reducer ───────────
    tool_trace: Annotated[list, add]
    node_trace: Annotated[list, add]
    errors: Annotated[list, add]
