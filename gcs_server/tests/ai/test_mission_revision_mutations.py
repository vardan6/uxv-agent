from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ai.migrations import apply_ai_store_migrations
from ai.mission_execution_service import MissionExecutionService


def _make_service() -> tuple[MissionExecutionService, Path]:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return MissionExecutionService(db_path), db_path


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
        draft_status="awaiting_approval",
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
    assert rev["status"] == "awaiting_approval"
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
    assert wps[1]["x"] == 99.0
    assert wps[1]["y"] == 88.0


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


def test_update_waypoint_locked_on_approved_revision() -> None:
    svc, _ = _make_service()
    _make_proposal(svc)
    svc.approve_revision_for_draft("draft-1")
    rev = svc.get_revision_by_draft_id("draft-1")

    result = svc.update_waypoint(rev["id"], 1, point={"x": 0.0, "y": 0.0, "z": 0.0}, expected_version=0)

    assert result["ok"] is False
    assert result["status"] == "revision_locked"


# --- insert_waypoint ---

def test_insert_waypoint_appends_when_after_index_is_negative() -> None:
    svc, _ = _make_service()
    proposal = _make_proposal(svc, n_waypoints=2)
    rev_id = proposal["id"]

    result = svc.insert_waypoint(rev_id, after_index=-1, point={"x": 7.0, "y": 7.0, "z": 0.0}, expected_version=0)

    assert result["ok"] is True
    wps = result["revision"]["mission"]["waypoints"]
    assert len(wps) == 3
    assert wps[-1]["x"] == 7.0


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


# --- helpers ---

def _collect_ids(revision: dict) -> list[str]:
    wps = revision.get("mission", {}).get("waypoints") or []
    return [w.get("id") or f"wp-{i+1}" for i, w in enumerate(wps)]
