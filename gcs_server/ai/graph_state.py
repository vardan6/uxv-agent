from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class WorkbenchGraphState(TypedDict, total=False):
    """State for the workbench planning graph.

    ``total=False`` makes all keys optional — each node returns only the keys
    it produces. The three trace lists are annotated with the ``add`` reducer
    so LangGraph concatenates new entries rather than replacing the whole list.
    """

    # ── Request identity ──────────────────────────────────────────────────────
    session_id: str
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
    settings_summary: dict
    llm_summary: dict

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

    # ── Draft layer ───────────────────────────────────────────────────────────
    draft: dict
    draft_id: str
    validation: dict
    draft_usage_metadata: dict
    draft_response_metadata: dict
    approval_status: str           # awaiting_approval | approved | rejected | validation_failed | needs_clarification
    approval_note: str
    operator_decision: str         # Phase 2: approve | reject | pending_rest (set by request_workbench_approval)

    # ── Append-only traces — LangGraph concatenates via add reducer ───────────
    tool_trace: Annotated[list, add]
    node_trace: Annotated[list, add]
    errors: Annotated[list, add]
