from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from ai.migrations import apply_ai_store_migrations
from ai.mission_store import MissionStore
from app import delete_mission


def _make_store() -> tuple[MissionStore, Path]:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return MissionStore(db_path), db_path


def _request(runtime: object, path: str) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": path,
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_list_missions_surfaces_vehicle_profile_id_from_active_revision() -> None:
    store, db_path = _make_store()
    mission = store.create_mission(user_id="", name="Survey route", origin="manual")
    now = time.time()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_mission_operations (
              id, session_id, source_message_id, status, active_revision_id, policy_json, created_at, updated_at
            ) VALUES (?, '', '', 'planning', ?, '{}', ?, ?)
            """,
            ("op-1", "rev-1", now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_mission_revisions (
              id, operation_id, draft_id, parent_revision_id, status,
              mission_json, intent_json, target_resolution_json, validation_json,
              review_context_json, created_at, updated_at, approved_at, rejected_at
            ) VALUES (?, ?, '', '', 'proposed', ?, '{}', '{}', '{}', '{}', ?, ?, NULL, NULL)
            """,
            ("rev-1", "op-1", json.dumps({"vehicle_profile_id": "quad_x500"}), now, now),
        )
        conn.commit()

    store.set_active_operation(str(mission["id"]), operation_id="op-1")

    missions = store.list_missions(user_id="")

    assert missions[0]["id"] == mission["id"]
    assert missions[0]["vehicle_profile_id"] == "quad_x500"


def test_list_missions_derives_waypoint_count_from_active_revision() -> None:
    store, db_path = _make_store()
    mission = store.create_mission(user_id="", name="Tree mission", origin="manual")
    now = time.time()

    mission_json = {
        "tree": {
            "type": "sequence",
            "children": [
                {
                    "type": "nav_leaf",
                    "waypoints": [
                        {"lat": 1.0, "lon": 2.0, "alt": 0.0},
                        {"lat": 3.0, "lon": 4.0, "alt": 0.0},
                    ],
                },
                {"type": "condition", "condition": "gps_ok"},
                {
                    "type": "nav_leaf",
                    "waypoints": [
                        {"lat": 5.0, "lon": 6.0, "alt": 0.0},
                    ],
                },
            ],
        }
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_mission_operations (
              id, session_id, source_message_id, status, active_revision_id, policy_json, created_at, updated_at
            ) VALUES (?, '', '', 'planning', ?, '{}', ?, ?)
            """,
            ("op-2", "rev-2", now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_mission_revisions (
              id, operation_id, draft_id, parent_revision_id, status,
              mission_json, intent_json, target_resolution_json, validation_json,
              review_context_json, created_at, updated_at, approved_at, rejected_at
            ) VALUES (?, ?, '', '', 'proposed', ?, '{}', '{}', '{}', '{}', ?, ?, NULL, NULL)
            """,
            ("rev-2", "op-2", json.dumps(mission_json), now, now),
        )
        conn.commit()

    store.set_active_operation(str(mission["id"]), operation_id="op-2")

    missions = store.list_missions(user_id="")

    assert missions[0]["id"] == mission["id"]
    assert missions[0]["waypoint_count"] == 3


def test_list_missions_derives_waypoint_count_from_direct_waypoints_payload() -> None:
    store, db_path = _make_store()
    mission = store.create_mission(user_id="", name="Editable mission", origin="manual")
    now = time.time()

    mission_json = {
        "goal": "editable mission",
        "waypoints": [
            {"x": 1.0, "y": 2.0, "z": 0.0},
            {"x": 3.0, "y": 4.0, "z": 0.0},
            {"x": 5.0, "y": 6.0, "z": 0.0},
            {"x": 7.0, "y": 8.0, "z": 0.0},
        ],
        "steps": [],
        "constraints": [],
        "assumptions": [],
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_mission_operations (
              id, session_id, source_message_id, status, active_revision_id, policy_json, created_at, updated_at
            ) VALUES (?, '', '', 'planning', ?, '{}', ?, ?)
            """,
            ("op-3", "rev-3", now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_mission_revisions (
              id, operation_id, draft_id, parent_revision_id, status,
              mission_json, intent_json, target_resolution_json, validation_json,
              review_context_json, created_at, updated_at, approved_at, rejected_at
            ) VALUES (?, ?, '', '', 'proposed', ?, '{}', '{}', '{}', '{}', ?, ?, NULL, NULL)
            """,
            ("rev-3", "op-3", json.dumps(mission_json), now, now),
        )
        conn.commit()

    store.set_active_operation(str(mission["id"]), operation_id="op-3")

    missions = store.list_missions(user_id="")

    assert missions[0]["id"] == mission["id"]
    assert missions[0]["waypoint_count"] == 4


def test_delete_mission_rejects_armed_execution() -> None:
    store, _ = _make_store()
    mission = store.create_mission(user_id="", name="Protected mission", origin="manual")
    mission_id = str(mission["id"])
    runtime = SimpleNamespace(
        mission_store=store,
        mission_execution_sessions=SimpleNamespace(
            get_for_mission=lambda mid: SimpleNamespace(status="awaiting_confirm") if mid == mission_id else None
        ),
    )

    response = asyncio.run(delete_mission(mission_id, _request(runtime, f"/api/ai/missions/{mission_id}")))
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["ok"] is False
    assert payload["execution_status"] == "awaiting_confirm"
