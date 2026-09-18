from __future__ import annotations

import inspect
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import json

from backend.ai.context_service import AIContextService
from backend.ai.intent_service import IntentService as _IntentService
from backend.ai.mission_draft_service import validate_draft_payload
from backend.ai.mission_execution_session import build_mission_executor
from backend.ai.mission_control import mission_control_for
from backend.ai.mission_export_service import MissionExportService
from backend.ai import mission_patterns
from backend.ai.mission_tree import MissionTreeError, flatten_navigable_segments, parse_tree
from backend.ai.provider_registry import resolve_intent_provider as _resolve_intent_provider
from backend.ai.provider_registry import resolve_provider as _resolve_provider
from backend.ai.retrieval import search_project_docs as _search_project_docs
from backend.ai.road_graph_service import RoadGraphService
from backend.ai.session_store import normalize_source_controls
from backend.ai.spatial_query_service import SpatialQueryService
from backend.ai.vehicle_profile import VehicleProfile, get_active_profile


READ_ONLY = "read_only"
ANALYSIS = "analysis"
PLANNING = "planning"
COMMAND_STAGING = "command_staging"
EXECUTION = "execution"
DEFAULT_PERMISSIONS = frozenset({READ_ONLY, ANALYSIS, PLANNING})
# COMMAND_STAGING stays hard-disabled (no staged-command surface yet). EXECUTION
# is now reachable (ADR 0021 §1 / ADR 0023 Phase 3): the actual gate is the
# per-mode tool binding in agent_loop — Strict binds no arm/execute, Confirm
# binds arm_execution, Autonomous binds execute_mission; cancel/abort always.
DISABLED_PERMISSIONS = frozenset({COMMAND_STAGING})

