from __future__ import annotations

from ai.controller_mission_adapter import JsonFileControllerMissionAdapter
from ai.mission_execution_service import MissionExecutionService


def _service(tmp_path):
    return MissionExecutionService(
        tmp_path / "ai.sqlite3",
        controller_adapter=JsonFileControllerMissionAdapter(tmp_path / "controller.json"),
    )


def _mission_json() -> dict:
    return {
        "goal": "Inspect the north loop",
        "waypoints": [
            {"x": 1, "y": 2, "z": 0, "label": "Start"},
            {"x": 3, "y": 4, "z": 0, "label": "Finish"},
        ],
    }


def test_get_controller_state_reports_idle_json_adapter(tmp_path) -> None:
    service = _service(tmp_path)

    controller_state = service.get_controller_state()

    assert controller_state["available"] is True
    assert controller_state["status"] == "idle"
    assert controller_state["controller_version"] == 0
    assert controller_state["adapter"] == "json_file_controller"
    assert controller_state["verified_snapshot"] == {}


def test_execute_mission_by_id_installs_mission_and_returns_controller_state(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.execute_mission_by_id(
        mission_id=42,
        mission_json=_mission_json(),
        expected_controller_version=0,
    )

    assert result["ok"] is True
    assert result["status"] == "executing"
    assert result["mission_id"] == 42
    assert result["adapter_result"]["verified"] is True

    controller_state = result["controller_state"]
    assert controller_state["status"] == "executing"
    assert controller_state["controller_version"] == 1
    assert controller_state["active_draft_id"] == "mission-42"
    assert controller_state["active_mission_id"] == ""
    snapshot = controller_state["verified_snapshot"]
    assert snapshot["mission"]["goal"] == "Inspect the north loop"
    assert snapshot["mission_export"]["waypoint_count"] == 2


def test_arm_execution_by_id_maps_success_status_to_armed(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.arm_execution_by_id(
        mission_id=7,
        mission_json=_mission_json(),
        expected_controller_version=0,
    )

    assert result["ok"] is True
    assert result["status"] == "armed"
    assert result["controller_state"]["status"] == "executing"


def test_cancel_execution_by_id_clears_controller_snapshot(tmp_path) -> None:
    service = _service(tmp_path)
    execute = service.execute_mission_by_id(
        mission_id=3,
        mission_json=_mission_json(),
        expected_controller_version=0,
    )

    result = service.cancel_execution_by_id(
        mode="clear",
        expected_controller_version=execute["controller_state"]["controller_version"],
    )

    assert result["ok"] is True
    assert result["status"] == "cancelled"
    assert result["cancel_mode"] == "clear"

    controller_state = result["controller_state"]
    assert controller_state["status"] == "cancelled"
    assert controller_state["controller_version"] == 2
    assert controller_state["active_mission_id"] == ""
    assert controller_state["verified_snapshot"] == {}
