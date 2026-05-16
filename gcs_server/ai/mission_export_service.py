"""QGC .plan mission exporter for approved MissionDrafts.

Converts an approved draft's waypoints into a QGroundControl-compatible
.plan JSON file at data/missions/<draft_id>.plan.

Coordinate projection: flat-earth from terrain_scene.v1.json georeference
(origin_lat / origin_lon / origin_alt). Good to ~10 m over the ~300 m scene.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    from gcs_server.ai.vehicle_profile import VehicleProfile, get_active_profile
except ModuleNotFoundError:
    from ai.vehicle_profile import VehicleProfile, get_active_profile

_SCENE_PATH = Path(__file__).resolve().parents[2] / "config" / "terrain_scene.v1.json"
_MISSIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "missions"

_MAV_CMD_NAV_WAYPOINT = 16
_MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
_FRAME_GLOBAL_RELATIVE_ALT = 3

_DEFAULT_ACCEPT_RADIUS_M = 2.0
_DEFAULT_HOLD_S = 0.0


def _load_georeference() -> dict[str, float]:
    scene = json.loads(_SCENE_PATH.read_text())
    geo = scene.get("coordinate_system", {}).get("georeference", {})
    return {
        "origin_lat": float(geo.get("origin_lat", 0.0)),
        "origin_lon": float(geo.get("origin_lon", 0.0)),
        "origin_alt": float(geo.get("origin_alt", 0.0)),
    }


def local_to_latlon(x: float, y: float, z: float, geo: dict[str, float]) -> tuple[float, float, float]:
    """Flat-earth projection from local metres to WGS84."""
    origin_lat = geo["origin_lat"]
    origin_lon = geo["origin_lon"]
    origin_alt = geo["origin_alt"]
    # 1 degree latitude ≈ 111 320 m
    lat = origin_lat + y / 111_320.0
    # 1 degree longitude ≈ 111 320 m × cos(lat)
    lon = origin_lon + x / (111_320.0 * math.cos(math.radians(origin_lat)))
    alt = origin_alt + z
    return lat, lon, alt


class MissionExportService:
    """Export approved MissionDraft to QGC .plan format.

    Usage:
        svc = MissionExportService()
        result = svc.export(draft, profile)   # profile defaults to get_active_profile()
    """

    def __init__(
        self,
        missions_dir: str | Path | None = None,
        accept_radius_m: float = _DEFAULT_ACCEPT_RADIUS_M,
        hold_s: float = _DEFAULT_HOLD_S,
    ):
        self._missions_dir = Path(missions_dir) if missions_dir else _MISSIONS_DIR
        self._accept_radius_m = accept_radius_m
        self._hold_s = hold_s
        self._geo = _load_georeference()

    def export(
        self,
        draft: dict[str, Any],
        profile: VehicleProfile | None = None,
        home_position: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Serialize an approved draft to a .plan file.

        Returns a result dict with ok, file_path, waypoint_count, and plan.
        """
        if profile is None:
            profile = get_active_profile()

        draft_id = str(draft.get("id") or "unknown")
        status = str(draft.get("status") or "")
        if status not in ("approved", "exported"):
            return {
                "ok": False,
                "error": f"draft '{draft_id}' is not approved or exported (status='{status}'); export requires approval",
                "draft_id": draft_id,
            }

        waypoints = self._collect_waypoints(draft)
        if not waypoints:
            return {
                "ok": False,
                "error": "draft contains no waypoints to export",
                "draft_id": draft_id,
            }

        plan = self._build_plan(waypoints, profile, home_position)

        self._missions_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._missions_dir / f"{draft_id}.plan"
        out_path.write_text(json.dumps(plan, indent=2))

        return {
            "ok": True,
            "draft_id": draft_id,
            "file_path": str(out_path),
            "waypoint_count": len(waypoints),
            "vehicle_type": profile.mav_vehicle_type,
            "plan": plan,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_waypoints(self, draft: dict[str, Any]) -> list[dict[str, Any]]:
        """Pull waypoints out of draft steps (from route planner results)."""
        payload = draft.get("draft") or {}
        waypoints: list[dict[str, Any]] = []

        # Draft payload may carry a top-level waypoints list (set by route tools)
        if isinstance(payload.get("waypoints"), list):
            return [dict(wp) for wp in payload["waypoints"] if isinstance(wp, dict)]

        # Planner-loop route tools persist full waypoint lists under route_artifacts
        # so the LLM only has to reason over compact summaries.
        artifact_waypoints: list[dict[str, Any]] = []
        for artifact in (payload.get("route_artifacts") or []):
            if not isinstance(artifact, dict):
                continue
            artifact_wps = artifact.get("waypoints")
            if isinstance(artifact_wps, list):
                artifact_waypoints.extend(wp for wp in artifact_wps if isinstance(wp, dict))
        if artifact_waypoints:
            return artifact_waypoints

        # Otherwise extract from steps
        for step in (payload.get("steps") or []):
            if not isinstance(step, dict):
                continue
            step_wps = step.get("waypoints")
            if isinstance(step_wps, list):
                waypoints.extend(wp for wp in step_wps if isinstance(wp, dict))

        return waypoints

    def _build_plan(
        self,
        waypoints: list[dict[str, Any]],
        profile: VehicleProfile,
        home_position: dict[str, float] | None,
    ) -> dict[str, Any]:
        home = home_position or {"latitude": self._geo["origin_lat"], "longitude": self._geo["origin_lon"], "altitude": self._geo["origin_alt"]}

        items: list[dict[str, Any]] = []
        for i, wp in enumerate(waypoints):
            x = float(wp.get("x") or 0.0)
            y = float(wp.get("y") or 0.0)
            z = float(wp.get("z") or 0.0)
            lat, lon, alt = local_to_latlon(x, y, z, self._geo)

            if profile.kind == "ground":
                alt = 0.0

            yaw_rad = wp.get("yaw_rad")
            yaw_val = float("nan") if (yaw_rad is None or not profile.supports_yaw_at_waypoint) else float(yaw_rad)

            accept_radius = wp.get("accept_radius_m")
            accept_radius_val = float(accept_radius) if accept_radius is not None else self._accept_radius_m

            hold = wp.get("hold_s")
            hold_val = float(hold) if hold is not None else self._hold_s

            items.append({
                "autoContinue": True,
                "command": _MAV_CMD_NAV_WAYPOINT,
                "doJumpId": i + 1,
                "frame": _FRAME_GLOBAL_RELATIVE_ALT,
                "params": [hold_val, accept_radius_val, 0, yaw_val, lat, lon, alt],
                "type": "SimpleItem",
            })

        # Trailing return-to-launch
        items.append({
            "autoContinue": True,
            "command": _MAV_CMD_NAV_RETURN_TO_LAUNCH,
            "doJumpId": len(items) + 1,
            "frame": _FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0, 0, 0, 0, 0, 0, 0],
            "type": "SimpleItem",
        })

        return {
            "fileType": "Plan",
            "version": 1,
            "geoFence": {"circles": [], "polygons": [], "version": 2},
            "groundStation": "QGroundControl",
            "mission": {
                "cruiseSpeed": profile.max_speed_mps,
                "firmwareType": 3,  # ArduPilot
                "globalPlanAltitudeMode": 1,
                "hoverSpeed": profile.max_speed_mps,
                "items": items,
                "plannedHomePosition": [
                    home.get("latitude", self._geo["origin_lat"]),
                    home.get("longitude", self._geo["origin_lon"]),
                    home.get("altitude", self._geo["origin_alt"]),
                ],
                "vehicleType": profile.mav_vehicle_type,
                "version": 2,
            },
            "rallyPoints": {"points": [], "version": 2},
        }
