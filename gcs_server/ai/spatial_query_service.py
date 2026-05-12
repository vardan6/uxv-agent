from __future__ import annotations

import math
from typing import Any


class SpatialQueryService:
    def get_scene_summary(self, scene: dict[str, Any] | None) -> dict[str, Any]:
        if scene is None:
            return {"available": False, "error": "scene payload unavailable"}
        kinds: dict[str, int] = {}
        for obj in _objects(scene):
            kind = str(obj.get("kind") or "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "available": True,
            "backend": scene.get("backend"),
            "source_path": scene.get("source_path"),
            "terrain_size": scene.get("terrain_size"),
            "bounds": scene.get("bounds"),
            "road_count": len(scene.get("roads") or []),
            "object_count": len(_objects(scene)),
            "object_kinds": kinds,
            "spawn": scene.get("spawn"),
        }

    def find_objects_in_front(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        max_distance_m: float = 100.0,
        fov_deg: float = 20.0,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.find_objects_in_sector(
            scene,
            rover_state,
            center_relative_bearing_deg=0.0,
            fov_deg=fov_deg,
            max_distance_m=max_distance_m,
            kinds=kinds,
        )

    def find_objects_near(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        radius_m: float = 50.0,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        pose = _rover_position(rover_state)
        if pose is None:
            return {"available": False, "reason": "rover position is unavailable"}
        radius = max(0.0, _float(radius_m, 50.0))
        matches = [
            _object_hit(obj, pose)
            for obj in _objects(scene)
            if _kind_allowed(obj, kinds) and _distance_to(obj, pose) <= radius
        ]
        matches.sort(key=lambda item: item["distance_m"])
        return {
            "available": True,
            "query": {"radius_m": radius, "kinds": _clean_kinds(kinds)},
            "rover_pose": pose,
            "objects": matches,
        }

    def find_objects_by_kind(self, scene: dict[str, Any] | None, kind: str) -> dict[str, Any]:
        clean = str(kind or "").strip().lower()
        matches = [_object_hit(obj, None) for obj in _objects(scene) if str(obj.get("kind") or "").lower() == clean]
        return {"available": True, "query": {"kind": clean}, "objects": matches}

    def find_objects_to_left(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.find_objects_in_sector(scene, rover_state, -90.0, angle_width_deg, max_distance_m, kinds)

    def find_objects_to_right(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        max_distance_m: float = 100.0,
        angle_width_deg: float = 90.0,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.find_objects_in_sector(scene, rover_state, 90.0, angle_width_deg, max_distance_m, kinds)

    def find_nearest_objects(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        limit: int = 5,
        max_distance_m: float | None = None,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        pose = _rover_position(rover_state)
        if pose is None:
            return {"available": False, "reason": "rover position is unavailable"}
        max_distance = None if max_distance_m is None else max(0.0, _float(max_distance_m, 0.0))
        matches = []
        for obj in _objects(scene):
            distance = _distance_to(obj, pose)
            if max_distance is not None and distance > max_distance:
                continue
            if _kind_allowed(obj, kinds):
                matches.append(_object_hit(obj, pose))
        matches.sort(key=lambda item: item["distance_m"])
        count = max(1, int(limit or 5))
        return {
            "available": True,
            "query": {"limit": count, "max_distance_m": max_distance, "kinds": _clean_kinds(kinds)},
            "rover_pose": pose,
            "objects": matches[:count],
        }

    def find_objects_in_sector(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        center_relative_bearing_deg: float,
        fov_deg: float,
        max_distance_m: float,
        kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        pose = _rover_pose(rover_state)
        if pose is None:
            return {"available": False, "reason": "rover pose or heading is unavailable"}
        center = _float(center_relative_bearing_deg, 0.0)
        half_fov = max(0.0, _float(fov_deg, 20.0)) / 2.0
        max_distance = max(0.0, _float(max_distance_m, 100.0))
        matches = []
        for obj in _objects(scene):
            hit = _object_hit(obj, pose)
            if hit["distance_m"] > max_distance:
                continue
            if not _kind_allowed(obj, kinds):
                continue
            if abs(_angle_delta_deg(hit["relative_bearing_deg"], center)) <= half_fov:
                matches.append(hit)
        matches.sort(key=lambda item: item["distance_m"])
        return {
            "available": True,
            "query": {
                "center_relative_bearing_deg": center,
                "fov_deg": half_fov * 2.0,
                "max_distance_m": max_distance,
                "kinds": _clean_kinds(kinds),
            },
            "rover_pose": pose,
            "objects": matches,
        }

    def resolve_target_description(
        self,
        scene: dict[str, Any] | None,
        rover_state: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any]:
        clean_target = dict(target or {})
        kinds = [clean_target["kind"]] if str(clean_target.get("kind") or "").strip() else None
        max_distance = clean_target.get("max_distance_m")
        max_distance_m = _float(max_distance, 100.0) if max_distance is not None else 100.0
        side = str(clean_target.get("side") or "").strip().lower()
        if side == "front":
            result = self.find_objects_in_front(scene, rover_state, max_distance_m=max_distance_m, kinds=kinds)
        elif side == "left":
            result = self.find_objects_to_left(scene, rover_state, max_distance_m=max_distance_m, kinds=kinds)
        elif side == "right":
            result = self.find_objects_to_right(scene, rover_state, max_distance_m=max_distance_m, kinds=kinds)
        elif clean_target.get("relative_bearing_deg") is not None:
            result = self.find_objects_in_sector(
                scene,
                rover_state,
                center_relative_bearing_deg=_float(clean_target.get("relative_bearing_deg"), 0.0),
                fov_deg=30.0,
                max_distance_m=max_distance_m,
                kinds=kinds,
            )
        else:
            result = self.find_nearest_objects(scene, rover_state, limit=5, max_distance_m=max_distance_m, kinds=kinds)

        min_distance = clean_target.get("min_distance_m")
        if min_distance is not None and isinstance(result.get("objects"), list):
            floor = _float(min_distance, 0.0)
            result = dict(result)
            result["objects"] = [obj for obj in result["objects"] if float(obj.get("distance_m") or 0.0) >= floor]

        candidates = result.get("objects") if isinstance(result.get("objects"), list) else []
        return {
            "available": bool(result.get("available")),
            "target": clean_target,
            "query_result": result,
            "candidates": candidates,
            "selected": candidates[0] if candidates else None,
            "needs_clarification": len(candidates) != 1,
        }


def _objects(scene: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(scene, dict):
        return []
    return [obj for obj in list(scene.get("objects") or []) if isinstance(obj, dict)]


def _rover_pose(rover: dict[str, Any] | None) -> dict[str, float] | None:
    pose = _rover_position(rover)
    if pose is None:
        return None
    heading_raw = rover.get("heading_deg")
    if heading_raw is None:
        return None
    try:
        heading = float(heading_raw) % 360.0
    except (TypeError, ValueError):
        return None
    return {**pose, "heading_deg": heading}


def _rover_position(rover: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(rover, dict):
        return None
    pos = rover.get("position") or {}
    try:
        x = float(pos["x"])
        y = float(pos["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"x": x, "y": y, "z": float(pos.get("z") or 0.0)}


def _object_hit(obj: dict[str, Any], pose: dict[str, float] | None) -> dict[str, Any]:
    hit = {
        "id": obj.get("id"),
        "kind": obj.get("kind"),
        "label": obj.get("label"),
        "center": obj.get("center"),
        "size": obj.get("size"),
    }
    if pose is None:
        return hit
    center = obj.get("center") or {}
    dx = float(center.get("x") or 0.0) - pose["x"]
    dy = float(center.get("y") or 0.0) - pose["y"]
    distance = math.hypot(dx, dy)
    bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    hit["distance_m"] = round(distance, 2)
    hit["bearing_deg"] = round(bearing, 1)
    heading = pose.get("heading_deg")
    if heading is not None:
        relative = _angle_delta_deg(bearing, float(heading))
        hit["relative_bearing_deg"] = round(relative, 1)
        hit["side"] = _side_for_relative_bearing(relative)
        hit["sector"] = _sector_for_relative_bearing(relative)
    return hit


def _distance_to(obj: dict[str, Any], pose: dict[str, float]) -> float:
    center = obj.get("center") or {}
    return math.hypot(float(center.get("x") or 0.0) - pose["x"], float(center.get("y") or 0.0) - pose["y"])


def _angle_delta_deg(target: float, heading: float) -> float:
    return ((target - heading + 540.0) % 360.0) - 180.0


def _side_for_relative_bearing(relative: float) -> str:
    if abs(relative) <= 45.0:
        return "front"
    if abs(relative) >= 135.0:
        return "behind"
    return "right" if relative > 0.0 else "left"


def _sector_for_relative_bearing(relative: float) -> str:
    if abs(relative) <= 22.5:
        return "front"
    if 22.5 < relative <= 67.5:
        return "front_right"
    if 67.5 < relative <= 112.5:
        return "right"
    if 112.5 < relative < 157.5:
        return "back_right"
    if -67.5 <= relative < -22.5:
        return "front_left"
    if -112.5 <= relative < -67.5:
        return "left"
    if -157.5 < relative < -112.5:
        return "back_left"
    return "behind"


def _kind_allowed(obj: dict[str, Any], kinds: list[str] | str | None) -> bool:
    allowed = _clean_kinds(kinds)
    if not allowed:
        return True
    return str(obj.get("kind") or "").strip().lower() in allowed


def _clean_kinds(kinds: list[str] | str | None) -> list[str]:
    raw = [kinds] if isinstance(kinds, str) else list(kinds or [])
    return sorted({str(kind).strip().lower() for kind in raw if str(kind).strip()})


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
