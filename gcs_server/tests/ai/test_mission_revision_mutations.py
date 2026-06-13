from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ai.controller_mission_adapter import ControllerMissionAdapterState
from ai.migrations import apply_ai_store_migrations
from ai.mission_export_service import MissionExportService
from ai.mission_execution_service import MissionExecutionService


class _FixedControllerStateAdapter:
    adapter_name = "fixed_controller_state"

    def __init__(self, state: ControllerMissionAdapterState) -> None:
        self._state = state

    def get_controller_state(self) -> ControllerMissionAdapterState:
        return self._state

    def install_mission(self, *, pending_snapshot: dict, expected_controller_version: int | None = None):
        raise AssertionError("install_mission should not be called for stale-version rejection tests")


def _make_service(adapter=None) -> tuple[MissionExecutionService, Path]:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return MissionExecutionService(db_path, controller_adapter=adapter), db_path


def _make_proposal(svc: MissionExecutionService, *, n_waypoints: int = 3) -> dict:
    waypoints = [{"x": float(i), "y": float(i), "z": 0.0} for i in range(n_waypoints)]
    draft_payload = {
        "goal": "test mission",
        "waypoints": waypoints,
        "steps": [],
        "constraints": [],
        "assumptions": [],
    }
    return svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-1",
        draft_id="draft-1",
        intent={},
        target_resolution={},
        draft_payload=draft_payload,
        validation={},
        draft_status="proposed",
    )


# --- migration: new columns exist ---

def test_migration_adds_client_version_and_provenance() -> None:
    _, db_path = _make_service()
    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ai_mission_revisions)").fetchall()}
    assert "client_version" in cols
    assert "provenance_json" in cols


# --- create_client_revision ---

def test_create_client_revision_happy_path() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)
    operation_id = proposal["operation_id"]

    result = svc.create_client_revision(
        operation_id=operation_id,
        waypoints=[{"x": 1.0, "y": 2.0, "z": 0.0}, {"x": 3.0, "y": 4.0, "z": 0.0}],
        label="hand-crafted",
    )

    assert result["ok"] is True
    rev = result["revision"]
    assert rev["status"] == "proposed"
    assert rev["mission"]["goal"] == "hand-crafted"
    assert len(rev["mission"]["waypoints"]) == 2


def test_create_client_revision_assigns_user_provenance() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)

    result = svc.create_client_revision(
        operation_id=proposal["operation_id"],
        waypoints=[{"x": 0.0, "y": 0.0, "z": 0.0}],
    )

    rev = result["revision"]
    provenance = rev["provenance"]
    assert all(v == "user" for v in provenance.values())


def test_create_client_revision_missing_operation_id() -> None:
    svc, _ = _make_service()
    result = svc.create_client_revision(operation_id="", waypoints=[{"x": 0.0, "y": 0.0, "z": 0.0}])
    assert result["ok"] is False
    assert result["status"] == "invalid_request"


def test_create_client_revision_unknown_operation() -> None:
    svc, _ = _make_service()
    result = svc.create_client_revision(operation_id="nonexistent", waypoints=[])
    assert result["ok"] is False
    assert result["status"] == "operation_not_found"


def test_create_client_revision_invalid_waypoint() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)
    result = svc.create_client_revision(
        operation_id=proposal["operation_id"],
        waypoints=[{"x": "bad", "y": 0.0, "z": 0.0}],
    )
    assert result["ok"] is False
    assert result["status"] == "invalid_waypoint"


def test_create_client_revision_sets_active_revision() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)
    operation_id = proposal["operation_id"]

    result = svc.create_client_revision(
        operation_id=operation_id,
        waypoints=[{"x": 5.0, "y": 5.0, "z": 0.0}],
    )

    new_rev_id = result["revision"]["id"]
    state = svc.get_current_mission_state()
    assert state["revision_id"] == new_rev_id


# --- update_waypoint ---

def test_update_waypoint_happy_path() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=3)
    rev_id = proposal["id"]

    result = svc.update_waypoint(rev_id, 2, point={"x": 99.0, "y": 88.0, "z": 1.0}, expected_version=0)

    assert result["ok"] is True
    assert result["client_version"] == 1
    wps = result["revision"]["mission"]["waypoints"]
    # Local x/y are re-derived from the stored WGS84 truth (ADR 0022), so the
    # round-trip introduces sub-metre float drift; compare approximately.
    assert wps[1]["x"] == pytest.approx(99.0, abs=1e-3)
    assert wps[1]["y"] == pytest.approx(88.0, abs=1e-3)


