from __future__ import annotations

import sqlite3

import pytest

from ai.mission_repository import (
    Mission,
    MissionNotFound,
    MissionRepository,
    MissionVersionConflict,
    default_mission_color,
    validate_mission_json,
)


def _repo(tmp_path) -> MissionRepository:
    return MissionRepository(tmp_path / "ai.sqlite3")


def _mission_json() -> dict:
    return {
        "goal": "Inspect north loop",
        "waypoints": [
            {"x": 1, "y": 2, "z": 0, "label": "Start"},
            {"x": 3, "y": 4, "z": 0, "label": "Finish"},
        ],
    }


def test_create_assigns_monotonic_ids_and_zero_version(tmp_path) -> None:
    repo = _repo(tmp_path)

    first = repo.create(name="One", origin="manual", mission_json=_mission_json())
    second = repo.create(name="Two", origin="ai_chat", origin_chat_id="chat-1")

    assert isinstance(first, Mission)
    assert second.id == first.id + 1
    assert first.client_version == 0
    assert second.origin_chat_id == "chat-1"
    assert first.color == default_mission_color(first.id)
    assert second.color == default_mission_color(second.id)


def test_create_rejects_invalid_origin(tmp_path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(ValueError):
        repo.create(name="bad", origin="bogus")


def test_get_returns_none_for_missing(tmp_path) -> None:
    repo = _repo(tmp_path)

    assert repo.get(9999) is None


def test_update_bumps_client_version_and_persists_fields(tmp_path) -> None:
    repo = _repo(tmp_path)
    created = repo.create(name="orig", origin="manual", mission_json=_mission_json())

    updated = repo.update(
        created.id,
        expected_client_version=0,
        name="renamed",
        mission_json={"goal": "new", "waypoints": []},
    )

    assert updated.name == "renamed"
    assert updated.client_version == 1
    assert updated.mission_json == {"goal": "new", "waypoints": []}

    reloaded = repo.get(created.id)
    assert reloaded is not None
    assert reloaded.name == "renamed"
    assert reloaded.client_version == 1


def test_update_persists_color_override(tmp_path) -> None:
    repo = _repo(tmp_path)
    created = repo.create(name="orig", origin="manual")

    updated = repo.update(
        created.id,
        expected_client_version=created.client_version,
        color="#112233",
    )

    assert updated.color == "#112233"
    reloaded = repo.get(created.id)
    assert reloaded is not None
    assert reloaded.color == "#112233"


def test_update_raises_on_version_conflict(tmp_path) -> None:
    repo = _repo(tmp_path)
    created = repo.create(name="m", origin="manual")
    repo.update(created.id, expected_client_version=0, name="first")

    with pytest.raises(MissionVersionConflict) as excinfo:
        repo.update(created.id, expected_client_version=0, name="second")

    assert excinfo.value.mission_id == created.id
    assert excinfo.value.expected == 0
    assert excinfo.value.actual == 1


def test_update_raises_when_mission_missing(tmp_path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(MissionNotFound):
        repo.update(424242, expected_client_version=0, name="x")


def test_list_filters_by_origin_chat_and_orders_recent_first(tmp_path) -> None:
    repo = _repo(tmp_path)
    a = repo.create(name="A", origin="manual")
    b = repo.create(name="B", origin="ai_chat", origin_chat_id="chat-1")
    c = repo.create(name="C", origin="ai_chat", origin_chat_id="chat-2")

    chat1 = repo.list(origin_chat_id="chat-1")
    assert [m.id for m in chat1] == [b.id]

    all_missions = repo.list()
    # created_at DESC — most recent first
    assert [m.id for m in all_missions[:3]] == [c.id, b.id, a.id]


def test_list_respects_limit(tmp_path) -> None:
    repo = _repo(tmp_path)
    for i in range(5):
        repo.create(name=f"m{i}", origin="manual")

    assert len(repo.list(limit=2)) == 2


def test_delete_and_restore_roundtrip(tmp_path) -> None:
    repo = _repo(tmp_path)
    mission = repo.create(name="m", origin="manual")

    assert repo.delete(mission.id) is True
    assert repo.get(mission.id) is None
    assert repo.get(mission.id, include_deleted=True) is not None
    assert repo.list() == []
    # idempotent: deleting again is a no-op
    assert repo.delete(mission.id) is False

    restored = repo.restore(mission.id)
    assert restored is not None
    assert restored.id == mission.id
    assert repo.get(mission.id) is not None
    # restoring a non-deleted mission returns None
    assert repo.restore(mission.id) is None


def test_validate_mission_json_blocks_empty() -> None:
    result = validate_mission_json({})
    assert result["status"] == "blocked"
    assert "empty" in result["blockers"][0]


def test_validate_mission_json_blocks_missing_coords() -> None:
    result = validate_mission_json({"waypoints": [{"x": 1}]})
    assert result["status"] == "blocked"
    assert any("'y'" in b for b in result["blockers"])


def test_validate_mission_json_warns_on_non_numeric_z() -> None:
    result = validate_mission_json(
        {"waypoints": [{"x": 0, "y": 0, "z": "tall"}]}
    )
    assert result["status"] == "warned"
    assert result["blockers"] == []
    assert any("'z'" in w for w in result["warnings"])


def test_validate_mission_json_accepts_step_waypoints() -> None:
    result = validate_mission_json(
        {"steps": [{"waypoints": [{"x": 1, "y": 2}]}]}
    )
    assert result["status"] == "ok"


def test_schema_drops_approval_status_column(tmp_path) -> None:
    db_path = tmp_path / "ai.sqlite3"
    _repo(tmp_path)

    with sqlite3.connect(db_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(missions)").fetchall()
        }

    assert "approval_status" not in columns


def test_get_falls_back_to_default_color_when_column_is_blank(tmp_path) -> None:
    repo = _repo(tmp_path)
    mission = repo.create(name="m", origin="manual")

    with sqlite3.connect(tmp_path / "ai.sqlite3") as conn:
        conn.execute("UPDATE missions SET color = '' WHERE id = ?", (mission.id,))
        conn.commit()

    reloaded = repo.get(mission.id)
    assert reloaded is not None
    assert reloaded.color == default_mission_color(mission.id)
