from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

try:
    from gcs_server.ai.context_service import AIContextService
    from gcs_server.ai.spatial_query_service import SpatialQueryService
except ModuleNotFoundError:
    from ai.context_service import AIContextService
    from ai.spatial_query_service import SpatialQueryService


READ_ONLY = "read_only"
ANALYSIS = "analysis"
PLANNING = "planning"
COMMAND_STAGING = "command_staging"
EXECUTION = "execution"
DEFAULT_PERMISSIONS = frozenset({READ_ONLY, ANALYSIS, PLANNING})
DISABLED_PERMISSIONS = frozenset({COMMAND_STAGING, EXECUTION})


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    permission: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]


@dataclass(frozen=True)
class ToolInvocationContext:
    runtime: Any
    context_snapshot: dict[str, Any]
    timezone_name: str
    permissions: frozenset[str]


class ToolRegistry:
    def __init__(self, spatial: SpatialQueryService | None = None):
        self._spatial = spatial or SpatialQueryService()
        self._definitions = self._build_definitions()

    def definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def build_langchain_tools(
        self,
        runtime: Any,
        context_snapshot: dict[str, Any],
        timezone_name: str = "",
        permissions: set[str] | None = None,
    ) -> list[Any]:
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:
            raise RuntimeError("LangChain core tools are not installed. Install gcs_server/requirements-gcs.txt.") from exc

        invocation_context = self._invocation_context(runtime, context_snapshot, timezone_name, permissions)
        tools = []
        for definition in self.definitions():
            if not self._is_allowed(definition, invocation_context.permissions):
                continue
            tools.append(
                StructuredTool.from_function(
                    func=self._callable_for(definition, invocation_context),
                    name=definition.name,
                    description=definition.description,
                )
            )
        return tools

    def invoke(
        self,
        name: str,
        args: dict[str, Any],
        runtime: Any,
        context_snapshot: dict[str, Any],
        timezone_name: str = "",
        permissions: set[str] | None = None,
    ) -> dict[str, Any]:
        definition = self._definitions.get(str(name or "").strip())
        if definition is None:
            return {"ok": False, "error": f"tool '{name}' is not available"}
        invocation_context = self._invocation_context(runtime, context_snapshot, timezone_name, permissions)
        if definition.permission in DISABLED_PERMISSIONS:
            return {"ok": False, "error": f"tool permission '{definition.permission}' is not enabled"}
        if definition.permission not in invocation_context.permissions:
            return {"ok": False, "error": f"tool permission '{definition.permission}' is not allowed"}
        try:
            result = definition.handler(invocation_context, **(args if isinstance(args, dict) else {}))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return result if isinstance(result, dict) else {"ok": True, "result": result}

    def _build_definitions(self) -> dict[str, ToolDefinition]:
        definitions = [
            ToolDefinition(
                "get_current_rover_state",
                "Get the current rover telemetry snapshot captured for this request, including pose, heading, freshness, battery, speed, and camera state.",
                READ_ONLY,
                {},
                {},
                self._get_current_rover_state,
            ),
            ToolDefinition(
                "get_scene_summary",
                "Get the current terrain scene summary, including bounds, road count, object count, object kinds, spawn point, and site name.",
                READ_ONLY,
                {},
                {},
                self._get_scene_summary,
            ),
            ToolDefinition(
                "query_objects_in_front",
                "Find map objects in front of the rover within max_distance_m and fov_deg. Optional kinds filters the returned object kinds.",
                READ_ONLY,
                {},
                {},
                self._query_objects_in_front,
            ),
            ToolDefinition("query_objects_near", "Find map objects near the rover within radius_m.", READ_ONLY, {}, {}, self._query_objects_near),
            ToolDefinition("query_objects_by_kind", "Find all map objects whose kind exactly matches the given kind string.", READ_ONLY, {}, {}, self._query_objects_by_kind),
            ToolDefinition("query_objects_to_left", "Find map objects to the rover's left.", READ_ONLY, {}, {}, self._query_objects_to_left),
            ToolDefinition("query_objects_to_right", "Find map objects to the rover's right.", READ_ONLY, {}, {}, self._query_objects_to_right),
            ToolDefinition("query_nearest_objects", "Find nearest map objects to the rover.", READ_ONLY, {}, {}, self._query_nearest_objects),
            ToolDefinition("resolve_spatial_target", "Resolve a structured spatial target description against the current map and rover pose.", PLANNING, {}, {}, self._resolve_spatial_target),
            ToolDefinition("get_current_mission_state", "Get the current mission state. This is read-only.", READ_ONLY, {}, {}, self._get_current_mission_state),
            ToolDefinition("get_current_replay_summary", "Get the active replay session summary.", READ_ONLY, {}, {}, self._get_current_replay_summary),
            ToolDefinition("get_recent_telemetry", "Get recent telemetry samples from the active replay session.", READ_ONLY, {}, {}, self._get_recent_telemetry),
            ToolDefinition("resolve_replay_sessions", "Resolve a natural-language replay session selector.", ANALYSIS, {}, {}, self._resolve_replay_sessions),
            ToolDefinition("get_replay_session_summary", "Get a replay session summary by session_id.", READ_ONLY, {}, {}, self._get_replay_session_summary),
            ToolDefinition("get_replay_session_metrics", "Get computed replay analytics metrics for a session_id.", ANALYSIS, {}, {}, self._get_replay_session_metrics),
            ToolDefinition("get_replay_session_path", "Get downsampled replay path points for a session_id.", ANALYSIS, {}, {}, self._get_replay_session_path),
            ToolDefinition("search_replay_session_events", "Search runtime events within a replay session.", ANALYSIS, {}, {}, self._search_replay_session_events),
            ToolDefinition("compare_replay_sessions", "Compare multiple replay sessions by explicit session_ids.", ANALYSIS, {}, {}, self._compare_replay_sessions),
            ToolDefinition("aggregate_replay_sessions", "Aggregate replay analytics across resolved selector results or explicit session_ids.", ANALYSIS, {}, {}, self._aggregate_replay_sessions),
        ]
        return {definition.name: definition for definition in definitions}

    def _invocation_context(
        self,
        runtime: Any,
        context_snapshot: dict[str, Any],
        timezone_name: str,
        permissions: set[str] | None,
    ) -> ToolInvocationContext:
        allowed = DEFAULT_PERMISSIONS if permissions is None else frozenset(permissions)
        return ToolInvocationContext(
            runtime=runtime,
            context_snapshot=_snapshot_context(context_snapshot),
            timezone_name=str(timezone_name or "").strip(),
            permissions=frozenset(allowed),
        )

    def _callable_for(self, definition: ToolDefinition, invocation_context: ToolInvocationContext) -> Callable[..., Any]:
        def call(**kwargs: Any) -> Any:
            return definition.handler(invocation_context, **kwargs)

        call.__name__ = definition.name
        call.__doc__ = definition.description
        parameters = list(inspect.signature(definition.handler).parameters.values())
        call.__signature__ = inspect.Signature(parameters=parameters[1:])  # type: ignore[attr-defined]
        return call

    def _is_allowed(self, definition: ToolDefinition, permissions: frozenset[str]) -> bool:
        return definition.permission in permissions and definition.permission not in DISABLED_PERMISSIONS

    def _scene_payload(self, context: ToolInvocationContext) -> dict[str, Any] | None:
        return AIContextService(context.runtime).load_scene_payload()

    def _rover_snapshot(self, context: ToolInvocationContext) -> dict[str, Any]:
        rover = context.context_snapshot.get("rover")
        return rover if isinstance(rover, dict) else {}

    def _get_current_rover_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        return dict(self._rover_snapshot(context))

    def _get_scene_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        scene = context.context_snapshot.get("scene")
        return dict(scene) if isinstance(scene, dict) else AIContextService(context.runtime).get_scene_map_summary()

    def _query_objects_in_front(self, context: ToolInvocationContext, max_distance_m: float = 100.0, fov_deg: float = 20.0, kinds: list[str] | None = None) -> dict[str, Any]:
        return self._spatial.find_objects_in_front(self._scene_payload(context), self._rover_snapshot(context), max_distance_m, fov_deg, kinds)

    def _query_objects_near(self, context: ToolInvocationContext, radius_m: float = 50.0, kinds: list[str] | None = None) -> dict[str, Any]:
        return self._spatial.find_objects_near(self._scene_payload(context), self._rover_snapshot(context), radius_m, kinds)

    def _query_objects_by_kind(self, context: ToolInvocationContext, kind: str) -> dict[str, Any]:
        return self._spatial.find_objects_by_kind(self._scene_payload(context), kind)

    def _query_objects_to_left(self, context: ToolInvocationContext, max_distance_m: float = 100.0, angle_width_deg: float = 90.0, kinds: list[str] | None = None) -> dict[str, Any]:
        return self._spatial.find_objects_to_left(self._scene_payload(context), self._rover_snapshot(context), max_distance_m, angle_width_deg, kinds)

    def _query_objects_to_right(self, context: ToolInvocationContext, max_distance_m: float = 100.0, angle_width_deg: float = 90.0, kinds: list[str] | None = None) -> dict[str, Any]:
        return self._spatial.find_objects_to_right(self._scene_payload(context), self._rover_snapshot(context), max_distance_m, angle_width_deg, kinds)

    def _query_nearest_objects(self, context: ToolInvocationContext, limit: int = 5, max_distance_m: float | None = None, kinds: list[str] | None = None) -> dict[str, Any]:
        return self._spatial.find_nearest_objects(self._scene_payload(context), self._rover_snapshot(context), limit, max_distance_m, kinds)

    def _resolve_spatial_target(self, context: ToolInvocationContext, target: dict[str, Any]) -> dict[str, Any]:
        return self._spatial.resolve_target_description(self._scene_payload(context), self._rover_snapshot(context), target)

    def _get_current_mission_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        mission = context.context_snapshot.get("mission")
        return dict(mission) if isinstance(mission, dict) else AIContextService(context.runtime).get_current_mission_state()

    def _get_current_replay_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        return AIContextService(context.runtime).get_current_replay_summary()

    def _get_recent_telemetry(self, context: ToolInvocationContext, seconds: int = 120, limit: int = 10) -> list[dict[str, Any]]:
        return AIContextService(context.runtime).get_recent_telemetry(seconds=seconds, limit=limit)

    def _resolve_replay_sessions(self, context: ToolInvocationContext, selector: str, timezone_name: str = "") -> dict[str, Any]:
        return context.runtime.replay_analytics.resolve_sessions(
            selector,
            timezone_name=str(timezone_name or context.timezone_name).strip(),
            active_session_id=context.runtime.replay_store.current_session_id,
            limit=1000,
        )

    def _get_replay_session_summary(self, context: ToolInvocationContext, session_id: str) -> dict[str, Any] | None:
        return context.runtime.replay_analytics.get_session_summary(session_id)

    def _get_replay_session_metrics(self, context: ToolInvocationContext, session_id: str, refresh: bool = False) -> dict[str, Any] | None:
        return context.runtime.replay_analytics.get_session_metrics(session_id, refresh=refresh)

    def _get_replay_session_path(self, context: ToolInvocationContext, session_id: str, downsample: int = 10, limit: int = 500) -> dict[str, Any] | None:
        return context.runtime.replay_analytics.get_session_path(session_id, downsample=downsample, limit=limit)

    def _search_replay_session_events(self, context: ToolInvocationContext, session_id: str, event_type: str = "", text: str = "", limit: int = 50) -> dict[str, Any] | None:
        return context.runtime.replay_analytics.search_session_events(session_id, event_type=event_type, text=text, limit=limit)

    def _compare_replay_sessions(self, context: ToolInvocationContext, session_ids: list[str]) -> dict[str, Any]:
        return context.runtime.replay_analytics.compare_sessions(session_ids)

    def _aggregate_replay_sessions(self, context: ToolInvocationContext, selector: str = "", session_ids: list[str] | None = None, timezone_name: str = "") -> dict[str, Any]:
        return context.runtime.replay_analytics.aggregate_sessions(
            session_ids=session_ids or None,
            selector=selector or None,
            timezone_name=str(timezone_name or context.timezone_name).strip(),
            active_session_id=context.runtime.replay_store.current_session_id,
            limit=1000,
        )


def _snapshot_context(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return {}
    snapshot = meta.get("context_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}
