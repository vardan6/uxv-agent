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
