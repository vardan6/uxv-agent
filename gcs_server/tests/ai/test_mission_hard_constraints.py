from __future__ import annotations

from ai import mission_tree
from ai.coordinate_frame import Origin, local_to_wgs84
from ai.mission_execution_service import _check_hard_constraints

ORIGIN = Origin(lat=0.0, lon=0.0, alt=0.0)


def _poly(corners_local: list[tuple[float, float]]) -> list[dict[str, float]]:
    """Build a WGS84 constraint polygon from local-metre corners through ORIGIN."""
    out = []
    for x, y in corners_local:
        lat, lon, _ = local_to_wgs84(x, y, 0.0, ORIGIN)
        out.append({"lat": lat, "lon": lon})
    return out


def _nav_node(points_local: list[tuple[float, float]]) -> mission_tree.Node:
    return mission_tree.Node(
        type=mission_tree.NAV_LEAF,
        waypoints=[{"x": x, "y": y, "z": 0.0} for x, y in points_local],
    )


class _FakeStore:
    def __init__(self, constraints: list[dict]) -> None:
        self._constraints = constraints

    def list_constraints(self) -> list[dict]:
        return self._constraints


def _blockage(corners, name="block"):
    return {"id": name, "name": name, "kind": "blockage", "rule": "hard", "enabled": True, "polygon": _poly(corners)}


def _corridor(corners, name="lane"):
    return {"id": name, "name": name, "kind": "allowed_corridor", "rule": "hard", "enabled": True, "polygon": _poly(corners)}


def test_no_hard_constraints_passes() -> None:
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    assert _check_hard_constraints(node, ORIGIN, _FakeStore([])) is None


def test_segment_crossing_blockage_is_rejected() -> None:
    # Both waypoints sit outside the blockage, but the leg between them cuts
    # through it — only a segment-level check catches this.
    block = _blockage([(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)])
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    msg = _check_hard_constraints(node, ORIGIN, _FakeStore([block]))
    assert msg is not None and "blockage" in msg


def test_route_clear_of_blockage_passes() -> None:
    block = _blockage([(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)])
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    assert _check_hard_constraints(node, ORIGIN, _FakeStore([block])) is None


def test_segment_leaving_corridor_union_gap_is_rejected() -> None:
    # Two corridors with a gap between x=12 and x=18. Both waypoints lie inside the
    # union, but the leg crosses the uncovered gap.
    left = _corridor([(-5.0, -2.0), (12.0, -2.0), (12.0, 2.0), (-5.0, 2.0)], name="left")
    right = _corridor([(18.0, -2.0), (35.0, -2.0), (35.0, 2.0), (18.0, 2.0)], name="right")
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    msg = _check_hard_constraints(node, ORIGIN, _FakeStore([left, right]))
    assert msg is not None and "corridor" in msg


def test_segment_within_corridor_passes() -> None:
    lane = _corridor([(-5.0, -2.0), (35.0, -2.0), (35.0, 2.0), (-5.0, 2.0)])
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    assert _check_hard_constraints(node, ORIGIN, _FakeStore([lane])) is None


def test_disabled_constraint_is_ignored() -> None:
    block = _blockage([(10.0, -5.0), (20.0, -5.0), (20.0, 5.0), (10.0, 5.0)])
    block["enabled"] = False
    node = _nav_node([(0.0, 0.0), (30.0, 0.0)])
    assert _check_hard_constraints(node, ORIGIN, _FakeStore([block])) is None
