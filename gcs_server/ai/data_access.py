from __future__ import annotations

from typing import Any


def build_data_access_manifest(tool_definitions: list[Any], *, allowed_tool_names: set[str] | None = None) -> dict[str, Any]:
    allowed = set(allowed_tool_names or [])
    restrict = allowed_tool_names is not None
    tool_by_name = {
        str(getattr(definition, "name", "")).strip(): definition
        for definition in tool_definitions
        if str(getattr(definition, "name", "")).strip()
    }

    def _tool_entry(name: str) -> dict[str, Any] | None:
        definition = tool_by_name.get(name)
        if definition is None:
            return None
        enabled = not restrict or name in allowed
        return {
            "name": definition.name,
            "permission": definition.permission,
            "tier": int(getattr(definition, "tier", 0)),
            "required_scopes": sorted(str(item) for item in getattr(definition, "required_scopes", ()) or ()),
            "side_effects": sorted(str(item) for item in getattr(definition, "side_effects", ()) or ()),
            "enabled": enabled,
        }

    def _surface(name: str, description: str, access: str, tool_names: list[str], initial_context: str) -> dict[str, Any]:
        entries = [entry for entry in (_tool_entry(tool_name) for tool_name in tool_names) if entry is not None]
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

    return {
        "data_surfaces": [
            _surface(
                "system_capabilities",
                "Discovery of available bounded data surfaces and source-control gating for this session.",
                "tool",
                ["list_data_surfaces"],
                "manifest_only",
            ),
            _surface(
                "current_rover_state",
                "Latest telemetry snapshot and freshness metadata.",
                "tool",
                ["get_current_rover_state"],
                "summary",
            ),
            _surface(
                "terrain_scene",
                "Terrain/map objects and deterministic spatial geometry.",
                "tool",
                [
                    "get_scene_summary",
                    "query_objects_in_front",
                    "query_objects_near",
                    "query_objects_by_kind",
                    "query_objects_to_left",
                    "query_objects_to_right",
                    "query_nearest_objects",
                    "resolve_spatial_target",
                ],
                "scene_summary_only",
            ),
            _surface(
                "mission_state",
                "Current mission placeholder and mission-related state available to read-only AI flows.",
                "tool",
                ["get_current_mission_state"],
                "summary",
            ),
            _surface(
                "replay_sessions",
                "Recorded sessions, telemetry, events, paths, and metrics.",
                "tool",
                [
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
                ],
                "active_session_summary_only",
            ),
            _surface(
                "ai_chat_history",
                "Saved AI chat sessions and messages.",
                "tool",
                ["list_ai_sessions", "search_ai_messages", "get_ai_session_messages"],
                "lazy_recent_session_summary",
            ),
            _surface(
                "settings",
                "Safe GCS settings sections plus LLM provider and routing metadata.",
                "tool",
                ["get_settings_summary", "get_settings_section", "get_llm_provider_summary"],
                "safe_summary_only",
            ),
            _surface(
                "video_perception",
                "Metadata-only sensor/video status for the current runtime; raw frames and detections remain unavailable in this phase.",
                "tool",
                ["get_sensor_status"],
                "video_metadata_only",
            ),
            _surface(
                "route_planning",
                "Road-graph route planning and QGC mission export. Compute drivable routes over the terrain road network and export approved drafts as .plan files.",
                "tool",
                [
                    "plan_route_around_group",
                    "plan_route_between",
                    "export_mission",
                ],
                "manifest_only",
            ),
        ]
    }
