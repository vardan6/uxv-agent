"""QGC .plan mission exporter for approved mission artifacts.

Converts an approved draft or mission revision into a QGroundControl-compatible
.plan JSON file at data/missions/<artifact_id>.plan.

Coordinate handling: waypoints carry WGS84 ``{lat, lon, alt}`` as the stored
truth (ADR 0022); export reads it directly. Legacy payloads that predate the
truth flip carry only local metres ``{x, y, z}`` — those are projected through
the Mission Origin (seeded from the terrain scene georeference) as a fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from gcs_server.ai.coordinate_frame import load_scene_origin, local_to_wgs84
    from gcs_server.ai.vehicle_profile import VehicleProfile, get_active_profile
except ModuleNotFoundError:
    from ai.coordinate_frame import load_scene_origin, local_to_wgs84
    from ai.vehicle_profile import VehicleProfile, get_active_profile

_MISSIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "missions"

_MAV_CMD_NAV_WAYPOINT = 16
_MAV_CMD_NAV_LOITER_TIME = 19
_MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
_MAV_CMD_DO_CHANGE_SPEED = 178
_MAV_CMD_DO_SET_ROI = 201
_FRAME_GLOBAL_RELATIVE_ALT = 3
_FRAME_MISSION = 2  # MAV_FRAME_MISSION — DO_ commands with no geographic payload

# DO_CHANGE_SPEED speed type: 0 = airspeed, 1 = ground speed (rover uses ground)
_SPEED_TYPE_GROUND = 1

_DEFAULT_ACCEPT_RADIUS_M = 2.0
_DEFAULT_HOLD_S = 0.0


class MissionExportService:
    """Export approved planning artifact to QGC .plan format.

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
        self._origin = load_scene_origin()

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

        draft_id = str(draft.get("id") or draft.get("draft_id") or "unknown")
        status = str(draft.get("status") or "")
        if status not in ("approved", "exported"):
            return {
                "ok": False,
                "error": f"artifact '{draft_id}' is not approved or exported (status='{status}'); export requires approval",
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

    def build_plan(
        self,
        waypoints: list[dict[str, Any]],
        profile: VehicleProfile | None = None,
        home_position: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Build a QGC ``.plan`` dict from a raw WGS84 waypoint list, without
        the draft/approval envelope :meth:`export` requires.

        This is the entry point the behavior-tree executor's leaf driver uses to
        compile one navigable segment (ADR 0023 decision 3) before handing it to
        a controller adapter. Returns the same ``plan`` structure :meth:`export`
        embeds, so adapter ``install_mission`` normalization is identical.
        """
        if profile is None:
            profile = get_active_profile()
        return self._build_plan(
            [dict(wp) for wp in waypoints if isinstance(wp, dict)],
            profile,
            home_position,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_waypoints(self, draft: dict[str, Any]) -> list[dict[str, Any]]:
        """Pull waypoints out of draft or revision payloads."""
        payload = draft.get("draft")
        if not isinstance(payload, dict):
            payload = draft.get("mission") or {}
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
        origin = self._origin
        home = home_position or {"latitude": origin.lat, "longitude": origin.lon, "altitude": origin.alt}

        items: list[dict[str, Any]] = []

        def _append(command: int, params: list[float], frame: int = _FRAME_GLOBAL_RELATIVE_ALT) -> None:
            # doJumpId must be a stable 1-based running sequence across every emitted
            # item, including the DO_ commands inserted ahead of a navigation leaf.
            items.append({
                "autoContinue": True,
                "command": command,
                "doJumpId": len(items) + 1,
                "frame": frame,
                "params": params,
                "type": "SimpleItem",
            })

        for wp in waypoints:
            # ADR 0022: stored WGS84 is authoritative — read it directly. Only
            # legacy payloads without lat/lon need the flat-earth projection.
            if wp.get("lat") is not None and wp.get("lon") is not None:
                lat = float(wp["lat"])
                lon = float(wp["lon"])
                alt = float(wp.get("alt") or 0.0)
            else:
                lat, lon, alt = local_to_wgs84(
                    float(wp.get("x") or 0.0),
                    float(wp.get("y") or 0.0),
                    float(wp.get("z") or 0.0),
                    origin,
                )

            if profile.kind == "ground":
                alt = 0.0

            yaw_rad = wp.get("yaw_rad")
            yaw_val = float("nan") if (yaw_rad is None or not profile.supports_yaw_at_waypoint) else float(yaw_rad)

            accept_radius = wp.get("accept_radius_m")
            accept_radius_val = float(accept_radius) if accept_radius is not None else self._accept_radius_m

            hold = wp.get("hold_s")
            hold_val = float(hold) if hold is not None else self._hold_s

            # Rover command subset on navigation leaves (Phase 2). Optional per-leaf
            # fields emit the matching MAVLink DO_/NAV_ items; absent fields fall
            # back to a plain waypoint. DO_JUMP is intentionally not emitted — the
            # behavior-tree owns loop structure (ADR 0023).
            speed = wp.get("speed_mps")
            if speed is not None:
                # param2 = target speed; param3 throttle -1 = no change.
                _append(
                    _MAV_CMD_DO_CHANGE_SPEED,
                    [_SPEED_TYPE_GROUND, float(speed), -1, 0, 0, 0, 0],
                    frame=_FRAME_MISSION,
                )

            roi = wp.get("roi")
            if isinstance(roi, dict) and roi.get("lat") is not None and roi.get("lon") is not None:
                roi_alt = 0.0 if profile.kind == "ground" else float(roi.get("alt") or 0.0)
                _append(
                    _MAV_CMD_DO_SET_ROI,
                    [0, 0, 0, 0, float(roi["lat"]), float(roi["lon"]), roi_alt],
                )

            loiter_time = wp.get("loiter_time_s")
            if loiter_time is not None:
                # NAV_LOITER_TIME param1 = seconds; radius 0 for a ground rover hold.
                _append(
                    _MAV_CMD_NAV_LOITER_TIME,
                    [float(loiter_time), 0, 0, yaw_val, lat, lon, alt],
                )
            else:
                _append(
                    _MAV_CMD_NAV_WAYPOINT,
                    [hold_val, accept_radius_val, 0, yaw_val, lat, lon, alt],
                )

        # Trailing return-to-launch
        _append(_MAV_CMD_NAV_RETURN_TO_LAUNCH, [0, 0, 0, 0, 0, 0, 0])

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
                    home.get("latitude", origin.lat),
                    home.get("longitude", origin.lon),
                    home.get("altitude", origin.alt),
                ],
                "vehicleType": profile.mav_vehicle_type,
                "version": 2,
            },
            "rallyPoints": {"points": [], "version": 2},
        }
