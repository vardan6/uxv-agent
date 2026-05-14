from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from gcs_server.ai.context_service import AIContextService
    from gcs_server.ai.data_access import build_data_access_manifest
    from gcs_server.ai.session_store import normalize_source_controls
    from gcs_server.ai.spatial_query_service import SpatialQueryService
except ModuleNotFoundError:
    from ai.context_service import AIContextService
    from ai.data_access import build_data_access_manifest
    from ai.session_store import normalize_source_controls
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
    tier: int
    required_scopes: frozenset[str]
    side_effects: frozenset[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolInvocationContext:
    runtime: Any
    context_snapshot: dict[str, Any]
    timezone_name: str
    permissions: frozenset[str]
    source_controls: dict[str, bool]
    session_id: str


_ALWAYS_ALLOWED_TOOL_NAMES = frozenset({
    "list_data_surfaces",
    "get_current_rover_state",
    "get_scene_summary",
    "query_objects_in_front",
    "query_objects_near",
    "query_objects_by_kind",
    "query_objects_to_left",
    "query_objects_to_right",
    "query_nearest_objects",
    "resolve_spatial_target",
    "get_current_mission_state",
})

_OPTIONAL_TOOL_NAMES_BY_SOURCE = {
    "replay_reports": frozenset({
        "get_current_replay_summary",
        "get_recent_telemetry",
        "list_replay_sessions",
        "resolve_replay_sessions",
        "get_replay_session_summary",
        "get_replay_session_metrics",
        "get_replay_session_path",
        "search_replay_session_events",
        "compare_replay_sessions",
        "aggregate_replay_sessions",
    }),
    "ai_chat_history": frozenset({
        "list_ai_sessions",
        "search_ai_messages",
        "get_ai_session_messages",
    }),
    "settings_config": frozenset({
        "get_settings_summary",
        "get_settings_section",
        "get_llm_provider_summary",
    }),
    "sensor_context": frozenset({
        "get_sensor_status",
    }),
}


def allowed_tool_names_for_source_controls(source_controls: dict[str, Any] | None) -> set[str]:
    clean = normalize_source_controls(source_controls)
    allowed = set(_ALWAYS_ALLOWED_TOOL_NAMES)
    for key, tool_names in _OPTIONAL_TOOL_NAMES_BY_SOURCE.items():
        if clean.get(key):
            allowed.update(tool_names)
    return allowed


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
                    description=_tool_runtime_description(definition),
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
        def tool(
            name: str,
            description: str,
            permission: str,
            handler: Callable[..., Any],
            *,
            required_scopes: frozenset[str] | None = None,
            side_effects: frozenset[str] | None = None,
        ) -> ToolDefinition:
            return ToolDefinition(
                name=name,
                description=description,
                permission=permission,
                tier=_permission_tier(permission),
                required_scopes=required_scopes or frozenset(),
                side_effects=side_effects or frozenset(),
                input_schema={},
                output_schema={},
                handler=handler,
            )

        definitions = [
            tool(
                "list_data_surfaces",
                "List every bounded data surface available to this session, show which source controls currently enable them, and identify the exact tools that can load each surface. Call this first when you need to discover where replay history, AI chat history, settings/config, or sensor metadata can be retrieved from.",
                READ_ONLY,
                self._list_data_surfaces,
            ),
            tool(
                "get_current_rover_state",
                "Get the current rover telemetry snapshot captured for this request, including pose, heading, freshness, battery, speed, and camera state. If live telemetry is stale or unavailable, inspect last_known_replay_state for the latest recorded rover values and source session.",
                READ_ONLY,
                self._get_current_rover_state,
            ),
            tool(
                "get_scene_summary",
                "Get the current terrain scene summary, including bounds, road count, object count, object kinds, spawn point, and site name. Use this before object queries when the operator asks what exists on the map or in the loaded scene.",
                READ_ONLY,
                self._get_scene_summary,
            ),
            tool(
                "query_objects_in_front",
                "Find map objects in front of the rover within max_distance_m and fov_deg. Use this for prompts about what is ahead, in front, straight ahead, on the route ahead, or visible in a forward cone. Optional kinds filters the returned object kinds. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg instead of requiring live telemetry.",
                READ_ONLY,
                self._query_objects_in_front,
            ),
            tool("query_objects_near", "Find map objects near the rover within radius_m. Uses rover position only (heading not required), with automatic fallback to last_known_replay_state when available. Use this for prompts about nearby, around the rover, close objects, or surroundings. If the operator provides hypothetical map coordinates, pass them as position or coordinates.", READ_ONLY, self._query_objects_near),
            tool("query_objects_by_kind", "Find all map objects whose kind exactly matches the given kind string. Use this when the operator names an object type such as tree, rock, road, building, or waypoint.", READ_ONLY, self._query_objects_by_kind),
            tool("query_objects_to_left", "Find map objects to the rover's left. Use this for prompts about left side, port side, left flank, or objects off the left of the rover. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg.", READ_ONLY, self._query_objects_to_left),
            tool("query_objects_to_right", "Find map objects to the rover's right. Use this for prompts about right side, starboard side, right flank, or objects off the right of the rover. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg.", READ_ONLY, self._query_objects_to_right),
            tool("query_nearest_objects", "Find nearest map objects to the rover. Uses rover position only (heading not required). Use this when the operator asks what is closest or nearest, optionally constrained by max_distance_m or kinds. If heading is unavailable, results still include distance and absolute bearing, while heading-relative fields may be omitted. If live rover telemetry is stale, this tool automatically falls back to last_known_replay_state when available. If the operator provides hypothetical map coordinates, pass them as position or coordinates.", READ_ONLY, self._query_nearest_objects),
            tool("resolve_spatial_target", "Resolve a spatial target against the current map and rover pose. Accepts either a target object (kind/side/max_distance_m/min_distance_m/relative_bearing_deg and optional position/coordinates/heading_deg) or a plain-language string such as 'nearest tree on the left'. If live telemetry is stale, it can use last_known_replay_state when available.", PLANNING, self._resolve_spatial_target),
            tool("get_current_mission_state", "Get the current mission state. This is read-only.", READ_ONLY, self._get_current_mission_state),
            tool("get_current_replay_summary", "Get the active replay session summary.", READ_ONLY, self._get_current_replay_summary),
            tool("get_recent_telemetry", "Get telemetry samples. By default returns recent samples from the active replay session using seconds+limit. If session_id is provided, returns samples for that explicit session_id so the agent can fetch telemetry from older sessions without extra clarification.", READ_ONLY, self._get_recent_telemetry),
            tool("list_replay_sessions", "List replay sessions with started_at, ended_at, telemetry_count, control_count, and runtime_event_count. Use this to enumerate sessions, fetch latest/first sessions, or gather candidates before comparing or ranking by metrics.", ANALYSIS, self._list_replay_sessions),
            tool("resolve_replay_sessions", "Resolve a natural-language replay session selector such as 'all sessions', 'latest 5 sessions', 'first session', or a date-based selector into explicit session_ids.", ANALYSIS, self._resolve_replay_sessions),
            tool("get_replay_session_summary", "Get a replay session summary by session_id.", READ_ONLY, self._get_replay_session_summary),
            tool("get_replay_session_metrics", "Get computed replay analytics metrics for a session_id, including duration_s, path_length_m, net_displacement_m, and max_distance_from_start_m.", ANALYSIS, self._get_replay_session_metrics),
            tool("get_replay_session_path", "Get downsampled replay path points for a session_id.", ANALYSIS, self._get_replay_session_path),
            tool("search_replay_session_events", "Search runtime events within a replay session.", ANALYSIS, self._search_replay_session_events),
            tool("compare_replay_sessions", "Compare multiple replay sessions by explicit session_ids. Returns per-session summaries and metrics so you can rank, sort, and answer longest/furthest questions. Travel distance means path_length_m. Furthest from home/start means max_distance_from_start_m.", ANALYSIS, self._compare_replay_sessions),
            tool("aggregate_replay_sessions", "Aggregate replay analytics across resolved selector results or explicit session_ids. Use this for totals, averages, built-in longest/latest/furthest summaries, and ranked top-N session lists. Travel distance means path_length_m. Furthest from home/start means max_distance_from_start_m.", ANALYSIS, self._aggregate_replay_sessions),
            tool(
                "list_ai_sessions",
                "List saved AI chat sessions with bounded metadata, message counts, archival state, and latest-message previews. Call this before `get_ai_session_messages` when you need a specific session_id, or before `search_ai_messages` when the operator refers to earlier chats without naming the session.",
                ANALYSIS,
                self._list_ai_sessions,
            ),
            tool(
                "search_ai_messages",
                "Search saved AI messages by text across the current session or across saved sessions and return bounded match snippets with session/message references. Use this when the operator asks about earlier answers, prior discussions, or something that was said before and you need to locate the right session or message window.",
                ANALYSIS,
                self._search_ai_messages,
            ),
            tool(
                "get_ai_session_messages",
                "Load a bounded window of saved AI messages from one session. If session_id is omitted, use the current AI session. Call this after `list_ai_sessions` or `search_ai_messages` when you need the surrounding conversation, not just a preview or search snippet.",
                READ_ONLY,
                self._get_ai_session_messages,
            ),
            tool(
                "get_settings_summary",
                "Get the safe compact settings summary available to AI flows, including which top-level sections exist, key non-secret configuration summaries, and the settings path. Call this first before requesting one section with `get_settings_section` or checking provider/routing state with `get_llm_provider_summary`.",
                READ_ONLY,
                self._get_settings_summary,
            ),
            tool(
                "get_settings_section",
                "Get one safe settings section by name. Supported sections are `mqtt`, `key_bindings`, `video`, `gcs`, `simulation`, `map`, `ai_settings`, and `settings_path`. Call `get_settings_summary` first if you need section discovery or a compact overview. This tool never exposes secrets.",
                READ_ONLY,
                self._get_settings_section,
            ),
            tool(
                "get_llm_provider_summary",
                "Get safe LLM provider and model-routing metadata, including enabled providers, active chat-provider resolution, and routing rules without exposing secrets. Use this when the operator asks which provider/model path is active or how AI routing is configured.",
                READ_ONLY,
                self._get_llm_provider_summary,
            ),
            tool(
                "get_sensor_status",
                "Get metadata-only sensor and video status, including telemetry freshness, camera freshness, configured video delivery, and current perception limitations. Use this for questions about whether the agent can currently see live camera data or rely on sensor freshness. This tool does not expose raw frames, detections, or vision inference output.",
                READ_ONLY,
                self._get_sensor_status,
            ),
        ]
        with_contracts = [_with_tool_contract(definition) for definition in definitions]
        return {definition.name: definition for definition in with_contracts}

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
            source_controls=_snapshot_source_controls(context_snapshot),
            session_id=_snapshot_session_id(context_snapshot),
        )

    def _callable_for(self, definition: ToolDefinition, invocation_context: ToolInvocationContext) -> Callable[..., Any]:
        def call(**kwargs: Any) -> Any:
            return definition.handler(invocation_context, **kwargs)

        call.__name__ = definition.name
        call.__doc__ = _tool_runtime_description(definition)
        parameters = list(inspect.signature(definition.handler).parameters.values())
        exposed_parameters = parameters[1:]
        call.__signature__ = inspect.Signature(parameters=exposed_parameters)  # type: ignore[attr-defined]
        annotations: dict[str, Any] = {}
        for parameter in exposed_parameters:
            if parameter.annotation is not inspect.Signature.empty:
                annotations[parameter.name] = parameter.annotation
        return_annotation = inspect.signature(definition.handler).return_annotation
        if return_annotation is not inspect.Signature.empty:
            annotations["return"] = return_annotation
        call.__annotations__ = annotations
        return call

    def _is_allowed(self, definition: ToolDefinition, permissions: frozenset[str]) -> bool:
        return definition.permission in permissions and definition.permission not in DISABLED_PERMISSIONS

    def _scene_payload(self, context: ToolInvocationContext) -> dict[str, Any] | None:
        return AIContextService(context.runtime).load_scene_payload()

    def _rover_snapshot(self, context: ToolInvocationContext) -> dict[str, Any]:
        rover = context.context_snapshot.get("rover")
        if not isinstance(rover, dict):
            return {}
        if _has_pose_and_heading(rover):
            return rover
        fallback = rover.get("last_known_replay_state")
        if isinstance(fallback, dict) and _has_position(fallback):
            merged = dict(rover)
            merged["position"] = fallback.get("position") or {}
            if fallback.get("heading_deg") is not None:
                merged["heading_deg"] = fallback.get("heading_deg")
            merged["gps"] = fallback.get("gps") or merged.get("gps") or {}
            merged["position_frame"] = fallback.get("position_frame") or merged.get("position_frame") or "unknown"
            merged["telemetry_fresh"] = False
            merged["telemetry_source"] = "last_known_replay_state"
            merged["telemetry_source_session_id"] = fallback.get("session_id")
            return merged
        return rover

    def _get_current_rover_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        return dict(self._rover_snapshot(context))

    def _list_data_surfaces(self, context: ToolInvocationContext) -> dict[str, Any]:
        allowed_tool_names = allowed_tool_names_for_source_controls(context.source_controls)
        manifest = build_data_access_manifest(self.definitions(), allowed_tool_names=allowed_tool_names)
        surface_to_control = {
            "replay_sessions": "replay_reports",
            "ai_chat_history": "ai_chat_history",
            "settings": "settings_config",
            "video_perception": "sensor_context",
        }
        surfaces: list[dict[str, Any]] = []
        for raw_surface in manifest.get("data_surfaces") or []:
            if not isinstance(raw_surface, dict):
                continue
            entry = dict(raw_surface)
            source_key = surface_to_control.get(str(entry.get("name") or ""))
            if source_key:
                entry["source_control"] = source_key
                entry["source_control_enabled"] = bool(context.source_controls.get(source_key))
            else:
                entry["source_control"] = None
                entry["source_control_enabled"] = True
            surfaces.append(entry)
        planned_sources = [
            {
                "source": key,
                "enabled": bool(context.source_controls.get(key)),
                "status": "planned",
            }
            for key in ("project_docs", "mission_history", "web_research")
        ]
        return {
            "available": True,
            "session_id": context.session_id,
            "source_controls": dict(context.source_controls),
            "data_surfaces": surfaces,
            "planned_sources": planned_sources,
        }

    def _get_scene_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        scene = context.context_snapshot.get("scene")
        return dict(scene) if isinstance(scene, dict) else AIContextService(context.runtime).get_scene_map_summary()

    def _query_objects_in_front(
        self,
        context: ToolInvocationContext,
        max_distance_m: float = 100.0,
        fov_deg: float = 20.0,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
    ) -> dict[str, Any]:
        rover_state = self._rover_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_in_front(self._scene_payload(context), rover_state, max_distance_m, fov_deg, kinds)

    def _query_objects_near(
        self,
        context: ToolInvocationContext,
        radius_m: float = 50.0,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict[str, Any]:
        rover_state = self._rover_snapshot_with_override(context, position=position if position is not None else coordinates)
        return self._spatial.find_objects_near(self._scene_payload(context), rover_state, radius_m, kinds)

    def _query_objects_by_kind(self, context: ToolInvocationContext, kind: str) -> dict[str, Any]:
        return self._spatial.find_objects_by_kind(self._scene_payload(context), kind)

    def _query_objects_to_left(
        self,
        context: ToolInvocationContext,
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
    ) -> dict[str, Any]:
        rover_state = self._rover_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_to_left(self._scene_payload(context), rover_state, max_distance_m, angle_width_deg, kinds)

    def _query_objects_to_right(
        self,
        context: ToolInvocationContext,
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
    ) -> dict[str, Any]:
        rover_state = self._rover_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_to_right(self._scene_payload(context), rover_state, max_distance_m, angle_width_deg, kinds)

    def _query_nearest_objects(
        self,
        context: ToolInvocationContext,
        limit: int = 5,
        max_distance_m: float | None = None,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict[str, Any]:
        rover_state = self._rover_snapshot_with_override(context, position=position if position is not None else coordinates)
        return self._spatial.find_nearest_objects(self._scene_payload(context), rover_state, limit, max_distance_m, kinds)

    def _resolve_spatial_target(self, context: ToolInvocationContext, target: dict[str, Any] | str) -> dict[str, Any]:
        resolved_target = _normalize_spatial_target(target)
        rover_state = self._rover_snapshot_with_override(
            context,
            position=resolved_target.get("position") if isinstance(resolved_target, dict) and resolved_target.get("position") is not None else resolved_target.get("coordinates") if isinstance(resolved_target, dict) else None,
            heading_deg=resolved_target.get("heading_deg") if isinstance(resolved_target, dict) else None,
        )
        return self._spatial.resolve_target_description(self._scene_payload(context), rover_state, resolved_target)

    def _rover_snapshot_with_override(
        self,
        context: ToolInvocationContext,
        *,
        position: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
    ) -> dict[str, Any]:
        rover = dict(self._rover_snapshot(context))
        explicit_position = _normalize_position_override(position)
        if explicit_position is not None:
            rover["position"] = explicit_position
            rover["position_frame"] = "explicit_query_position"
            rover["telemetry_fresh"] = False
            rover["telemetry_source"] = "explicit_query_position"
        if heading_deg is not None:
            try:
                rover["heading_deg"] = float(heading_deg) % 360.0
                rover["telemetry_fresh"] = False
                rover["telemetry_source"] = "explicit_query_pose"
            except (TypeError, ValueError):
                pass
        return rover

    def _get_current_mission_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        mission = context.context_snapshot.get("mission")
        return dict(mission) if isinstance(mission, dict) else AIContextService(context.runtime).get_current_mission_state()

    def _get_current_replay_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        return AIContextService(context.runtime).get_current_replay_summary()

    def _get_recent_telemetry(
        self,
        context: ToolInvocationContext,
        seconds: int = 120,
        limit: int = 10,
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        clean_session_id = str(session_id or "").strip()
        if clean_session_id:
            return context.runtime.replay_store.list_telemetry_samples(clean_session_id, limit=max(1, int(limit)))
        return AIContextService(context.runtime).get_recent_telemetry(seconds=seconds, limit=limit)

    def _list_replay_sessions(
        self,
        context: ToolInvocationContext,
        limit: int = 100,
        order: str = "desc",
    ) -> dict[str, Any]:
        sessions = context.runtime.replay_analytics.list_sessions(limit=max(1, int(limit)), order=order)
        return {
            "count": len(sessions),
            "limit": max(1, int(limit)),
            "order": "asc" if str(order).strip().lower() == "asc" else "desc",
            "sessions": sessions,
        }

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

    def _aggregate_replay_sessions(self, context: ToolInvocationContext, selector: str = "", session_ids: list[str] | None = None, timezone_name: str = "", top_n: int = 5) -> dict[str, Any]:
        return context.runtime.replay_analytics.aggregate_sessions(
            session_ids=session_ids or None,
            selector=selector or None,
            timezone_name=str(timezone_name or context.timezone_name).strip(),
            active_session_id=context.runtime.replay_store.current_session_id,
            limit=1000,
            top_n=max(1, int(top_n)),
        )

    def _list_ai_sessions(
        self,
        context: ToolInvocationContext,
        limit: int = 20,
        include_archived: bool = False,
        archived_only: bool = False,
        query: str = "",
    ) -> dict[str, Any]:
        store = getattr(context.runtime, "ai_store", None)
        if store is None:
            return {"available": False, "sessions": [], "error": "AI session store is not available"}
        sessions = store.list_sessions(
            limit=max(1, min(50, int(limit))),
            include_archived=include_archived,
            archived_only=archived_only,
        )
        clean_query = " ".join(str(query or "").split()).strip().lower()
        if clean_query:
            sessions = [
                session
                for session in sessions
                if clean_query in str(session.get("title") or "").lower()
                or clean_query in str(session.get("last_message") or "").lower()
            ]
        compact_sessions = []
        for session in sessions:
            compact_sessions.append({
                "id": str(session.get("id") or ""),
                "title": str(session.get("title") or ""),
                "mode": str(session.get("mode") or ""),
                "provider_id": str(session.get("provider_id") or ""),
                "updated_at": session.get("updated_at"),
                "created_at": session.get("created_at"),
                "archived_at": session.get("archived_at"),
                "message_count": int(session.get("message_count") or 0),
                "last_message_preview": _compact_text(session.get("last_message"), limit=160),
                "is_current_session": str(session.get("id") or "") == context.session_id,
            })
        return {
            "available": True,
            "query": clean_query,
            "count": len(compact_sessions),
            "sessions": compact_sessions,
            "current_session_id": context.session_id,
        }

    def _search_ai_messages(
        self,
        context: ToolInvocationContext,
        query: str,
        limit: int = 20,
        session_id: str = "",
        include_archived: bool = False,
        role: str = "",
    ) -> dict[str, Any]:
        clean_query = " ".join(str(query or "").split()).strip()
        if not clean_query:
            return {"available": False, "matches": [], "error": "query is required"}
        store = getattr(context.runtime, "ai_store", None)
        if store is None:
            return {"available": False, "matches": [], "error": "AI session store is not available"}
        target_session_id = str(session_id or "").strip()
        if target_session_id == "current":
            target_session_id = context.session_id
        matches = store.search_messages(
            clean_query,
            limit=max(1, min(50, int(limit))),
            session_id=target_session_id,
            include_archived=include_archived,
            role=role,
        )
        compact_matches = []
        for match in matches:
            compact_matches.append({
                "message_id": str(match.get("id") or ""),
                "session_id": str(match.get("session_id") or ""),
                "session_title": str(match.get("session_title") or ""),
                "session_mode": str(match.get("session_mode") or ""),
                "role": str(match.get("role") or ""),
                "created_at": match.get("created_at"),
                "snippet": _compact_text(match.get("content"), limit=220),
                "is_current_session": str(match.get("session_id") or "") == context.session_id,
            })
        return {
            "available": True,
            "query": clean_query,
            "session_id": target_session_id,
            "count": len(compact_matches),
            "matches": compact_matches,
            "current_session_id": context.session_id,
        }

    def _get_ai_session_messages(
        self,
        context: ToolInvocationContext,
        session_id: str = "",
        limit: int = 12,
        before_message_id: str = "",
        role: str = "",
    ) -> dict[str, Any]:
        store = getattr(context.runtime, "ai_store", None)
        if store is None:
            return {"available": False, "messages": [], "error": "AI session store is not available"}
        target_session_id = str(session_id or "").strip()
        if target_session_id == "current" or not target_session_id:
            target_session_id = context.session_id
        if not target_session_id:
            return {"available": False, "messages": [], "error": "session_id is required"}
        bounded_limit = max(1, min(20, int(limit)))
        messages = store.list_session_messages(
            target_session_id,
            limit=bounded_limit + 1,
            before_message_id=before_message_id,
            role=role,
        )
        truncated = len(messages) > bounded_limit
        messages = messages[-bounded_limit:] if truncated else messages
        compact_messages = []
        for message in messages:
            compact_messages.append({
                "id": str(message.get("id") or ""),
                "role": str(message.get("role") or ""),
                "created_at": message.get("created_at"),
                "content": _compact_text(message.get("content"), limit=280),
            })
        return {
            "available": True,
            "session_id": target_session_id,
            "count": len(compact_messages),
            "messages": compact_messages,
            "before_message_id": str(before_message_id or ""),
            "current_session_id": context.session_id,
            "truncated": truncated,
        }

    def _get_settings_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        summary = AIContextService(context.runtime).get_settings_context()
        return {
            "available": bool(summary),
            "settings_path": summary.get("settings_path"),
            "section_names": [key for key in summary.keys() if key != "settings_path"],
            "summary": summary,
        }

    def _get_settings_section(self, context: ToolInvocationContext, section: str) -> dict[str, Any]:
        clean_section = str(section or "").strip()
        summary = AIContextService(context.runtime).get_settings_context()
        if clean_section == "settings_path":
            return {
                "available": True,
                "section": clean_section,
                "value": summary.get("settings_path"),
            }
        if clean_section not in summary or clean_section == "settings_path":
            return {
                "available": False,
                "section": clean_section,
                "available_sections": [key for key in summary.keys() if key != "settings_path"],
                "error": "unsupported settings section",
            }
        value = summary.get(clean_section)
        return {
            "available": isinstance(value, dict),
            "section": clean_section,
            "value": value if isinstance(value, dict) else {},
        }

    def _get_llm_provider_summary(self, context: ToolInvocationContext) -> dict[str, Any]:
        summary = AIContextService(context.runtime).get_llm_context(session_id=context.session_id)
        return {
            "available": bool(summary),
            **summary,
        }

    def _get_sensor_status(self, context: ToolInvocationContext) -> dict[str, Any]:
        rover = self._rover_snapshot(context)
        runtime_summary = context.context_snapshot.get("runtime")
        runtime_details = dict(runtime_summary) if isinstance(runtime_summary, dict) else {}
        video = runtime_details.get("video")
        return {
            "available": True,
            "telemetry_fresh": bool(rover.get("telemetry_fresh")),
            "camera_fresh": bool(rover.get("camera_fresh")),
            "last_telemetry_ts": rover.get("last_telemetry_ts"),
            "last_camera_ts": rover.get("last_camera_ts"),
            "camera": dict(rover.get("camera") or {}),
            "video": dict(video) if isinstance(video, dict) else {},
            "perception_available": False,
            "perception_note": "This phase exposes only metadata and freshness; raw frames, detections, and perception events are not implemented.",
        }


def _snapshot_context(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return {}
    snapshot = meta.get("context_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _snapshot_source_controls(context_snapshot: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(context_snapshot, dict):
        return normalize_source_controls(None)
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return normalize_source_controls(None)
    return normalize_source_controls(meta.get("source_controls"))


def _snapshot_session_id(context_snapshot: dict[str, Any] | None) -> str:
    snapshot = _snapshot_context(context_snapshot)
    llm = snapshot.get("llm")
    if not isinstance(llm, dict):
        return ""
    session = llm.get("session")
    if not isinstance(session, dict):
        return ""
    return str(session.get("id") or "").strip()


def _has_pose_and_heading(rover: dict[str, Any]) -> bool:
    if not _has_position(rover):
        return False
    try:
        float(rover.get("heading_deg"))
        return True
    except (TypeError, ValueError):
        return False


def _has_position(rover: dict[str, Any]) -> bool:
    if not isinstance(rover, dict):
        return False
    position = rover.get("position")
    if not isinstance(position, dict):
        return False
    try:
        float(position.get("x"))
        float(position.get("y"))
        return True
    except (TypeError, ValueError):
        return False


def _normalize_spatial_target(target: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(target, dict):
        normalized = dict(target)
        description = str(normalized.get("description") or "").strip()
        if description:
            return normalized
        kind = str(normalized.get("kind") or "").strip()
        normalized["description"] = f"nearest {kind}" if kind else "nearest object"
        return normalized

    text = str(target or "").strip()
    if not text:
        return {"description": "nearest object"}
    lowered = text.lower()
    parsed: dict[str, Any] = {"description": text}
    if "left" in lowered:
        parsed["side"] = "left"
    elif "right" in lowered:
        parsed["side"] = "right"
    elif "front" in lowered or "ahead" in lowered:
        parsed["side"] = "front"
    elif "behind" in lowered or "back" in lowered:
        parsed["side"] = "behind"
    kind_match = re.search(r"\b(tree|stone|boulder|building|charger|solar_panel|solar frame|solar_frame|pad|guard_rail|collision_proxy|rock|rocks)\b", lowered)
    if kind_match:
        kind = kind_match.group(1).replace(" ", "_")
        parsed["kind"] = "stone" if kind in {"rock", "rocks"} else kind
    return parsed


def _normalize_position_override(value: dict[str, Any] | list[Any] | str | None) -> dict[str, float] | None:
    if isinstance(value, dict):
        try:
            x = float(value.get("x"))
            y = float(value.get("y"))
            z = float(value.get("z") or 0.0)
        except (TypeError, ValueError):
            return None
        return {"x": x, "y": y, "z": z}
    if isinstance(value, list) and len(value) >= 2:
        try:
            x = float(value[0])
            y = float(value[1])
            z = float(value[2]) if len(value) >= 3 and value[2] is not None else 0.0
        except (TypeError, ValueError):
            return None
        return {"x": x, "y": y, "z": z}
    if isinstance(value, str):
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value)
        if len(numbers) < 2:
            return None
        try:
            x = float(numbers[0])
            y = float(numbers[1])
            z = float(numbers[2]) if len(numbers) >= 3 else 0.0
        except ValueError:
            return None
        return {"x": x, "y": y, "z": z}
    return None


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _with_tool_contract(definition: ToolDefinition) -> ToolDefinition:
    contract = TOOL_CONTRACTS.get(definition.name, {})
    if not contract:
        return definition
    return ToolDefinition(
        name=definition.name,
        description=definition.description,
        permission=definition.permission,
        tier=definition.tier,
        required_scopes=definition.required_scopes,
        side_effects=definition.side_effects,
        input_schema=dict(contract.get("inputs") or {}),
        output_schema=dict(contract.get("returns") or {}),
        handler=definition.handler,
        contract=contract,
    )


def _tool_runtime_description(definition: ToolDefinition) -> str:
    lines = [definition.description.strip()]
    contract = definition.contract if isinstance(definition.contract, dict) else {}
    inputs = contract.get("inputs")
    required = contract.get("required_inputs")
    upstream = contract.get("upstream_from_tools")
    returns = contract.get("returns")
    downstream = contract.get("next_tools")
    if isinstance(inputs, dict) and inputs:
        lines.append(f"Inputs: {_format_contract_mapping(inputs)}.")
    if isinstance(required, list) and required:
        lines.append(f"Required inputs: {', '.join(str(item) for item in required)}.")
    if isinstance(upstream, list) and upstream:
        lines.append(f"Upstream sources: {', '.join(str(item) for item in upstream)}.")
    if isinstance(returns, dict) and returns:
        lines.append(f"Returns: {_format_contract_mapping(returns)}.")
    if isinstance(downstream, list) and downstream:
        lines.append(f"Next tools: {', '.join(str(item) for item in downstream)}.")
    return "\n".join(line for line in lines if line).strip()


def _format_contract_mapping(values: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items())


def _permission_tier(permission: str) -> int:
    return {
        READ_ONLY: 0,
        ANALYSIS: 1,
        PLANNING: 2,
        COMMAND_STAGING: 3,
        EXECUTION: 4,
    }.get(str(permission or "").strip(), 0)


TOOL_CONTRACTS: dict[str, dict[str, Any]] = {
    "list_data_surfaces": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"data_surfaces": "surface[]", "source_controls": "object", "planned_sources": "object[]"},
        "next_tools": ["get_settings_summary", "list_ai_sessions", "get_sensor_status"],
    },
    "get_current_rover_state": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {
            "position": "object{x,y,z} | {}",
            "heading_deg": "number | null",
            "telemetry_fresh": "boolean",
            "last_known_replay_state": "object | null",
        },
        "next_tools": ["query_nearest_objects", "query_objects_near", "query_objects_in_front", "resolve_spatial_target"],
    },
    "get_scene_summary": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"object_kinds": "object{kind->count}", "spawn": "object{x,y,z}", "object_count": "number"},
        "next_tools": ["query_objects_by_kind", "resolve_spatial_target"],
    },
    "query_objects_in_front": {
        "inputs": {"max_distance_m": "number", "fov_deg": "number", "kinds": "string[]", "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "heading_deg": "number"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state (pose/heading)", "operator-provided coordinates/heading", "get_scene_summary (kind discovery)"],
        "returns": {"available": "boolean", "objects": "object[]", "reason": "string?"},
        "next_tools": ["resolve_spatial_target"],
    },
    "query_objects_near": {
        "inputs": {"radius_m": "number", "kinds": "string[]", "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state (position; heading optional; replay fallback supported)", "operator-provided coordinates", "get_scene_summary"],
        "returns": {"available": "boolean", "objects": "object[]", "reason": "string?"},
        "next_tools": ["resolve_spatial_target"],
    },
    "query_objects_by_kind": {
        "inputs": {"kind": "string"},
        "required_inputs": ["kind"],
        "upstream_from_tools": ["get_scene_summary.object_kinds"],
        "returns": {"available": "boolean", "objects": "object[]"},
        "next_tools": ["resolve_spatial_target"],
    },
    "query_objects_to_left": {
        "inputs": {"max_distance_m": "number", "angle_width_deg": "number", "kinds": "string[]", "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "heading_deg": "number"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state (pose/heading)", "operator-provided coordinates/heading"],
        "returns": {"available": "boolean", "objects": "object[]", "reason": "string?"},
        "next_tools": ["resolve_spatial_target"],
    },
    "query_objects_to_right": {
        "inputs": {"max_distance_m": "number", "angle_width_deg": "number", "kinds": "string[]", "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "heading_deg": "number"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state (pose/heading)", "operator-provided coordinates/heading"],
        "returns": {"available": "boolean", "objects": "object[]", "reason": "string?"},
        "next_tools": ["resolve_spatial_target"],
    },
    "query_nearest_objects": {
        "inputs": {"limit": "integer", "max_distance_m": "number|null", "kinds": "string[]", "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'", "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state (position; heading optional; replay fallback supported)", "operator-provided coordinates", "get_scene_summary"],
        "returns": {"available": "boolean", "objects": "object[]", "reason": "string?"},
        "next_tools": ["resolve_spatial_target"],
    },
    "resolve_spatial_target": {
        "inputs": {"target": "string | object{description,kind,side,min_distance_m,max_distance_m,relative_bearing_deg,position,coordinates,heading_deg}"},
        "required_inputs": ["target"],
        "upstream_from_tools": ["get_current_rover_state", "operator-provided coordinates/heading", "get_scene_summary", "query_objects_* results"],
        "returns": {"available": "boolean", "candidates": "object[]", "selected": "object|null", "needs_clarification": "boolean"},
        "next_tools": [],
    },
    "get_current_mission_state": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"active": "boolean", "status": "string", "summary": "string"},
        "next_tools": [],
    },
    "get_current_replay_summary": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"session_id": "string|null", "telemetry_count": "number", "runtime_event_count": "number"},
        "next_tools": ["get_recent_telemetry", "get_replay_session_metrics", "get_replay_session_path", "search_replay_session_events"],
    },
    "get_recent_telemetry": {
        "inputs": {"seconds": "integer", "limit": "integer", "session_id": "string (optional)"},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_replay_summary.session_id", "resolve_replay_sessions.resolved_session_ids[*]"],
        "returns": {"result": "telemetry_sample[]"},
        "next_tools": ["query_nearest_objects", "query_objects_near"],
    },
    "list_replay_sessions": {
        "inputs": {"limit": "integer", "order": "string(desc|asc)"},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"sessions": "session_summary[]", "count": "number"},
        "next_tools": ["resolve_replay_sessions", "get_replay_session_summary", "get_replay_session_metrics", "compare_replay_sessions", "aggregate_replay_sessions"],
    },
    "resolve_replay_sessions": {
        "inputs": {"selector": "string", "timezone_name": "string"},
        "required_inputs": ["selector"],
        "upstream_from_tools": ["operator natural-language selector"],
        "returns": {"resolved_session_ids": "string[]", "matched_count": "number", "preview_sessions": "session_summary[]"},
        "next_tools": ["get_replay_session_summary", "get_replay_session_metrics", "get_replay_session_path", "search_replay_session_events", "compare_replay_sessions", "aggregate_replay_sessions", "get_recent_telemetry"],
    },
    "get_replay_session_summary": {
        "inputs": {"session_id": "string"},
        "required_inputs": ["session_id"],
        "upstream_from_tools": ["resolve_replay_sessions.resolved_session_ids[*]", "list_replay_sessions.sessions[*].session_id", "get_current_replay_summary.session_id"],
        "returns": {"session_id": "string", "telemetry_count": "number", "control_count": "number", "runtime_event_count": "number"},
        "next_tools": ["get_replay_session_metrics", "get_replay_session_path", "search_replay_session_events", "get_recent_telemetry"],
    },
    "get_replay_session_metrics": {
        "inputs": {"session_id": "string", "refresh": "boolean"},
        "required_inputs": ["session_id"],
        "upstream_from_tools": ["resolve_replay_sessions.resolved_session_ids[*]", "list_replay_sessions.sessions[*].session_id", "get_replay_session_summary.session_id"],
        "returns": {"path_length_m": "number", "duration_s": "number", "max_distance_from_start_m": "number", "net_displacement_m": "number"},
        "next_tools": ["compare_replay_sessions", "aggregate_replay_sessions"],
    },
    "get_replay_session_path": {
        "inputs": {"session_id": "string", "downsample": "integer", "limit": "integer"},
        "required_inputs": ["session_id"],
        "upstream_from_tools": ["resolve_replay_sessions.resolved_session_ids[*]", "list_replay_sessions.sessions[*].session_id"],
        "returns": {"session_id": "string", "point_count": "number", "points": "path_point[]"},
        "next_tools": ["get_recent_telemetry"],
    },
    "search_replay_session_events": {
        "inputs": {"session_id": "string", "event_type": "string", "text": "string", "limit": "integer"},
        "required_inputs": ["session_id"],
        "upstream_from_tools": ["resolve_replay_sessions.resolved_session_ids[*]", "list_replay_sessions.sessions[*].session_id"],
        "returns": {"events": "event[]", "count": "number"},
        "next_tools": ["compare_replay_sessions", "aggregate_replay_sessions"],
    },
    "compare_replay_sessions": {
        "inputs": {"session_ids": "string[]"},
        "required_inputs": ["session_ids"],
        "upstream_from_tools": ["resolve_replay_sessions.resolved_session_ids", "list_replay_sessions.sessions[*].session_id"],
        "returns": {"sessions": "comparison_row[]", "best_by_metric": "object"},
        "next_tools": ["aggregate_replay_sessions"],
    },
    "aggregate_replay_sessions": {
        "inputs": {"selector": "string", "session_ids": "string[]", "timezone_name": "string", "top_n": "integer"},
        "required_inputs": [],
        "upstream_from_tools": ["resolve_replay_sessions", "list_replay_sessions"],
        "returns": {"totals": "object", "averages": "object", "top_sessions": "session_metric[]"},
        "next_tools": [],
    },
    "list_ai_sessions": {
        "inputs": {"limit": "integer", "include_archived": "boolean", "archived_only": "boolean", "query": "string"},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"sessions": "ai_session_summary[]", "count": "number", "current_session_id": "string"},
        "next_tools": ["search_ai_messages", "get_ai_session_messages"],
    },
    "search_ai_messages": {
        "inputs": {"query": "string", "limit": "integer", "session_id": "string", "include_archived": "boolean", "role": "string"},
        "required_inputs": ["query"],
        "upstream_from_tools": ["list_ai_sessions"],
        "returns": {"matches": "ai_message_match[]", "count": "number"},
        "next_tools": ["get_ai_session_messages"],
    },
    "get_ai_session_messages": {
        "inputs": {"session_id": "string", "limit": "integer", "before_message_id": "string", "role": "string"},
        "required_inputs": [],
        "upstream_from_tools": ["list_ai_sessions", "search_ai_messages"],
        "returns": {"messages": "ai_message[]", "count": "number", "truncated": "boolean"},
        "next_tools": ["search_ai_messages"],
    },
    "get_settings_summary": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": [],
        "returns": {"settings_path": "string", "section_names": "string[]", "summary": "object"},
        "next_tools": ["get_settings_section", "get_llm_provider_summary"],
    },
    "get_settings_section": {
        "inputs": {"section": "string"},
        "required_inputs": ["section"],
        "upstream_from_tools": ["get_settings_summary"],
        "returns": {"section": "string", "value": "object|string", "available": "boolean"},
        "next_tools": ["get_llm_provider_summary"],
    },
    "get_llm_provider_summary": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["get_settings_summary"],
        "returns": {"providers": "object[]", "model_routing": "object", "active_chat_provider": "object|null"},
        "next_tools": [],
    },
    "get_sensor_status": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["get_current_rover_state"],
        "returns": {"telemetry_fresh": "boolean", "camera_fresh": "boolean", "video": "object", "perception_available": "boolean"},
        "next_tools": [],
    },
}
