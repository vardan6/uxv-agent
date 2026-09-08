from __future__ import annotations

from ai.mission_safety import (
    FencePoint,
    Geofence,
    RallyPoint,
    parse_geofence,
    validate_waypoints,
)


def _square_fence(min_alt=None, max_alt=None) -> Geofence:
    return Geofence(
        polygon=[
            FencePoint(lat=0.0, lon=0.0),
            FencePoint(lat=0.0, lon=10.0),
            FencePoint(lat=10.0, lon=10.0),
            FencePoint(lat=10.0, lon=0.0),
        ],
        min_alt=min_alt,
        max_alt=max_alt,
    )


def _wp(lat: float, lon: float, alt: float = 0.0) -> dict:
    return {"lat": lat, "lon": lon, "alt": alt}


def test_geofence_is_usable_requires_three_vertices():
    assert Geofence().is_usable is False
    assert Geofence(polygon=[FencePoint(0, 0), FencePoint(1, 1)]).is_usable is False
    assert _square_fence().is_usable is True


def test_geofence_to_dict_omits_unset_alt_band():
    fence = _square_fence()
    out = fence.to_dict()
    assert "min_alt" not in out
    assert "max_alt" not in out
    assert out["polygon"] == [
        {"lat": 0.0, "lon": 0.0},
        {"lat": 0.0, "lon": 10.0},
        {"lat": 10.0, "lon": 10.0},
        {"lat": 10.0, "lon": 0.0},
    ]

    banded = _square_fence(min_alt=1.5, max_alt=50.0)
    out2 = banded.to_dict()
    assert out2["min_alt"] == 1.5
    assert out2["max_alt"] == 50.0


def test_rally_point_to_dict_defaults_alt():
    assert RallyPoint(lat=1.0, lon=2.0).to_dict() == {"lat": 1.0, "lon": 2.0, "alt": 0.0}


def test_parse_geofence_round_trips_to_dict():
    fence = _square_fence(min_alt=1.0, max_alt=20.0)
    fence.rally_points.append(RallyPoint(lat=5.0, lon=5.0, alt=3.0))
    parsed = parse_geofence(fence.to_dict())
    assert parsed.to_dict() == fence.to_dict()


def test_parse_geofence_drops_malformed_entries():
    data = {
        "polygon": [
            {"lat": 0.0, "lon": 0.0},
            "not-a-dict",
            {"lat": "bad", "lon": 1.0},
            {"lon": 1.0},  # missing lat
            {"lat": 1.0, "lon": 1.0},
        ],
        "rally_points": [{"lat": 2.0, "lon": 2.0}, "junk"],
    }
    parsed = parse_geofence(data)
    assert parsed.polygon == [FencePoint(0.0, 0.0), FencePoint(1.0, 1.0)]
    assert parsed.rally_points == [RallyPoint(2.0, 2.0, 0.0)]


def test_parse_geofence_rejects_non_dict_input():
    assert parse_geofence(None) == Geofence()
    assert parse_geofence("not-a-dict") == Geofence()
    assert parse_geofence([1, 2, 3]) == Geofence()


def test_validate_waypoints_missing_fence_fails_closed():
    violations = validate_waypoints([_wp(5.0, 5.0)], None)
    assert len(violations) == 1
    assert violations[0].reason == "no_fence"


def test_validate_waypoints_unusable_fence_fails_closed():
    tiny = Geofence(polygon=[FencePoint(0, 0), FencePoint(1, 1)])
    violations = validate_waypoints([_wp(0.5, 0.5)], tiny)
    assert [v.reason for v in violations] == ["no_fence"]


def test_validate_waypoints_inside_polygon_and_alt_band_is_clean():
    fence = _square_fence(min_alt=1.0, max_alt=10.0)
    violations = validate_waypoints([_wp(5.0, 5.0, alt=5.0)], fence)
    assert violations == []


def test_validate_waypoints_outside_polygon():
    fence = _square_fence()
    violations = validate_waypoints([_wp(20.0, 20.0)], fence)
    assert len(violations) == 1
    assert violations[0].reason == "outside_polygon"


def test_validate_waypoints_below_and_above_alt_band():
    fence = _square_fence(min_alt=2.0, max_alt=8.0)
    violations = validate_waypoints(
        [_wp(5.0, 5.0, alt=1.0), _wp(5.0, 5.0, alt=9.0)], fence
    )
    assert [v.reason for v in violations] == ["below_min_alt", "above_max_alt"]


def test_validate_waypoints_reports_index_and_coordinates():
    fence = _square_fence()
    violations = validate_waypoints(
        [_wp(5.0, 5.0), _wp(50.0, 50.0)], fence
    )
    assert len(violations) == 1
    violation = violations[0]
    assert violation.index == 1
    assert violation.lat == 50.0
    assert violation.lon == 50.0
    assert violation.to_dict() == {
        "index": 1,
        "reason": "outside_polygon",
        "lat": 50.0,
        "lon": 50.0,
        "alt": 0.0,
    }