def test_update_waypoint_provenance_changes_ai_to_ai_edited() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    result = svc.update_waypoint(rev_id, 1, point={"x": 1.0, "y": 1.0, "z": 0.0}, expected_version=0)

    provenance = result["revision"]["provenance"]
    assert "ai+edited" in provenance.values()


def test_update_waypoint_version_conflict() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    result = svc.update_waypoint(rev_id, 1, point={"x": 1.0, "y": 1.0, "z": 0.0}, expected_version=99)

    assert result["ok"] is False
    assert result["status"] == "version_conflict"


def test_update_waypoint_out_of_range() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)

    result = svc.update_waypoint(proposal["id"], 5, point={"x": 1.0, "y": 1.0, "z": 0.0}, expected_version=0)

    assert result["ok"] is False
    assert result["status"] == "invalid_index"


def test_update_waypoint_locked_on_exported_revision() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)
    svc.mark_revision_exported_by_revision_id(
        proposal["id"],
        export_result={"file_path": "/tmp/test.plan", "waypoint_count": 3, "vehicle_type": 10},
    )

    result = svc.update_waypoint(proposal["id"], 1, point={"x": 0.0, "y": 0.0, "z": 0.0}, expected_version=0)

    assert result["ok"] is False
    assert result["status"] == "revision_locked"


def test_mark_revision_exported_by_revision_id() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc)

    updated = svc.mark_revision_exported_by_revision_id(
        proposal["id"],
        export_result={"file_path": "/tmp/test.plan", "waypoint_count": 3, "vehicle_type": 10},
    )

    assert updated is not None
    assert updated["status"] == "exported"
    assert updated["mission"]["mission_export"]["file_path"] == "/tmp/test.plan"


def test_export_service_accepts_revision_payload() -> None:
    svc, tmp_path = _make_service()
    proposal = _make_proposal(svc)

    result = MissionExportService(missions_dir=tmp_path.parent).export(proposal)

    assert result["ok"] is True
    assert result["draft_id"] == proposal["id"]
    assert result["file_path"].endswith(f"{proposal['id']}.plan")


# --- insert_waypoint ---

def test_insert_waypoint_appends_when_after_index_is_negative() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    result = svc.insert_waypoint(rev_id, after_index=-1, point={"x": 7.0, "y": 7.0, "z": 0.0}, expected_version=0)

    assert result["ok"] is True
    wps = result["revision"]["mission"]["waypoints"]
    assert len(wps) == 3
    # ADR 0022 WGS84 round-trip drift — compare approximately (see above).
    assert wps[-1]["x"] == pytest.approx(7.0, abs=1e-3)


def test_insert_waypoint_gets_user_provenance() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=1)

    result = svc.insert_waypoint(
        proposal["id"], after_index=1, point={"x": 2.0, "y": 2.0, "z": 0.0}, expected_version=0
    )

    provenance = result["revision"]["provenance"]
    new_wp_id = result["revision"]["mission"]["waypoints"][1]["id"]
    assert provenance[new_wp_id] == "user"


def test_insert_waypoint_increments_version() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=1)

    result = svc.insert_waypoint(
        proposal["id"], after_index=0, point={"x": 0.0, "y": 0.0, "z": 0.0}, expected_version=0
    )
    assert result["client_version"] == 1


# --- delete_waypoint ---

def test_delete_waypoint_removes_correct_index() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=3)
    rev_id = proposal["id"]

    orig_wps = _collect_ids(proposal)
    result = svc.delete_waypoint(rev_id, 2, expected_version=0)

    assert result["ok"] is True
    remaining = result["revision"]["mission"]["waypoints"]
    assert len(remaining) == 2
    remaining_ids = [w["id"] for w in remaining]
    assert orig_wps[1] not in remaining_ids


def test_delete_waypoint_removes_provenance_entry() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    wps = proposal["mission"].get("waypoints") or []
    target_id = wps[0].get("id") or "wp-1"

    result = svc.delete_waypoint(rev_id, 1, expected_version=0)
    assert target_id not in result["revision"]["provenance"]


def test_delete_waypoint_out_of_range() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=1)

    result = svc.delete_waypoint(proposal["id"], 5, expected_version=0)
    assert result["ok"] is False
    assert result["status"] == "invalid_index"


# --- overlay includes provenance ---

def test_overlay_includes_provenance_field() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    overlay = svc.get_revision_overlay(revision_id=rev_id)
    waypoint_features = [f for f in overlay["features"] if f["type"] == "waypoint"]
    assert all("provenance" in f for f in waypoint_features)
    assert all(f["provenance"] == "ai" for f in waypoint_features)


