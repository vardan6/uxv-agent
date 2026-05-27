"""Shared mission-overlay helpers used by the planning graph and HTTP layer.

The overlay payload describes how a Mission renders on the map: waypoint
markers, optional route lines, and the bounding box. Inputs are a flat
Mission dict (per ADR 0021 §2 / `mission_repository.Mission.mission_json`).
"""

from __future__ import annotations

from typing import Any


def coerce_scene_point(value: Any, *, fallback_id: str = "") -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        point = {
            "x": float(value.get("x")),
            "y": float(value.get("y")),
            "z": float(value.get("z", 0.0) or 0.0),
        }
    except (TypeError, ValueError):
        return None
    point["id"] = str(value.get("id") or fallback_id or "")
    point["label"] = str(value.get("label") or "")
    point["kind"] = str(value.get("kind") or "")
    return point


def collect_waypoints(mission: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(mission, dict):
        return []
    if isinstance(mission.get("waypoints"), list):
        direct = [
            coerce_scene_point(wp, fallback_id=f"wp-{index}")
            for index, wp in enumerate(mission["waypoints"], start=1)
        ]
        direct_points = [wp for wp in direct if wp is not None]
        if direct_points:
            return direct_points

    route_waypoints: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(mission.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        artifact_waypoints = artifact.get("waypoints")
        if not isinstance(artifact_waypoints, list):
            continue
        for waypoint_index, waypoint in enumerate(artifact_waypoints, start=1):
            point = coerce_scene_point(
                waypoint,
                fallback_id=f"route-{artifact_index}-wp-{waypoint_index}",
            )
            if point is not None:
                route_waypoints.append(point)
    if route_waypoints:
        return route_waypoints

    step_waypoints: list[dict[str, Any]] = []
    for step_index, step in enumerate(mission.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        waypoints = step.get("waypoints")
        if not isinstance(waypoints, list):
            continue
        for waypoint_index, waypoint in enumerate(waypoints, start=1):
            point = coerce_scene_point(
                waypoint,
                fallback_id=f"step-{step_index}-wp-{waypoint_index}",
            )
            if point is not None:
                step_waypoints.append(point)
    return step_waypoints


def _route_features(mission: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(mission.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("route_id") or f"route-{artifact_index}")
        waypoints = [
            point
            for point in (
                coerce_scene_point(wp, fallback_id=f"{artifact_id}-wp-{waypoint_index}")
                for waypoint_index, wp in enumerate(artifact.get("waypoints") or [], start=1)
            )
            if point is not None
        ]
        if not waypoints:
            continue
        features.append({
            "id": artifact_id,
            "type": "route_line",
            "label": str(artifact.get("label") or artifact.get("kind") or artifact_id),
            "route_hash": str(artifact.get("route_hash") or ""),
            "waypoint_count": int(artifact.get("waypoint_count") or len(waypoints)),
            "distance_m": float(
                (artifact.get("summary") or {}).get("total_distance_m")
                or artifact.get("total_distance_m")
                or 0.0
            ),
            "points": [{"x": p["x"], "y": p["y"], "z": p["z"]} for p in waypoints],
        })
    return features


def build_mission_overlay(
    mission_id: Any,
    mission_json: dict[str, Any],
) -> dict[str, Any]:
    """Build a map-overlay payload from a flat Mission's mission_json.

    `mission_id` is used to derive a fallback route id for two-or-more waypoint
    missions that don't declare an explicit route artifact.
    """
    mission = mission_json if isinstance(mission_json, dict) else {}
    waypoints = collect_waypoints(mission)
    route_features = _route_features(mission)
    marker_features = [
        {
            "id": str(point.get("id") or f"mission-wp-{index}"),
            "type": "waypoint",
            "label": str(point.get("label") or f"Waypoint {index}"),
            "kind": str(point.get("kind") or "waypoint"),
            "index": index,
            "point": {"x": point["x"], "y": point["y"], "z": point["z"]},
        }
        for index, point in enumerate(waypoints, start=1)
    ]
    if route_features:
        features = [*route_features, *marker_features]
    elif len(marker_features) >= 2:
        features = [{
            "id": f"mission-{mission_id}-route",
            "type": "route_line",
            "label": "Mission route",
            "route_hash": "",
            "waypoint_count": len(marker_features),
            "distance_m": 0.0,
            "points": [dict(marker["point"]) for marker in marker_features],
        }, *marker_features]
    else:
        features = marker_features

    xs = [point["x"] for point in waypoints]
    ys = [point["y"] for point in waypoints]
    zs = [point["z"] for point in waypoints]
    bounds: dict[str, float] | None = None
    if xs and ys:
        bounds = {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
            "min_z": min(zs) if zs else 0.0,
            "max_z": max(zs) if zs else 0.0,
        }

    return {
        "available": bool(features),
        "mission_id": mission_id,
        "goal": str(mission.get("goal") or ""),
        "waypoint_count": len(waypoints),
        "bounds": bounds,
        "features": features,
        "mission_export": (
            mission.get("mission_export")
            if isinstance(mission.get("mission_export"), dict)
            else {}
        ),
    }


def empty_mission_overlay() -> dict[str, Any]:
    return {
        "available": False,
        "status": "no_mission_overlay",
        "summary": "No mission overlay is available.",
        "features": [],
        "waypoint_count": 0,
        "bounds": None,
    }
