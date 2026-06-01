from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import json
import re as _re

try:
    from gcs_server.ai.context_service import AIContextService
    from gcs_server.ai.data_access import build_data_access_manifest
    from gcs_server.ai.intent_service import IntentService as _IntentService
    from gcs_server.ai.mission_draft_service import MissionDraftService
    from gcs_server.ai.mission_execution_session import build_mission_executor
    from gcs_server.ai.mission_export_service import MissionExportService
    from gcs_server.ai import mission_patterns
    from gcs_server.ai.mission_tree import MissionTreeError, flatten_navigable_segments, parse_tree
    from gcs_server.ai.provider_registry import resolve_intent_provider as _resolve_intent_provider
    from gcs_server.ai.provider_registry import resolve_provider as _resolve_provider
    from gcs_server.ai.road_graph_service import RoadGraphService
    from gcs_server.ai.session_store import normalize_source_controls
    from gcs_server.ai.spatial_query_service import SpatialQueryService
    from gcs_server.ai.vehicle_profile import get_active_profile
except ModuleNotFoundError:
    from ai.context_service import AIContextService
    from ai.data_access import build_data_access_manifest
    from ai.intent_service import IntentService as _IntentService
    from ai.mission_draft_service import MissionDraftService
    from ai.mission_execution_session import build_mission_executor
    from ai.mission_export_service import MissionExportService
    from ai import mission_patterns
    from ai.mission_tree import MissionTreeError, flatten_navigable_segments, parse_tree
    from ai.provider_registry import resolve_intent_provider as _resolve_intent_provider
    from ai.provider_registry import resolve_provider as _resolve_provider
    from ai.road_graph_service import RoadGraphService
    from ai.session_store import normalize_source_controls
    from ai.spatial_query_service import SpatialQueryService
    from ai.vehicle_profile import get_active_profile


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
    required_scopes: frozenset[str]
    side_effects: frozenset[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    contract: dict[str, Any] = field(default_factory=dict)
    is_terminal: bool = False


@dataclass(frozen=True)
class ToolInvocationContext:
    runtime: Any
    context_snapshot: dict[str, Any]
    timezone_name: str
    permissions: frozenset[str]
    source_controls: dict[str, bool]
    session_id: str
    user_id: str


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
    "plan_route_around_group",
    "plan_route_between",
    "generate_pattern_subtree",
    "set_mission_geofence",
    "export_mission",
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
        self._road_graph = RoadGraphService()
        self._exporter = MissionExportService()
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
            is_terminal: bool = False,
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
                is_terminal=is_terminal,
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
                "Get one safe settings section by name. Supported sections are `mqtt`, `key_bindings`, `video`, `gcs`, `simulation`, `map`, `mission_lifecycle`, `ai_settings`, and `settings_path`. Call `get_settings_summary` first if you need section discovery or a compact overview. This tool never exposes secrets.",
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
            tool(
                "plan_route_around_group",
                "Use when the operator asks the vehicle to traverse a named area — drive around a plantation, patrol a zone, or cover all roads in a group. Computes a route from the rover's current position to the group, traverses every road edge in the group at least once (Chinese-Postman), and returns to the start. Returns a compact route summary (waypoint_count, total_distance_m, legs) and the full waypoints list for the draft. NOTE: the returned route_hash is only a waypoint fingerprint, NOT a draft_id — do not pass it to export_mission. Next step is propose_mission_draft with these waypoints to create a draft; then export_mission(draft_id) after approval. Does not upload to the flight controller.",
                PLANNING,
                self._plan_route_around_group,
            ),
            tool(
                "plan_route_between",
                "Use when the operator asks the vehicle to drive from one resolved target to another — 'drive to charger 1', 'go to the second plantation entrance'. Resolves both targets via resolve_spatial_target, snaps to the road graph, and runs Dijkstra. Returns a compact route summary and full waypoints. NOTE: the returned route_hash is only a waypoint fingerprint, NOT a draft_id — do not pass it to export_mission. Next step is propose_mission_draft with these waypoints to create a draft; then export_mission(draft_id) after approval. Does not upload.",
                PLANNING,
                self._plan_route_between,
            ),
            tool(
                "generate_pattern_subtree",
                "Use when the operator asks the vehicle to follow a path repeatedly or to systematically cover an area, instead of hand-listing waypoints. 'corridor' densifies an ordered polyline into evenly-spaced waypoints (optionally back-and-forth for multiple passes); 'survey' fills a rectangle with a lawnmower (boustrophedon) sweep. Pass 'pattern' ('corridor'|'survey') and 'params' in local scene metres (x=east, y=north, z=up). corridor params: path (list of {x,y}, >=2), spacing_m, altitude_m, optional passes. survey params: width_m, height_m, line_spacing_m, altitude_m, optional origin_xy ({x,y}) and heading_deg. Returns a navigation subtree as 'tree' (a nav_leaf, or a sequence of nav_leaf passes) plus waypoint_count — set it as the draft's 'tree' (or splice it into a larger tree) in propose_mission_draft. Does not upload; pair with export_mission after approval.",
                PLANNING,
                self._generate_pattern_subtree,
            ),
            tool(
                "set_mission_geofence",
                "Use when the operator wants to fence a mission to a safe area — 'keep it inside this boundary', 'add a geofence', or 'clear the fence'. Sets an inclusion geofence on an existing flat Mission (by mission_id): waypoints must stay inside the polygon, and the flight controller enforces it authoritatively while the executor also refuses any breaching mission before driving. Pass 'mission_id' and 'polygon' as a list of at least three {lat, lon} WGS84 vertices (the stored truth); optional 'rally_points' (list of {lat, lon, alt}) are safe-return points, and optional 'min_alt'/'max_alt' bound altitude in metres. Pass clear=true to remove the fence. Appends a new (approval-required) revision; does not upload by itself — the fence uploads to the FC when the mission is armed/executed.",
                PLANNING,
                self._set_mission_geofence,
            ),
            tool(
                "export_mission",
                "Convert an approved mission draft to a QGC-compatible .plan file saved under data/missions/<draft_id>.plan. The draft_id is the id returned by propose_mission_draft — NOT a route_hash from plan_route_* (those only fingerprint waypoints). Only callable after the operator has approved the draft (approval interrupt resolved positively). If called on an unapproved draft, returns a structured rejection — do not retry until approval is granted. If draft_id is unknown, the result lists available_drafts for this session. Returns file_path, waypoint_count, and the plan structure.",
                PLANNING,
                self._export_mission,
                side_effects=frozenset({"writes_file"}),
            ),
            # ── Planner loop tools (Phase 5) ──────────────────────────────────
            tool(
                "parse_rover_intent",
                "Parse the operator's mission request into a structured RoverIntent. Call this first in the planner loop to extract intent_type, target, requested_actions, constraints, and missing_information. Pass the original user prompt and the compact context_summary from retrieve_initial_context.",
                READ_ONLY,
                self._parse_rover_intent,
            ),
            tool(
                "lazy_load_replay",
                "Load the active replay session summary for the current request. Returns replay_summary with the most recent session metadata. Call this when the operator's request references prior missions, replay sessions, or recorded data. Available only when replay_reports source control is enabled.",
                READ_ONLY,
                self._lazy_load_replay,
            ),
            tool(
                "lazy_load_ai_memory",
                "Load the AI chat history summary for the current session. Returns chat_history_summary with a bounded view of recent AI conversation context. Call this when the operator references earlier discussions or prior planning sessions.",
                READ_ONLY,
                self._lazy_load_ai_memory,
            ),
            tool(
                "lazy_load_settings",
                "Load the GCS settings summary for the current request. Returns settings_summary with safe configuration metadata. Call this when the operator references configuration, provider routing, or enabled capabilities.",
                READ_ONLY,
                self._lazy_load_settings,
            ),
            tool(
                "lazy_load_sensor",
                "Load sensor and telemetry freshness status. Returns telemetry_fresh and camera_fresh flags. Call this when the operator's request depends on live sensor availability or to flag staleness constraints in the mission draft.",
                READ_ONLY,
                self._lazy_load_sensor,
            ),
            tool(
                "request_clarification",
                "Ask the operator for missing information before drafting a mission. Pass the questions list from parse_rover_intent's missing_information field. Calling this tool signals the graph to pause and surface a clarification card to the operator. Only call this once per planning run.",
                READ_ONLY,
                self._request_clarification,
                is_terminal=True,
            ),
            tool(
                "propose_mission_draft",
                "Submit the final mission draft. Terminal planning action — call after parse_rover_intent and optional route-planning tools. Provide a complete 'draft' object (goal, steps, constraints, assumptions, risks) to submit it directly — preferred when route-planning was done so waypoints are preserved. Omit 'draft' to have one generated from 'intent' and 'target_resolution'. Pass route tool outputs as 'route_artifacts' to attach them to the draft. For a structured mission — branching, retries, loops, or operator prompts — set the draft's 'tree' to a behavior tree: nested nodes of type 'sequence'/'fallback'/'loop'/'recovery' (each with 'children'), 'nav_leaf' (a 'waypoints' run that drives the vehicle), 'condition', and 'ask_operator'. Omit 'tree' for a plain linear mission (the flat 'waypoints' list still works). The draft always has execution_allowed=false and required_operator_approval=true. Set 'mission_edit_mode' to choose how the result lands in the operator's Mission list: 'create' (default) for a brand-new mission; 'clone_and_edit' when changing an existing mission — pass its id as 'source_mission_id' — which creates a NEW mission row so the original is preserved for side-by-side comparison (use this for almost all edits); 'edit_in_place' ONLY when the operator explicitly said to edit the existing mission in place — also pass 'source_mission_id', and it mutates that mission instead of cloning.",
                PLANNING,
                self._propose_mission_draft,
                is_terminal=True,
            ),
            tool(
                "resolve_mission_reference",
                "Resolve an operator's reference to an existing Mission into a concrete mission id before editing it. Pass the operator's exact phrasing as 'reference' — an index ('#26', 'mission 26'), a name ('the orchard sweep'), or a pronoun ('it', 'this mission'). Resolution order is index → exact name → fuzzy name → pronoun (most-recent Mission of the current chat). Returns status 'resolved' with the mission (use mission.id as source_mission_id), 'ambiguous' with candidates to disambiguate with the operator, or 'not_found'. Call this before propose_mission_draft with clone_and_edit/edit_in_place when the operator refers to a mission you do not already have an id for.",
                READ_ONLY,
                self._resolve_mission_reference,
            ),
            # ── Execution tools (ADR 0021 §1 / ADR 0023 Phase 3) ──────────────
            # Bound per execution mode by agent_loop: Strict binds neither
            # arm_execution nor execute_mission; Confirm binds arm_execution;
            # Autonomous binds execute_mission; cancel_execution/abort always bind.
            tool(
                "arm_execution",
                "Confirm-mode only: arm an approved Mission's behavior tree and request operator confirmation. Pass the flat Mission id as 'mission_id'. This does NOT start the rover — it opens a bounded confirm window; the run starts only when the operator confirms via the on-screen banner ([Play]) before it expires. Arming authorizes exactly one run. Use this when the operator has asked to run/play a mission and the system is in Confirm mode. Tell the operator the rover is awaiting their confirmation, not that it is running. 'cancel_execution' drops an armed/awaiting run; 'abort'/'cancel_execution' stop a run once started.",
                EXECUTION,
                self._arm_execution,
                side_effects=frozenset({"drives_rover"}),
            ),
            tool(
                "execute_mission",
                "Autonomous-mode only: run an approved Mission's behavior tree on the rover immediately. Pass the flat Mission id as 'mission_id'. The behavior tree is flattened to navigable segments and driven through the controller adapter on the server. Returns once started; the run continues asynchronously and can be stopped with 'abort'/'cancel_execution'.",
                EXECUTION,
                self._execute_mission,
                side_effects=frozenset({"drives_rover"}),
            ),
            tool(
                "cancel_execution",
                "Stop a pending or running mission for this session. For an armed/awaiting-confirm run (Confirm mode before the operator confirms) this cancels it so a later banner confirm cannot still start it; for a run already executing it cooperatively aborts the behavior tree between node steps. Always available regardless of execution mode. Returns the execution status snapshot.",
                EXECUTION,
                self._cancel_execution,
            ),
            tool(
                "abort",
                "Immediately abort the mission currently executing for this session. Cooperatively stops the running behavior tree at the next node-step boundary. Always available regardless of execution mode. Use this as the emergency-stop for AI-driven execution.",
                EXECUTION,
                self._abort_execution,
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
            user_id=_snapshot_user_id(context_snapshot),
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

    def _plan_route_around_group(
        self,
        context: ToolInvocationContext,
        group_id: str,
    ) -> dict[str, Any]:
        rover = self._rover_snapshot(context)
        pos = rover.get("position") or {}
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
        scene = self._scene_payload(context)
        rover = self._rover_snapshot(context)

        if start_target is None or str(start_target or "").strip() in ("", "rover_pose"):
            start_pos = rover.get("position") or {}
            try:
                sx = float(start_pos.get("x") or 0.0)
                sy = float(start_pos.get("y") or 0.0)
            except (TypeError, ValueError):
                return {"ok": False, "error": "rover position unavailable for start_target=None; provide explicit start_target"}
        else:
            resolved = self._spatial.resolve_target_description(scene, rover, _normalize_spatial_target(start_target))
            selected = resolved.get("selected")
            if not selected:
                return {"ok": False, "error": "start_target could not be resolved on the scene map"}
            p = selected.get("position") or {}
            sx, sy = float(p.get("x") or 0.0), float(p.get("y") or 0.0)

        if not goal_target:
            return {"ok": False, "error": "goal_target is required"}
        resolved_goal = self._spatial.resolve_target_description(scene, rover, _normalize_spatial_target(goal_target))
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

    def _export_mission(
        self,
        context: ToolInvocationContext,
        draft_id: str,
    ) -> dict[str, Any]:
        clean_id = str(draft_id or "").strip()
        if not clean_id:
            return {"ok": False, "error": "draft_id is required"}
        store = getattr(context.runtime, "ai_store", None)
        if store is None:
            return {"ok": False, "error": "AI store is not available"}
        draft_service = MissionDraftService(store.db_path)
        draft, recovery = self._resolve_export_draft(
            draft_service, clean_id, session_id=context.session_id
        )
        if draft is None:
            return recovery
        # Auto-bridge may have resolved a different id than the caller passed.
        clean_id = str(draft.get("id") or clean_id)
        profile = get_active_profile()
        rover = self._rover_snapshot(context)
        pos = rover.get("position") or {}
        gps = rover.get("gps") or {}
        home: dict[str, float] | None = None
        if gps.get("lat") and gps.get("lon"):
            home = {
                "latitude": float(gps["lat"]),
                "longitude": float(gps["lon"]),
                "altitude": float(gps.get("alt") or 0.0),
            }
        result = self._exporter.export(draft, profile=profile, home_position=home)
        if result.get("ok"):
            updated = draft_service.mark_exported(clean_id, export_result=result)
            if updated is not None:
                result["draft_status"] = updated.get("status", "")
                result["mission_export"] = (updated.get("draft") or {}).get("mission_export") or {}
            if recovery is not None:
                # Auto-bridge recovered the draft from a non-draft id (e.g. a route_hash).
                result["resolved_via"] = recovery.get("resolved_via")
                result["resolved_draft_id"] = clean_id
        return result

    @staticmethod
    def _looks_like_route_hash(value: str) -> bool:
        """A bare 12-char hex string with no ``draft`` prefix is a route_hash,
        not a draft id. Draft ids are always prefixed (``ai-draft-``,
        ``draft-draw-``, ``draft-fence-``). See :func:`_route_hash`."""
        return bool(_re.fullmatch(r"[0-9a-f]{12}", value or "")) and "draft" not in value

    def _resolve_export_draft(
        self,
        draft_service: "MissionDraftService",
        requested_id: str,
        *,
        session_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Resolve the id passed to ``export_mission`` into a stored draft.

        Returns ``(draft, recovery)``. On a direct hit ``recovery`` is ``None``.
        When the id is not a draft but auto-bridges to a session draft (e.g. the
        planner handed back a ``route_hash`` instead of the ``draft_id``),
        ``recovery`` carries ``resolved_via`` describing the bridge. When nothing
        resolves, ``draft`` is ``None`` and ``recovery`` is a directed error.
        """
        direct = draft_service.get_draft(requested_id)
        if direct is not None:
            return direct, None

        session_drafts = draft_service.list_drafts(session_id=session_id, limit=20)

        # Auto-bridge: a route_hash matches the route_artifacts of a session draft.
        if self._looks_like_route_hash(requested_id):
            for row in session_drafts:
                payload = row.get("draft") or {}
                artifacts = payload.get("route_artifacts") or []
                for art in artifacts:
                    if isinstance(art, dict) and str(art.get("route_hash") or "") == requested_id:
                        return row, {"resolved_via": "route_hash->draft"}

        # No permissive "sole draft" fallback: a route_hash miss must surface the
        # directed error below rather than silently exporting an unrelated draft
        # (ADR 0022/0023 pre-merge safety). Only an exact draft_id or an exact
        # route_hash->artifact match writes a .plan.
        available = [
            {"draft_id": r.get("id"), "status": r.get("status")}
            for r in session_drafts
        ]
        if self._looks_like_route_hash(requested_id):
            hint = (
                f"'{requested_id}' is a route_hash, not a draft_id. A route_hash only "
                "fingerprints waypoints — it is not a persisted draft. Call "
                "propose_mission_draft with the route waypoints first to create a draft, "
                "get it approved, then call export_mission with the returned draft_id."
            )
        else:
            hint = (
                f"draft '{requested_id}' not found. Create one with propose_mission_draft "
                "(get it approved), then export it with the returned draft_id."
            )
        return None, {
            "ok": False,
            "error": hint,
            "next_tool": "propose_mission_draft",
            "available_drafts": available,
        }

    # ── Planner loop handlers (Phase 5) ───────────────────────────────────────

    def _parse_rover_intent(
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
        rover = context.context_snapshot.get("rover") or {}
        return {
            "ok": True,
            "telemetry_fresh": rover.get("telemetry_fresh"),
            "camera_fresh": rover.get("camera_fresh"),
            "available": bool(rover),
        }

    def _request_clarification(
        self,
        context: ToolInvocationContext,
        questions: list,
        intent_summary: str = "",
    ) -> dict[str, Any]:
        # Terminal tool: returning a handoff causes the agent loop to stop with
        # stop_reason="clarification_requested". The graph routes to prepare_clarification,
        # which surfaces the card to the operator via interrupt() and then bridges to the
        # legacy draft generation path on resume.
        return {
            "ok": True,
            "handoff": {
                "type": "clarification_request",
                "questions": list(questions or []),
                "intent_summary": str(intent_summary or ""),
            },
        }

    def _propose_mission_draft(
        self,
        context: ToolInvocationContext,
        intent: dict,
        target_resolution: dict | None = None,
        rover_position: dict | None = None,
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
            return {
                "ok": True,
                "draft": normalized,
                "repairs": repairs,
                "source": "planner_submitted",
                "parent_operation_id": parent_op,
                "mission_edit_mode": edit_mode,
                "source_mission_id": source_mission,
            }

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
            rover_position or {},
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
        return {"ok": True, "draft": normalized, "repairs": repairs, "source": "llm_generated", "parent_operation_id": parent_op, "mission_edit_mode": edit_mode, "source_mission_id": source_mission}

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
        try:
            executor, root = build_mission_executor(context.runtime, content)
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


def _resolve_confirm_timeout_s(runtime: Any) -> int:
    """Confirm-banner timeout from the persisted mission_lifecycle setting,
    clamped to [3, 60] s (ADR 0021 §6); falls back to the default when unset."""
    try:
        from gcs_server.ai.execution_mode import normalize_confirm_timeout
    except ModuleNotFoundError:
        from ai.execution_mode import normalize_confirm_timeout
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


def _planner_draft_prompt(intent: dict, target_resolution: dict, rover_position: dict) -> str:
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
    if rover_position:
        parts.append(f"Current rover position: {json.dumps(rover_position)}")
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
        is_terminal=definition.is_terminal,
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
    "plan_route_around_group": {
        "inputs": {"group_id": "string — one of known_groups; e.g. 'plant_a', 'plant_b', 'connector', 'building', 'start_hub'"},
        "required_inputs": ["group_id"],
        "upstream_from_tools": ["get_current_rover_state (rover position for transit legs)", "get_scene_summary (to discover group names)"],
        "returns": {"ok": "boolean", "waypoint_count": "integer", "total_distance_m": "number", "legs": "leg[]", "waypoints": "waypoint[]", "route_hash": "string (waypoint fingerprint, NOT a draft_id)", "known_groups": "string[]"},
        "next_tools": ["propose_mission_draft (with waypoints) -> export_mission (after approval)"],
    },
    "plan_route_between": {
        "inputs": {"start_target": "string | object | null (null = rover current pose)", "goal_target": "string | object"},
        "required_inputs": ["goal_target"],
        "upstream_from_tools": ["get_current_rover_state (when start_target is null)", "resolve_spatial_target (to resolve start/goal targets)"],
        "returns": {"ok": "boolean", "waypoint_count": "integer", "total_distance_m": "number", "waypoints": "waypoint[]", "route_hash": "string (waypoint fingerprint, NOT a draft_id)"},
        "next_tools": ["propose_mission_draft (with waypoints) -> export_mission (after approval)"],
    },
    "export_mission": {
        "inputs": {"draft_id": "string — the draft_id returned by propose_mission_draft (NOT a route_hash)"},
        "required_inputs": ["draft_id"],
        "upstream_from_tools": ["plan_route_around_group or plan_route_between (to populate draft waypoints)", "approval interrupt (draft must be approved before calling)"],
        "returns": {"ok": "boolean", "file_path": "string", "waypoint_count": "integer", "vehicle_type": "integer", "plan": "object"},
        "next_tools": [],
    },
    "parse_rover_intent": {
        "inputs": {
            "prompt": "string — original operator mission request",
            "context_summary": "string — compact planning context summary (optional)",
        },
        "required_inputs": ["prompt"],
        "upstream_from_tools": ["operator mission request", "planning-shell context summary"],
        "returns": {"ok": "boolean", "intent": "object", "parse_errors": "string[]"},
        "next_tools": [
            "lazy_load_replay",
            "lazy_load_ai_memory",
            "lazy_load_settings",
            "lazy_load_sensor",
            "resolve_spatial_target",
            "request_clarification",
            "propose_mission_draft",
        ],
    },
    "lazy_load_replay": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["source_controls.replay_reports", "parse_rover_intent (when the request references prior missions or recorded data)"],
        "returns": {"ok": "boolean", "replay_summary": "object", "available": "boolean"},
        "next_tools": ["propose_mission_draft"],
    },
    "lazy_load_ai_memory": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["source_controls.ai_chat_history", "parse_rover_intent (when the request references earlier discussions)"],
        "returns": {"ok": "boolean", "chat_history_summary": "object", "available": "boolean"},
        "next_tools": ["propose_mission_draft"],
    },
    "lazy_load_settings": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["source_controls.settings_config", "parse_rover_intent (when the request depends on configuration or provider routing)"],
        "returns": {"ok": "boolean", "settings_summary": "object", "available": "boolean"},
        "next_tools": ["propose_mission_draft"],
    },
    "lazy_load_sensor": {
        "inputs": {},
        "required_inputs": [],
        "upstream_from_tools": ["source_controls.sensor_context", "parse_rover_intent (when the request depends on live telemetry or camera freshness)"],
        "returns": {
            "ok": "boolean",
            "telemetry_fresh": "boolean | null",
            "camera_fresh": "boolean | null",
            "available": "boolean",
        },
        "next_tools": ["propose_mission_draft"],
    },
    "request_clarification": {
        "inputs": {
            "questions": "object[] — clarification prompts derived from parse_rover_intent.missing_information",
            "intent_summary": "string — compact explanation of the blocked intent (optional)",
        },
        "required_inputs": ["questions"],
        "upstream_from_tools": ["parse_rover_intent.missing_information"],
        "returns": {"ok": "boolean", "handoff": "object{type,questions,intent_summary}"},
        "next_tools": [],
    },
    "propose_mission_draft": {
        "inputs": {
            "intent": "object — from parse_rover_intent.intent",
            "target_resolution": "object — from resolve_spatial_target (optional)",
            "rover_position": "object — rover position override (optional)",
            "draft": "object — complete draft to submit directly; preferred when route-planning was done (optional)",
            "route_artifacts": "object[] — route artifacts from plan_route_* tools (optional)",
        },
        "required_inputs": ["intent"],
        "upstream_from_tools": ["parse_rover_intent", "resolve_spatial_target (optional)", "plan_route_around_group or plan_route_between (optional)"],
        "returns": {"ok": "boolean", "draft": "mission_draft", "repairs": "string[]", "source": "planner_submitted|llm_generated"},
        "next_tools": [],
    },
}
