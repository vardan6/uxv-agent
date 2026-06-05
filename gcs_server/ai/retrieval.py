from __future__ import annotations

from typing import Any

from gcs_server.ai.session_store import normalize_source_controls


def normalize_retrieval_request(
    value: Any,
    *,
    user_prompt: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    source_controls = normalize_source_controls(source.get("source_controls"))
    enabled = [key for key, is_enabled in source_controls.items() if is_enabled]
    disabled = [key for key, is_enabled in source_controls.items() if not is_enabled]
    lazy_branches = [
        str(branch)
        for branch in source.get("lazy_branches") or []
        if str(branch).strip()
    ]
    return {
        "session_id": str(session_id or source.get("session_id") or ""),
        "source_controls": source_controls,
        "enabled_sources": enabled,
        "disabled_sources": disabled,
        "lazy_branches": lazy_branches,
        "request_scope": str(source.get("request_scope") or "rover_task"),
    }


def build_retrieved_sources(
    *,
    retrieval_request: dict[str, Any] | None = None,
    session_id: str = "",
    replay_summary: dict[str, Any] | None = None,
    chat_history_summary: dict[str, Any] | None = None,
    settings_summary: dict[str, Any] | None = None,
    sensor_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    request = retrieval_request if isinstance(retrieval_request, dict) else {}
    source_controls = normalize_source_controls(request.get("source_controls"))
    requested = set(request.get("lazy_branches") or [])
    replay_summary = replay_summary or {}
    chat_history_summary = chat_history_summary or {}
    settings_summary = settings_summary or {}
    sensor_summary = sensor_summary or {}

    sources: list[dict[str, Any]] = []
    if source_controls.get("project_docs"):
        sources.append({
            "source": "project_docs",
            "kind": "knowledge",
            "available": False,
            "status": "planned",
            "requested": False,
            "note": "Project-document retrieval is a Phase 4 surface; RAG is not wired yet.",
        })
    if source_controls.get("mission_history"):
        sources.append({
            "source": "mission_history",
            "kind": "missions",
            "available": True,
            "status": "bounded",
            "requested": False,
            "note": "Mission draft records are available through the mission draft store.",
        })
    if source_controls.get("replay_reports"):
        replay_requested = "retrieve_replay_context" in requested
        sources.append({
            "source": "replay_reports",
            "kind": "replay",
            "available": bool(replay_summary),
            "status": "loaded_summary" if replay_requested and replay_summary else "bounded",
            "requested": replay_requested,
            "note": (
                "Replay summary was loaded lazily for this request."
                if replay_requested and replay_summary
                else "Replay summaries and analytics tools are available on demand."
            ),
        })
    if source_controls.get("ai_chat_history"):
        memory_requested = "retrieve_application_memory" in requested
        history_loaded = bool(chat_history_summary.get("available"))
        sources.append({
            "source": "ai_chat_history",
            "kind": "memory",
            "available": bool(session_id),
            "status": "loaded_summary" if memory_requested and history_loaded else "bounded",
            "requested": memory_requested,
            "note": (
                "Bounded recent session history was loaded lazily for this request."
                if memory_requested and history_loaded
                else "Bounded recent session history can be loaded lazily for memory-style prompts."
            ),
            "session_id": str(session_id or ""),
            "message_count": int(chat_history_summary.get("message_count") or 0) if history_loaded else 0,
        })
    if source_controls.get("settings_config"):
        settings_requested = "retrieve_settings_context" in requested
        sources.append({
            "source": "settings_config",
            "kind": "settings",
            "available": bool(settings_summary),
            "status": "loaded_summary" if settings_requested and settings_summary else "bounded",
            "requested": settings_requested,
            "note": (
                "Compact settings context was loaded lazily for this request."
                if settings_requested and settings_summary
                else "Compact settings context is available; section-scoped retrieval is still planned."
            ),
        })
    if source_controls.get("sensor_context"):
        sensor_requested = "retrieve_sensor_context" in requested
        sources.append({
            "source": "sensor_context",
            "kind": "perception",
            "available": bool(sensor_summary),
            "status": "metadata_only" if sensor_requested and sensor_summary else "placeholder",
            "requested": sensor_requested,
            "note": (
                "Only compact sensor metadata is available in this phase."
                if sensor_requested and sensor_summary
                else "Perception and sampled sensor retrieval are not implemented yet."
            ),
        })
    if source_controls.get("web_research"):
        sources.append({
            "source": "web_research",
            "kind": "external",
            "available": False,
            "status": "planned",
            "requested": False,
            "note": "Web research is not enabled in the current AI path.",
        })
    return sources


def build_loaded_data_refs(
    *,
    retrieval_request: dict[str, Any] | None = None,
    session_id: str = "",
    replay_summary: dict[str, Any] | None = None,
    chat_history_summary: dict[str, Any] | None = None,
    settings_summary: dict[str, Any] | None = None,
    sensor_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    request = retrieval_request if isinstance(retrieval_request, dict) else {}
    replay_summary = replay_summary or {}
    chat_history_summary = chat_history_summary or {}
    settings_summary = settings_summary or {}
    sensor_summary = sensor_summary or {}
    refs: list[dict[str, Any]] = []
    for branch in request.get("lazy_branches") or []:
        if branch == "retrieve_replay_context":
            refs.append({
                "branch": branch,
                "source": "replay_reports",
                "ref": "current_replay_summary",
                "status": "loaded" if replay_summary else "unavailable",
            })
        elif branch == "retrieve_application_memory":
            refs.append({
                "branch": branch,
                "source": "ai_chat_history",
                "ref": "recent_session_history",
                "status": "loaded" if chat_history_summary.get("available") else "unavailable",
                "session_id": str(session_id or ""),
                "message_count": int(chat_history_summary.get("message_count") or 0),
            })
        elif branch == "retrieve_settings_context":
            refs.append({
                "branch": branch,
                "source": "settings_config",
                "ref": "settings_summary",
                "status": "loaded" if settings_summary else "unavailable",
            })
        elif branch == "retrieve_sensor_context":
            refs.append({
                "branch": branch,
                "source": "sensor_context",
                "ref": "sensor_metadata",
                "status": "loaded" if sensor_summary else "unavailable",
            })
    return refs


def build_retrieval_citations(
    sources: list[dict[str, Any]] | None,
    loaded_data_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    refs_by_source = {
        str(ref.get("source") or ""): ref
        for ref in (loaded_data_refs or [])
        if isinstance(ref, dict) and str(ref.get("source") or "")
    }
    citations: list[dict[str, Any]] = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        entry = {
            "source": str(source.get("source") or ""),
            "status": str(source.get("status") or ""),
        }
        ref = refs_by_source.get(entry["source"])
        if ref:
            entry["ref"] = str(ref.get("ref") or "")
        citations.append(entry)
    return citations
