from __future__ import annotations

import json

import pytest

from ai.road_graph_service import RoadGraphService


def _road(rid, a, b, *, group="", drivable=True, cost="default", width=4.0):
    return {
        "id": rid,
        "centerline": [list(a), list(b)],
        "geometry": {"width": width},
        "metadata": {"drivable": drivable, "route_planning_cost": cost, "group": group},
    }


def _write_scene(tmp_path, roads):
    path = tmp_path / "terrain_scene.v1.json"
    path.write_text(json.dumps({"roads": roads}))
    return path


def _square_loop_scene(tmp_path):
    """A 4-edge cycle: (0,0)-(10,0)-(10,10)-(0,10)-(0,0), all in group 'loop'."""
    roads = [
        _road("r1", (0, 0, 0), (10, 0, 0), group="loop"),
        _road("r2", (10, 0, 0), (10, 10, 0), group="loop"),
        _road("r3", (10, 10, 0), (0, 10, 0), group="loop"),
        _road("r4", (0, 10, 0), (0, 0, 0), group="loop"),
    ]
    return _write_scene(tmp_path, roads)


def test_build_produces_expected_node_and_edge_counts(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    assert svc.node_count == 4
    assert svc.edge_count == 4
    assert svc.known_groups() == ["loop"]


def test_non_drivable_roads_are_excluded(tmp_path):
    roads = [
        _road("r1", (0, 0, 0), (10, 0, 0), group="loop"),
        _road("r2", (10, 0, 0), (10, 10, 0), group="loop", drivable=False),
    ]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    assert svc.edge_count == 1
    assert svc.node_count == 2


def test_group_derived_from_road_id_when_metadata_missing(tmp_path):
    roads = [_road("road_plant_a_loop_1", (0, 0, 0), (5, 0, 0))]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    assert svc.known_groups() == ["plant_a"]


def test_avoid_cost_multiplier_makes_edge_effectively_impassable(tmp_path):
    roads = [
        _road("direct", (0, 0, 0), (10, 0, 0), group="g", cost="avoid"),
        _road("around_a", (0, 0, 0), (0, 5, 0), group="g"),
        _road("around_b", (0, 5, 0), (10, 5, 0), group="g"),
        _road("around_c", (10, 5, 0), (10, 0, 0), group="g"),
    ]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    start = svc.nearest_node(0, 0)
    goal = svc.nearest_node(10, 0)
    path = svc.shortest_path(start, goal)
    # The direct "avoid" edge is ~1e9x cost, so Dijkstra takes the long way around.
    assert svc.path_length_m(path) < 1e6


def test_nearest_node_and_shortest_path_on_loop(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    start = svc.nearest_node(0.0, 0.0)
    goal = svc.nearest_node(10.0, 10.0)
    path = svc.shortest_path(start, goal)
    assert path[0] == start
    assert path[-1] == goal
    assert svc.path_length_m(path) == pytest.approx(20.0)


def test_shortest_path_same_start_and_goal_is_trivial(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    node = svc.nearest_node(0.0, 0.0)
    assert svc.shortest_path(node, node) == [node]


def test_shortest_path_returns_empty_when_unreachable(tmp_path):
    roads = [
        _road("island_a", (0, 0, 0), (1, 0, 0), group="a"),
        _road("island_b", (100, 100, 0), (101, 100, 0), group="b"),
    ]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    a = svc.nearest_node(0, 0)
    b = svc.nearest_node(100, 100)
    assert svc.shortest_path(a, b) == []


def test_cover_group_visits_every_edge_and_returns_to_entry(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    entry = svc.nearest_node(0.0, 0.0)
    circuit = svc.cover_group("loop", entry)
    assert circuit[0] == entry
    assert circuit[-1] == entry
    # 4-edge Eulerian circuit visits 5 nodes (start counted once more at the end).
    assert len(circuit) == 5


def test_cover_group_with_unknown_group_returns_entry_only(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    entry = svc.nearest_node(0.0, 0.0)
    assert svc.cover_group("does-not-exist", entry) == [entry]


def test_route_between_reports_ok_and_distance(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    result = svc.route_between(0.0, 0.0, 10.0, 10.0)
    assert result["ok"] is True
    assert result["total_distance_m"] == pytest.approx(20.0)
    assert result["waypoint_count"] == len(result["waypoints"])


def test_route_between_unreachable_reports_not_ok(tmp_path):
    roads = [
        _road("island_a", (0, 0, 0), (1, 0, 0), group="a"),
        _road("island_b", (100, 100, 0), (101, 100, 0), group="b"),
    ]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    result = svc.route_between(0, 0, 100, 100)
    assert result["ok"] is False
    assert "error" in result


def test_route_to_then_around_then_back_composes_legs(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    result = svc.route_to_then_around_then_back(0.0, 0.0, "loop")
    assert result["ok"] is True
    assert [leg["name"] for leg in result["legs"]] == [
        "transit_to_group",
        "cover_group",
        "return_to_start",
    ]
    assert result["total_distance_m"] == pytest.approx(
        sum(leg["distance_m"] for leg in result["legs"])
    )


def test_route_to_then_around_then_back_unknown_group_reports_error(tmp_path):
    svc = RoadGraphService(scene_path=_square_loop_scene(tmp_path))
    result = svc.route_to_then_around_then_back(0.0, 0.0, "does-not-exist")
    assert result["ok"] is False
    assert "error" in result


def test_t_junction_split_connects_interior_touch_point(tmp_path):
    """A connector road touching the midpoint of a longer road must split that
    road into two segments so the connector's endpoint becomes a real node —
    otherwise the scene produces disconnected components (the bug this pass
    guards against, per the module docstring)."""
    roads = [
        _road("main", (0, 0, 0), (10, 0, 0), group="g"),
        _road("connector", (5, 0, 0), (5, 5, 0), group="g"),
    ]
    svc = RoadGraphService(scene_path=_write_scene(tmp_path, roads))
    # Without the split, "main" would be one edge between (0,0) and (10,0),
    # and "connector"'s (5,0) endpoint would be an unconnected duplicate node.
    assert svc.node_count == 4
    assert svc.edge_count == 3
    start = svc.nearest_node(0, 0)
    tip = svc.nearest_node(5, 5)
    path = svc.shortest_path(start, tip)
    assert path != []
    assert svc.path_length_m(path) == pytest.approx(10.0)
