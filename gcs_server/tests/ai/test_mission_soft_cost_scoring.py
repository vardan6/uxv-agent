from __future__ import annotations

import math
import sqlite3
import tempfile
from pathlib import Path

from ai.coordinate_frame import Origin, local_to_wgs84
from ai.migrations import apply_ai_store_migrations
from ai.mission_execution_service import (
    SOFT_BLOCKAGE_PENALTY_PER_M,
    SOFT_CORRIDOR_PENALTY_PER_M,
    MissionExecutionService,
)

ORIGIN = Origin(lat=0.0, lon=0.0, alt=0.0)


class _FakeStore:
    def __init__(self, constraints: list[dict]) -> None:
        self._constraints = constraints

    def list_constraints(self) -> list[dict]:
        return self._constraints


def _make_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return db_path


def _point(x: float, y: float) -> dict[str, float]:
    lat, lon, _ = local_to_wgs84(x, y, 0.0, ORIGIN)
    return {"lat": lat, "lon": lon}


def _polygon(corners_local: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [_point(x, y) for x, y in corners_local]


def _constraint(*, kind: str, rule: str, corners_local: list[tuple[float, float]], name: str) -> dict:
    return {
        "id": name,
        "name": name,
        "kind": kind,
        "rule": rule,
        "enabled": True,
        "polygon": _polygon(corners_local),
    }


def test_survey_soft_corridor_scoring_prefers_vertical_candidate() -> None:
    svc = MissionExecutionService(_make_db())
    soft_corridor = _constraint(
        kind="allowed_corridor",
        rule="soft",
        corners_local=[(19.0, -1.0), (21.0, -1.0), (21.0, 21.0), (19.0, 21.0)],
        name="preferred-lane",
    )

    result = svc.create_drawn_pattern_mission(
        session_id="sess-1",
        pattern="survey",
        points=[_point(0.0, 0.0), _point(40.0, 20.0)],
        params={"line_spacing_m": 10.0, "altitude_m": 5.0},
        constraints_store=_FakeStore([soft_corridor]),
    )

    assert result["ok"] is True
    soft_cost = result["soft_cost"]
    assert soft_cost["chosen_heading_deg"] == 90.0
    assert soft_cost["candidate_count"] == 4
    assert math.isclose(soft_cost["base_length_m"], 140.0)
    assert math.isclose(soft_cost["breakdown"]["soft_blockage_m"], 0.0)
    assert math.isclose(soft_cost["breakdown"]["soft_corridor_outside_m"], 118.0)
    assert math.isclose(soft_cost["soft_penalty"], 118.0 * SOFT_CORRIDOR_PENALTY_PER_M)
    assert math.isclose(soft_cost["total_cost"], 140.0 + 118.0 * SOFT_CORRIDOR_PENALTY_PER_M)


def test_corridor_returns_soft_blockage_metadata() -> None:
    svc = MissionExecutionService(_make_db())
    soft_blockage = _constraint(
        kind="blockage",
        rule="soft",
        corners_local=[(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)],
        name="mud",
    )

    result = svc.create_drawn_pattern_mission(
        session_id="sess-1",
        pattern="corridor",
        points=[_point(0.0, 0.0), _point(30.0, 0.0)],
        params={"spacing_m": 5.0, "altitude_m": 3.0, "passes": 1},
        constraints_store=_FakeStore([soft_blockage]),
    )

    assert result["ok"] is True
    soft_cost = result["soft_cost"]
    assert soft_cost["candidate_count"] == 1
    assert "chosen_heading_deg" not in soft_cost
    assert math.isclose(soft_cost["base_length_m"], 30.0)
    assert math.isclose(soft_cost["breakdown"]["soft_blockage_m"], 10.0)
    assert math.isclose(soft_cost["breakdown"]["soft_corridor_outside_m"], 0.0)
    assert math.isclose(soft_cost["soft_penalty"], 10.0 * SOFT_BLOCKAGE_PENALTY_PER_M)
    assert math.isclose(soft_cost["total_cost"], 30.0 + 10.0 * SOFT_BLOCKAGE_PENALTY_PER_M)
