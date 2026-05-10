from __future__ import annotations

from ai.spatial_query_service import SpatialQueryService


def _scene() -> dict:
    return {
        "backend": "test",
        "roads": [],
        "objects": [
            {"id": "north_tree", "kind": "tree", "label": "North tree", "center": {"x": 0, "y": 10, "z": 0}, "size": {}},
            {"id": "east_rock", "kind": "rock", "label": "East rock", "center": {"x": 10, "y": 0, "z": 0}, "size": {}},
            {"id": "south_tree", "kind": "tree", "label": "South tree", "center": {"x": 0, "y": -10, "z": 0}, "size": {}},
            {"id": "west_barrel", "kind": "barrel", "label": "West barrel", "center": {"x": -10, "y": 0, "z": 0}, "size": {}},
            {"id": "near_rock", "kind": "rock", "label": "Near rock", "center": {"x": 0, "y": 3, "z": 0}, "size": {}},
        ],
    }


def _rover(heading: float = 0.0) -> dict:
    return {"position": {"x": 0, "y": 0, "z": 0}, "heading_deg": heading}


def test_front_query_cardinal_headings() -> None:
    service = SpatialQueryService()

    assert _ids(service.find_objects_in_front(_scene(), _rover(0), fov_deg=30)) == ["near_rock", "north_tree"]
    assert _ids(service.find_objects_in_front(_scene(), _rover(90), fov_deg=30)) == ["east_rock"]
    assert _ids(service.find_objects_in_front(_scene(), _rover(180), fov_deg=30)) == ["south_tree"]
    assert _ids(service.find_objects_in_front(_scene(), _rover(270), fov_deg=30)) == ["west_barrel"]


def test_heading_wraparound_near_zero_and_360() -> None:
    service = SpatialQueryService()
    scene = {"objects": [{"id": "wrap", "kind": "marker", "center": {"x": -0.87, "y": 10, "z": 0}, "size": {}}]}

    assert _ids(service.find_objects_in_front(scene, _rover(358), fov_deg=10)) == ["wrap"]
    assert _ids(service.find_objects_in_front(scene, _rover(2), fov_deg=10)) == []


def test_left_right_classification() -> None:
    service = SpatialQueryService()

    assert _ids(service.find_objects_to_left(_scene(), _rover(0), angle_width_deg=100)) == ["west_barrel"]
    assert _ids(service.find_objects_to_right(_scene(), _rover(0), angle_width_deg=100)) == ["east_rock"]


def test_sector_filtering() -> None:
    service = SpatialQueryService()

    result = service.find_objects_in_sector(_scene(), _rover(0), center_relative_bearing_deg=90, fov_deg=40, max_distance_m=20)

    assert _ids(result) == ["east_rock"]


def test_kind_filtering() -> None:
    service = SpatialQueryService()

    result = service.find_objects_near(_scene(), _rover(0), radius_m=20, kinds=["tree"])

    assert _ids(result) == ["north_tree", "south_tree"]


def test_nearest_object_ranking() -> None:
    service = SpatialQueryService()

    result = service.find_nearest_objects(_scene(), _rover(0), limit=3)

    assert _ids(result) == ["near_rock", "north_tree", "east_rock"]


def test_unavailable_rover_pose() -> None:
    service = SpatialQueryService()

    result = service.find_objects_in_front(_scene(), {"position": {"x": 0, "y": 0}}, fov_deg=30)

    assert result["available"] is False
    assert "pose" in result["reason"]


def test_empty_scene_payload() -> None:
    service = SpatialQueryService()

    summary = service.get_scene_summary(None)
    objects = service.find_objects_near(None, _rover(0), radius_m=20)

    assert summary["available"] is False
    assert objects["available"] is True
    assert objects["objects"] == []


def _ids(result: dict) -> list[str]:
    return [obj["id"] for obj in result["objects"]]
