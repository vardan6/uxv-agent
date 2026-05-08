from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any

try:
    from gcs_server.scene_map import get_scene_map_payload
except ModuleNotFoundError:
    from scene_map import get_scene_map_payload


@dataclass(frozen=True, slots=True)
class AIContextSnapshot:
    prompt: str
    meta: dict[str, Any]


class AIContextService:
    def __init__(self, runtime: Any):
        self._runtime = runtime

    async def build_compact_context(self, user_message: str = "") -> AIContextSnapshot:
        providers = [
            "get_current_rover_state",
            "get_runtime_context",
            "get_current_mission_state",
            "get_scene_map_summary",
        ]
        rover = await self.get_current_rover_state()
        runtime = await self.get_runtime_context()
        mission = self.get_current_mission_state()
        scene = self.get_scene_map_summary()
        details: dict[str, Any] = {}

        lower = user_message.lower()
        if "in front" in lower or "ahead" in lower:
            max_distance, fov = _parse_front_query(lower)
            details["objects_in_front"] = self.find_objects_in_front(
                max_distance_m=max_distance,
                fov_deg=fov,
                rover_state=rover,
            )
            providers.append("find_objects_in_front")
        if "near" in lower and ("object" in lower or "rover" in lower):
            radius = _parse_radius_query(lower, default=50.0)
            details["objects_near_rover"] = self.find_objects_near_rover(radius_m=radius, rover_state=rover)
            providers.append("find_objects_near_rover")
        kind = _parse_kind_query(lower)
        if kind:
            details["objects_by_kind"] = self.find_objects_by_kind(kind)
            providers.append("find_objects_by_kind")
        if "recent" in lower or "happened" in lower:
            details["current_replay"] = self.get_current_replay_summary()
            details["recent_telemetry"] = self.get_recent_telemetry(seconds=120, limit=10)
            providers.extend(["get_current_replay_summary", "get_recent_telemetry"])

        context = {
            "generated_at": time.time(),
            "rover": rover,
            "runtime": runtime,
            "mission": mission,
            "scene": scene,
            "details": details,
        }
        return AIContextSnapshot(
            prompt=_format_context_block(context),
            meta={
                "context_snapshot": context,
                "context_providers": sorted(set(providers)),
            },
        )

    async def get_current_rover_state(self) -> dict[str, Any]:
        snapshot = await self._runtime.state_store.snapshot()
        telemetry = snapshot.get("telemetry") or {}
        broker = snapshot.get("broker") or {}
        return {
            "telemetry_fresh": not bool(broker.get("telemetry_stale", True)),
            "last_telemetry_ts": broker.get("last_telemetry_ts") or 0.0,
            "telemetry_age_s": _age_seconds(broker.get("last_telemetry_ts")),
            "backend": telemetry.get("backend") or self._runtime.config.simulation.get("backend", ""),
            "position": telemetry.get("position") or {},
            "gps": telemetry.get("gps") or {},
            "heading_deg": (telemetry.get("orientation") or {}).get("heading_deg"),
            "speed": telemetry.get("speed") or {},
            "battery": telemetry.get("power") or {},
            "camera": telemetry.get("camera") or {},
            "camera_fresh": not bool(broker.get("camera_stale", True)),
            "last_camera_ts": broker.get("last_camera_ts") or 0.0,
            "camera_age_s": _age_seconds(broker.get("last_camera_ts")),
        }

    async def get_runtime_context(self) -> dict[str, Any]:
        snapshot = await self._runtime.state_store.snapshot()
        return {
            "broker": snapshot.get("broker") or {},
            "controller": snapshot.get("controller") or {},
            "video": _without_latest_frame(snapshot.get("video") or {}),
            "simulation": dict(self._runtime.config.simulation),
            "map": dict(self._runtime.config.map),
            "replay_session_id": self._runtime.replay_store.current_session_id,
        }

    def get_scene_map_summary(self) -> dict[str, Any]:
        backend = str(self._runtime.config.simulation.get("backend") or "3d-env")
        try:
            scene = get_scene_map_payload(backend=backend, grid_size=32)
        except ValueError as exc:
            return {"available": False, "backend": backend, "error": str(exc)}
        kinds: dict[str, int] = {}
        for obj in scene.get("objects", []):
            kind = str(obj.get("kind") or "unknown")
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "available": True,
            "backend": scene.get("backend"),
            "source_path": scene.get("source_path"),
            "terrain_size": scene.get("terrain_size"),
            "bounds": scene.get("bounds"),
            "road_count": len(scene.get("roads") or []),
            "object_count": len(scene.get("objects") or []),
            "object_kinds": kinds,
            "spawn": scene.get("spawn"),
            "site_name": str(self._runtime.config.map.get("site_name", "default-site")),
        }

    def find_objects_in_front(
        self,
        max_distance_m: float = 100.0,
        fov_deg: float = 20.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rover = rover_state or {}
        pose = _rover_pose(rover)
        if pose is None:
            return {"available": False, "reason": "rover pose is unavailable"}
        objects = self._scene_objects()
        matches = []
        half_fov = max(0.0, float(fov_deg)) / 2.0
        for obj in objects:
            center = obj.get("center") or {}
            dx = float(center.get("x") or 0.0) - pose["x"]
            dy = float(center.get("y") or 0.0) - pose["y"]
            distance = math.hypot(dx, dy)
            if distance > max_distance_m:
                continue
            bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
            delta = _angle_delta_deg(bearing, pose["heading_deg"])
            if abs(delta) <= half_fov:
                matches.append(_object_hit(obj, distance, bearing, delta))
        matches.sort(key=lambda item: item["distance_m"])
        return {
            "available": True,
            "query": {"max_distance_m": max_distance_m, "fov_deg": fov_deg},
            "rover_pose": pose,
            "objects": matches,
        }

    def find_objects_near_rover(
        self,
        radius_m: float = 50.0,
        rover_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rover = rover_state or {}
        pose = _rover_pose(rover)
        if pose is None:
            return {"available": False, "reason": "rover pose is unavailable"}
        matches = []
        for obj in self._scene_objects():
            center = obj.get("center") or {}
            distance = math.hypot(
                float(center.get("x") or 0.0) - pose["x"],
                float(center.get("y") or 0.0) - pose["y"],
            )
            if distance <= radius_m:
                matches.append(_object_hit(obj, distance, None, None))
        matches.sort(key=lambda item: item["distance_m"])
        return {"available": True, "query": {"radius_m": radius_m}, "rover_pose": pose, "objects": matches}

    def find_objects_by_kind(self, kind: str) -> dict[str, Any]:
        clean = kind.strip().lower()
        matches = [
            _object_hit(obj, None, None, None)
            for obj in self._scene_objects()
            if str(obj.get("kind") or "").lower() == clean
        ]
        return {"available": True, "query": {"kind": clean}, "objects": matches}

    def get_current_replay_summary(self) -> dict[str, Any]:
        current_id = self._runtime.replay_store.current_session_id
        if not current_id:
            return {"active": False, "session_id": None}
        summary = self._runtime.replay_store.get_session_summary(current_id)
        return {"active": True, **(summary or {"session_id": current_id})}

    def get_recent_telemetry(self, seconds: int = 120, limit: int = 20) -> list[dict[str, Any]]:
        return self._runtime.replay_store.get_recent_telemetry(seconds=seconds, limit=limit)

    def get_current_mission_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "status": "no_active_mission",
            "summary": "No mission storage or active mission is implemented yet.",
        }

    def _scene_objects(self) -> list[dict[str, Any]]:
        backend = str(self._runtime.config.simulation.get("backend") or "3d-env")
        try:
            return list(get_scene_map_payload(backend=backend, grid_size=32).get("objects") or [])
        except ValueError:
            return []


def _format_context_block(context: dict[str, Any]) -> str:
    return (
        "Live GCS current context. Treat these structured facts as more current than conversation history. "
        "This chat is read-only and must not publish control commands.\n"
        f"{json.dumps(context, separators=(',', ':'), sort_keys=True)}"
    )


def _without_latest_frame(video: dict[str, Any]) -> dict[str, Any]:
    out = dict(video)
    latest = out.pop("latest_frame", None) or {}
    if latest:
        out["latest_frame_meta"] = {
            key: value
            for key, value in latest.items()
            if key not in {"data", "payload", "jpeg"}
        }
    return out


def _age_seconds(ts: Any) -> float | None:
    try:
        value = float(ts or 0.0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(0.0, time.time() - value)


def _rover_pose(rover: dict[str, Any]) -> dict[str, float] | None:
    pos = rover.get("position") or {}
    try:
        return {
            "x": float(pos.get("x")),
            "y": float(pos.get("y")),
            "z": float(pos.get("z") or 0.0),
            "heading_deg": float(rover.get("heading_deg") or 0.0) % 360.0,
        }
    except (TypeError, ValueError):
        return None


def _angle_delta_deg(target: float, heading: float) -> float:
    return ((target - heading + 540.0) % 360.0) - 180.0


def _object_hit(
    obj: dict[str, Any],
    distance: float | None,
    bearing: float | None,
    delta: float | None,
) -> dict[str, Any]:
    hit = {
        "id": obj.get("id"),
        "kind": obj.get("kind"),
        "label": obj.get("label"),
        "center": obj.get("center"),
        "size": obj.get("size"),
    }
    if distance is not None:
        hit["distance_m"] = round(distance, 2)
    if bearing is not None:
        hit["bearing_deg"] = round(bearing, 1)
    if delta is not None:
        hit["relative_bearing_deg"] = round(delta, 1)
    return hit


def _parse_front_query(text: str) -> tuple[float, float]:
    distance = _parse_radius_query(text, default=100.0)
    fov_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:degree|deg)", text)
    fov = float(fov_match.group(1)) if fov_match else 20.0
    return distance, fov


def _parse_radius_query(text: str, default: float) -> float:
    match = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(?:m|meter|meters)", text)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|meters)", text)
    return float(match.group(1)) if match else default


def _parse_kind_query(text: str) -> str:
    match = re.search(r"(?:kind|type)\s+([a-z0-9_-]+)", text)
    return match.group(1) if match else ""
