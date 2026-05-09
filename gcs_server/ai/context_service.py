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

    async def build_compact_context(self, user_message: str = "", session_id: str = "") -> AIContextSnapshot:
        providers = [
            "get_current_rover_state",
            "get_runtime_context",
            "get_settings_context",
            "get_llm_context",
            "get_current_mission_state",
            "get_scene_map_summary",
        ]
        rover = await self.get_current_rover_state()
        runtime = await self.get_runtime_context()
        settings = self.get_settings_context()
        llm = self.get_llm_context(session_id=session_id)
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
            "settings": settings,
            "llm": llm,
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

    def get_settings_context(self) -> dict[str, Any]:
        config = self._runtime.config
        return {
            "settings_path": str(config.settings_path),
            "mqtt": _pick(
                config.mqtt,
                [
                    "broker_host",
                    "broker_port",
                    "topic_prefix",
                    "client_id",
                    "control_topic",
                    "state_topic",
                    "camera_topic",
                    "control_hz",
                    "telemetry_hz",
                    "telemetry_policy",
                    "gcs_presence_topic",
                    "gcs_presence_timeout_ms",
                    "failsafe_timeout_ms",
                    "control_mode",
                    "digital_throttle_step",
                    "digital_steer_step",
                    "video_endpoint",
                ],
            ),
            "key_bindings": _safe_mapping(config.key_bindings),
            "video": _pick(config.video, ["enabled", "ingest_mode", "delivery_mode"]),
            "gcs": _pick(config.gcs, ["host", "port", "state_backend", "controller_lock_backend", "telemetry_stale_ms"]),
            "simulation": _pick(config.simulation, ["backend", "backend_version", "available_backends"]),
            "map": _pick(config.map, ["site_name", "default_center_lat", "default_center_lon", "default_zoom"]),
            "ai_settings": {
                "tts": _pick(
                    (config.ai_settings.get("tts") or {}) if isinstance(config.ai_settings, dict) else {},
                    ["enabled", "engine", "auto_read", "service_url", "voice", "format", "speed", "browser_fallback", "voice_name", "rate", "pitch"],
                )
            },
        }

    def get_llm_context(self, session_id: str = "") -> dict[str, Any]:
        config = self._runtime.config
        providers = [provider for provider in config.llm_providers if isinstance(provider, dict)]
        routing = config.model_routing if isinstance(config.model_routing, dict) else {}
        session = self._ai_session(session_id)
        session_provider_id = str((session or {}).get("provider_id") or "").strip()
        resolved_provider, resolved_source, resolution_note = _resolve_chat_provider(
            providers,
            routing,
            session_provider_id=session_provider_id,
        )
        return {
            "session": {
                "id": session_id,
                "provider_id": session_provider_id,
                "has_provider_override": bool(session_provider_id),
            },
            "model_routing": _safe_mapping(routing),
            "general_chat_route": _safe_mapping(routing.get("general_chat") or {}),
            "active_chat_provider": self._safe_llm_provider(resolved_provider) if resolved_provider else None,
            "active_chat_provider_source": resolved_source,
            "active_chat_provider_note": resolution_note,
            "providers": [self._safe_llm_provider(provider) for provider in providers],
        }

    def _ai_session(self, session_id: str) -> dict[str, Any] | None:
        clean = str(session_id or "").strip()
        if not clean or not hasattr(self._runtime, "ai_store"):
            return None
        try:
            return self._runtime.ai_store.get_session(clean, include_messages=False)
        except Exception:
            return None

    def _safe_llm_provider(self, provider: dict[str, Any]) -> dict[str, Any]:
        auth_mode = str(provider.get("auth_mode", "env_var"))
        secret_ref = str(provider.get("secret_ref", "")).strip()
        has_stored_secret = False
        if auth_mode == "stored_secret" and secret_ref and hasattr(self._runtime, "secret_store"):
            try:
                has_stored_secret = bool(self._runtime.secret_store.has_secret(secret_ref))
            except Exception:
                has_stored_secret = False
        return {
            "id": provider.get("id", ""),
            "display_name": provider.get("display_name", ""),
            "provider_type": provider.get("provider_type", ""),
            "model_id": provider.get("model_id", ""),
            "base_url": provider.get("base_url", ""),
            "enabled": provider.get("enabled", True),
            "capabilities": list(provider.get("capabilities") or []),
            "auth_mode": auth_mode,
            "auth": {
                "uses_secret": auth_mode in {"env_var", "stored_secret"},
                "secret_ref_configured": bool(secret_ref),
                "has_stored_secret": has_stored_secret,
            },
            "last_check": _pick(provider.get("last_check") or {}, ["status", "ok", "checked_at"]),
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


def _pick(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source.get(key) for key in keys if key in source}


def _safe_mapping(source: Any) -> dict[str, Any]:
    return dict(source) if isinstance(source, dict) else {}


def _resolve_chat_provider(
    providers: list[dict[str, Any]],
    routing: dict[str, Any],
    *,
    session_provider_id: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    if session_provider_id:
        provider = _find_provider(providers, session_provider_id)
        if provider is None:
            return None, "session_override", "session provider override was not found"
        if not provider.get("enabled", True):
            return provider, "session_override", "session provider override is disabled"
        return provider, "session_override", ""

    rule = routing.get("general_chat", {}) if isinstance(routing, dict) else {}
    if isinstance(rule, dict):
        candidate_ids = [
            str(rule.get("primary_provider_id", "")).strip(),
            *[str(item).strip() for item in rule.get("fallback_provider_ids", []) if str(item).strip()],
        ]
        for provider_id in candidate_ids:
            provider = _find_provider(providers, provider_id)
            if provider and provider.get("enabled", True):
                return provider, "general_chat_route", ""

    provider = next((item for item in providers if item.get("enabled", True)), None)
    return provider, "first_enabled_provider" if provider else "none", "" if provider else "no enabled provider is configured"


def _find_provider(providers: list[dict[str, Any]], provider_id: str) -> dict[str, Any] | None:
    clean = str(provider_id or "").strip()
    if not clean:
        return None
    return next((provider for provider in providers if str(provider.get("id")) == clean), None)


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
