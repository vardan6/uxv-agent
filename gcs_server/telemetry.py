from __future__ import annotations

import copy
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(default)


def normalize_telemetry(payload: dict[str, Any] | None, backend_type: str) -> dict[str, Any]:
    raw = copy.deepcopy(payload or {})
    position = raw.get("position") or {}
    gps = raw.get("gps") or {}
    orientation = raw.get("orientation") or {}
    speed = raw.get("speed") or {}
    camera = raw.get("camera") or {}
    power = raw.get("power") or {}
    georeference = raw.get("georeference") or {}

    normalized = {
        "timestamp": _num(raw.get("timestamp"), 0.0),
        "backend": str(raw.get("backend") or backend_type),
        "position": {
            "x": _num(position.get("x")),
            "y": _num(position.get("y")),
            "z": _num(position.get("z")),
        },
        "gps": {
            "lat": _num(gps.get("lat")),
            "lon": _num(gps.get("lon")),
            "alt": _num(gps.get("alt")),
        },
        "orientation": {
            "heading_deg": _num(orientation.get("heading_deg")),
        },
        "speed": {
            "m_s": _num(speed.get("m_s")),
            "km_h": _num(speed.get("km_h")),
        },
        "camera": {
            "mode": str(camera.get("mode") or ""),
            "video_endpoint": str(camera.get("video_endpoint") or ""),
        },
        "power": {
            "battery_pct": _num(power.get("battery_pct")),
            "voltage_v": _num(power.get("voltage_v")),
            "current_a": _num(power.get("current_a")),
            "temperature_c": _num(power.get("temperature_c")),
        },
        "georeference": copy.deepcopy(georeference),
    }
    normalized["map_pose"] = {
        "lat": normalized["gps"]["lat"],
        "lon": normalized["gps"]["lon"],
        "alt": normalized["gps"]["alt"],
        "heading_deg": normalized["orientation"]["heading_deg"],
    }
    return normalized
