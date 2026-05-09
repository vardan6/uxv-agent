from __future__ import annotations

from typing import Any

try:
    from gcs_server.ai.context_service import AIContextService
except ModuleNotFoundError:
    from ai.context_service import AIContextService


class ReadOnlyAgentToolset:
    def __init__(self, runtime: Any):
        self._runtime = runtime

    def build_langchain_tools(
        self,
        *,
        timezone_name: str = "",
        context_snapshot: dict[str, Any] | None = None,
    ) -> list[Any]:
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:
            raise RuntimeError("LangChain core tools are not installed. Install gcs_server/requirements-gcs.txt.") from exc

        clean_timezone = str(timezone_name or "").strip()
        analytics = self._runtime.replay_analytics
        active_session_id = self._runtime.replay_store.current_session_id
        context = AIContextService(self._runtime)
        snapshot = _snapshot_context(context_snapshot)
        rover_snapshot = snapshot.get("rover") if isinstance(snapshot.get("rover"), dict) else {}

        def get_current_rover_state() -> dict[str, Any]:
            return dict(rover_snapshot)

        def get_scene_summary() -> dict[str, Any]:
            scene = snapshot.get("scene")
            return dict(scene) if isinstance(scene, dict) else context.get_scene_map_summary()

        def query_objects_in_front(
            max_distance_m: float = 100.0,
            fov_deg: float = 20.0,
            kinds: list[str] | None = None,
        ) -> dict[str, Any]:
            result = context.find_objects_in_front(
                max_distance_m=max_distance_m,
                fov_deg=fov_deg,
                rover_state=rover_snapshot,
            )
            return _filter_object_result(result, kinds)

        def query_objects_near(
            radius_m: float = 50.0,
            kinds: list[str] | None = None,
        ) -> dict[str, Any]:
            result = context.find_objects_near_rover(radius_m=radius_m, rover_state=rover_snapshot)
            return _filter_object_result(result, kinds)

        def query_objects_by_kind(kind: str) -> dict[str, Any]:
            return context.find_objects_by_kind(kind)

        def get_current_mission_state() -> dict[str, Any]:
            mission = snapshot.get("mission")
            return dict(mission) if isinstance(mission, dict) else context.get_current_mission_state()

        def get_current_replay_summary() -> dict[str, Any]:
            return context.get_current_replay_summary()

        def get_recent_telemetry(seconds: int = 120, limit: int = 10) -> list[dict[str, Any]]:
            return context.get_recent_telemetry(seconds=seconds, limit=limit)

        def resolve_replay_sessions(selector: str, timezone_name: str = "") -> dict[str, Any]:
            return analytics.resolve_sessions(
                selector,
                timezone_name=str(timezone_name or clean_timezone).strip(),
                active_session_id=active_session_id,
                limit=1000,
            )

        def get_replay_session_summary(session_id: str) -> dict[str, Any] | None:
            return analytics.get_session_summary(session_id)

        def get_replay_session_metrics(session_id: str, refresh: bool = False) -> dict[str, Any] | None:
            return analytics.get_session_metrics(session_id, refresh=refresh)

        def get_replay_session_path(session_id: str, downsample: int = 10, limit: int = 500) -> dict[str, Any] | None:
            return analytics.get_session_path(session_id, downsample=downsample, limit=limit)

        def search_replay_session_events(
            session_id: str,
            event_type: str = "",
            text: str = "",
            limit: int = 50,
        ) -> dict[str, Any] | None:
            return analytics.search_session_events(
                session_id,
                event_type=event_type,
                text=text,
                limit=limit,
            )

        def compare_replay_sessions(session_ids: list[str]) -> dict[str, Any]:
            return analytics.compare_sessions(session_ids)

        def aggregate_replay_sessions(
            selector: str = "",
            session_ids: list[str] | None = None,
            timezone_name: str = "",
        ) -> dict[str, Any]:
            return analytics.aggregate_sessions(
                session_ids=session_ids or None,
                selector=selector or None,
                timezone_name=str(timezone_name or clean_timezone).strip(),
                active_session_id=active_session_id,
                limit=1000,
            )

        return [
            StructuredTool.from_function(
                func=get_current_rover_state,
                name="get_current_rover_state",
                description="Get the current rover telemetry snapshot captured for this request, including pose, heading, freshness, battery, speed, and camera state.",
            ),
            StructuredTool.from_function(
                func=get_scene_summary,
                name="get_scene_summary",
                description="Get the current terrain scene summary, including bounds, road count, object count, object kinds, spawn point, and site name.",
            ),
            StructuredTool.from_function(
                func=query_objects_in_front,
                name="query_objects_in_front",
                description="Find map objects in front of the rover within max_distance_m and fov_deg. Optional kinds filters the returned object kinds.",
            ),
            StructuredTool.from_function(
                func=query_objects_near,
                name="query_objects_near",
                description="Find map objects near the rover within radius_m. Optional kinds filters the returned object kinds.",
            ),
            StructuredTool.from_function(
                func=query_objects_by_kind,
                name="query_objects_by_kind",
                description="Find all map objects whose kind exactly matches the given kind string, such as tree, rock, or building.",
            ),
            StructuredTool.from_function(
                func=get_current_mission_state,
                name="get_current_mission_state",
                description="Get the current mission state. This is read-only and reports whether mission storage or an active mission exists.",
            ),
            StructuredTool.from_function(
                func=get_current_replay_summary,
                name="get_current_replay_summary",
                description="Get the active replay session summary for the current rover runtime.",
            ),
            StructuredTool.from_function(
                func=get_recent_telemetry,
                name="get_recent_telemetry",
                description="Get recent telemetry samples from the active replay session.",
            ),
            StructuredTool.from_function(
                func=resolve_replay_sessions,
                name="resolve_replay_sessions",
                description="Resolve a natural-language replay session selector like 'last session', 'yesterday sessions', or 'sessions from 2026-05-08'.",
            ),
            StructuredTool.from_function(
                func=get_replay_session_summary,
                name="get_replay_session_summary",
                description="Get a replay session summary by session_id.",
            ),
            StructuredTool.from_function(
                func=get_replay_session_metrics,
                name="get_replay_session_metrics",
                description="Get computed replay analytics metrics for a session_id.",
            ),
            StructuredTool.from_function(
                func=get_replay_session_path,
                name="get_replay_session_path",
                description="Get downsampled replay path points for a session_id.",
            ),
            StructuredTool.from_function(
                func=search_replay_session_events,
                name="search_replay_session_events",
                description="Search runtime events within a replay session by session_id and optional filters.",
            ),
            StructuredTool.from_function(
                func=compare_replay_sessions,
                name="compare_replay_sessions",
                description="Compare multiple replay sessions by explicit session_ids.",
            ),
            StructuredTool.from_function(
                func=aggregate_replay_sessions,
                name="aggregate_replay_sessions",
                description="Aggregate replay analytics across resolved selector results or explicit session_ids.",
            ),
        ]


def _snapshot_context(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return {}
    snapshot = meta.get("context_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _filter_object_result(result: dict[str, Any], kinds: list[str] | str | None) -> dict[str, Any]:
    if not kinds:
        return result
    raw_kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    allowed = {str(kind).strip().lower() for kind in raw_kinds if str(kind).strip()}
    if not allowed:
        return result
    out = dict(result)
    objects = out.get("objects")
    if isinstance(objects, list):
        out["objects"] = [
            obj for obj in objects
            if isinstance(obj, dict) and str(obj.get("kind") or "").strip().lower() in allowed
        ]
        out["kind_filter"] = sorted(allowed)
    return out
