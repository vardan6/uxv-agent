from __future__ import annotations

from ai.controller_mission_adapter import JsonFileControllerMissionAdapter
from ai.mission_execution_service import MissionExecutionService
from ai.mission_repository import MissionRepository


def test_read_apis_degrade_cleanly_when_legacy_tables_are_absent(tmp_path) -> None:
    service = MissionExecutionService(
        tmp_path / "ai.sqlite3",
        controller_adapter=JsonFileControllerMissionAdapter(tmp_path / "controller.json"),
    )

    assert service.get_revision("missing") is None
    assert service.list_revisions(limit=5) == []

    mission_state = service.get_current_mission_state(session_id="session-1")
    assert mission_state["active"] is False
    assert mission_state["status"] == "no_active_mission"

    controller_state = service.get_controller_state()
    assert controller_state["available"] is True
    assert controller_state["status"] == "idle"
    assert controller_state["controller_version"] == 0


def test_read_apis_project_flat_missions_when_legacy_tables_are_absent(tmp_path) -> None:
    db_path = tmp_path / "ai.sqlite3"
    repo = MissionRepository(db_path)
    created = repo.create(
        name="North loop",
        origin="ai_chat",
        origin_chat_id="session-123",
        mission_json={
            "goal": "Inspect the north loop",
            "waypoints": [
                {"x": 1, "y": 2, "z": 0, "label": "Start"},
                {"x": 3, "y": 4, "z": 0, "label": "Finish"},
            ],
        },
    )
    service = MissionExecutionService(
        db_path,
        controller_adapter=JsonFileControllerMissionAdapter(tmp_path / "controller.json"),
    )

    revisions = service.list_revisions(session_id="session-123", limit=5)

    assert len(revisions) == 1
    revision = revisions[0]
    assert revision["id"] == str(created.id)
    assert revision["operation_id"] == str(created.id)
    assert revision["goal"] == "Inspect the north loop"
    assert revision["name"] == "North loop"
    assert revision["status"] == "stored"
    assert revision["mission"]["goal"] == "Inspect the north loop"

    fetched = service.get_revision(str(created.id))
    assert fetched is not None
    assert fetched["id"] == str(created.id)

    state = service.get_current_mission_state(session_id="session-123")
    assert state["revision_id"] == str(created.id)
    assert state["goal"] == "Inspect the north loop"
    assert state["waypoint_count"] == 2

    overlay = service.get_revision_overlay(revision_id=str(created.id))
    assert overlay["available"] is True
    assert overlay["revision_id"] == str(created.id)
    assert overlay["waypoint_count"] == 2