def test_overlay_reflects_updated_provenance() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    svc.update_waypoint(rev_id, 1, point={"x": 1.0, "y": 1.0, "z": 0.0}, expected_version=0)
    overlay = svc.get_revision_overlay(revision_id=rev_id)

    waypoint_features = [f for f in overlay["features"] if f["type"] == "waypoint"]
    provenances = [f["provenance"] for f in waypoint_features]
    assert "ai+edited" in provenances


def test_execute_revision_creates_rebased_revision_on_stale_controller_version() -> None:
    live_waypoints = [{"id": "live-wp-1", "x": 50.0, "y": 60.0, "z": 0.0}]
    live_mission = {
        "goal": "controller live mission",
        "waypoints": live_waypoints,
        "steps": [],
        "constraints": [],
        "assumptions": [],
        "risks": [],
        "required_operator_approval": True,
        "execution_allowed": False,
    }
    adapter = _FixedControllerStateAdapter(
        ControllerMissionAdapterState(
            controller_version=7,
            status="executing",
            operation_id="mission-op-live123",
            revision_id="mission-rev-live123",
            mission=live_mission,
            mission_export={"file_path": "/tmp/live.plan", "waypoint_count": 1, "vehicle_type": 10},
            plan={"fileType": "Plan"},
        )
    )
    svc, db_path = _make_service(adapter=adapter)
    proposal = _make_proposal(svc, n_waypoints=2)
    export_result = MissionExportService(missions_dir=db_path.parent).export(proposal)
    assert export_result["ok"] is True
    exported = svc.mark_revision_exported_by_revision_id(proposal["id"], export_result=export_result)

    result = svc.execute_revision(exported["id"], expected_controller_version=6)

    assert result["ok"] is False
    assert result["status"] == "stale_controller_version"
    rebased = result["rebased_revision"]
    assert rebased["id"] != exported["id"]
    assert rebased["status"] == "proposed"
    assert rebased["operation_id"] != exported["operation_id"]
    assert "mission_export" not in rebased["mission"]
    assert rebased["review_context"]["rebase"]["base_controller_version"] == 7
    assert rebased["review_context"]["rebase"]["rebased_from_revision_id"] == exported["id"]
    assert rebased["review_context"]["rebase"]["base_revision_id"] == "mission-rev-live123"


# --- ADR 0019 backend provenance guard ---

def test_create_proposal_blocks_edit_in_place_over_operator_waypoints() -> None:
    # Simulate: AI proposal → operator edits a waypoint (ai+edited) → AI tries
    # edit_in_place without operator confirmation → backend must block it.
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    operation_id = proposal["operation_id"]
    rev_id = proposal["id"]

    # Operator edits a waypoint → provenance becomes "ai+edited"
    svc.update_waypoint(rev_id, 1, point={"x": 5.0, "y": 5.0, "z": 0.0}, expected_version=0)

    draft_payload = {
        "goal": "ai replacement",
        "waypoints": [{"x": 1.0, "y": 1.0, "z": 0.0}],
        "steps": [], "constraints": [], "assumptions": [],
    }
    with pytest.raises(ValueError, match="provenance_conflict"):
        svc.create_proposal(
            session_id="sess-1",
            source_message_id="msg-2",
            draft_id="draft-2",
            intent={},
            target_resolution={},
            draft_payload=draft_payload,
            validation={},
            draft_status="proposed",
            parent_operation_id=operation_id,
        )


def test_create_proposal_allows_edit_in_place_with_override() -> None:
    # Same setup, but with allow_provenance_override=True (operator confirmed).
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    operation_id = proposal["operation_id"]
    rev_id = proposal["id"]

    svc.update_waypoint(rev_id, 1, point={"x": 5.0, "y": 5.0, "z": 0.0}, expected_version=0)

    draft_payload = {
        "goal": "confirmed ai replacement",
        "waypoints": [{"x": 1.0, "y": 1.0, "z": 0.0}],
        "steps": [], "constraints": [], "assumptions": [],
    }
    result = svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-2",
        draft_id="draft-2",
        intent={},
        target_resolution={},
        draft_payload=draft_payload,
        validation={},
        draft_status="proposed",
        parent_operation_id=operation_id,
        allow_provenance_override=True,
    )
    assert result.get("id") is not None
    assert result.get("operation_id") == operation_id


# --- helpers ---

def _collect_ids(revision: dict) -> list[str]:
    wps = revision.get("mission", {}).get("waypoints") or []
    return [w.get("id") or f"wp-{i+1}" for i, w in enumerate(wps)]
