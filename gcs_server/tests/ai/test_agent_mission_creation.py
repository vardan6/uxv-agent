from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from ai.agent_loop import _draft_proposed_message
from ai.chat_service import AGENT_SYSTEM_PROMPT
from ai.migrations import apply_ai_store_migrations
from ai.mission_execution_service import MissionExecutionService
from ai.mission_store import MissionStore
from scene_map import get_scene_map_payload
from ai.tool_registry import (
    ToolInvocationContext,
    ToolRegistry,
    allowed_tool_names_for_source_controls,
    _sample_scene_ground_height,
)


def _context(runtime: object, *, run_mode: str) -> ToolInvocationContext:
    return ToolInvocationContext(
        runtime=runtime,
        context_snapshot={},
        timezone_name="",
        permissions=frozenset(),
        source_controls={},
        session_id="chat-1",
        user_id="operator-1",
        run_mode=run_mode,
    )


def _draft() -> dict:
    return {
        "goal": "Go around plant A and return",
        "waypoints": [
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 10.0, "y": 5.0, "z": 0.0},
            {"x": 0.0, "y": 0.0, "z": 0.0},
        ],
        "steps": [],
        "constraints": [],
        "assumptions": [],
        "risks": [],
    }


def test_agent_mode_exposes_mission_creation_tools() -> None:
    allowed = allowed_tool_names_for_source_controls({})

    assert "parse_rover_intent" in allowed
    assert "create_mission_from_waypoints" in allowed
    assert "propose_mission_draft" in allowed
    assert "resolve_mission_reference" in allowed
    assert "prose alone does not create a Mission" in AGENT_SYSTEM_PROMPT


def test_agent_proposal_creates_durable_mission_and_revision(tmp_path) -> None:
    db_path = tmp_path / "ai.sqlite3"
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    mission_store = MissionStore(db_path)
    mission_execution = MissionExecutionService(db_path)
    runtime = SimpleNamespace(
        config=SimpleNamespace(simulation={"backend": "3d-env"}),
        mission_store=mission_store,
        mission_execution_service=mission_execution,
    )

    result = ToolRegistry()._propose_mission_draft(
        _context(runtime, run_mode="agent"),
        intent={"intent_type": "navigate", "requires_rover_motion": False},
        draft=_draft(),
    )

    assert result["ok"] is True
    assert result["mission_id"]
    mission = mission_store.get_mission(result["mission_id"])
    assert mission is not None
    assert mission["name"] == "Go around plant A and return"
    assert mission["origin"] == "ai_chat"
    assert mission["origin_chat_id"] == "chat-1"
    assert mission["active_operation_id"] == result["mission_operation_id"]
    revision = mission_execution.get_revision(result["mission_revision_id"])
    assert revision is not None
    assert revision["status"] == "exported"
    assert isinstance(revision["mission"].get("mission_export"), dict)
    assert revision["mission"]["mission_export"].get("file_path")
    assert len(revision["mission"]["waypoints"]) == 3


def test_planner_proposal_remains_unpersisted_until_store_node() -> None:
    result = ToolRegistry()._propose_mission_draft(
        _context(SimpleNamespace(), run_mode="planner"),
        intent={"intent_type": "navigate"},
        draft=_draft(),
    )

    assert result["ok"] is True
    assert "mission_id" not in result


def test_terminal_agent_result_keeps_human_readable_text() -> None:
    text = _draft_proposed_message([
        {
            "name": "propose_mission_draft",
            "result": {
                "ok": True,
                "mission_id": "mission-1",
                "mission": {"mission_index": 7, "name": "Plant A loop"},
                "draft": _draft(),
            },
        }
    ])

    assert 'Created mission #7 "Plant A loop" with 3 waypoints.' in text
    assert "map and in the mission sidebar" in text


def test_agent_creates_mission_from_supplied_waypoints(tmp_path) -> None:
    db_path = tmp_path / "ai.sqlite3"
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    mission_store = MissionStore(db_path)
    mission_execution = MissionExecutionService(db_path)
    runtime = SimpleNamespace(
        config=SimpleNamespace(simulation={"backend": "3d-env"}),
        mission_store=mission_store,
        mission_execution_service=mission_execution,
    )
    result = ToolRegistry()._create_mission_from_waypoints(
        _context(runtime, run_mode="agent"),
        waypoints=[
            {"x": 75.0, "y": 56.0, "z": -4.6},
            {"x": 75.0, "y": 82.0, "z": -4.6},
            {"x": 75.0, "y": 56.0, "z": -4.6},
        ],
        goal="Imported loop route",
        route_metadata={
            "waypoint_count": 3,
            "path_length_m": 52.0,
            "route_hash": "example-hash",
        },
    )

    assert result["ok"] is True
    assert result["mission_id"]
    assert result["draft"]["route_metadata"] == {
        "waypoint_count": 3,
        "source": "operator_supplied_waypoints",
        "path_length_m": 52.0,
        "route_hash": "example-hash",
    }
    revision = mission_execution.get_revision(result["mission_revision_id"])
    assert revision is not None
    assert revision["status"] == "exported"
    assert isinstance(revision["mission"].get("mission_export"), dict)
    assert revision["mission"]["mission_export"].get("file_path")
    assert len(revision["mission"]["waypoints"]) == 3
    assert revision["mission"]["waypoints"][0]["z"] == -4.6
    assert abs(revision["mission"]["waypoints"][-1]["x"] - 75.0) < 1e-6


def test_supplied_waypoints_reject_declared_count_mismatch() -> None:
    result = ToolRegistry()._create_mission_from_waypoints(
        _context(SimpleNamespace(), run_mode="agent"),
        waypoints=[{"x": 1, "y": 2, "z": 3}],
        route_metadata={"waypoint_count": 2},
    )

    assert result["ok"] is False
    assert result["declared_waypoint_count"] == 2
    assert result["supplied_waypoint_count"] == 1


def test_agent_creates_mission_from_supplied_waypoints_without_z_by_sampling_ground(tmp_path) -> None:
    db_path = tmp_path / "ai.sqlite3"
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    mission_store = MissionStore(db_path)
    mission_execution = MissionExecutionService(db_path)
    runtime = SimpleNamespace(
        config=SimpleNamespace(simulation={"backend": "3d-env"}),
        mission_store=mission_store,
        mission_execution_service=mission_execution,
    )
    context = _context(runtime, run_mode="agent")
    registry = ToolRegistry()

    result = registry._create_mission_from_waypoints(
        context,
        waypoints=[
            {"x": 44.0, "y": 34.0},
            {"x": 60.0, "y": 40.0},
        ],
        goal="Ground-following route",
    )

    assert result["ok"] is True
    revision = mission_execution.get_revision(result["mission_revision_id"])
    assert revision is not None
    stored = revision["mission"]["waypoints"]
    scene = get_scene_map_payload(grid_size=32)
    assert stored[0]["z"] == _sample_scene_ground_height(scene, 44.0, 34.0)
    assert stored[1]["z"] == _sample_scene_ground_height(scene, 60.0, 40.0)
