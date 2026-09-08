from __future__ import annotations

import math
from pathlib import Path

from ai.coordinate_frame import Origin, local_to_wgs84
from ai.mission_execution_service import MissionExecutionService

ORIGIN = Origin(lat=0.0, lon=0.0, alt=0.0)


def _point(x: float, y: float) -> dict[str, float]:
    lat, lon, _ = local_to_wgs84(x, y, 0.0, ORIGIN)
    return {"lat": lat, "lon": lon}


def test_preview_survey_matches_created_mission_geometry(mission_db_path: Path) -> None:
    svc = MissionExecutionService(mission_db_path)
    points = [_point(0.0, 0.0), _point(40.0, 20.0)]
    params = {"line_spacing_m": 10.0, "altitude_m": 5.0}

    preview = svc.preview_drawn_pattern(pattern="survey", points=points, params=params)
    assert preview["ok"] is True
    assert preview["line_count"] == len(preview["points"])
    assert preview["line_count"] > 0
    assert preview["soft_cost"]["candidate_count"] == 4

    created = svc.create_drawn_pattern_mission(
        session_id="sess-1", pattern="survey", points=points, params=params
    )
    assert created["ok"] is True
    revision_tree = created["revision"]["mission"]["tree"]

    def _collect_waypoints(node: dict) -> list[dict]:
        if node.get("type") == "nav_leaf":
            return list(node.get("waypoints") or [])
        out: list[dict] = []
        for child in node.get("children") or []:
            out.extend(_collect_waypoints(child))
        return out

    created_waypoints = _collect_waypoints(revision_tree)
    assert len(created_waypoints) == len(preview["points"])
    for wp, preview_pt in zip(created_waypoints, preview["points"]):
        lat, lon, _ = local_to_wgs84(wp["x"], wp["y"], wp.get("z", 0.0), ORIGIN)
        assert math.isclose(lat, preview_pt["lat"], abs_tol=1e-9)
        assert math.isclose(lon, preview_pt["lon"], abs_tol=1e-9)


def test_preview_does_not_persist_a_mission(mission_db_path: Path) -> None:
    svc = MissionExecutionService(mission_db_path)
    points = [_point(0.0, 0.0), _point(30.0, 0.0)]

    preview = svc.preview_drawn_pattern(
        pattern="corridor", points=points, params={"spacing_m": 5.0, "altitude_m": 3.0}
    )
    assert preview["ok"] is True
    assert svc.list_revisions() == []


def test_preview_rejects_bad_pattern(mission_db_path: Path) -> None:
    svc = MissionExecutionService(mission_db_path)
    result = svc.preview_drawn_pattern(pattern="triangle", points=[{"lat": 0, "lon": 0}])
    assert result["ok"] is False
    assert "error" in result
