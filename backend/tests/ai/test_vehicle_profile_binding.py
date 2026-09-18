"""R3: the active profile reaches the services, and revisions stay vehicle-bound.

Vehicle-bound revisions are specified in
`docs/components/ai-agent/requirements.md` §Vehicle-bound revisions and
`design.md` §Mission authoring: a saved mission keeps the profile it was
authored against, and dispatch refuses when a different profile is active.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai.controller_mission_adapter import ControllerMissionAdapterState, ControllerMissionInstallResult
from ai.mission_execution_service import MissionExecutionService
from ai.mission_export_service import MissionExportService
from ai.vehicle_profile import KNOWN_PROFILES, QUAD_X500, ROVER_DEFAULT


class _SuccessfulInstallAdapter:
    adapter_name = "successful_install"

    def __init__(self) -> None:
        self.installs: list[dict] = []

    def get_controller_state(self) -> ControllerMissionAdapterState:
        return ControllerMissionAdapterState(controller_version=0, status="idle")

    def install_mission(self, *, pending_snapshot: dict, expected_controller_version: int | None = None):
        self.installs.append(dict(pending_snapshot))
        return ControllerMissionInstallResult(
            ok=True,
            status="executing",
            controller_state=ControllerMissionAdapterState(
                controller_version=1,
                status="executing",
                operation_id=str(pending_snapshot.get("operation_id") or ""),
                revision_id=str(pending_snapshot.get("revision_id") or ""),
                draft_id=str(pending_snapshot.get("draft_id") or ""),
                mission_export=dict(pending_snapshot.get("mission_export") or {}),
                mission=dict(pending_snapshot.get("mission") or {}),
                plan=dict(pending_snapshot.get("plan") or {}),
            ),
        )


class _MutableSelection:
    """Stands in for the settings-backed resolver the app wires in."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id

    def __call__(self):
        return KNOWN_PROFILES[self.profile_id]


def _make_service(db_path: Path, selection: _MutableSelection, adapter=None) -> MissionExecutionService:
    return MissionExecutionService(
        db_path,
        controller_adapter=adapter,
        profile_resolver=selection,
    )


def _make_proposal(svc: MissionExecutionService, *, n_waypoints: int = 2) -> dict:
    return svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-1",
        draft_id="draft-1",
        intent={},
        target_resolution={},
        draft_payload={
            "goal": "test mission",
            "waypoints": [{"x": float(i), "y": float(i), "z": 0.0} for i in range(n_waypoints)],
            "steps": [],
            "constraints": [],
            "assumptions": [],
        },
        validation={},
        draft_status="proposed",
    )


def test_exporter_reads_the_injected_resolver(tmp_path: Path) -> None:
    selection = _MutableSelection("quad_x500")
    svc = MissionExportService(missions_dir=tmp_path, profile_resolver=selection)

    result = svc.export({"id": "draft-x", "draft": {"waypoints": [{"x": 1.0, "y": 2.0, "z": 0.0}]}})

    assert result["ok"] is True
    assert result["vehicle_type"] == QUAD_X500.mav_vehicle_type

    # A selection change is picked up per call, without rebuilding the service.
    selection.profile_id = "rover_default"
    assert svc.export({"id": "draft-y", "draft": {"waypoints": [{"x": 1.0, "y": 2.0, "z": 0.0}]}})[
        "vehicle_type"
    ] == ROVER_DEFAULT.mav_vehicle_type


def test_proposals_are_stamped_with_the_active_profile(mission_db_path: Path) -> None:
    svc = _make_service(mission_db_path, _MutableSelection("quad_x500"))

    proposal = _make_proposal(svc)

    assert proposal["mission"]["vehicle_profile_id"] == "quad_x500"


def test_client_revisions_are_stamped_with_the_active_profile(mission_db_path: Path) -> None:
    svc = _make_service(mission_db_path, _MutableSelection("fixed_wing_default"))
    proposal = _make_proposal(svc)

    result = svc.create_client_revision(
        operation_id=proposal["operation_id"],
        waypoints=[{"x": 1.0, "y": 2.0, "z": 0.0}, {"x": 3.0, "y": 4.0, "z": 0.0}],
    )

    assert result["ok"] is True
    assert result["revision"]["mission"]["vehicle_profile_id"] == "fixed_wing_default"


def test_execute_refuses_a_revision_bound_to_another_profile(mission_db_path: Path) -> None:
    adapter = _SuccessfulInstallAdapter()
    selection = _MutableSelection("rover_default")
    svc = _make_service(mission_db_path, selection, adapter=adapter)
    proposal = _make_proposal(svc)

    # The operator switches vehicles after authoring the mission.
    selection.profile_id = "quad_x500"
    result = svc.execute_revision(proposal["id"])

    assert result["ok"] is False
    assert result["status"] == "vehicle_profile_mismatch"
    assert result["vehicle_profile_id"] == "rover_default"
    assert result["active_profile_id"] == "quad_x500"
    assert adapter.installs == []
    # The saved mission keeps its own profile — it is not re-stamped or
    # re-interpreted under the current selection.
    assert svc.get_revision(proposal["id"])["mission"]["vehicle_profile_id"] == "rover_default"


def test_execute_proceeds_when_the_bound_profile_is_active(mission_db_path: Path) -> None:
    adapter = _SuccessfulInstallAdapter()
    svc = _make_service(mission_db_path, _MutableSelection("rover_default"), adapter=adapter)
    proposal = _make_proposal(svc)

    result = svc.execute_revision(proposal["id"])

    assert result["ok"] is True
    assert adapter.installs


def test_execute_allows_a_revision_authored_before_profiles_were_stamped(
    mission_db_path: Path,
) -> None:
    import sqlite3

    adapter = _SuccessfulInstallAdapter()
    svc = _make_service(mission_db_path, _MutableSelection("quad_x500"), adapter=adapter)
    proposal = _make_proposal(svc)
    with sqlite3.connect(mission_db_path) as conn:
        mission = dict(proposal["mission"])
        mission.pop("vehicle_profile_id")
        import json

        conn.execute(
            "UPDATE ai_mission_revisions SET mission_json = ? WHERE id = ?",
            (json.dumps(mission), proposal["id"]),
        )
        conn.commit()

    result = svc.execute_revision(proposal["id"])

    assert result["ok"] is True
    assert adapter.installs


@pytest.mark.parametrize("profile_id", sorted(KNOWN_PROFILES))
def test_every_known_profile_round_trips_through_the_resolver(
    mission_db_path: Path, profile_id: str
) -> None:
    svc = _make_service(mission_db_path, _MutableSelection(profile_id))

    assert _make_proposal(svc)["mission"]["vehicle_profile_id"] == profile_id
