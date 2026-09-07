from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gcs_server.runtime import AppRuntime
from scene.scene_map import get_scene_map_payload

router = APIRouter()


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _request_timezone_name(request: Request, payload: dict[str, Any] | None = None) -> str:
    if isinstance(payload, dict):
        clean = str(payload.get("timezone", "")).strip()
        if clean:
            return clean
    return str(request.headers.get("x-operator-timezone", "")).strip()


@router.get("/api/replay/sessions")
async def replay_sessions(
    request: Request,
    limit: int = 100,
    started_at_from: float | None = None,
    started_at_to: float | None = None,
    order: str = "desc",
) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "sessions": runtime.replay_analytics.list_sessions(
            limit=limit,
            started_at_from=started_at_from,
            started_at_to=started_at_to,
            order=order,
        ),
        "current_session_id": runtime.replay_store.current_session_id,
    }


@router.post("/api/replay/sessions/rollover")
async def rollover_replay_session(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason = str(payload.get("reason", "manual_rollover"))
    session_id = runtime.replay_store.rollover_session(reason=reason)
    return {"ok": True, "current_session_id": session_id}


@router.get("/api/replay/sessions/{session_id}")
async def replay_session_detail(session_id: str, request: Request, limit: int = 2000) -> dict[str, Any]:
    runtime = _runtime(request)
    session = runtime.replay_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session": session,
        "timeline": runtime.replay_store.get_session_timeline(session_id, limit=limit),
    }


@router.get("/api/replay/sessions/{session_id}/summary")
async def replay_session_summary(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    summary = runtime.replay_analytics.get_session_summary(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session": summary}


@router.get("/api/replay/sessions/{session_id}/metrics")
async def replay_session_metrics(session_id: str, request: Request, refresh: bool = False) -> dict[str, Any]:
    runtime = _runtime(request)
    metrics = runtime.replay_analytics.get_session_metrics(session_id, refresh=refresh)
    if metrics is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"metrics": metrics}


@router.get("/api/replay/sessions/{session_id}/path")
async def replay_session_path(
    session_id: str,
    request: Request,
    downsample: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    runtime = _runtime(request)
    path = runtime.replay_analytics.get_session_path(session_id, downsample=downsample, limit=limit)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return path


@router.get("/api/replay/sessions/{session_id}/events/search")
async def replay_session_events_search(
    session_id: str,
    request: Request,
    event_type: str = "",
    text: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    runtime = _runtime(request)
    result = runtime.replay_analytics.search_session_events(
        session_id,
        event_type=event_type,
        text=text,
        limit=limit,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="session not found")
    return result


@router.post("/api/replay/sessions/compare")
async def replay_sessions_compare(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    session_ids = payload.get("session_ids", [])
    if not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    clean_ids = [str(item).strip() for item in session_ids if str(item).strip()]
    return runtime.replay_analytics.compare_sessions(clean_ids)


@router.post("/api/replay/sessions/resolve")
async def replay_sessions_resolve(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    selector = payload.get("selector", payload.get("query", ""))
    timezone_name = _request_timezone_name(request, payload)
    return runtime.replay_analytics.resolve_sessions(
        selector,
        timezone_name=timezone_name,
        active_session_id=runtime.replay_store.current_session_id,
    )


@router.post("/api/replay/sessions/aggregate")
async def replay_sessions_aggregate(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    selector = payload.get("selector", payload.get("query"))
    session_ids = payload.get("session_ids", [])
    if session_ids is not None and not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    timezone_name = _request_timezone_name(request, payload)
    return runtime.replay_analytics.aggregate_sessions(
        session_ids=[str(item).strip() for item in session_ids if str(item).strip()] if isinstance(session_ids, list) else None,
        selector=selector,
        timezone_name=timezone_name,
        active_session_id=runtime.replay_store.current_session_id,
    )


@router.delete("/api/replay/sessions/{session_id}")
async def delete_replay_session(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        deleted = runtime.replay_store.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "ok": True,
        "deleted_session_id": session_id,
        "current_session_id": runtime.replay_store.current_session_id,
    }


@router.get("/api/replay/scene-map")
async def replay_scene_map(backend: str = "3d-env", grid_size: int = 128) -> dict[str, Any]:
    try:
        return get_scene_map_payload(backend=backend, grid_size=grid_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
