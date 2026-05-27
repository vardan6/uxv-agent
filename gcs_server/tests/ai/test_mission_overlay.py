from __future__ import annotations

from ai.mission_overlay import (
    build_mission_overlay,
    collect_waypoints,
    coerce_scene_point,
    empty_mission_overlay,
)


def test_coerce_scene_point_returns_none_for_non_dict() -> None:
    assert coerce_scene_point(None) is None
    assert coerce_scene_point("nope") is None


def test_coerce_scene_point_returns_none_for_non_numeric() -> None:
    assert coerce_scene_point({"x": "a", "y": 1}) is None


def test_coerce_scene_point_defaults_z_and_uses_fallback_id() -> None:
    point = coerce_scene_point({"x": 1, "y": 2}, fallback_id="wp-7")
    assert point == {
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
        "id": "wp-7",
        "label": "",
        "kind": "",
    }


def test_collect_waypoints_prefers_direct_waypoints_list() -> None:
    mission = {
        "waypoints": [{"x": 1, "y": 1}],
        "route_artifacts": [{"waypoints": [{"x": 9, "y": 9}]}],
        "steps": [{"waypoints": [{"x": 8, "y": 8}]}],
    }
    waypoints = collect_waypoints(mission)
    assert [(p["x"], p["y"]) for p in waypoints] == [(1.0, 1.0)]


def test_collect_waypoints_falls_back_to_route_artifacts() -> None:
    mission = {
        "route_artifacts": [
            {"waypoints": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]},
        ],
        "steps": [{"waypoints": [{"x": 8, "y": 8}]}],
    }
    waypoints = collect_waypoints(mission)
    assert len(waypoints) == 2
    assert waypoints[0]["id"] == "route-1-wp-1"


def test_collect_waypoints_falls_back_to_steps() -> None:
    mission = {"steps": [{"waypoints": [{"x": 5, "y": 6}]}]}
    waypoints = collect_waypoints(mission)
    assert waypoints[0]["id"] == "step-1-wp-1"
    assert (waypoints[0]["x"], waypoints[0]["y"]) == (5.0, 6.0)


def test_collect_waypoints_returns_empty_for_non_dict() -> None:
    assert collect_waypoints(None) == []


def test_build_mission_overlay_emits_markers_and_synthesized_route() -> None:
    overlay = build_mission_overlay(
        42,
        {
            "goal": "loop",
            "waypoints": [
                {"x": 0, "y": 0, "label": "start"},
                {"x": 10, "y": 5, "label": "end"},
            ],
        },
    )

    assert overlay["available"] is True
    assert overlay["mission_id"] == 42
    assert overlay["goal"] == "loop"
    assert overlay["waypoint_count"] == 2

    feature_types = [f["type"] for f in overlay["features"]]
    # 2+ markers without explicit route → synthesized route line + markers
    assert feature_types[0] == "route_line"
    assert feature_types.count("waypoint") == 2
    route = overlay["features"][0]
    assert route["id"] == "mission-42-route"
    assert route["waypoint_count"] == 2

    assert overlay["bounds"] == {
        "min_x": 0.0, "max_x": 10.0,
        "min_y": 0.0, "max_y": 5.0,
        "min_z": 0.0, "max_z": 0.0,
    }


def test_build_mission_overlay_single_waypoint_skips_synthesized_route() -> None:
    overlay = build_mission_overlay(1, {"waypoints": [{"x": 0, "y": 0}]})

    assert overlay["available"] is True
    assert overlay["waypoint_count"] == 1
    assert [f["type"] for f in overlay["features"]] == ["waypoint"]


def test_build_mission_overlay_uses_explicit_route_artifact() -> None:
    overlay = build_mission_overlay(
        7,
        {
            "route_artifacts": [
                {
                    "route_id": "alpha",
                    "label": "Alpha route",
                    "waypoints": [{"x": 1, "y": 1}, {"x": 2, "y": 2}],
                    "summary": {"total_distance_m": 1.414},
                }
            ],
        },
    )

    route = next(f for f in overlay["features"] if f["type"] == "route_line")
    assert route["id"] == "alpha"
    assert route["label"] == "Alpha route"
    assert route["distance_m"] == 1.414


def test_build_mission_overlay_empty_returns_unavailable() -> None:
    overlay = build_mission_overlay(1, {})
    assert overlay["available"] is False
    assert overlay["features"] == []
    assert overlay["bounds"] is None
    assert overlay["waypoint_count"] == 0


def test_empty_mission_overlay_shape() -> None:
    payload = empty_mission_overlay()
    assert payload["available"] is False
    assert payload["features"] == []
    assert payload["waypoint_count"] == 0
    assert payload["bounds"] is None