_PLANNER_DRAFT_SYSTEM_PROMPT = (
    "You are a mission planning assistant for a remote vehicle GCS.\n"
    "Generate a structured mission draft from the provided vehicle intent and resolved target.\n\n"
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

_ALLOWED_DRAFT_STEP_TYPES = frozenset({"navigate", "inspect", "search", "report"})
_EXECUTION_FIELDS = frozenset({
    "mqtt_topic", "mqtt_payload", "command", "control_command",
    "motor_values", "velocity", "speed_command",
})


def normalize_mission_draft_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Normalize and repair a draft payload. Returns (normalized_draft, repairs).

    Enforces safety invariants regardless of model output. Call before storing
    any draft produced by a planner or LLM to guarantee execution safety.
    """
    repairs: list[str] = []
    out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}

    out["execution_allowed"] = False
    out["required_operator_approval"] = True

    for key in ("steps", "constraints", "assumptions", "risks"):
        if not isinstance(out.get(key), list):
            if key in out:
                repairs.append(f"reset invalid '{key}' field to []")
            out[key] = []

    clean_steps: list[dict[str, Any]] = []
    for i, step in enumerate(out["steps"]):
        if not isinstance(step, dict):
            repairs.append(f"step[{i}] was not a dict; dropped")
            continue
        step_type = str(step.get("type") or "").strip().lower()
        if step_type not in _ALLOWED_DRAFT_STEP_TYPES:
            repairs.append(f"step[{i}] type '{step_type}' converted to 'report'")
            step = {**step, "type": "report", "description": f"[converted from '{step_type}'] {step.get('description', '')}"}
        clean_steps.append(step)
    out["steps"] = clean_steps

    # ADR 0023: a draft may author a behavior-tree structure (sequence/fallback/
    # loop/recovery/condition/ask_operator around nav_leaf runs) instead of, or
    # alongside, a flat waypoint list. Validate it through the canonical parser so
    # only a structurally-sound tree reaches storage; an invalid tree is dropped
    # (the flat waypoint path still applies) rather than failing the whole draft.
    if "tree" in out:
        raw_tree = out["tree"]
        if isinstance(raw_tree, dict) and raw_tree.get("tree") is not None:
            raw_tree = raw_tree["tree"]
        try:
            out["tree"] = parse_tree(raw_tree).to_dict()
        except MissionTreeError as exc:
            del out["tree"]
            repairs.append(f"dropped invalid 'tree' field: {exc}")

    for field in _EXECUTION_FIELDS:
        if field in out:
            del out[field]
            repairs.append(f"stripped execution field '{field}'")

    return out, repairs


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    permission: str
    tier: int
    side_effects: frozenset[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    contract: dict[str, Any] = field(default_factory=dict)
    is_terminal: bool = False
    surface: str = ""


@dataclass(frozen=True)
class ToolMeta:
    """Single per-tool declaration (O9): the source every other tool-facing
    surface (LangChain schema, contract text, data-access manifest, cache
    list, always-allowed/source-gated sets) derives from, instead of each
    surface re-listing tool names independently."""

    name: str
    description: str
    permission: str
    handler: Callable[..., Any]
    side_effects: frozenset[str] = frozenset()
    is_terminal: bool = False
    inputs: dict[str, Any] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()
    returns: dict[str, Any] = field(default_factory=dict)
    upstream_from_tools: tuple[str, ...] = ()
    next_tools: tuple[str, ...] = ()
    surface: str = ""
    always_allowed: bool = False
    source_control: str | None = None
    cacheable: bool = False
    cache_ttl_s: int | None = None

    @property
    def contract(self) -> dict[str, Any]:
        if not (self.inputs or self.required_inputs or self.returns or self.upstream_from_tools or self.next_tools):
            return {}
        return {
            "inputs": dict(self.inputs),
            "required_inputs": list(self.required_inputs),
            "upstream_from_tools": list(self.upstream_from_tools),
            "returns": dict(self.returns),
            "next_tools": list(self.next_tools),
        }


@dataclass(frozen=True)
class ToolInvocationContext:
    runtime: Any
    context_snapshot: dict[str, Any]
    timezone_name: str
    permissions: frozenset[str]
    source_controls: dict[str, bool]
    session_id: str
    user_id: str
    run_mode: str = ""


def allowed_tool_names_for_source_controls(source_controls: dict[str, Any] | None) -> set[str]:
    clean = normalize_source_controls(source_controls)
    allowed = {meta.name for meta in _TOOL_META.values() if meta.always_allowed}
    for meta in _TOOL_META.values():
        if meta.source_control and clean.get(meta.source_control):
            allowed.add(meta.name)
    return allowed


def cacheable_tool_names() -> frozenset[str]:
    return frozenset(meta.name for meta in _TOOL_META.values() if meta.cacheable)


def tool_cache_ttl_s(name: str, default: int = 300) -> int:
    meta = _TOOL_META.get(name)
    if meta is None or meta.cache_ttl_s is None:
        return default
    return meta.cache_ttl_s


_DATA_SURFACES: tuple[tuple[str, str, str, str], ...] = (
    # (surface_name, description, access, initial_context)
    ("system_capabilities", "Discovery of available bounded data surfaces and source-control gating for this session.", "tool", "manifest_only"),
    ("current_vehicle_state", "Latest telemetry snapshot and freshness metadata.", "tool", "summary"),
    ("terrain_scene", "Terrain/map objects and deterministic spatial geometry.", "tool", "scene_summary_only"),
    ("mission_state", "Current mission placeholder and mission-related state available to read-only AI flows.", "tool", "summary"),
    ("replay_sessions", "Recorded sessions, telemetry, events, paths, and metrics.", "tool", "manifest_only"),
    ("ai_chat_history", "Saved AI chat sessions and messages.", "tool", "manifest_only"),
    ("settings", "Safe GCS settings sections plus LLM provider and routing metadata.", "tool", "manifest_only"),
    ("video_perception", "Metadata-only sensor/video status for the current runtime; raw frames and detections remain unavailable in this phase.", "tool", "video_metadata_only"),
    ("route_planning", "Road-graph route planning. Compute drivable routes over the terrain road network for a mission draft.", "tool", "manifest_only"),
)


def build_data_access_manifest(tool_definitions: list[Any], *, allowed_tool_names: set[str] | None = None) -> dict[str, Any]:
    allowed = set(allowed_tool_names or [])
    restrict = allowed_tool_names is not None
    by_surface: dict[str, list[Any]] = {}
    for definition in tool_definitions:
        surface = str(getattr(definition, "surface", "") or "")
        if surface:
            by_surface.setdefault(surface, []).append(definition)

    def _tool_entry(definition: Any) -> dict[str, Any]:
        enabled = not restrict or definition.name in allowed
        return {
            "name": definition.name,
            "permission": definition.permission,
            "tier": int(getattr(definition, "tier", 0)),
            "side_effects": sorted(str(item) for item in getattr(definition, "side_effects", ()) or ()),
            "enabled": enabled,
        }

    def _surface(name: str, description: str, access: str, initial_context: str) -> dict[str, Any]:
        entries = [_tool_entry(definition) for definition in by_surface.get(name, [])]
        enabled_entries = [entry for entry in entries if entry.get("enabled")]
        return {
            "name": name,
            "description": description,
            "access": access,
            "initial_context": initial_context,
            "tool_names": [entry["name"] for entry in entries],
            "enabled_tool_names": [entry["name"] for entry in enabled_entries],
            "tools": entries,
            "enabled": bool(enabled_entries) if entries else access != "tool",
        }

    return {"data_surfaces": [_surface(*surface) for surface in _DATA_SURFACES]}


class ToolRegistry:
    def __init__(
        self,
        spatial: SpatialQueryService | None = None,
        profile_resolver: Callable[[], VehicleProfile] | None = None,
    ):
        self._spatial = spatial or SpatialQueryService()
        self._road_graph = RoadGraphService()
        self._profile_resolver = profile_resolver or get_active_profile
        self._exporter = MissionExportService(profile_resolver=self._profile_resolver)
        self._definitions = self._build_definitions()

    def definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def build_langchain_tools(
        self,
        runtime: Any,
        context_snapshot: dict[str, Any],
        timezone_name: str = "",
        permissions: set[str] | None = None,
        run_mode: str = "",
    ) -> list[Any]:
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:
            raise RuntimeError("LangChain core tools are not installed. Install backend/requirements-gcs.txt.") from exc

        invocation_context = self._invocation_context(runtime, context_snapshot, timezone_name, permissions, run_mode)
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

    def _build_definitions(self) -> dict[str, ToolDefinition]:
        definitions = {}
        for name, meta in _TOOL_META.items():
            definitions[name] = ToolDefinition(
                name=meta.name,
                description=meta.description,
                permission=meta.permission,
                tier=_permission_tier(meta.permission),
                side_effects=meta.side_effects,
                input_schema=dict(meta.inputs),
                output_schema=dict(meta.returns),
                handler=meta.handler.__get__(self, ToolRegistry),
                contract=meta.contract,
                is_terminal=meta.is_terminal,
                surface=meta.surface,
            )
        return definitions

    def _invocation_context(
        self,
        runtime: Any,
        context_snapshot: dict[str, Any],
        timezone_name: str,
        permissions: set[str] | None,
        run_mode: str = "",
    ) -> ToolInvocationContext:
        allowed = DEFAULT_PERMISSIONS if permissions is None else frozenset(permissions)
        return ToolInvocationContext(
            runtime=runtime,
            context_snapshot=_snapshot_context(context_snapshot),
            timezone_name=str(timezone_name or "").strip(),
            permissions=frozenset(allowed),
            source_controls=_snapshot_source_controls(context_snapshot),
            session_id=_snapshot_session_id(context_snapshot),
            user_id=_snapshot_user_id(context_snapshot),
            run_mode=str(run_mode or "").strip().lower(),
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

    def _vehicle_snapshot(self, context: ToolInvocationContext) -> dict[str, Any]:
        vehicle = context.context_snapshot.get("vehicle")
        if not isinstance(vehicle, dict):
            return {}
        if _has_pose_and_heading(vehicle):
            return vehicle
        fallback = vehicle.get("last_known_replay_state")
        if isinstance(fallback, dict) and _has_position(fallback):
            merged = dict(vehicle)
            merged["position"] = fallback.get("position") or {}
            if fallback.get("heading_deg") is not None:
                merged["heading_deg"] = fallback.get("heading_deg")
            merged["gps"] = fallback.get("gps") or merged.get("gps") or {}
            merged["position_frame"] = fallback.get("position_frame") or merged.get("position_frame") or "unknown"
            merged["telemetry_fresh"] = False
            merged["telemetry_source"] = "last_known_replay_state"
            merged["telemetry_source_session_id"] = fallback.get("session_id")
            return merged
        return vehicle

    def _get_current_vehicle_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        return dict(self._vehicle_snapshot(context))

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

    def _get_runtime_context(self, context: ToolInvocationContext) -> dict[str, Any]:
        runtime = context.context_snapshot.get("runtime")
        return dict(runtime) if isinstance(runtime, dict) else {}

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
        vehicle_state = self._vehicle_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_in_front(self._scene_payload(context), vehicle_state, max_distance_m, fov_deg, kinds)

    def _query_objects_near(
        self,
        context: ToolInvocationContext,
        radius_m: float = 50.0,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict[str, Any]:
        vehicle_state = self._vehicle_snapshot_with_override(context, position=position if position is not None else coordinates)
        return self._spatial.find_objects_near(self._scene_payload(context), vehicle_state, radius_m, kinds)

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
        vehicle_state = self._vehicle_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_to_left(self._scene_payload(context), vehicle_state, max_distance_m, angle_width_deg, kinds)

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
        vehicle_state = self._vehicle_snapshot_with_override(context, position=position if position is not None else coordinates, heading_deg=heading_deg)
        return self._spatial.find_objects_to_right(self._scene_payload(context), vehicle_state, max_distance_m, angle_width_deg, kinds)

    def _query_nearest_objects(
        self,
        context: ToolInvocationContext,
        limit: int = 5,
        max_distance_m: float | None = None,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
    ) -> dict[str, Any]:
        vehicle_state = self._vehicle_snapshot_with_override(context, position=position if position is not None else coordinates)
        return self._spatial.find_nearest_objects(self._scene_payload(context), vehicle_state, limit, max_distance_m, kinds)

    def _query_map_objects(
        self,
        context: ToolInvocationContext,
        mode: str,
        kinds: list[str] | None = None,
        position: dict[str, Any] | list[Any] | str | None = None,
        coordinates: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
        max_distance_m: float | None = None,
        fov_deg: float = 20.0,
        angle_width_deg: float = 90.0,
        radius_m: float = 50.0,
        limit: int = 5,
        kind: str | None = None,
    ) -> dict[str, Any]:
        pos = position if position is not None else coordinates
        if mode == "front":
            return self._query_objects_in_front(context, max_distance_m=max_distance_m or 100.0, fov_deg=fov_deg, kinds=kinds, position=pos, heading_deg=heading_deg)
        if mode == "near":
            return self._query_objects_near(context, radius_m=radius_m, kinds=kinds, position=pos)
        if mode == "by_kind":
            if not kind:
                return {"error": "mode=by_kind requires kind"}
            return self._query_objects_by_kind(context, kind=kind)
        if mode == "left":
            return self._query_objects_to_left(context, max_distance_m=max_distance_m or 100.0, angle_width_deg=angle_width_deg, kinds=kinds, position=pos, heading_deg=heading_deg)
        if mode == "right":
            return self._query_objects_to_right(context, max_distance_m=max_distance_m or 100.0, angle_width_deg=angle_width_deg, kinds=kinds, position=pos, heading_deg=heading_deg)
        if mode == "nearest":
            return self._query_nearest_objects(context, limit=limit, max_distance_m=max_distance_m, kinds=kinds, position=pos)
        return {"error": f"unknown mode: {mode!r}. Use one of: front, near, by_kind, left, right, nearest"}

    def _resolve_spatial_target(self, context: ToolInvocationContext, target: dict[str, Any] | str) -> dict[str, Any]:
        resolved_target = _normalize_spatial_target(target)
        vehicle_state = self._vehicle_snapshot_with_override(
            context,
            position=resolved_target.get("position") if isinstance(resolved_target, dict) and resolved_target.get("position") is not None else resolved_target.get("coordinates") if isinstance(resolved_target, dict) else None,
            heading_deg=resolved_target.get("heading_deg") if isinstance(resolved_target, dict) else None,
        )
        return self._spatial.resolve_target_description(self._scene_payload(context), vehicle_state, resolved_target)

    def _vehicle_snapshot_with_override(
        self,
        context: ToolInvocationContext,
        *,
        position: dict[str, Any] | list[Any] | str | None = None,
        heading_deg: float | None = None,
    ) -> dict[str, Any]:
        vehicle = dict(self._vehicle_snapshot(context))
        explicit_position = _normalize_position_override(position)
        if explicit_position is not None:
            vehicle["position"] = explicit_position
            vehicle["position_frame"] = "explicit_query_position"
            vehicle["telemetry_fresh"] = False
            vehicle["telemetry_source"] = "explicit_query_position"
        if heading_deg is not None:
            try:
                vehicle["heading_deg"] = float(heading_deg) % 360.0
                vehicle["telemetry_fresh"] = False
                vehicle["telemetry_source"] = "explicit_query_pose"
            except (TypeError, ValueError):
                pass
        return vehicle

    def _get_current_mission_state(self, context: ToolInvocationContext) -> dict[str, Any]:
        mission = context.context_snapshot.get("mission")
        return (
            dict(mission)
            if isinstance(mission, dict)
            else AIContextService(context.runtime).get_current_mission_state(session_id=context.session_id)
        )

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

    def _query_replay_sessions(
        self,
        context: ToolInvocationContext,
        operation: str,
        session_id: str = "",
        selector: str = "",
        timezone_name: str = "",
        limit: int = 100,
        order: str = "desc",
        downsample: int = 10,
        event_type: str = "",
        text: str = "",
        seconds: int = 120,
    ) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        if op == "current":
            return self._get_current_replay_summary(context)
        if op == "telemetry":
            return self._get_recent_telemetry(context, seconds=seconds, limit=limit, session_id=session_id)
        if op == "list":
            return self._list_replay_sessions(context, limit=limit, order=order)
        if op == "resolve":
            return self._resolve_replay_sessions(context, selector=selector, timezone_name=timezone_name)
        if op == "summary":
            return self._get_replay_session_summary(context, session_id=session_id)
        if op == "path":
            return self._get_replay_session_path(context, session_id=session_id, downsample=downsample, limit=limit)
        if op == "events":
            return self._search_replay_session_events(context, session_id=session_id, event_type=event_type, text=text, limit=limit)
        return {"error": f"unknown operation: {op!r}. Use one of: current, telemetry, list, resolve, summary, path, events"}

    def _analyze_replay_sessions(
        self,
        context: ToolInvocationContext,
        operation: str,
        session_id: str = "",
        session_ids: list[str] | None = None,
        selector: str = "",
        timezone_name: str = "",
        refresh: bool = False,
        top_n: int = 5,
    ) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        if op == "metrics":
            return self._get_replay_session_metrics(context, session_id=session_id, refresh=refresh)
        if op == "compare":
            return self._compare_replay_sessions(context, session_ids=session_ids or [])
        if op == "aggregate":
            return self._aggregate_replay_sessions(context, selector=selector, session_ids=session_ids, timezone_name=timezone_name, top_n=top_n)
        return {"error": f"unknown operation: {op!r}. Use one of: metrics, compare, aggregate"}

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

    def _query_ai_memory(
        self,
        context: ToolInvocationContext,
        operation: str,
        query: str = "",
        session_id: str = "",
        limit: int = 20,
        include_archived: bool = False,
        archived_only: bool = False,
        role: str = "",
        before_message_id: str = "",
    ) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        if op == "list":
            return self._list_ai_sessions(context, limit=limit, include_archived=include_archived, archived_only=archived_only, query=query)
        if op == "search":
            return self._search_ai_messages(context, query=query, limit=limit, session_id=session_id, include_archived=include_archived, role=role)
        if op == "get":
            return self._get_ai_session_messages(context, session_id=session_id, limit=limit, before_message_id=before_message_id, role=role)
        return {"error": f"unknown operation: {op!r}. Use one of: list, search, get"}

    def _query_settings(
        self,
        context: ToolInvocationContext,
        operation: str,
        section: str = "",
    ) -> dict[str, Any]:
        op = str(operation or "").strip().lower()
        if op == "summary":
            return self._get_settings_summary(context)
        if op == "section":
            return self._get_settings_section(context, section=section)
        if op == "provider":
            return self._get_llm_provider_summary(context)
        return {"error": f"unknown operation: {op!r}. Use one of: summary, section, provider"}

    def _get_sensor_status(self, context: ToolInvocationContext) -> dict[str, Any]:
        vehicle = self._vehicle_snapshot(context)
        runtime_summary = context.context_snapshot.get("runtime")
        runtime_details = dict(runtime_summary) if isinstance(runtime_summary, dict) else {}
        video = runtime_details.get("video")
        return {
            "available": True,
            "telemetry_fresh": bool(vehicle.get("telemetry_fresh")),
            "camera_fresh": bool(vehicle.get("camera_fresh")),
            "last_telemetry_ts": vehicle.get("last_telemetry_ts"),
            "last_camera_ts": vehicle.get("last_camera_ts"),
            "camera": dict(vehicle.get("camera") or {}),
            "video": dict(video) if isinstance(video, dict) else {},
            "perception_available": False,
            "perception_note": "This phase exposes only metadata and freshness; raw frames, detections, and perception events are not implemented.",
        }

    def _search_project_docs(
        self,
        context: ToolInvocationContext,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        secret_resolver = getattr(getattr(context.runtime, "secret_store", None), "get_secret", None)
        return _search_project_docs(
            context.runtime.config,
            query,
            limit=limit,
            secret_resolver=secret_resolver,
        )

    def _plan_route_around_group(
        self,
        context: ToolInvocationContext,
        group_id: str,
    ) -> dict[str, Any]:
        vehicle = self._vehicle_snapshot(context)
        pos = vehicle.get("position") or {}
        try:
            x = float(pos.get("x") or 0.0)
            y = float(pos.get("y") or 0.0)
        except (TypeError, ValueError):
            x, y = 0.0, 0.0
        if not str(group_id or "").strip():
            return {"ok": False, "error": "group_id is required"}
        known = self._road_graph.known_groups()
        clean_group = str(group_id).strip()
        if clean_group not in known:
            scene_may_be_loading = not known
            if scene_may_be_loading:
                hint = (
                    "No route groups are registered for this scene yet — the road graph may still be "
                    "building. Either retry once, or use plan_route_between with explicit start/goal "
                    "targets resolved via resolve_spatial_target."
                )
            else:
                hint = (
                    f"'{clean_group}' is not a registered route group. Pick one of known_groups, "
                    "or use plan_route_between with explicit targets."
                )
            return {
                "ok": False,
                "error": f"unknown group '{clean_group}'",
                "known_groups": known,
                "scene_may_be_loading": scene_may_be_loading,
                "fallback_tool": "plan_route_between",
                "hint": hint,
            }
        result = self._road_graph.route_to_then_around_then_back(x, y, clean_group)
        if result.get("ok"):
            result["route_hash"] = _route_hash(result.get("waypoints", []))
            result["known_groups"] = known
        return result

    def _plan_route_between(
        self,
        context: ToolInvocationContext,
        goal_target: dict[str, Any] | str,
        start_target: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        try:
            scene = self._scene_payload(context)
        except Exception:
            scene = None
        vehicle = self._vehicle_snapshot(context)

        if start_target is None or str(start_target or "").strip() in ("", "vehicle_pose"):
            start_pos = vehicle.get("position") or {}
            try:
                sx = float(start_pos.get("x") or 0.0)
                sy = float(start_pos.get("y") or 0.0)
            except (TypeError, ValueError):
                return {"ok": False, "error": "vehicle position unavailable for start_target=None; provide explicit start_target"}
        else:
            start_point = _normalize_scene_point(start_target, scene=scene)
            if start_point is not None:
                sx, sy = start_point["x"], start_point["y"]
            else:
                resolved = self._spatial.resolve_target_description(scene, vehicle, _normalize_spatial_target(start_target))
                selected = resolved.get("selected")
                if not selected:
                    return {"ok": False, "error": "start_target could not be resolved on the scene map"}
                p = selected.get("position") or {}
                sx, sy = float(p.get("x") or 0.0), float(p.get("y") or 0.0)

        if not goal_target:
            return {"ok": False, "error": "goal_target is required"}
        goal_point = _normalize_scene_point(goal_target, scene=scene)
        if goal_point is not None:
            gx, gy = goal_point["x"], goal_point["y"]
        else:
            resolved_goal = self._spatial.resolve_target_description(scene, vehicle, _normalize_spatial_target(goal_target))
            selected_goal = resolved_goal.get("selected")
            if not selected_goal:
                return {"ok": False, "error": "goal_target could not be resolved on the scene map"}
            gp = selected_goal.get("position") or {}
            gx, gy = float(gp.get("x") or 0.0), float(gp.get("y") or 0.0)

        result = self._road_graph.route_between(sx, sy, gx, gy)
        if result.get("ok"):
            result["route_hash"] = _route_hash(result.get("waypoints", []))
        return result

    def _generate_pattern_subtree(
        self,
        context: ToolInvocationContext,
        pattern: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        kind = str(pattern or "").strip().lower()
        if kind not in ("corridor", "survey"):
            return {"ok": False, "error": "pattern must be 'corridor' or 'survey'"}
        if not isinstance(params, dict):
            return {"ok": False, "error": "params must be an object"}

        def _num(key: str, default: float | None = None) -> float:
            raw = params.get(key, default)
            if raw is None:
                raise ValueError(f"'{key}' is required")
            return float(raw)

        def _xy(value: Any) -> tuple[float, float]:
            if isinstance(value, dict):
                return float(value.get("x") or 0.0), float(value.get("y") or 0.0)
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return float(value[0]), float(value[1])
            raise ValueError("point must be {x, y} or [x, y]")

        try:
            if kind == "corridor":
                raw_path = params.get("path")
                if not isinstance(raw_path, list) or len(raw_path) < 2:
                    return {"ok": False, "error": "corridor 'path' must be a list of at least two {x, y} points"}
                node = mission_patterns.corridor_pattern(
                    path=[_xy(p) for p in raw_path],
                    spacing_m=_num("spacing_m"),
                    altitude_m=_num("altitude_m"),
                    passes=int(params.get("passes", 1)),
                )
            else:
                origin_xy = _xy(params["origin_xy"]) if params.get("origin_xy") is not None else (0.0, 0.0)
                node = mission_patterns.survey_pattern(
                    width_m=_num("width_m"),
                    height_m=_num("height_m"),
                    line_spacing_m=_num("line_spacing_m"),
                    altitude_m=_num("altitude_m"),
                    origin_xy=origin_xy,
                    heading_deg=float(params.get("heading_deg", 0.0)),
                )
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": f"invalid {kind} params: {exc}"}

        tree = node.to_dict()
        # Count every navigable waypoint in the subtree, including nested
        # sequences/passes — flatten_navigable_segments is the canonical walk.
        waypoint_count = sum(len(segment) for segment in flatten_navigable_segments(node))
        return {
            "ok": True,
            "pattern": kind,
            "tree": tree,
            "waypoint_count": waypoint_count,
        }

    def _set_mission_geofence(
        self,
        context: ToolInvocationContext,
        mission_id: str,
        polygon: list[dict[str, Any]] | None = None,
        rally_points: list[dict[str, Any]] | None = None,
        min_alt: float | None = None,
        max_alt: float | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Author or clear a Mission's inclusion geofence (ADR 0023 Phase 5).

        Resolves the flat Mission to its active operation, then appends a fenced
        revision via the execution service. The fence is WGS84 (the stored truth);
        ``polygon`` is a list of ``{lat, lon}`` vertices.
        """
        clean_id = str(mission_id or "").strip()
        if not clean_id:
            return {"ok": False, "error": "mission_id is required"}
        store = getattr(context.runtime, "mission_store", None)
        service = getattr(context.runtime, "mission_execution_service", None)
        if store is None or service is None:
            return {"ok": False, "error": "mission services are not available"}
        mission = store.get_mission(clean_id)
        if mission is None:
            return {"ok": False, "error": f"mission '{clean_id}' not found"}
        operation_id = str(mission.get("active_operation_id") or "").strip()
        if not operation_id:
            return {"ok": False, "error": f"mission '{clean_id}' has no active operation to fence"}

        geofence: dict[str, Any] | None = None
        if not clear:
            if not isinstance(polygon, list) or len(polygon) < 3:
                return {"ok": False, "error": "polygon must be a list of at least three {lat, lon} vertices (or pass clear=true)"}
            geofence = {"polygon": polygon, "rally_points": rally_points or []}
            if min_alt is not None:
                geofence["min_alt"] = min_alt
            if max_alt is not None:
                geofence["max_alt"] = max_alt

        return service.set_operation_geofence(
            session_id=context.session_id,
            operation_id=operation_id,
            geofence=geofence,
        )

    # ── Planner loop handlers (Phase 5) ───────────────────────────────────────

    def _parse_vehicle_intent(
        self,
        context: ToolInvocationContext,
        prompt: str,
        context_summary: str = "",
    ) -> dict[str, Any]:
        secret_resolver = getattr(getattr(context.runtime, "secret_store", None), "get_secret", None)
        try:
            resolved = _resolve_intent_provider(
                context.runtime.config,
                secret_resolver=secret_resolver,
            )
        except Exception as exc:
            return {"ok": False, "error": f"no intent provider: {exc}"}
        try:
            result = _IntentService().parse(
                str(prompt or "").strip(),
                model=resolved.model,
                context_summary=str(context_summary or ""),
                timezone_name=context.timezone_name,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "intent": result["intent"],
            "parse_errors": result.get("parse_errors") or [],
        }

    def _lazy_load_replay(self, context: ToolInvocationContext) -> dict[str, Any]:
        if not context.source_controls.get("replay_reports", True):
            return {"ok": False, "error": "source_disabled", "source": "replay_reports"}
        replay = AIContextService(context.runtime).get_current_replay_summary()
        return {"ok": True, "replay_summary": replay, "available": bool(replay.get("active"))}

    def _lazy_load_ai_memory(self, context: ToolInvocationContext) -> dict[str, Any]:
        if not context.source_controls.get("ai_chat_history", False):
            return {"ok": False, "error": "source_disabled", "source": "ai_chat_history"}
        history = AIContextService(context.runtime).get_recent_ai_chat_history(
            session_id=context.session_id,
        )
        return {"ok": True, "chat_history_summary": history, "available": bool(history.get("available"))}

    def _lazy_load_settings(self, context: ToolInvocationContext) -> dict[str, Any]:
        if not context.source_controls.get("settings_config", False):
            return {"ok": False, "error": "source_disabled", "source": "settings_config"}
        settings = AIContextService(context.runtime).get_settings_context()
        return {"ok": True, "settings_summary": settings, "available": bool(settings)}

    def _lazy_load_sensor(self, context: ToolInvocationContext) -> dict[str, Any]:
        if not context.source_controls.get("sensor_context", False):
            return {"ok": False, "error": "source_disabled", "source": "sensor_context"}
        vehicle = context.context_snapshot.get("vehicle") or {}
        return {
            "ok": True,
            "telemetry_fresh": vehicle.get("telemetry_fresh"),
            "camera_fresh": vehicle.get("camera_fresh"),
            "available": bool(vehicle),
        }

    def _create_mission_from_waypoints(
        self,
        context: ToolInvocationContext,
        waypoints: list,
        goal: str = "",
        route_metadata: dict | None = None,
    ) -> dict[str, Any]:
        try:
            scene = self._scene_payload(context)
        except Exception:
            scene = None
        clean_waypoints: list[dict[str, float]] = []
        for index, waypoint in enumerate(waypoints or [], start=1):
            point = _normalize_scene_point(waypoint, scene=scene)
            if point is None:
                return {
                    "ok": False,
                    "error": f"waypoint {index} requires numeric x and y coordinates; z is optional and defaults to terrain ground",
                }
            clean_waypoints.append(point)
        if not clean_waypoints:
            return {"ok": False, "error": "at least one waypoint is required"}

        metadata = dict(route_metadata or {})
        declared_count = metadata.get("waypoint_count")
        if declared_count is not None:
            try:
                declared_count = int(declared_count)
            except (TypeError, ValueError):
                return {
                    "ok": False,
                    "error": "route_metadata.waypoint_count must be an integer",
                }
        if declared_count is not None and declared_count != len(clean_waypoints):
            return {
                "ok": False,
                "error": (
                    f"declared waypoint count is {declared_count}, but "
                    f"{len(clean_waypoints)} waypoints were supplied"
                ),
                "declared_waypoint_count": declared_count,
                "supplied_waypoint_count": len(clean_waypoints),
            }
        metadata["waypoint_count"] = len(clean_waypoints)
        metadata.setdefault("source", "operator_supplied_waypoints")

        mission_goal = str(goal or "").strip() or "AI mission"
        return self._propose_mission_draft(
            context,
            intent={
                "intent_type": "navigate",
                "requires_vehicle_motion": True,
                "requested_actions": ["follow supplied waypoint route"],
            },
            draft={
                "goal": mission_goal,
                "waypoints": clean_waypoints,
                "route_metadata": metadata,
                "steps": [],
                "constraints": [],
                "assumptions": ["Coordinates are local scene metres (x=east, y=north, z=up)."],
                "risks": [],
            },
        )

    def _propose_mission_draft(
        self,
        context: ToolInvocationContext,
        intent: dict,
        target_resolution: dict | None = None,
        vehicle_position: dict | None = None,
        draft: dict | None = None,
        route_artifacts: list | None = None,
        parent_operation_id: str = "",
        mission_edit_mode: str = "create",
        source_mission_id: str = "",
    ) -> dict[str, Any]:
        # Pure artifact submitter mode: planner provides the draft directly.
        # Preferred when route-planning tools were called so waypoints are preserved.
        parent_op = str(parent_operation_id or "").strip()
        # ADR 0021 §3 flat-Mission lifecycle selector. The store layer maps the
        # mode onto operation reuse; "clone_and_edit" is the default for AI edits.
        edit_mode = str(mission_edit_mode or "create").strip() or "create"
        if edit_mode not in ("create", "clone_and_edit", "edit_in_place"):
            edit_mode = "create"
        source_mission = str(source_mission_id or "").strip()
        if draft and isinstance(draft, dict):
            normalized, repairs = normalize_mission_draft_payload(draft)
            if route_artifacts and isinstance(route_artifacts, list):
                normalized["route_artifacts"] = list(route_artifacts)
            result = {
                "ok": True,
                "draft": normalized,
                "repairs": repairs,
                "source": "planner_submitted",
                "parent_operation_id": parent_op,
                "mission_edit_mode": edit_mode,
                "source_mission_id": source_mission,
            }
            return self._persist_agent_mission_proposal(
                context,
                result=result,
                intent=intent,
                target_resolution=target_resolution or {},
                vehicle_position=vehicle_position or {},
            )

        # LLM generation mode: second model generates draft from intent summary.
        secret_resolver = getattr(getattr(context.runtime, "secret_store", None), "get_secret", None)
        resolved = None
        for purpose in ("mission_planner", "general_chat"):
            try:
                resolved = _resolve_provider(
                    context.runtime.config,
                    purpose=purpose,
                    secret_resolver=secret_resolver,
                )
                break
            except Exception:
                continue
        if resolved is None:
            return {"ok": False, "error": "no LLM provider available for draft generation"}
        prompt = _planner_draft_prompt(
            intent or {},
            target_resolution or {},
            vehicle_position or {},
        )
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            response = resolved.model.invoke([
                SystemMessage(content=_PLANNER_DRAFT_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            raw_text = str(getattr(response, "content", response) or "")
            raw_draft = _parse_planner_draft_json(raw_text)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        normalized, repairs = normalize_mission_draft_payload(raw_draft)
        if route_artifacts and isinstance(route_artifacts, list):
            normalized["route_artifacts"] = list(route_artifacts)
        result = {
            "ok": True,
            "draft": normalized,
            "repairs": repairs,
            "source": "llm_generated",
            "parent_operation_id": parent_op,
            "mission_edit_mode": edit_mode,
            "source_mission_id": source_mission,
        }
        return self._persist_agent_mission_proposal(
            context,
            result=result,
            intent=intent,
            target_resolution=target_resolution or {},
            vehicle_position=vehicle_position or {},
        )

    def _persist_agent_mission_proposal(
        self,
        context: ToolInvocationContext,
        *,
        result: dict[str, Any],
        intent: dict[str, Any],
        target_resolution: dict[str, Any],
        vehicle_position: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist terminal Agent-chat proposals as real Mission objects."""
        if context.run_mode != "agent":
            return result

        mission_execution = getattr(context.runtime, "mission_execution_service", None)
        mission_store = getattr(context.runtime, "mission_store", None)
        if mission_execution is None or mission_store is None:
            return {
                **result,
                "ok": False,
                "error": "mission persistence services are unavailable",
            }

        draft = result["draft"]
        validation = validate_draft_payload(
            intent,
            target_resolution,
            draft,
            vehicle_position or None,
        )
        if validation.get("status") in {"blocked", "unsafe", "needs_clarification"}:
            return {
                **result,
                "ok": False,
                "error": "mission draft did not pass validation",
                "validation": validation,
            }

        edit_mode = str(result.get("mission_edit_mode") or "create")
        source_mission_id = str(result.get("source_mission_id") or "")
        parent_operation_id = str(result.get("parent_operation_id") or "")
        if edit_mode == "edit_in_place" and source_mission_id:
            source = mission_store.get_mission(source_mission_id)
            parent_operation_id = str((source or {}).get("active_operation_id") or parent_operation_id)
        elif edit_mode in {"create", "clone_and_edit"}:
            parent_operation_id = ""

        draft_id = f"ai-draft-{uuid.uuid4().hex[:12]}"
        try:
            revision = mission_execution.create_proposal(
                session_id=context.session_id,
                source_message_id="",
                draft_id=draft_id,
                intent=intent,
                target_resolution=target_resolution,
                draft_payload=draft,
                validation=validation,
                draft_status="awaiting_approval",
                review_context={
                    "goal": draft.get("goal", ""),
                    "risks": draft.get("risks") or [],
                    "approval_scope": "planning_artifact_only",
                },
                parent_operation_id=parent_operation_id,
            )
            operation_id = str(revision.get("operation_id") or "")
            existing = mission_store.get_by_operation_id(operation_id)
            if existing is not None:
                mission_id = str(existing.get("id") or "")
                mission = mission_store.bump_client_version(mission_id) or existing
            else:
                mission = mission_store.create_mission(
                    user_id=context.user_id,
                    name=str(draft.get("goal") or "").strip() or "AI mission",
                    origin="ai_chat",
                    origin_chat_id=context.session_id,
                )
                mission_id = str(mission.get("id") or "")
                if not mission_id:
                    raise RuntimeError("failed to create Mission row")
                mission = mission_store.set_active_operation(
                    mission_id,
                    operation_id=operation_id,
                ) or mission
        except Exception as exc:
            return {
                **result,
                "ok": False,
                "error": str(exc) or "failed to persist mission",
                "validation": validation,
            }

        revision_id = str(revision.get("id") or "")
        export_error: str = ""
        try:
            vehicle = self._vehicle_snapshot(context)
            gps = vehicle.get("gps") or {}
            home: dict[str, float] | None = None
            if gps.get("lat") and gps.get("lon"):
                home = {
                    "latitude": float(gps["lat"]),
                    "longitude": float(gps["lon"]),
                    "altitude": float(gps.get("alt") or 0.0),
                }
            export_result = self._exporter.export(
                {"id": draft_id, "draft": draft},
                profile=self._profile_resolver(),
                home_position=home,
            )
            if export_result.get("ok"):
                mission_execution.mark_revision_exported_by_revision_id(
                    revision_id, export_result=export_result
                )
            else:
                export_error = str(export_result.get("error") or "export failed")
        except Exception as exc:
            export_error = str(exc)

        out: dict[str, Any] = {
            **result,
            "draft_id": draft_id,
            "mission_id": mission_id,
            "mission_operation_id": operation_id,
            "mission_revision_id": revision_id,
            "mission": _compact_mission_reference(mission),
            "validation": validation,
        }
        if export_error:
            out["export_warning"] = export_error
        return out

    def _resolve_mission_reference(
        self,
        context: ToolInvocationContext,
        reference: str,
    ) -> dict[str, Any]:
        """ADR 0021 §5 chat reference resolution exposed to the planner."""
        if not str(reference or "").strip():
            return {"ok": False, "error": "reference is required"}
        store = getattr(context.runtime, "mission_store", None)
        if store is None:
            return {"ok": False, "error": "mission store is not available"}
        result = store.resolve_reference(
            user_id=context.user_id,
            reference=reference,
            current_chat_id=context.session_id,
        )
        return {
            "ok": True,
            "reference": str(reference),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "mission": _compact_mission_reference(result.get("mission")),
            "candidates": [_compact_mission_reference(m) for m in (result.get("candidates") or [])],
        }

    # ── Execution tool handlers (ADR 0021 §1 / ADR 0023 Phase 3) ───────────────

    def _load_mission_content(
        self, context: ToolInvocationContext, mission_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Resolve a flat Mission id to its latest revision content payload.

        Returns ``(content, error)``; on success ``error`` is empty. The content
        is the stored mission payload (legacy flat ``{waypoints:[...]}`` or a
        behavior tree) that :func:`build_mission_executor` parses into a tree.
        """
        clean_id = str(mission_id or "").strip()
        if not clean_id:
            return None, "mission_id is required"
        store = getattr(context.runtime, "mission_store", None)
        service = getattr(context.runtime, "mission_execution_service", None)
        if store is None or service is None:
            return None, "mission services are not available"
        mission = store.get_mission(clean_id)
        if mission is None:
            return None, f"mission '{clean_id}' not found"
        operation_id = str(mission.get("active_operation_id") or "").strip()
        if not operation_id:
            return None, f"mission '{clean_id}' has no active operation to execute"
        revisions = service.list_revisions(operation_id=operation_id, limit=1)
        if not revisions:
            return None, f"mission '{clean_id}' has no stored revision to execute"
        content = revisions[0].get("mission")
        if not isinstance(content, dict):
            return None, f"mission '{clean_id}' revision has no executable content"
        return content, ""

    def _prepare_execution(
        self, context: ToolInvocationContext, mission_id: str
    ) -> dict[str, Any]:
        """Shared arm/execute path: load content, build the mode-resolved executor,
        and register it on the runtime's per-session execution holder."""
        sessions = getattr(context.runtime, "mission_execution_sessions", None)
        if sessions is None:
            return {"ok": False, "error": "execution sessions are not available"}
        content, error = self._load_mission_content(context, mission_id)
        if error:
            return {"ok": False, "error": error}
        override_adapter = sessions.get_adapter_override(context.session_id)
        try:
            executor, root = build_mission_executor(context.runtime, content, adapter=override_adapter)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        try:
            sessions.prepare(
                context.session_id,
                executor=executor,
                root=root,
                mission_id=str(mission_id or "").strip(),
                mode=executor.mode,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "executor": executor}

    def _arm_execution(self, context: ToolInvocationContext, mission_id: str) -> dict[str, Any]:
        prepared = self._prepare_execution(context, mission_id)
        if not prepared.get("ok"):
            return prepared
        sessions = context.runtime.mission_execution_sessions
        # Confirm mode (ADR 0021 §1): arm and open a bounded confirm window, then
        # return — the run starts only when the operator confirms via the banner
        # ([Play]) inside the window. Chat does not block on the handshake.
        timeout_s = _resolve_confirm_timeout_s(context.runtime)
        return sessions.arm_confirm(context.session_id, timeout_s)

    def _execute_mission(self, context: ToolInvocationContext, mission_id: str) -> dict[str, Any]:
        prepared = self._prepare_execution(context, mission_id)
        if not prepared.get("ok"):
            return prepared
        return context.runtime.mission_execution_sessions.start(context.session_id)

    def _abort_execution(self, context: ToolInvocationContext) -> dict[str, Any]:
        sessions = getattr(context.runtime, "mission_execution_sessions", None)
        if sessions is None:
            return {"ok": False, "error": "execution sessions are not available"}
        return sessions.request_abort(context.session_id)

    def _cancel_execution(self, context: ToolInvocationContext) -> dict[str, Any]:
        """Cancel a prepared/armed/awaiting-confirm run via ``sessions.cancel()``
        (so a later banner confirm cannot start it); for a run already on its
        thread, fall back to a cooperative abort. ``abort`` remains the running
        emergency stop."""
        sessions = getattr(context.runtime, "mission_execution_sessions", None)
        if sessions is None:
            return {"ok": False, "error": "execution sessions are not available"}
        active = sessions.get(context.session_id)
        if active is None:
            return {"ok": False, "error": "no execution for this session"}
        if active.thread and active.thread.is_alive():
            return sessions.request_abort(context.session_id)
        return sessions.cancel(context.session_id)

    def _set_session_adapter(self, context: ToolInvocationContext, adapter_type: str) -> dict[str, Any]:
        sessions = getattr(context.runtime, "mission_execution_sessions", None)
        if sessions is None:
            return {"ok": False, "error": "execution sessions are not available"}
        clean_type = str(adapter_type or "").strip().lower()
        if clean_type in ("default", "reset", ""):
            sessions.clear_adapter_override(context.session_id)
            return {"ok": True, "adapter": "default", "note": "reverted to global config adapter"}
        _valid = frozenset({"file_sink", "json_file", "mavlink", "mavsdk"})
        if clean_type not in _valid:
            return {"ok": False, "error": f"unsupported adapter_type '{clean_type}'; must be one of {sorted(_valid)} or 'default'"}
        try:
            from backend.ai.controller_mission_adapter_factory import build_controller_mission_adapter
            from backend.runtime import GCS_DIR
        except Exception as exc:
            return {"ok": False, "error": f"could not import adapter factory: {exc}"}
        config = getattr(context.runtime, "config", None)
        if config is None:
            return {"ok": False, "error": "runtime has no config"}
        # Build a transient config using persisted URL/timeout settings but override the type.
        logging_cfg = dict(getattr(config, "logging", {}) or {})
        logging_cfg["controller_mission_adapter"] = clean_type

        def _path_resolver(path: object):
            from pathlib import Path
            p = Path(str(path or ""))
            return p if p.is_absolute() else GCS_DIR / p

        try:
            adapter = build_controller_mission_adapter(logging_cfg, path_resolver=_path_resolver)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        sessions.set_adapter_override(context.session_id, adapter)
        return {
            "ok": True,
            "adapter": clean_type,
            "session_id": context.session_id,
            "note": "active for this session only; reverts when session ends",
        }

    def _control_mission_execution(
        self, context: ToolInvocationContext, action: str, mission_id: str
    ) -> dict[str, Any]:
        control = mission_control_for(context.runtime)
        if control is None:
            return {"ok": False, "error": "execution sessions are not available"}
        handler = {"pause": control.pause, "resume": control.resume, "stop": control.stop}.get(action)
        if handler is None:
            return {"ok": False, "error": f"unknown action '{action}'; must be pause, resume, or stop"}
        return handler(mission_id)


def _resolve_confirm_timeout_s(runtime: Any) -> int:
    """Confirm-banner timeout from the persisted mission_lifecycle setting,
    clamped to [3, 60] s (ADR 0021 §6); falls back to the default when unset."""
    from backend.ai.execution_mode import normalize_confirm_timeout
    section: Any = None
    try:
        section = runtime.config.mission_lifecycle
    except Exception:
        section = None
    value = section.get("confirm_timeout_s") if isinstance(section, dict) else None
    return normalize_confirm_timeout(value)


def _compact_mission_reference(mission: dict[str, Any] | None) -> dict[str, Any] | None:
    """Bounded Mission view for chat-reference tool results (ADR 0021 §5)."""
    if not isinstance(mission, dict):
        return None
    return {
        "id": str(mission.get("id") or ""),
        "mission_index": mission.get("mission_index"),
        "name": str(mission.get("name") or ""),
        "origin": str(mission.get("origin") or ""),
        "origin_chat_id": str(mission.get("origin_chat_id") or ""),
        "active_revision_status": str(mission.get("active_revision_status") or ""),
    }


def _route_hash(waypoints: list[dict[str, Any]]) -> str:
    import hashlib
    key = "|".join(f"{w.get('x',0):.1f},{w.get('y',0):.1f}" for w in waypoints)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _snapshot_context(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_snapshot, dict):
        return {}
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return {}
    snapshot = meta.get("context_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _planner_draft_prompt(intent: dict, target_resolution: dict, vehicle_position: dict) -> str:
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
    missing = intent.get("missing_information") or []
    if missing:
        parts.append(f"Missing information (flag as assumption): {', '.join(str(m) for m in missing)}")
    if vehicle_position:
        parts.append(f"Current vehicle position: {json.dumps(vehicle_position)}")
    return "\n".join(parts)


def _parse_planner_draft_json(text: str) -> dict:
    clean = _re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=_re.MULTILINE)
    clean = _re.sub(r"\s*```$", "", clean, flags=_re.MULTILINE).strip()
    match = _re.search(r"\{.*\}", clean, _re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _snapshot_source_controls(context_snapshot: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(context_snapshot, dict):
        return normalize_source_controls(None)
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return normalize_source_controls(None)
    return normalize_source_controls(meta.get("source_controls"))


def _snapshot_session_id(context_snapshot: dict[str, Any] | None) -> str:
    if isinstance(context_snapshot, dict):
        meta = context_snapshot.get("meta")
        if isinstance(meta, dict) and str(meta.get("session_id") or "").strip():
            return str(meta["session_id"]).strip()
    snapshot = _snapshot_context(context_snapshot)
    llm = snapshot.get("llm")
    if not isinstance(llm, dict):
        return ""
    session = llm.get("session")
    if not isinstance(session, dict):
        return ""
    return str(session.get("id") or "").strip()


def _snapshot_user_id(context_snapshot: dict[str, Any] | None) -> str:
    if not isinstance(context_snapshot, dict):
        return ""
    meta = context_snapshot.get("meta")
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("user_id") or "").strip()


def _has_pose_and_heading(vehicle: dict[str, Any]) -> bool:
    if not _has_position(vehicle):
        return False
    try:
        float(vehicle.get("heading_deg"))
        return True
    except (TypeError, ValueError):
        return False


def _has_position(vehicle: dict[str, Any]) -> bool:
    if not isinstance(vehicle, dict):
        return False
    position = vehicle.get("position")
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


def _sample_scene_ground_height(scene: dict[str, Any] | None, x: float, y: float) -> float | None:
    if not isinstance(scene, dict):
        return None
    heightmap = scene.get("heightmap")
    height_range = scene.get("height_range") or {}
    bounds = scene.get("bounds") or {}
    if not isinstance(heightmap, list) or len(heightmap) < 2:
        return None
    try:
        min_h = float(height_range["min"])
        max_h = float(height_range["max"])
        min_x = float(bounds["min_x"])
        max_x = float(bounds["max_x"])
        min_y = float(bounds["min_y"])
        max_y = float(bounds["max_y"])
    except (KeyError, TypeError, ValueError):
        return None
    gs = int(scene.get("grid_size") or len(heightmap))
    if gs < 2 or max_x == min_x or max_y == min_y:
        return None
    try:
        col = ((float(x) - min_x) / (max_x - min_x)) * (gs - 1)
        row = ((float(y) - min_y) / (max_y - min_y)) * (gs - 1)
        c0 = max(0, min(gs - 2, int(col)))
        c1 = c0 + 1
        r0 = max(0, min(gs - 2, int(row)))
        r1 = r0 + 1
        tc = col - c0
        tr = row - r0
        n = (
            float(heightmap[r0][c0]) * (1 - tc) * (1 - tr)
            + float(heightmap[r0][c1]) * tc * (1 - tr)
            + float(heightmap[r1][c0]) * (1 - tc) * tr
            + float(heightmap[r1][c1]) * tc * tr
        )
    except (IndexError, TypeError, ValueError):
        return None
    span = max_h - min_h
    if abs(span) < 1e-9:
        return min_h
    return min_h + (n / 255.0) * span


def _normalize_scene_point(
    value: dict[str, Any] | list[Any] | str | None,
    *,
    scene: dict[str, Any] | None = None,
) -> dict[str, float] | None:
    raw: dict[str, Any] | list[Any] | str | None = value
    if isinstance(value, dict):
        if value.get("position") is not None:
            raw = value.get("position")
        elif value.get("coordinates") is not None:
            raw = value.get("coordinates")

    if isinstance(raw, dict):
        try:
            x = float(raw.get("x"))
            y = float(raw.get("y"))
        except (TypeError, ValueError):
            return None
        z_raw = raw.get("z")
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            x = float(raw[0])
            y = float(raw[1])
        except (TypeError, ValueError):
            return None
        z_raw = raw[2] if len(raw) >= 3 else None
    elif isinstance(raw, str):
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)
        if len(numbers) < 2:
            return None
        try:
            x = float(numbers[0])
            y = float(numbers[1])
        except ValueError:
            return None
        z_raw = numbers[2] if len(numbers) >= 3 else None
    else:
        return None

    if z_raw in (None, ""):
        z = _sample_scene_ground_height(scene, x, y)
        if z is None:
            z = 0.0
    else:
        try:
            z = float(z_raw)
        except (TypeError, ValueError):
            z = _sample_scene_ground_height(scene, x, y)
            if z is None:
                return None
    return {"x": x, "y": y, "z": z}


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."




def _tool_runtime_description(definition: ToolDefinition) -> str:
    lines = [definition.description.strip()]
    contract = definition.contract if isinstance(definition.contract, dict) else {}
    inputs = contract.get("inputs")
    required = contract.get("required_inputs")
    returns = contract.get("returns")
    # `upstream_from_tools` and `next_tools` are intentionally omitted from the
    # model-facing runtime description (P3 compact-projection, conservative first
    # slice). Both fields remain on the ToolMeta declaration for operator/debug
    # surfaces (e.g. /capabilities); only the always-on schema text is trimmed here.
    if isinstance(inputs, dict) and inputs:
        lines.append(f"Inputs: {_format_contract_mapping(inputs)}.")
    if isinstance(required, list) and required:
        lines.append(f"Required inputs: {', '.join(str(item) for item in required)}.")
    if isinstance(returns, dict) and returns:
        lines.append(f"Returns: {_format_contract_mapping(returns)}.")
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


def _meta(
    name: str,
    description: str,
    permission: str,
    handler: Callable[..., Any],
    *,
    side_effects: frozenset[str] | None = None,
    is_terminal: bool = False,
    inputs: dict[str, Any] | None = None,
    required_inputs: tuple[str, ...] = (),
    returns: dict[str, Any] | None = None,
    upstream_from_tools: tuple[str, ...] = (),
    next_tools: tuple[str, ...] = (),
    surface: str = "",
    always_allowed: bool = False,
    source_control: str | None = None,
    cacheable: bool = False,
    cache_ttl_s: int | None = None,
) -> ToolMeta:
    return ToolMeta(
        name=name,
        description=description,
        permission=permission,
        handler=handler,
        side_effects=side_effects or frozenset(),
        is_terminal=is_terminal,
        inputs=inputs or {},
        required_inputs=required_inputs,
        returns=returns or {},
        upstream_from_tools=upstream_from_tools,
        next_tools=next_tools,
        surface=surface,
        always_allowed=always_allowed,
        source_control=source_control,
        cacheable=cacheable,
        cache_ttl_s=cache_ttl_s,
    )


# O9: single per-tool declaration. Every other tool-facing surface (LangChain
# schema, contract text on /capabilities, the data-access manifest, the
# result-result cache list, and the always-allowed/source-gated name sets)
# derives from this table instead of re-listing tool names independently.
_TOOL_META: dict[str, ToolMeta] = {meta.name: meta for meta in [
    _meta(
        "list_data_surfaces",
        "List every bounded data surface available to this session, show which source controls currently enable them, and identify the exact tools that can load each surface. Call this first when you need to discover where replay history, AI chat history, settings/config, or sensor metadata can be retrieved from.",
        READ_ONLY,
        ToolRegistry._list_data_surfaces,
        surface="system_capabilities",
        always_allowed=True,
        cacheable=True,
        returns={"data_surfaces": "surface[]", "source_controls": "object", "planned_sources": "object[]"},
        next_tools=("query_settings", "query_ai_memory", "query_replay_sessions", "get_sensor_status"),
    ),
    _meta(
        "get_current_vehicle_state",
        "Get the current vehicle telemetry snapshot captured for this request, including pose, heading, freshness, battery, speed, and camera state. If live telemetry is stale or unavailable, inspect last_known_replay_state for the latest recorded vehicle values and source session.",
        READ_ONLY,
        ToolRegistry._get_current_vehicle_state,
        surface="current_vehicle_state",
        always_allowed=True,
        returns={
            "position": "object{x,y,z} | {}",
            "heading_deg": "number | null",
            "telemetry_fresh": "boolean",
            "last_known_replay_state": "object | null",
        },
        next_tools=("query_map_objects", "resolve_spatial_target"),
    ),
    _meta(
        "get_scene_summary",
        "Get the current terrain scene summary, including bounds, road count, object count, object kinds, spawn point, and site name. Use this before object queries when the operator asks what exists on the map or in the loaded scene.",
        READ_ONLY,
        ToolRegistry._get_scene_summary,
        surface="terrain_scene",
        always_allowed=True,
        cacheable=True,
        returns={"object_kinds": "object{kind->count}", "spawn": "object{x,y,z}", "object_count": "number"},
        next_tools=("query_map_objects", "resolve_spatial_target"),
    ),
    _meta(
        "get_runtime_context",
        "Get the current runtime environment: MQTT broker connection (host, port, state), controller link state, video delivery config, simulation backend settings, map config, and active replay session id. Call this when the operator asks about connectivity, MQTT configuration, broker status, video pipeline, or simulation parameters.",
        READ_ONLY,
        ToolRegistry._get_runtime_context,
        always_allowed=True,
        returns={
            "broker": "object{host,port,connected,...}",
            "controller": "object",
            "video": "object",
            "simulation": "object",
            "map": "object",
            "replay_session_id": "string | null",
        },
    ),
    _meta(
        "query_map_objects",
        "Query map objects by spatial mode. mode='front': objects in a forward cone (fov_deg, max_distance_m). mode='near': objects within radius_m. mode='by_kind': all objects whose kind matches kind=. mode='left' or mode='right': lateral flank objects (angle_width_deg, max_distance_m). mode='nearest': closest objects overall (limit, optional max_distance_m). Optional kinds filters by object kind for positional modes. For all positional modes, pass position or coordinates and optionally heading_deg to query from a hypothetical pose instead of live telemetry. Falls back to last_known_replay_state when live telemetry is stale.",
        READ_ONLY,
        ToolRegistry._query_map_objects,
        surface="terrain_scene",
        always_allowed=True,
        inputs={
            "mode": "string (front|near|by_kind|left|right|nearest)",
            "kinds": "string[]",
            "kind": "string (required for mode=by_kind)",
            "position": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'",
            "coordinates": "object{x,y,z} | [x,y,z?] | 'x,y[,z]'",
            "heading_deg": "number",
            "max_distance_m": "number",
            "fov_deg": "number",
            "angle_width_deg": "number",
            "radius_m": "number",
            "limit": "integer",
        },
        required_inputs=("mode",),
        upstream_from_tools=("get_current_vehicle_state (pose/heading/replay fallback)", "operator-provided coordinates/heading", "get_scene_summary (kind discovery)"),
        returns={"available": "boolean", "objects": "object[]", "reason": "string?"},
        next_tools=("resolve_spatial_target",),
    ),
    _meta(
        "resolve_spatial_target",
        "Resolve a spatial target against the current map and vehicle pose. Accepts either a target object (kind/side/max_distance_m/min_distance_m/relative_bearing_deg and optional position/coordinates/heading_deg) or a plain-language string such as 'nearest tree on the left'. If live telemetry is stale, it can use last_known_replay_state when available.",
        PLANNING,
        ToolRegistry._resolve_spatial_target,
        surface="terrain_scene",
        always_allowed=True,
        inputs={"target": "string | object{description,kind,side,min_distance_m,max_distance_m,relative_bearing_deg,position,coordinates,heading_deg}"},
        required_inputs=("target",),
        upstream_from_tools=("get_current_vehicle_state", "operator-provided coordinates/heading", "get_scene_summary", "query_map_objects results"),
        returns={"available": "boolean", "candidates": "object[]", "selected": "object|null", "needs_clarification": "boolean"},
    ),
    _meta(
        "get_current_mission_state",
        "Get the current mission state. This is read-only.",
        READ_ONLY,
        ToolRegistry._get_current_mission_state,
        surface="mission_state",
        always_allowed=True,
        returns={"active": "boolean", "status": "string", "summary": "string"},
        next_tools=("control_mission",),
    ),
    _meta(
        "query_replay_sessions",
        "Query replay session data by operation. operation='current': active replay session summary. operation='telemetry': recent telemetry samples (seconds, limit, optional session_id for a specific session). operation='list': enumerate sessions with started_at/ended_at/counts (limit, order). operation='resolve': resolve a natural-language selector like 'latest 5 sessions' or 'all sessions' into explicit session_ids (selector, timezone_name). operation='summary': session metadata by session_id. operation='path': downsampled path points for session_id (downsample, limit). operation='events': search runtime events within a session (session_id, optional event_type/text/limit). Call 'list' or 'resolve' first when you need session_ids.",
        ANALYSIS,
        ToolRegistry._query_replay_sessions,
        surface="replay_sessions",
        source_control="replay_reports",
        cacheable=True,
        inputs={
            "operation": "string (current|telemetry|list|resolve|summary|path|events)",
            "session_id": "string (required for summary/path/events; optional for telemetry)",
            "selector": "string (required for resolve; e.g. 'latest 5 sessions', 'all sessions')",
            "timezone_name": "string (optional, for resolve)",
            "limit": "integer",
            "order": "string(desc|asc) (for list)",
            "downsample": "integer (for path)",
            "event_type": "string (for events)",
            "text": "string (for events)",
            "seconds": "integer (for telemetry)",
        },
        required_inputs=("operation",),
        upstream_from_tools=("query_replay_sessions(operation='list'|'resolve') for session_ids", "get_current_replay_summary via operation='current'"),
        returns={
            "current": "{session_id, telemetry_count, runtime_event_count}",
            "telemetry": "{result: telemetry_sample[]}",
            "list": "{sessions: session_summary[], count}",
            "resolve": "{resolved_session_ids: string[], matched_count, preview_sessions}",
            "summary": "{session_id, telemetry_count, control_count, runtime_event_count}",
            "path": "{session_id, point_count, points: path_point[]}",
            "events": "{events: event[], count}",
        },
        next_tools=("analyze_replay_sessions", "query_map_objects"),
    ),
    _meta(
        "analyze_replay_sessions",
        "Analyze replay session data by metric operation. operation='metrics': compute analytics for session_id — duration_s, path_length_m, net_displacement_m, max_distance_from_start_m (refresh to recompute). operation='compare': compare multiple sessions by session_ids — per-session summaries and metrics for ranking and answering longest/furthest questions. operation='aggregate': aggregate across a natural-language selector or explicit session_ids — totals, averages, built-in longest/latest/furthest summaries, ranked top-N (selector, session_ids, timezone_name, top_n). Travel distance = path_length_m; furthest from start = max_distance_from_start_m. Resolve session_ids first with query_replay_sessions(operation='resolve') when needed.",
        ANALYSIS,
        ToolRegistry._analyze_replay_sessions,
        surface="replay_sessions",
        source_control="replay_reports",
        cacheable=True,
        inputs={
            "operation": "string (metrics|compare|aggregate)",
            "session_id": "string (required for metrics)",
            "session_ids": "string[] (required for compare; optional for aggregate)",
            "selector": "string (for aggregate)",
            "timezone_name": "string (for aggregate)",
            "refresh": "boolean (for metrics)",
            "top_n": "integer (for aggregate)",
        },
        required_inputs=("operation",),
        upstream_from_tools=("query_replay_sessions(operation='resolve'|'list') for session_ids",),
        returns={
            "metrics": "{path_length_m, duration_s, max_distance_from_start_m, net_displacement_m}",
            "compare": "{sessions: comparison_row[], best_by_metric: object}",
            "aggregate": "{totals: object, averages: object, top_sessions: session_metric[]}",
        },
    ),
    _meta(
        "query_ai_memory",
        "Query AI chat session history by operation. operation='list': list saved sessions with metadata, message counts, archival state, and last-message previews (limit, include_archived, archived_only, optional query filter). operation='search': search saved messages by text across sessions or within one (query required, limit, session_id, role). operation='get': load a bounded message window from one session (session_id, limit, before_message_id, role; omit session_id to use the current session). Call 'list' first to discover session_ids, or 'search' to locate a specific message.",
        ANALYSIS,
        ToolRegistry._query_ai_memory,
        surface="ai_chat_history",
        source_control="ai_chat_history",
        cacheable=True,
        cache_ttl_s=30,
        inputs={
            "operation": "string (list|search|get)",
            "query": "string (required for search; optional title/preview filter for list)",
            "session_id": "string (for search/get; omit on get to use the current session)",
            "limit": "integer",
            "include_archived": "boolean",
            "archived_only": "boolean",
            "role": "string (for search/get)",
            "before_message_id": "string (for get pagination)",
        },
        required_inputs=("operation",),
        upstream_from_tools=("query_ai_memory(operation='list') for session_ids", "query_ai_memory(operation='search') to locate a message"),
        returns={
            "list": "{sessions: ai_session_summary[], count, current_session_id}",
            "search": "{matches: ai_message_match[], count}",
            "get": "{messages: ai_message[], count, truncated}",
        },
    ),
    _meta(
        "query_settings",
        "Query GCS settings and LLM provider configuration by operation. operation='summary': compact settings overview — section names, settings_path, and key non-secret configuration summaries. operation='section': one settings section by name (section required; supported: mqtt, key_bindings, video, gcs, simulation, map, mission_lifecycle, ai_settings, settings_path). operation='provider': safe LLM provider and model-routing metadata — enabled providers, active chat-provider resolution, and routing rules. Never exposes secrets.",
        READ_ONLY,
        ToolRegistry._query_settings,
        surface="settings",
        source_control="settings_config",
        cacheable=True,
        cache_ttl_s=60,
        inputs={
            "operation": "string (summary|section|provider)",
            "section": "string (required for section; one of mqtt, key_bindings, video, gcs, simulation, map, mission_lifecycle, ai_settings, settings_path)",
        },
        required_inputs=("operation",),
        upstream_from_tools=("query_settings(operation='summary') for section names",),
        returns={
            "summary": "{settings_path, section_names: string[], summary: object}",
            "section": "{section, value: object|string, available: boolean}",
            "provider": "{providers: object[], model_routing: object, active_chat_provider: object|null}",
        },
    ),
    _meta(
        "get_sensor_status",
        "Get metadata-only sensor and video status, including telemetry freshness, camera freshness, configured video delivery, and current perception limitations. Use this for questions about whether the agent can currently see live camera data or rely on sensor freshness. This tool does not expose raw frames, detections, or vision inference output.",
        READ_ONLY,
        ToolRegistry._get_sensor_status,
        surface="video_perception",
        source_control="sensor_context",
        upstream_from_tools=("get_current_vehicle_state",),
        returns={"telemetry_fresh": "boolean", "camera_fresh": "boolean", "video": "object", "perception_available": "boolean"},
    ),
    _meta(
        "search_project_docs",
        "Search the project's own documentation — requirements, design docs, ADRs, glossary, and operational notes — for grounded, citeable context. Returns the most relevant doc chunks with their file path, heading path, similarity score, and a citation ref. Use this when the operator asks how the system is designed, why a decision was made, what an ADR or requirement says, or for definitions of project terms. Pass a focused natural-language query and optionally limit (default 5). Available only when the project_docs source control is enabled.",
        ANALYSIS,
        ToolRegistry._search_project_docs,
        source_control="project_docs",
        inputs={"query": "string — natural-language search query", "limit": "integer (default 5)"},
        required_inputs=("query",),
        returns={"available": "boolean", "status": "string", "results": "doc_chunk[]", "citations": "citation[]"},
    ),
    _meta(
        "plan_route_around_group",
        "Use when the operator asks the vehicle to traverse a named area — drive around a plantation, patrol a zone, or cover all roads in a group. Computes a route from the vehicle's current position to the group, traverses every road edge in the group at least once (Chinese-Postman), and returns to the start. Returns a compact route summary (waypoint_count, total_distance_m, legs) and the full waypoints list for the draft. NOTE: the returned route_hash is only a waypoint fingerprint, NOT a draft_id. Next step is propose_mission_draft with these waypoints — it persists and exports the Mission. Does not upload to the flight controller.",
        PLANNING,
        ToolRegistry._plan_route_around_group,
        surface="route_planning",
        always_allowed=True,
        inputs={"group_id": "string — one of known_groups; e.g. 'plant_a', 'plant_b', 'connector', 'building', 'start_hub'"},
        required_inputs=("group_id",),
        upstream_from_tools=("get_current_vehicle_state (vehicle position for transit legs)", "get_scene_summary (to discover group names)"),
        returns={"ok": "boolean", "waypoint_count": "integer", "total_distance_m": "number", "legs": "leg[]", "waypoints": "waypoint[]", "route_hash": "string (waypoint fingerprint, NOT a draft_id)", "known_groups": "string[]"},
        next_tools=("propose_mission_draft (with waypoints)",),
    ),
    _meta(
        "plan_route_between",
        "Use when the operator asks the vehicle to drive from one resolved target to another — 'drive to charger 1', 'go to the second plantation entrance'. Resolves both targets via resolve_spatial_target, snaps to the road graph, and runs Dijkstra. Returns a compact route summary and full waypoints. NOTE: the returned route_hash is only a waypoint fingerprint, NOT a draft_id. Next step is propose_mission_draft with these waypoints — it persists and exports the Mission. Does not upload.",
        PLANNING,
        ToolRegistry._plan_route_between,
        surface="route_planning",
        always_allowed=True,
        inputs={"start_target": "string | object | null (null = vehicle current pose)", "goal_target": "string | object"},
        required_inputs=("goal_target",),
        upstream_from_tools=("get_current_vehicle_state (when start_target is null)", "resolve_spatial_target (to resolve start/goal targets)"),
        returns={"ok": "boolean", "waypoint_count": "integer", "total_distance_m": "number", "waypoints": "waypoint[]", "route_hash": "string (waypoint fingerprint, NOT a draft_id)"},
        next_tools=("propose_mission_draft (with waypoints)",),
    ),
    _meta(
        "generate_pattern_subtree",
        "Use when the operator asks the vehicle to follow a path repeatedly or to systematically cover an area, instead of hand-listing waypoints. 'corridor' densifies an ordered polyline into evenly-spaced waypoints (optionally back-and-forth for multiple passes); 'survey' fills a rectangle with a lawnmower (boustrophedon) sweep. Pass 'pattern' ('corridor'|'survey') and 'params' in local scene metres (x=east, y=north, z=up). corridor params: path (list of {x,y}, >=2), spacing_m, altitude_m, optional passes. survey params: width_m, height_m, line_spacing_m, altitude_m, optional origin_xy ({x,y}) and heading_deg. Returns a navigation subtree as 'tree' (a nav_leaf, or a sequence of nav_leaf passes) plus waypoint_count — set it as the draft's 'tree' (or splice it into a larger tree) in propose_mission_draft. Does not upload by itself.",
        PLANNING,
        ToolRegistry._generate_pattern_subtree,
        always_allowed=True,
        inputs={
            "pattern": "string (corridor|survey)",
            "params": "object — corridor: {path, spacing_m, altitude_m, passes?}; survey: {width_m, height_m, line_spacing_m, altitude_m, origin_xy?, heading_deg?}",
        },
        required_inputs=("pattern", "params"),
        returns={"ok": "boolean", "pattern": "string", "tree": "object (nav_leaf or sequence of nav_leaf passes)", "waypoint_count": "integer"},
        next_tools=("propose_mission_draft (with tree)",),
    ),
    _meta(
        "set_mission_geofence",
        "Use when the operator wants to fence a mission to a safe area — 'keep it inside this boundary', 'add a geofence', or 'clear the fence'. Sets an inclusion geofence on an existing flat Mission (by mission_id): waypoints must stay inside the polygon, and the flight controller enforces it authoritatively while the executor also refuses any breaching mission before driving. Pass 'mission_id' and 'polygon' as a list of at least three {lat, lon} WGS84 vertices (the stored truth); optional 'rally_points' (list of {lat, lon, alt}) are safe-return points, and optional 'min_alt'/'max_alt' bound altitude in metres. Pass clear=true to remove the fence. Appends a new (approval-required) revision; does not upload by itself — the fence uploads to the FC when the mission is armed/executed.",
        PLANNING,
        ToolRegistry._set_mission_geofence,
        always_allowed=True,
        inputs={
            "mission_id": "string — durable flat Mission id",
            "polygon": "object[]{lat,lon} — at least 3 WGS84 vertices (required unless clear=true)",
            "rally_points": "object[]{lat,lon,alt} (optional)",
            "min_alt": "number (optional)",
            "max_alt": "number (optional)",
            "clear": "boolean — remove the fence instead of setting one",
        },
        required_inputs=("mission_id",),
        upstream_from_tools=("propose_mission_draft or create_mission_from_waypoints (mission_id)",),
        returns={"ok": "boolean", "error": "string?"},
    ),
    # ── Planner loop tools (Phase 5) ──────────────────────────────────
    _meta(
        "parse_vehicle_intent",
        "Parse the operator's mission request into a structured VehicleIntent. Call this first in the planner loop to extract intent_type, target, requested_actions, constraints, and missing_information. Pass the original user prompt and the compact context_summary from retrieve_initial_context.",
        READ_ONLY,
        ToolRegistry._parse_vehicle_intent,
        always_allowed=True,
        inputs={
            "prompt": "string — original operator mission request",
            "context_summary": "string — compact planning context summary (optional)",
        },
        required_inputs=("prompt",),
        upstream_from_tools=("operator mission request", "compact mission-planning context summary"),
        returns={"ok": "boolean", "intent": "object", "parse_errors": "string[]"},
        next_tools=(
            "lazy_load_replay",
            "lazy_load_ai_memory",
            "lazy_load_settings",
            "lazy_load_sensor",
            "resolve_spatial_target",
            "propose_mission_draft",
        ),
    ),
    _meta(
        "lazy_load_replay",
        "Load the active replay session summary for the current request. Returns replay_summary with the most recent session metadata. Call this when the operator's request references prior missions, replay sessions, or recorded data. Available only when replay_reports source control is enabled.",
        READ_ONLY,
        ToolRegistry._lazy_load_replay,
        upstream_from_tools=("source_controls.replay_reports", "parse_vehicle_intent (when the request references prior missions or recorded data)"),
        returns={"ok": "boolean", "replay_summary": "object", "available": "boolean"},
        next_tools=("propose_mission_draft",),
    ),
    _meta(
        "lazy_load_ai_memory",
        "Load the AI chat history summary for the current session. Returns chat_history_summary with a bounded view of recent AI conversation context. Call this when the operator references earlier discussions or prior planning sessions.",
        READ_ONLY,
        ToolRegistry._lazy_load_ai_memory,
        upstream_from_tools=("source_controls.ai_chat_history", "parse_vehicle_intent (when the request references earlier discussions)"),
        returns={"ok": "boolean", "chat_history_summary": "object", "available": "boolean"},
        next_tools=("propose_mission_draft",),
    ),
    _meta(
        "lazy_load_settings",
        "Load the GCS settings summary for the current request. Returns settings_summary with safe configuration metadata. Call this when the operator references configuration, provider routing, or enabled capabilities.",
        READ_ONLY,
        ToolRegistry._lazy_load_settings,
        upstream_from_tools=("source_controls.settings_config", "parse_vehicle_intent (when the request depends on configuration or provider routing)"),
        returns={"ok": "boolean", "settings_summary": "object", "available": "boolean"},
        next_tools=("propose_mission_draft",),
    ),
    _meta(
        "lazy_load_sensor",
        "Load sensor and telemetry freshness status. Returns telemetry_fresh and camera_fresh flags. Call this when the operator's request depends on live sensor availability or to flag staleness constraints in the mission draft.",
        READ_ONLY,
        ToolRegistry._lazy_load_sensor,
        upstream_from_tools=("source_controls.sensor_context", "parse_vehicle_intent (when the request depends on live telemetry or camera freshness)"),
        returns={"ok": "boolean", "telemetry_fresh": "boolean | null", "camera_fresh": "boolean | null", "available": "boolean"},
        next_tools=("propose_mission_draft",),
    ),
    _meta(
        "create_mission_from_waypoints",
        "Create an operator-visible Mission directly from supplied local-coordinate waypoints. Use this when the operator provides an explicit route in any text or structured format. Extract the route into a waypoints array of {x, y, z} objects and pass optional route metadata such as waypoint_count, path_length_m, or route_hash. The tool validates the structured data and persists the same durable Mission revision used by the map and mission sidebar. This is a terminal planning action; it does not execute or export the mission.",
        PLANNING,
        ToolRegistry._create_mission_from_waypoints,
        is_terminal=True,
        always_allowed=True,
        inputs={
            "waypoints": "object[] — ordered local-coordinate points with numeric x, y, z",
            "goal": "string — concise Mission name/goal (optional)",
            "route_metadata": "object — optional waypoint_count, path_length_m, route_hash, or source metadata",
        },
        required_inputs=("waypoints",),
        upstream_from_tools=("operator-supplied route", "plan_route_around_group", "plan_route_between"),
        returns={
            "ok": "boolean",
            "draft": "mission_draft",
            "mission_id": "string — durable flat Mission id in Agent mode",
            "mission_revision_id": "string — persisted revision id in Agent mode",
        },
    ),
    _meta(
        "propose_mission_draft",
        "Submit the final mission draft and create the operator-visible Mission. Terminal planning action — call after parse_vehicle_intent and optional route-planning tools. In Agent chat, success persists a durable Mission revision and flat Mission row, returning mission_id; the Mission then appears on the map and in the mission sidebar. Provide a complete 'draft' object (goal, steps, constraints, assumptions, risks) to submit it directly — preferred when route-planning was done so waypoints are preserved. Omit 'draft' to have one generated from 'intent' and 'target_resolution'. Pass route tool outputs as 'route_artifacts' to attach them to the draft. For a structured mission — branching, retries, loops, or operator prompts — set the draft's 'tree' to a behavior tree: nested nodes of type 'sequence'/'fallback'/'loop'/'recovery' (each with 'children'), 'nav_leaf' (a 'waypoints' run that drives the vehicle), 'condition', and 'ask_operator'. Omit 'tree' for a plain linear mission (the flat 'waypoints' list still works). The draft always has execution_allowed=false and required_operator_approval=true. Set 'mission_edit_mode' to choose how the result lands in the operator's Mission list: 'create' (default) for a brand-new mission; 'clone_and_edit' when changing an existing mission — pass its id as 'source_mission_id' — which creates a NEW mission row so the original is preserved for side-by-side comparison (use this for almost all edits); 'edit_in_place' ONLY when the operator explicitly said to edit the existing mission in place — also pass 'source_mission_id', and it mutates that mission instead of cloning.",
        PLANNING,
        ToolRegistry._propose_mission_draft,
        is_terminal=True,
        always_allowed=True,
        inputs={
            "intent": "object — from parse_vehicle_intent.intent",
            "target_resolution": "object — from resolve_spatial_target (optional)",
            "vehicle_position": "object — vehicle position override (optional)",
            "draft": "object — complete draft to submit directly; preferred when route-planning was done (optional)",
            "route_artifacts": "object[] — route artifacts from plan_route_* tools (optional)",
            "parent_operation_id": "string — internal parent operation for an explicit in-place edit (optional)",
            "mission_edit_mode": "create | clone_and_edit | edit_in_place",
            "source_mission_id": "string — existing flat Mission id for clone/edit operations (optional)",
        },
        required_inputs=("intent",),
        upstream_from_tools=("parse_vehicle_intent", "resolve_spatial_target (optional)", "plan_route_around_group or plan_route_between (optional)"),
        returns={
            "ok": "boolean",
            "draft": "mission_draft",
            "repairs": "string[]",
            "source": "planner_submitted|llm_generated",
            "mission_id": "string — durable flat Mission id in Agent mode",
            "mission_revision_id": "string — persisted revision id in Agent mode",
        },
    ),
    _meta(
        "resolve_mission_reference",
        "Resolve an operator's reference to an existing Mission into a concrete mission id before editing it. Pass the operator's exact phrasing as 'reference' — an index ('#26', 'mission 26'), a name ('the orchard sweep'), or a pronoun ('it', 'this mission'). Resolution order is index → exact name → fuzzy name → pronoun (most-recent Mission of the current chat). Returns status 'resolved' with the mission (use mission.id as source_mission_id), 'ambiguous' with candidates to disambiguate with the operator, or 'not_found'. Call this before propose_mission_draft with clone_and_edit/edit_in_place when the operator refers to a mission you do not already have an id for.",
        READ_ONLY,
        ToolRegistry._resolve_mission_reference,
        always_allowed=True,
        inputs={"reference": "string — index ('#26', 'mission 26'), a name, or a pronoun ('it', 'this mission')"},
        required_inputs=("reference",),
        returns={"ok": "boolean", "status": "resolved|ambiguous|not_found", "reason": "string?", "mission": "object|null", "candidates": "object[]"},
        next_tools=("propose_mission_draft (clone_and_edit/edit_in_place)",),
    ),
    # ── Execution tools (ADR 0021 §1 / ADR 0023 Phase 3) ──────────────
    # Bound per execution mode by agent_loop: Strict binds neither
    # arm_execution nor execute_mission; Confirm binds arm_execution;
    # Autonomous binds execute_mission; cancel_execution/abort always bind.
    _meta(
        "arm_execution",
        "Confirm-mode only: arm a Mission's behavior tree and request operator confirmation. Pass the flat Mission id as 'mission_id'. This does NOT start the vehicle — it opens a bounded confirm window; the run starts only when the operator confirms via the on-screen banner ([Play]) before it expires. Arming authorizes exactly one run. Use this when the operator has asked to run/play a mission and the system is in Confirm mode. Tell the operator the vehicle is awaiting their confirmation, not that it is running. 'cancel_execution' drops an armed/awaiting run; 'abort'/'cancel_execution' stop a run once started.",
        EXECUTION,
        ToolRegistry._arm_execution,
        side_effects=frozenset({"drives_vehicle"}),
        inputs={"mission_id": "string — durable flat Mission id"},
        required_inputs=("mission_id",),
        upstream_from_tools=("propose_mission_draft or create_mission_from_waypoints (mission_id)",),
        returns={"ok": "boolean", "armed": "boolean", "expires_at": "string?", "error": "string?"},
        next_tools=("cancel_execution", "control_mission"),
    ),
    _meta(
        "execute_mission",
        "Autonomous-mode only: run a Mission's behavior tree on the vehicle immediately. Pass the flat Mission id as 'mission_id'. The behavior tree is flattened to navigable segments and driven through the controller adapter on the server. Returns once started; the run continues asynchronously and can be stopped with 'abort'/'cancel_execution'.",
        EXECUTION,
        ToolRegistry._execute_mission,
        side_effects=frozenset({"drives_vehicle"}),
        inputs={"mission_id": "string — durable flat Mission id"},
        required_inputs=("mission_id",),
        upstream_from_tools=("propose_mission_draft or create_mission_from_waypoints (mission_id)",),
        returns={"ok": "boolean", "error": "string?"},
        next_tools=("abort", "cancel_execution", "control_mission"),
    ),
    _meta(
        "cancel_execution",
        "Stop a pending or running mission for this session. For an armed/awaiting-confirm run (Confirm mode before the operator confirms) this cancels it so a later banner confirm cannot still start it; for a run already executing it cooperatively aborts the behavior tree between node steps. Always available regardless of execution mode. Returns the execution status snapshot.",
        EXECUTION,
        ToolRegistry._cancel_execution,
        upstream_from_tools=("arm_execution or execute_mission (active run)",),
        returns={"ok": "boolean", "error": "string?"},
    ),
    _meta(
        "abort",
        "Immediately abort the mission currently executing for this session. Cooperatively stops the running behavior tree at the next node-step boundary. Always available regardless of execution mode. Use this as the emergency-stop for AI-driven execution.",
        EXECUTION,
        ToolRegistry._abort_execution,
        upstream_from_tools=("execute_mission (active run)",),
        returns={"ok": "boolean", "error": "string?"},
    ),
    # ── Mission-keyed pause / resume / stop (B.4) ────────────────────
    # Works on any active execution regardless of who started it
    # (operator via sidebar or AI via execute_mission). Does NOT
    # require a session-owned execution — only a mission_id.
    _meta(
        "control_mission",
        "Pause, resume, or stop a running mission by its mission id. "
        "action must be one of: 'pause' (park at FC level until resumed), "
        "'resume' (continue after a pause), or 'stop' (cooperatively halt "
        "the behavior tree at the next node-step boundary). Works whether "
        "the mission was started by the operator (sidebar) or by AI "
        "(execute_mission). Use resolve_mission_reference first if you only "
        "have a name or index, not the id.",
        EXECUTION,
        ToolRegistry._control_mission_execution,
        inputs={
            "action": "string (pause|resume|stop) — non-emergency execution control; use abort for emergency stop",
            "mission_id": "string — durable flat Mission id of the running execution",
        },
        required_inputs=("action", "mission_id"),
        upstream_from_tools=("get_current_mission_state (active mission_id and status)",),
        returns={"ok": "boolean", "error": "string?"},
        next_tools=("get_current_mission_state",),
    ),
    # ── Session adapter override (Phase E) ────────────────────────────
    _meta(
        "set_session_adapter",
        "Override the FC adapter used for mission execution in this chat session only. "
        "adapter_type must be one of: 'file_sink' (write uploads to data/fc_sink/), "
        "'json_file' (default dev adapter), 'mavlink' (real FC via MAVLink, uses configured URL), "
        "'mavsdk' (real FC via MAVSDK, uses configured URL), or 'default' (clear override — revert to global config adapter). "
        "The override is session-scoped: it reverts automatically when the session ends and never changes the persisted config.",
        EXECUTION,
        ToolRegistry._set_session_adapter,
        inputs={"adapter_type": "string (file_sink|json_file|mavlink|mavsdk|default)"},
        required_inputs=("adapter_type",),
        returns={"ok": "boolean", "adapter": "string", "note": "string?"},
    ),
]}

