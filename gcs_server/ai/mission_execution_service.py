from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from .controller_mission_adapter import (
    ControllerMissionAdapter,
    ControllerMissionAdapterState,
    JsonFileControllerMissionAdapter,
)
from .coordinate_frame import Origin, load_scene_origin, local_to_wgs84, wgs84_to_local
from .migrations import apply_ai_store_migrations
from . import mission_patterns, mission_tree
from .mission_safety import parse_geofence


def _point_in_polygon(lat: float, lon: float, polygon: list[dict[str, float]]) -> bool:
    """Ray-casting point-in-polygon test. Polygon is an open list of {lat, lon} dicts."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["lon"], polygon[i]["lat"]
        xj, yj = polygon[j]["lon"], polygon[j]["lat"]
        if ((yi > lat) != (yj > lat)) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _collect_nav_waypoints_wgs84(
    node: "mission_tree.Node", origin: Origin
) -> list[tuple[float, float]]:
    """Walk a mission tree node, return (lat, lon) for every nav_leaf waypoint."""
    if node.type == mission_tree.NAV_LEAF:
        result = []
        for wp in node.waypoints:
            lat, lon, _ = local_to_wgs84(
                float(wp.get("x", 0)), float(wp.get("y", 0)), float(wp.get("z", 0)), origin
            )
            result.append((lat, lon))
        return result
    pts: list[tuple[float, float]] = []
    for child in node.children:
        pts.extend(_collect_nav_waypoints_wgs84(child, origin))
    return pts


def _check_hard_constraints(
    node: "mission_tree.Node", origin: Origin, constraints_store: Any
) -> str | None:
    """Return an error string if the route violates any hard enabled constraint, else None.

    Hard allowed corridors: every waypoint must be inside the union of enabled ones.
    Hard blockages: every waypoint must be outside all enabled ones.
    """
    constraints = constraints_store.list_constraints()
    hard_corridors = [
        c for c in constraints
        if c["kind"] == "allowed_corridor" and c["rule"] == "hard" and c["enabled"]
    ]
    hard_blockages = [
        c for c in constraints
        if c["kind"] == "blockage" and c["rule"] == "hard" and c["enabled"]
    ]
    if not hard_corridors and not hard_blockages:
        return None

    waypoints = _collect_nav_waypoints_wgs84(node, origin)
    for lat, lon in waypoints:
        if hard_corridors:
            if not any(_point_in_polygon(lat, lon, c["polygon"]) for c in hard_corridors):
                return "Route leaves the hard allowed corridor area and was rejected"
        for blockage in hard_blockages:
            if _point_in_polygon(lat, lon, blockage["polygon"]):
                return f"Route enters hard blockage '{blockage.get('name', blockage['id'])}' and was rejected"
    return None


MISSION_OPERATION_ACTIVE_STATUSES = frozenset({
    "planning",
    "exported",
    "cutover_pending",
    "executing",
    "paused",
})

# Revision statuses that allow (re-)execution. "paused" and "aborted" are
# included so the play button re-launches a mission that was parked or stopped
# without requiring a fresh export.
MISSION_EXECUTION_READY_STATUSES = frozenset({"exported", "executing", "paused", "aborted"})
MISSION_CONTROLLER_ID = "primary"


def _json(data: Any) -> str:
    if data is None:
        return "{}"
    return json.dumps(data, separators=(",", ":"))


def _load_json(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _load_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        logger.warning("_load_json_file: failed to read %s", path, exc_info=True)
        return {}


def _mission_origin() -> Origin:
    """Coordinate datum used to convert between stored WGS84 truth and the local
    metres the simulator/UI render in (ADR 0022). Today every Mission inherits the
    scene georeference; a zero Origin (0,0,0) is the fallback for real-rover
    builds with no scene file and is a fully valid datum — the whole pipeline
    (export, leaf driver, geofence, basemap) round-trips through it, so missions
    are testable without ever seeding a real GPS home. Per-Mission datums
    (``missions.origin_*``) layer on top of this seam."""
    try:
        return load_scene_origin()
    except (OSError, ValueError, KeyError):
        return Origin(lat=0.0, lon=0.0, alt=0.0)


def _wgs84_fields(point: dict[str, Any], origin: Origin) -> dict[str, float]:
    """WGS84 truth for a waypoint: pass through stored ``lat/lon/alt`` when present,
    otherwise project the local ``x/y/z`` through the Origin (ADR 0022)."""
    if point.get("lat") is not None and point.get("lon") is not None:
        return {
            "lat": float(point["lat"]),
            "lon": float(point["lon"]),
            "alt": float(point.get("alt", 0.0) or 0.0),
        }
    lat, lon, alt = local_to_wgs84(
        float(point.get("x") or 0.0),
        float(point.get("y") or 0.0),
        float(point.get("z") or 0.0),
        origin,
    )
    return {"lat": lat, "lon": lon, "alt": alt}


def _stored_waypoint(point: dict[str, Any], origin: Origin) -> dict[str, Any]:
    """Persisted waypoint shape: WGS84 is the stored truth; local ``x/y/z`` are
    re-derived from it so the two frames can never drift (ADR 0022)."""
    geo = _wgs84_fields(point, origin)
    x, y, z = wgs84_to_local(geo["lat"], geo["lon"], geo["alt"], origin)
    out = dict(point)
    out.update(geo)
    out["x"], out["y"], out["z"] = x, y, z
    return out


def _store_waypoints_wgs84(payload: dict[str, Any], origin: Origin | None = None) -> dict[str, Any]:
    """Rewrite every waypoint list in a mission payload to carry WGS84 truth
    (``waypoints``, ``route_artifacts[].waypoints``, ``steps[].waypoints``)."""
    origin = origin if origin is not None else _mission_origin()

    def _rewrite_list(value: Any) -> list[dict[str, Any]]:
        return [
            _stored_waypoint(wp, origin) for wp in value if isinstance(wp, dict)
        ] if isinstance(value, list) else []

    if isinstance(payload.get("waypoints"), list):
        payload["waypoints"] = _rewrite_list(payload["waypoints"])
    for artifact in payload.get("route_artifacts") or []:
        if isinstance(artifact, dict) and isinstance(artifact.get("waypoints"), list):
            artifact["waypoints"] = _rewrite_list(artifact["waypoints"])
    for step in payload.get("steps") or []:
        if isinstance(step, dict) and isinstance(step.get("waypoints"), list):
            step["waypoints"] = _rewrite_list(step["waypoints"])

    # ADR 0023: a behavior-tree payload nests its waypoints inside nav_leaf nodes,
    # so the truth-flip must recurse the tree the same way it rewrites flat lists.
    def _rewrite_tree(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "nav_leaf" and isinstance(node.get("waypoints"), list):
            node["waypoints"] = _rewrite_list(node["waypoints"])
        for child in node.get("children") or []:
            _rewrite_tree(child)

    if isinstance(payload.get("tree"), dict):
        _rewrite_tree(payload["tree"])
    return payload


def _canonicalize_mission_payload(draft_payload: dict[str, Any], origin: Origin) -> dict[str, Any]:
    mission = dict(draft_payload)
    mission["execution_allowed"] = False
    mission["required_operator_approval"] = True

    steps: list[dict[str, Any]] = []
    for index, step in enumerate(mission.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        normalized = dict(step)
        normalized["id"] = str(step.get("id") or f"step-{index}")
        steps.append(normalized)
    mission["steps"] = steps

    route_artifacts: list[dict[str, Any]] = []
    for index, artifact in enumerate(mission.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        normalized = dict(artifact)
        normalized["route_id"] = str(artifact.get("route_id") or artifact.get("route_hash") or f"route-{index}")
        route_artifacts.append(normalized)
    if route_artifacts:
        mission["route_artifacts"] = route_artifacts

    # ADR 0022: WGS84 is the stored truth. Stamp lat/lon/alt onto every waypoint
    # (deriving x/y/z back from it) so persisted content is authoritative regardless
    # of which frame the planner/route tools emitted.
    _store_waypoints_wgs84(mission, origin)

    return mission


def _operation_status_from_revision(status: str) -> str:
    clean = str(status or "").strip().lower()
    if clean in {
        "exported",
        "cutover_pending",
        "executing",
        "rejected",
        "validation_failed",
        "needs_clarification",
    }:
        return clean
    return "planning"


def _coerce_scene_point(value: Any, origin: Origin, *, fallback_id: str = "") -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    # ADR 0022: when stored WGS84 truth is present, derive local x/y/z from it so
    # the rendered frame can never drift from the authoritative coordinate. Fall
    # back to a literal x/y/z for legacy payloads written before the truth flip.
    if value.get("lat") is not None and value.get("lon") is not None:
        try:
            lat = float(value["lat"])
            lon = float(value["lon"])
            alt = float(value.get("alt", 0.0) or 0.0)
            x, y, z = wgs84_to_local(lat, lon, alt, origin)
        except (TypeError, ValueError):
            return None
        point = {"x": x, "y": y, "z": z}
    else:
        try:
            x = float(value.get("x"))
            y = float(value.get("y"))
            z = float(value.get("z", 0.0) or 0.0)
            point = {"x": x, "y": y, "z": z}
            lat, lon, alt = local_to_wgs84(x, y, z, origin)
        except (TypeError, ValueError):
            return None
    # Carry WGS84 truth so the basemap (ADR 0022) can plot by lat/lon directly.
    point["lat"] = lat
    point["lon"] = lon
    point["alt"] = alt
    point["id"] = str(value.get("id") or fallback_id or "")
    point["label"] = str(value.get("label") or "")
    point["kind"] = str(value.get("kind") or "")
    return point


def _collect_waypoints(mission: dict[str, Any], origin: Origin) -> list[dict[str, Any]]:
    if not isinstance(mission, dict):
        return []
    if isinstance(mission.get("waypoints"), list):
        direct = [
            _coerce_scene_point(wp, origin, fallback_id=f"wp-{index}")
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
            point = _coerce_scene_point(
                waypoint,
                origin,
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
            point = _coerce_scene_point(
                waypoint,
                origin,
                fallback_id=f"step-{step_index}-wp-{waypoint_index}",
            )
            if point is not None:
                step_waypoints.append(point)
    return step_waypoints


def _route_overlay_features(mission: dict[str, Any], origin: Origin) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(mission.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("route_id") or f"route-{artifact_index}")
        waypoints = [
            point
            for point in (
                _coerce_scene_point(wp, origin, fallback_id=f"{artifact_id}-wp-{waypoint_index}")
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
            "distance_m": float((artifact.get("summary") or {}).get("total_distance_m") or artifact.get("total_distance_m") or 0.0),
            "points": [
                {
                    "x": point["x"], "y": point["y"], "z": point["z"],
                    "lat": point["lat"], "lon": point["lon"], "alt": point["alt"],
                }
                for point in waypoints
            ],
        })
    return features


def _overlay_geofence(mission: dict[str, Any]) -> dict[str, Any] | None:
    """Surface a Mission's stored inclusion fence (ADR 0023 Phase 5) for basemap
    display. The fence rides inside mission content under ``geofence`` as WGS84
    truth (``polygon``/``rally_points`` are ``{lat, lon[, alt]}``), so it passes
    straight through. Returns ``None`` for fenceless or unusable (< 3 vertices)
    fences so the client never draws a degenerate polygon."""
    fence = mission.get("geofence") if isinstance(mission, dict) else None
    if not isinstance(fence, dict):
        return None
    polygon = [
        {"lat": float(v["lat"]), "lon": float(v["lon"])}
        for v in fence.get("polygon") or []
        if isinstance(v, dict) and v.get("lat") is not None and v.get("lon") is not None
    ]
    if len(polygon) < 3:
        return None
    rally = [
        {"lat": float(v["lat"]), "lon": float(v["lon"])}
        for v in fence.get("rally_points") or []
        if isinstance(v, dict) and v.get("lat") is not None and v.get("lon") is not None
    ]
    out: dict[str, Any] = {"polygon": polygon, "rally_points": rally}
    if fence.get("min_alt") is not None:
        out["min_alt"] = float(fence["min_alt"])
    if fence.get("max_alt") is not None:
        out["max_alt"] = float(fence["max_alt"])
    return out


def _build_mission_overlay_payload(revision: dict[str, Any], origin: Origin) -> dict[str, Any]:
    mission = revision.get("mission") if isinstance(revision.get("mission"), dict) else {}
    provenance_map = revision.get("provenance") if isinstance(revision.get("provenance"), dict) else {}
    waypoints = _collect_waypoints(mission, origin)
    route_features = _route_overlay_features(mission, origin)
    marker_features = [
        {
            "id": str(point.get("id") or f"mission-wp-{index}"),
            "type": "waypoint",
            "label": str(point.get("label") or f"Waypoint {index}"),
            "kind": str(point.get("kind") or "waypoint"),
            "index": index,
            "point": {
                "x": point["x"], "y": point["y"], "z": point["z"],
                "lat": point["lat"], "lon": point["lon"], "alt": point["alt"],
            },
            "provenance": provenance_map.get(str(point.get("id") or f"mission-wp-{index}"), "ai"),
        }
        for index, point in enumerate(waypoints, start=1)
    ]
    if route_features:
        features = [*route_features, *marker_features]
    elif len(marker_features) >= 2:
        features = [{
            "id": f"{revision.get('id', 'mission')}-route",
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
    bounds = None
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
        "operation_id": revision.get("operation_id", ""),
        "revision_id": revision.get("id", ""),
        "draft_id": revision.get("draft_id", ""),
        "status": str(revision.get("status") or revision.get("operation_status") or ""),
        "goal": str(mission.get("goal") or ""),
        "waypoint_count": len(waypoints),
        "bounds": bounds,
        "features": features,
        "origin": {"lat": origin.lat, "lon": origin.lon, "alt": origin.alt},
        "geofence": _overlay_geofence(mission),
        "mission_export": mission.get("mission_export") if isinstance(mission.get("mission_export"), dict) else {},
    }


def _controller_snapshot_to_public(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot:
        return {}
    return {
        "controller_version": int(snapshot.get("controller_version") or 0),
        "operation_id": str(snapshot.get("operation_id") or ""),
        "revision_id": str(snapshot.get("revision_id") or ""),
        "draft_id": str(snapshot.get("draft_id") or ""),
        "captured_at": snapshot.get("captured_at"),
        "mission_export": snapshot.get("mission_export") if isinstance(snapshot.get("mission_export"), dict) else {},
        "mission": snapshot.get("mission") if isinstance(snapshot.get("mission"), dict) else {},
        "plan": snapshot.get("plan") if isinstance(snapshot.get("plan"), dict) else {},
    }


def _rebased_mission_payload(mission: dict[str, Any], origin: Origin) -> dict[str, Any]:
    rebased = _canonicalize_mission_payload(dict(mission or {}), origin)
    rebased.pop("mission_export", None)
    return rebased


class MissionExecutionService:
    """Backend-owned mission lifecycle and controller handoff boundary.

    Planning produces semantic proposal artifacts. This service owns the
    authoritative revision lifecycle, exported mission cutover, controller
    version checks, and durable verification state.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        controller_adapter: ControllerMissionAdapter | None = None,
        origin_resolver: Callable[[str | None], Origin | None] | None = None,
    ):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._adapter_lock = threading.Lock()
        self._controller_adapter = controller_adapter or JsonFileControllerMissionAdapter(
            self._db_path.parent / "controller_mission_adapter.json"
        )
        # ADR 0022: per-Mission coordinate datum. The resolver maps an internal
        # operation id to its Mission's Origin (runtime composes
        # MissionStore.get_by_operation_id → get_origin_datum); a None id or None
        # result falls back to the scene georeference. Paths that don't yet know
        # an operation (e.g. a brand-new proposal) pass operation_id=None and
        # inherit the scene origin.
        self._origin_resolver = origin_resolver
        self._init_db()

    @property
    def controller_adapter(self) -> ControllerMissionAdapter:
        """The configured controller link. Exposed so the behavior-tree executor
        (ADR 0023) can build a leaf driver against the same adapter the cutover
        flow uses, rather than spinning up a second connection."""
        with self._adapter_lock:
            return self._controller_adapter

    def set_controller_adapter(self, adapter: ControllerMissionAdapter) -> None:
        """Thread-safe adapter swap — guards against a concurrent executor mid-call."""
        with self._adapter_lock:
            self._controller_adapter = adapter

    def _resolve_origin(self, operation_id: str | None = None) -> Origin:
        """Coordinate datum for a Mission's WGS84↔local conversions (ADR 0022).

        Consults the injected per-Mission ``origin_resolver`` when an
        ``operation_id`` is known, otherwise (or when it yields nothing) falls
        back to the scene georeference via :func:`_mission_origin`."""
        if operation_id and self._origin_resolver is not None:
            resolved = self._origin_resolver(str(operation_id).strip())
            if resolved is not None:
                return resolved
        return _mission_origin()

    def create_proposal(
        self,
        *,
        session_id: str,
        source_message_id: str = "",
        draft_id: str,
        intent: dict[str, Any],
        target_resolution: dict[str, Any],
        draft_payload: dict[str, Any],
        validation: dict[str, Any],
        draft_status: str,
        review_context: dict[str, Any] | None = None,
        parent_operation_id: str = "",
        origin_override: Origin | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        revision_id = f"mission-rev-{uuid.uuid4().hex[:12]}"
        # ``origin_override`` lets a caller that has already chosen the datum (e.g.
        # the operator-draw path, which anchors on the drawn geometry) re-stamp
        # WGS84 truth through the *same* origin it used for wgs84→local, so the
        # round-trip cannot drift. Otherwise resolve per the operation/scene datum.
        origin = origin_override or self._resolve_origin(
            str(parent_operation_id or "").strip() or None
        )
        mission = _canonicalize_mission_payload(draft_payload, origin)
        operation_status = _operation_status_from_revision(draft_status)
        policy = {
            "execution_allowed": False,
            "approval_required": bool(mission.get("required_operator_approval", True)),
            "approval_scope": "planning_artifact_only",
        }

        parent_op = str(parent_operation_id or "").strip()

        with self._connect() as conn:
            if parent_op:
                op_row = conn.execute(
                    "SELECT id, status FROM ai_mission_operations WHERE id = ?",
                    (parent_op,),
                ).fetchone()
                if op_row is None or str(op_row["status"] or "") == "executing":
                    # Fall through to creating a new operation when the parent is
                    # missing or currently executing (safety invariant: no mutation
                    # while execution is in flight).
                    parent_op = ""

            if parent_op:
                operation_id = parent_op
                parent_op_row = conn.execute(
                    "SELECT active_revision_id FROM ai_mission_operations WHERE id = ?",
                    (parent_op,),
                ).fetchone()
                parent_revision_id = str(
                    (parent_op_row["active_revision_id"] if parent_op_row else "") or ""
                )
                conn.execute(
                    """
                    INSERT INTO ai_mission_revisions (
                      id, operation_id, draft_id, parent_revision_id, status,
                      mission_json, intent_json, target_resolution_json, validation_json,
                      review_context_json, created_at, updated_at, approved_at, rejected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        revision_id,
                        operation_id,
                        draft_id,
                        parent_revision_id,
                        operation_status,
                        _json(mission),
                        _json(intent),
                        _json(target_resolution),
                        _json(validation),
                        _json(review_context or {}),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE ai_mission_operations SET active_revision_id = ?, status = ?, updated_at = ? WHERE id = ?",
                    (revision_id, operation_status, now, operation_id),
                )
            else:
                operation_id = f"mission-op-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO ai_mission_operations (
                      id, session_id, source_message_id, status, active_revision_id,
                      policy_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        session_id,
                        source_message_id or "",
                        operation_status,
                        revision_id,
                        _json(policy),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO ai_mission_revisions (
                      id, operation_id, draft_id, parent_revision_id, status,
                      mission_json, intent_json, target_resolution_json, validation_json,
                      review_context_json, created_at, updated_at, approved_at, rejected_at
                    ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        revision_id,
                        operation_id,
                        draft_id,
                        operation_status,
                        _json(mission),
                        _json(intent),
                        _json(target_resolution),
                        _json(validation),
                        _json(review_context or {}),
                        now,
                        now,
                    ),
                )
            conn.commit()
        return self.get_revision(revision_id) or {}

    def create_drawn_pattern_mission(
        self,
        *,
        session_id: str,
        pattern: str,
        points: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        name: str = "",
        constraints_store: Any = None,
    ) -> dict[str, Any]:
        """Build a new Mission from an operator-drawn pattern (Phase 4 authoring).

        The operator sketches geometry on the WGS84 basemap; ``points`` are the
        drawn ``{lat, lon}`` vertices. We convert them to the local metre frame
        through the Mission origin (ADR 0022), run the corridor/survey generator
        (which works in metres), and persist the resulting nav subtree as a new
        proposal. ``create_proposal`` stamps WGS84 truth back onto every leaf, so
        the conversion round-trips through one origin and cannot drift.

        Returns ``{"ok": True, "revision": {...}, "operation_id": ...}`` or
        ``{"ok": False, "error": ...}``; never raises on bad input.
        """
        kind = str(pattern or "").strip().lower()
        if kind not in ("corridor", "survey"):
            return {"ok": False, "error": "pattern must be 'corridor' or 'survey'"}
        params = params if isinstance(params, dict) else {}
        if not isinstance(points, list) or len(points) < 2:
            return {"ok": False, "error": "at least two drawn points are required"}

        # Anchor the Mission's coordinate datum (ADR 0022) on the drawn geometry
        # itself — the first vertex — rather than the distant scene-origin
        # fallback, so the generated local metres sit near the origin. The same
        # origin is handed to create_proposal so its WGS84 re-stamp round-trips
        # through one datum (no frame drift), and is returned for the caller to
        # pin onto the new Mission row via MissionStore.set_origin_datum.
        first = points[0] if isinstance(points[0], dict) else {}
        if first.get("lat") is None or first.get("lon") is None:
            return {"ok": False, "error": "each point must be {lat, lon}"}
        try:
            origin = Origin(lat=float(first["lat"]), lon=float(first["lon"]), alt=0.0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid lat/lon in drawn points"}
        local: list[tuple[float, float]] = []
        for pt in points:
            if not isinstance(pt, dict) or pt.get("lat") is None or pt.get("lon") is None:
                return {"ok": False, "error": "each point must be {lat, lon}"}
            try:
                x, y, _z = wgs84_to_local(float(pt["lat"]), float(pt["lon"]), 0.0, origin)
            except (TypeError, ValueError):
                return {"ok": False, "error": "invalid lat/lon in drawn points"}
            local.append((x, y))

        def _num(key: str, default: float | None = None) -> float:
            raw = params.get(key, default)
            if raw is None:
                raise ValueError(f"'{key}' is required")
            return float(raw)

        try:
            altitude_m = _num("altitude_m", 0.0)
            if kind == "corridor":
                node = mission_patterns.corridor_pattern(
                    path=local,
                    spacing_m=_num("spacing_m", 5.0),
                    altitude_m=altitude_m,
                    passes=int(params.get("passes", 1)),
                )
            else:
                # The operator drags a rectangle; we take the bounding box of the
                # drawn points as the survey area (axis-aligned in the local frame).
                xs = [p[0] for p in local]
                ys = [p[1] for p in local]
                ox, oy = min(xs), min(ys)
                width_m = max(xs) - ox
                height_m = max(ys) - oy
                node = mission_patterns.survey_pattern(
                    width_m=width_m,
                    height_m=height_m,
                    line_spacing_m=_num("line_spacing_m", 10.0),
                    altitude_m=altitude_m,
                    origin_xy=(ox, oy),
                    heading_deg=float(params.get("heading_deg", 0.0)),
                )
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": f"invalid {kind} params: {exc}"}

        if constraints_store is not None:
            violation = _check_hard_constraints(node, origin, constraints_store)
            if violation:
                return {"ok": False, "error": violation}

        mission_name = str(name or "").strip() or f"{kind.capitalize()} pattern"
        draft_id = f"draft-draw-{uuid.uuid4().hex[:12]}"
        draft_payload = {
            "goal": mission_name,
            "summary": f"Operator-drawn {kind} pattern",
            "tree": node.to_dict(),
            "required_operator_approval": True,
        }
        revision = self.create_proposal(
            session_id=str(session_id or ""),
            draft_id=draft_id,
            intent={"source": "operator_draw", "pattern": kind},
            target_resolution={"mode": "create"},
            draft_payload=draft_payload,
            validation={"ok": True},
            draft_status="proposed",
            origin_override=origin,
        )
        return {
            "ok": True,
            "revision": revision,
            "operation_id": str(revision.get("operation_id") or ""),
            "origin_datum": origin.as_dict(),
        }

    def set_operation_geofence(
        self,
        *,
        session_id: str,
        operation_id: str,
        geofence: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Author/clear a Mission's inclusion geofence (ADR 0023 Phase 5, option A).

        The fence rides *inside* mission content under ``geofence`` — the exact
        dict :func:`ai.mission_execution_session.build_mission_executor` reads to
        enforce early and upload FENCE/RALLY to the FC. This appends a new
        revision to ``operation_id`` carrying the current content with the fence
        merged in (or removed when ``geofence`` is ``None``/empty), so the fence
        is versioned with the mission. Pass a :func:`ai.mission_safety.parse_geofence`
        ``to_dict`` shape (WGS84 polygon + optional rally points / alt band).

        A non-empty fence must be *usable* (>= 3 polygon vertices) or this fails
        closed with an error, so a malformed fence can never weaken enforcement.
        Returns ``{"ok": True, "revision": {...}, "operation_id": ...}`` or
        ``{"ok": False, "error": ...}``; never raises on bad input.
        """
        op_id = str(operation_id or "").strip()
        if not op_id:
            return {"ok": False, "error": "operation_id is required"}

        revisions = self.list_revisions(operation_id=op_id, limit=1)
        if not revisions:
            return {"ok": False, "error": f"operation '{op_id}' has no revision to fence"}
        current = revisions[0].get("mission")
        if not isinstance(current, dict):
            return {"ok": False, "error": f"operation '{op_id}' has no content to fence"}

        payload = dict(current)
        clearing = not geofence
        if clearing:
            payload.pop("geofence", None)
        else:
            fence = parse_geofence(geofence)
            if not fence.is_usable:
                return {"ok": False, "error": "geofence needs an inclusion polygon of at least three vertices"}
            payload["geofence"] = fence.to_dict()

        draft_id = f"draft-fence-{uuid.uuid4().hex[:12]}"
        revision = self.create_proposal(
            session_id=str(session_id or ""),
            draft_id=draft_id,
            intent={"source": "set_geofence", "action": "clear" if clearing else "set"},
            target_resolution={"mode": "edit_in_place"},
            draft_payload=payload,
            validation={"ok": True},
            draft_status="proposed",
            parent_operation_id=op_id,
        )
        return {
            "ok": True,
            "cleared": clearing,
            "revision": revision,
            "operation_id": str(revision.get("operation_id") or op_id),
        }

    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  r.*,
                  o.session_id AS operation_session_id,
                  o.source_message_id AS operation_source_message_id,
                  o.status AS operation_status,
                  o.policy_json AS operation_policy_json,
                  o.active_revision_id AS operation_active_revision_id
                FROM ai_mission_revisions r
                JOIN ai_mission_operations o ON o.id = r.operation_id
                WHERE r.id = ?
                """,
                (revision_id,),
            ).fetchone()
        return _revision_row_to_dict(row) if row else None

    def get_revision_by_draft_id(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  r.*,
                  o.session_id AS operation_session_id,
                  o.source_message_id AS operation_source_message_id,
                  o.status AS operation_status,
                  o.policy_json AS operation_policy_json,
                  o.active_revision_id AS operation_active_revision_id
                FROM ai_mission_revisions r
                JOIN ai_mission_operations o ON o.id = r.operation_id
                WHERE r.draft_id = ?
                ORDER BY r.created_at DESC
                LIMIT 1
                """,
                (draft_id,),
            ).fetchone()
        return _revision_row_to_dict(row) if row else None

    def list_revisions(
        self,
        *,
        session_id: str | None = None,
        operation_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None and str(session_id).strip():
            clauses.append("o.session_id = ?")
            params.append(str(session_id).strip())
        if operation_id is not None and str(operation_id).strip():
            clauses.append("r.operation_id = ?")
            params.append(str(operation_id).strip())
        if status_filter is not None and str(status_filter).strip():
            clauses.append("r.status = ?")
            params.append(str(status_filter).strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  r.*,
                  o.session_id AS operation_session_id,
                  o.source_message_id AS operation_source_message_id,
                  o.status AS operation_status,
                  o.policy_json AS operation_policy_json,
                  o.active_revision_id AS operation_active_revision_id
                FROM ai_mission_revisions r
                JOIN ai_mission_operations o ON o.id = r.operation_id
                {where}
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_revision_row_to_dict(row) for row in rows]

    def get_current_revision(self, *, session_id: str = "") -> dict[str, Any] | None:
        state = self.get_current_mission_state(session_id=session_id)
        revision_id = str(state.get("revision_id") or "").strip()
        if not revision_id:
            return None
        return self.get_revision(revision_id)

    def reject_revision(self, revision_id: str, *, note: str = "") -> dict[str, Any] | None:
        return self._set_revision_status_by_revision_id(revision_id, status="rejected", note=note, timestamp_field="rejected_at")

    def reject_revision_for_draft(self, draft_id: str, *, note: str = "") -> dict[str, Any] | None:
        return self._set_revision_status(draft_id, status="rejected", note=note, timestamp_field="rejected_at")

    def mark_revision_exported_by_revision_id(self, revision_id: str, *, export_result: dict[str, Any]) -> dict[str, Any] | None:
        revision = self.get_revision(str(revision_id or "").strip())
        if revision is None:
            return None
        return self._mark_revision_exported(revision, export_result=export_result)

    def mark_revision_exported(self, draft_id: str, *, export_result: dict[str, Any]) -> dict[str, Any] | None:
        revision = self.get_revision_by_draft_id(draft_id)
        if revision is None:
            return None
        return self._mark_revision_exported(revision, export_result=export_result)

    def _mark_revision_exported(self, revision: dict[str, Any], *, export_result: dict[str, Any]) -> dict[str, Any] | None:
        mission = dict(revision.get("mission") or {})
        mission["mission_export"] = {
            "file_path": str(export_result.get("file_path") or ""),
            "waypoint_count": int(export_result.get("waypoint_count") or 0),
            "vehicle_type": int(export_result.get("vehicle_type") or 0),
            "exported_at": time.time(),
        }
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_mission_revisions
                SET status = 'exported', mission_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json(mission), now, revision["id"]),
            )
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET status = 'exported', updated_at = ?
                WHERE id = ?
                """,
                (now, revision["operation_id"]),
            )
            conn.commit()
        return self.get_revision(revision["id"])

    def execute_revision(
        self,
        revision_id: str,
        *,
        expected_controller_version: int | None = None,
    ) -> dict[str, Any]:
        revision = self.get_revision(str(revision_id or "").strip())
        if revision is None:
            return {"ok": False, "status": "revision_not_found", "error": "mission revision not found"}

        active_revision_id = str(revision.get("active_revision_id") or "").strip()
        if active_revision_id and active_revision_id != str(revision.get("id") or "").strip():
            active_revision = self.get_revision(active_revision_id)
            return {
                "ok": False,
                "status": "stale_revision",
                "error": (
                    f"mission revision '{revision['id']}' is no longer the active revision for "
                    f"operation '{revision['operation_id']}'; execute the active revision instead"
                ),
                "revision": revision,
                "active_revision_id": active_revision_id,
                "active_revision": active_revision,
            }

        status = str(revision.get("status") or "")
        if status not in MISSION_EXECUTION_READY_STATUSES:
            return {
                "ok": False,
                "status": "revision_not_ready",
                "error": f"mission revision '{revision['id']}' is not ready for execution (status='{status}')",
                "revision": revision,
            }

        mission = dict(revision.get("mission") or {})
        mission_export = mission.get("mission_export") if isinstance(mission.get("mission_export"), dict) else {}
        export_path = str(mission_export.get("file_path") or "").strip()
        if not export_path:
            return {
                "ok": False,
                "status": "mission_export_missing",
                "error": "mission revision is missing an exported controller-ready plan",
                "revision": revision,
            }
        plan_file = Path(export_path)
        if not plan_file.exists():
            return {
                "ok": False,
                "status": "mission_export_missing",
                "error": f"mission export file does not exist: {export_path}",
                "revision": revision,
            }

        plan = _load_json_file(export_path)
        if not isinstance(plan, dict) or not plan:
            return {
                "ok": False,
                "status": "mission_export_invalid",
                "error": f"mission export file is not valid JSON plan data: {export_path}",
                "revision": revision,
            }

        now = time.time()
        attempt_id = f"mission-cutover-{uuid.uuid4().hex[:12]}"
        request_payload = {
            "revision_id": revision["id"],
            "operation_id": revision["operation_id"],
            "draft_id": revision.get("draft_id", ""),
            "expected_controller_version": expected_controller_version,
            "adapter": self._controller_adapter.adapter_name,
        }

        try:
            adapter_state = self._controller_adapter.get_controller_state()
        except Exception as exc:
            adapter_state = ControllerMissionAdapterState(status="unavailable")
            with self._connect() as conn:
                controller_row = self._ensure_controller_state_row(conn)
                observed_version = int(controller_row["current_version"] or 0)
                self._insert_execution_attempt(
                    conn,
                    attempt_id=attempt_id,
                    revision=revision,
                    expected_controller_version=expected_controller_version,
                    observed_controller_version=observed_version,
                    installed_controller_version=None,
                    status="cutover_failed",
                    request_payload=request_payload,
                    result_payload={"adapter": self._controller_adapter.adapter_name, "stage": "get_controller_state"},
                    error_text=str(exc),
                    now=now,
                )
                conn.commit()
            return {
                "ok": False,
                "status": "cutover_failed",
                "error": str(exc),
                "attempt_id": attempt_id,
                "revision": revision,
                "controller_state": self.get_controller_state(),
            }

        observed_version = int(adapter_state.controller_version or 0)
        observed_snapshot = adapter_state.to_snapshot()

        with self._connect() as conn:
            controller_row = self._ensure_controller_state_row(conn)
            verified_snapshot = observed_snapshot or _load_json(controller_row["verified_snapshot_json"])
            previous_verified_snapshot = _load_json(controller_row["previous_verified_snapshot_json"])

            if expected_controller_version is not None and int(expected_controller_version) != observed_version:
                self._project_controller_state(
                    conn,
                    adapter_state=adapter_state,
                    verified_snapshot=verified_snapshot,
                    previous_verified_snapshot=previous_verified_snapshot,
                    pending_snapshot={},
                    last_cutover_attempt={
                        "attempt_id": attempt_id,
                        "requested_at": now,
                        "expected_controller_version": expected_controller_version,
                        "adapter": self._controller_adapter.adapter_name,
                    },
                    last_error="",
                    last_cutover_at=now,
                )
                self._insert_execution_attempt(
                    conn,
                    attempt_id=attempt_id,
                    revision=revision,
                    expected_controller_version=expected_controller_version,
                    observed_controller_version=observed_version,
                    installed_controller_version=None,
                    status="stale_controller_version",
                    request_payload=request_payload,
                    result_payload={
                        "controller_version": observed_version,
                        "active_revision_id": adapter_state.revision_id,
                        "adapter": self._controller_adapter.adapter_name,
                    },
                    error_text="expected controller mission version does not match the latest verified version",
                    now=now,
                )
                rebased_revision = self._create_rebased_revision_from_controller_state(
                    revision,
                    conn=conn,
                    controller_state=self._controller_state_from_row(controller_row),
                    observed_controller_version=observed_version,
                    expected_controller_version=expected_controller_version,
                )
                conn.commit()
                result = {
                    "ok": False,
                    "status": "stale_controller_version",
                    "error": "expected controller mission version does not match the latest verified version",
                    "controller_state": self.get_controller_state(),
                    "attempt_id": attempt_id,
                    "revision": revision,
                }
                if rebased_revision is not None:
                    result["rebased_revision"] = rebased_revision
                    result["rebased_revision_id"] = rebased_revision["id"]
                return result

            next_version = observed_version + 1
            pending_snapshot = {
                "controller_version": next_version,
                "operation_id": revision["operation_id"],
                "revision_id": revision["id"],
                "draft_id": revision.get("draft_id", ""),
                "captured_at": now,
                "mission_export": mission_export,
                "mission": mission,
                "plan": plan,
            }

            conn.execute(
                """
                UPDATE ai_mission_controller_state
                SET status = 'verifying',
                    active_operation_id = ?,
                    active_revision_id = ?,
                    active_draft_id = ?,
                    pending_snapshot_json = ?,
                    last_cutover_attempt_json = ?,
                    last_error = '',
                    last_cutover_at = ?,
                    updated_at = ?
                WHERE controller_id = ?
                """,
                (
                    revision["operation_id"],
                    revision["id"],
                    revision.get("draft_id", ""),
                    _json(pending_snapshot),
                    _json({
                        "attempt_id": attempt_id,
                        "requested_at": now,
                        "expected_controller_version": expected_controller_version,
                        "adapter": self._controller_adapter.adapter_name,
                    }),
                    now,
                    now,
                    MISSION_CONTROLLER_ID,
                ),
            )
            conn.execute(
                """
                UPDATE ai_mission_revisions
                SET status = 'cutover_pending', updated_at = ?
                WHERE id = ?
                """,
                (now, revision["id"]),
            )
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET status = 'cutover_pending', active_revision_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (revision["id"], now, revision["operation_id"]),
            )
            conn.commit()

        try:
            install_result = self._controller_adapter.install_mission(
                pending_snapshot=pending_snapshot,
                expected_controller_version=observed_version,
            )
        except Exception as exc:
            install_result = None
            install_error = str(exc)
        else:
            install_error = ""

        final_now = time.time()
        if install_result is None:
            with self._connect() as conn:
                self._project_controller_state(
                    conn,
                    adapter_state=adapter_state,
                    verified_snapshot=verified_snapshot,
                    previous_verified_snapshot=previous_verified_snapshot,
                    pending_snapshot={},
                    last_cutover_attempt={
                        "attempt_id": attempt_id,
                        "requested_at": now,
                        "expected_controller_version": expected_controller_version,
                        "adapter": self._controller_adapter.adapter_name,
                    },
                    last_error=install_error,
                    last_cutover_at=final_now,
                )
                conn.execute(
                    """
                    UPDATE ai_mission_revisions
                    SET status = 'exported', updated_at = ?
                    WHERE id = ?
                    """,
                    (final_now, revision["id"]),
                )
                conn.execute(
                    """
                    UPDATE ai_mission_operations
                    SET status = 'exported', updated_at = ?
                    WHERE id = ?
                    """,
                    (final_now, revision["operation_id"]),
                )
                self._insert_execution_attempt(
                    conn,
                    attempt_id=attempt_id,
                    revision=revision,
                    expected_controller_version=expected_controller_version,
                    observed_controller_version=observed_version,
                    installed_controller_version=None,
                    status="cutover_failed",
                    request_payload=request_payload,
                    result_payload={"adapter": self._controller_adapter.adapter_name, "stage": "install_mission"},
                    error_text=install_error,
                    now=final_now,
                )
                conn.commit()
            return {
                "ok": False,
                "status": "cutover_failed",
                "error": install_error,
                "attempt_id": attempt_id,
                "revision": self.get_revision(revision["id"]),
                "controller_state": self.get_controller_state(),
            }

        final_adapter_state = install_result.controller_state
        final_snapshot = final_adapter_state.to_snapshot() or verified_snapshot
        result_payload = {
            "adapter": self._controller_adapter.adapter_name,
            "verified": bool(install_result.ok),
            "controller_state": final_adapter_state.to_public_dict(),
            "adapter_result": install_result.raw_result,
        }

        if install_result.ok:
            with self._connect() as conn:
                self._project_controller_state(
                    conn,
                    adapter_state=final_adapter_state,
                    verified_snapshot=final_snapshot,
                    previous_verified_snapshot=verified_snapshot,
                    pending_snapshot={},
                    last_cutover_attempt={
                        "attempt_id": attempt_id,
                        "requested_at": now,
                        "expected_controller_version": expected_controller_version,
                        "adapter": self._controller_adapter.adapter_name,
                    },
                    last_error="",
                    last_cutover_at=final_now,
                    verified_at=final_now,
                )
                conn.execute(
                    """
                    UPDATE ai_mission_revisions
                    SET status = 'executing', updated_at = ?
                    WHERE id = ?
                    """,
                    (final_now, revision["id"]),
                )
                conn.execute(
                    """
                    UPDATE ai_mission_operations
                    SET status = 'executing', active_revision_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (revision["id"], final_now, revision["operation_id"]),
                )
                self._insert_execution_attempt(
                    conn,
                    attempt_id=attempt_id,
                    revision=revision,
                    expected_controller_version=expected_controller_version,
                    observed_controller_version=observed_version,
                    installed_controller_version=int(final_adapter_state.controller_version or next_version),
                    status="executing",
                    request_payload=request_payload,
                    result_payload=result_payload,
                    error_text="",
                    now=final_now,
                )
                conn.commit()
        else:
            rollback_status = "exported" if install_result.status == "stale_controller_version" else install_result.status
            with self._connect() as conn:
                self._project_controller_state(
                    conn,
                    adapter_state=final_adapter_state,
                    verified_snapshot=final_snapshot,
                    previous_verified_snapshot=previous_verified_snapshot,
                    pending_snapshot={},
                    last_cutover_attempt={
                        "attempt_id": attempt_id,
                        "requested_at": now,
                        "expected_controller_version": expected_controller_version,
                        "adapter": self._controller_adapter.adapter_name,
                    },
                    last_error=install_result.error,
                    last_cutover_at=final_now,
                    verified_at=final_now if final_snapshot else None,
                )
                conn.execute(
                    """
                    UPDATE ai_mission_revisions
                    SET status = 'exported', updated_at = ?
                    WHERE id = ?
                    """,
                    (final_now, revision["id"]),
                )
                conn.execute(
                    """
                    UPDATE ai_mission_operations
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (rollback_status, final_now, revision["operation_id"]),
                )
                self._insert_execution_attempt(
                    conn,
                    attempt_id=attempt_id,
                    revision=revision,
                    expected_controller_version=expected_controller_version,
                    observed_controller_version=observed_version,
                    installed_controller_version=None,
                    status=install_result.status,
                    request_payload=request_payload,
                    result_payload=result_payload,
                    error_text=install_result.error or "controller mission read-back verification failed",
                    now=final_now,
                )
                conn.commit()
            return {
                "ok": False,
                "status": install_result.status,
                "error": install_result.error or "controller mission read-back verification failed",
                "attempt_id": attempt_id,
                "revision": self.get_revision(revision["id"]),
                "controller_state": self.get_controller_state(),
            }

        return {
            "ok": True,
            "status": "executing",
            "attempt_id": attempt_id,
            "revision": self.get_revision(revision["id"]),
            "controller_state": self.get_controller_state(),
        }

    def pause_mission(self, operation_id: str) -> dict[str, Any]:
        """Send HOLD to the FC adapter and mark the operation paused in the DB.

        Called by the API layer after the executor thread has been parked via
        ``MissionExecutionSessions.request_pause()``.  Adapter errors are
        returned rather than raised so the caller can decide whether to roll
        back the in-memory pause.
        """
        op_id = str(operation_id or "").strip()
        if not op_id:
            return {"ok": False, "status": "invalid_request", "error": "operation_id is required"}
        try:
            self._controller_adapter.pause_mission()
        except Exception as exc:
            return {"ok": False, "status": "adapter_error", "error": str(exc), "operation_id": op_id}
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE ai_mission_operations SET status = 'paused', updated_at = ? WHERE id = ?",
                (now, op_id),
            )
            conn.commit()
        return {"ok": True, "status": "paused", "operation_id": op_id}

    def abort_mission(self, operation_id: str) -> dict[str, Any]:
        """Send HOLD to the FC adapter and mark the operation aborted in the DB.

        Stop keeps the vehicle in place (ADR 0024 — no RTL).  Called by the
        API layer after ``MissionExecutionSessions.request_abort()`` has
        signalled the executor to stop cooperatively.
        """
        op_id = str(operation_id or "").strip()
        if not op_id:
            return {"ok": False, "status": "invalid_request", "error": "operation_id is required"}
        try:
            self._controller_adapter.stop_mission()
        except Exception as exc:
            return {"ok": False, "status": "adapter_error", "error": str(exc), "operation_id": op_id}
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE ai_mission_operations SET status = 'aborted', updated_at = ? WHERE id = ?",
                (now, op_id),
            )
            conn.commit()
        return {"ok": True, "status": "aborted", "operation_id": op_id}

    def get_controller_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._ensure_controller_state_row(conn)
            conn.commit()
        return self._controller_state_from_row(row)

    def check_controller_health(self) -> dict[str, Any]:
        """Probe the controller link (heartbeat + mission readability)."""
        try:
            health = self._controller_adapter.check_health()
            payload = health.to_dict()
        except Exception as exc:
            payload = {
                "ok": False,
                "adapter": self._controller_adapter.adapter_name,
                "connected": False,
                "detail": "controller link probe failed",
                "error": str(exc),
            }
        payload["controller_state"] = self.get_controller_state()
        return payload

    def clear_controller_mission(self, *, expected_controller_version: int | None = None) -> dict[str, Any]:
        """Clear the controller-owned mission (Read/Write/Clear), projecting the
        resulting idle state into the durable controller-state row."""
        now = time.time()
        attempt_id = f"mission-clear-{uuid.uuid4().hex[:12]}"
        try:
            result = self._controller_adapter.clear_mission(
                expected_controller_version=expected_controller_version,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "cutover_failed",
                "error": str(exc),
                "attempt_id": attempt_id,
                "controller_state": self.get_controller_state(),
            }

        final_now = time.time()
        final_adapter_state = result.controller_state
        final_snapshot = final_adapter_state.to_snapshot()
        last_cutover_attempt = {
            "attempt_id": attempt_id,
            "requested_at": now,
            "expected_controller_version": expected_controller_version,
            "adapter": self._controller_adapter.adapter_name,
            "action": "clear",
        }
        with self._connect() as conn:
            controller_row = self._ensure_controller_state_row(conn)
            previous_verified_snapshot = _load_json(controller_row["verified_snapshot_json"])
            self._project_controller_state(
                conn,
                adapter_state=final_adapter_state,
                verified_snapshot=final_snapshot if result.ok else (final_snapshot or previous_verified_snapshot),
                previous_verified_snapshot=previous_verified_snapshot,
                pending_snapshot={},
                last_cutover_attempt=last_cutover_attempt,
                last_error="" if result.ok else result.error,
                last_cutover_at=final_now,
                verified_at=final_now if result.ok else None,
            )
            conn.commit()

        return {
            "ok": result.ok,
            "status": result.status,
            "error": result.error,
            "attempt_id": attempt_id,
            "controller_state": self.get_controller_state(),
        }

    def get_current_mission_state(self, *, session_id: str = "") -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(session_id or "").strip():
            clauses.append("o.session_id = ?")
            params.append(str(session_id).strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                  o.id AS operation_id,
                  o.session_id,
                  o.source_message_id,
                  o.status AS operation_status,
                  o.active_revision_id,
                  o.policy_json,
                  o.created_at AS operation_created_at,
                  o.updated_at AS operation_updated_at,
                  r.id AS revision_id,
                  r.draft_id,
                  r.status AS revision_status,
                  r.mission_json,
                  r.intent_json,
                  r.validation_json,
                  r.review_context_json,
                  r.created_at AS revision_created_at,
                  r.updated_at AS revision_updated_at,
                  r.rejected_at
                FROM ai_mission_operations o
                LEFT JOIN ai_mission_revisions r ON r.id = o.active_revision_id
                {where}
                ORDER BY o.updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return {
                "active": False,
                "status": "no_active_mission",
                "summary": "No backend-owned mission proposal is stored yet.",
            }

        mission = _load_json(row["mission_json"])
        validation = _load_json(row["validation_json"])
        review_context = _load_json(row["review_context_json"])
        goal = str(mission.get("goal") or "").strip()
        route_artifacts = mission.get("route_artifacts") or []
        waypoint_count = 0
        for artifact in route_artifacts:
            if isinstance(artifact, dict):
                waypoint_count += int(artifact.get("waypoint_count") or len(artifact.get("waypoints") or []))
        status = str(row["operation_status"] or row["revision_status"] or "planning")
        active = status in MISSION_OPERATION_ACTIVE_STATUSES
        summary = f"Latest mission proposal status: {status}."
        if goal:
            summary = f"{summary} Goal: {goal}."
        if waypoint_count:
            summary = f"{summary} Route waypoints: {waypoint_count}."
        controller_state = self.get_controller_state()
        controller_version = int(controller_state.get("controller_version") or 0)
        controller_status = str(controller_state.get("status") or "")
        executing_revision_id = str(controller_state.get("active_revision_id") or "")
        if controller_status:
            summary = f"{summary} Controller status: {controller_status}."
        if controller_version:
            summary = f"{summary} Controller mission version: {controller_version}."

        return {
            "active": active,
            "status": status,
            "summary": summary,
            "operation_id": row["operation_id"],
            "revision_id": row["revision_id"],
            "draft_id": row["draft_id"],
            "session_id": row["session_id"],
            "goal": goal,
            "mission": mission,
            "validation": validation,
            "review_context": review_context,
            "waypoint_count": waypoint_count,
            "created_at": row["operation_created_at"],
            "updated_at": row["operation_updated_at"],
            "rejected_at": row["rejected_at"],
            "controller_state": controller_state,
            "controller_status": controller_status,
            "controller_version": controller_version,
            "executing_revision_id": executing_revision_id,
        }

    def get_revision_overlay(
        self,
        *,
        revision_id: str = "",
        draft_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        revision: dict[str, Any] | None = None
        if str(revision_id or "").strip():
            revision = self.get_revision(str(revision_id).strip())
        elif str(draft_id or "").strip():
            revision = self.get_revision_by_draft_id(str(draft_id).strip())
        else:
            revision = self.get_current_revision(session_id=session_id)
        if revision is None:
            return {
                "available": False,
                "status": "no_mission_overlay",
                "summary": "No mission overlay is available.",
                "features": [],
                "waypoint_count": 0,
                "bounds": None,
            }
        overlay = _build_mission_overlay_payload(
            revision, self._resolve_origin(revision.get("operation_id"))
        )
        overlay["summary"] = (
            f"Mission overlay for {overlay.get('status') or 'planning'} revision with "
            f"{int(overlay.get('waypoint_count') or 0)} waypoint"
            f"{'' if int(overlay.get('waypoint_count') or 0) == 1 else 's'}."
        )
        return overlay

    def create_client_revision(
        self,
        *,
        operation_id: str,
        waypoints: list[dict[str, Any]],
        label: str = "",
        from_revision_id: str = "",
    ) -> dict[str, Any]:
        operation_id = str(operation_id or "").strip()
        if not operation_id:
            return {"ok": False, "status": "invalid_request", "error": "operation_id is required"}

        with self._connect() as conn:
            op_row = conn.execute(
                "SELECT * FROM ai_mission_operations WHERE id = ?", (operation_id,)
            ).fetchone()
        if op_row is None:
            return {"ok": False, "status": "operation_not_found", "error": "operation not found"}

        op_status = str(op_row["status"] or "")
        if op_status == "executing":
            return {
                "ok": False,
                "status": "operation_locked",
                "error": "cannot create a revision while the operation is executing",
            }

        parent_provenance: dict[str, Any] = {}
        if from_revision_id:
            parent = self.get_revision(str(from_revision_id).strip())
            if parent is not None:
                parent_provenance = dict(parent.get("provenance") or {})

        now = time.time()
        revision_id = f"mission-rev-{uuid.uuid4().hex[:12]}"
        parent_revision_id = str(op_row["active_revision_id"] or "")

        origin = self._resolve_origin(operation_id)
        coerced: list[dict[str, Any]] = []
        for i, wp in enumerate(waypoints or [], start=1):
            point = _coerce_scene_point(wp, origin, fallback_id=f"client-wp-{i}")
            if point is None:
                return {
                    "ok": False,
                    "status": "invalid_waypoint",
                    "error": f"waypoint {i} is not a valid scene point (requires x, y, z as numbers)",
                }
            if not point.get("id"):
                point["id"] = f"client-wp-{uuid.uuid4().hex[:8]}"
            coerced.append(point)

        provenance: dict[str, str] = {}
        for wp in coerced:
            wid = wp["id"]
            provenance[wid] = parent_provenance.get(wid, "user")

        mission: dict[str, Any] = {
            "goal": str(label or "Client-authored revision"),
            "waypoints": [_stored_waypoint(
                {"id": wp["id"], "x": wp["x"], "y": wp["y"], "z": wp["z"],
                 "label": wp.get("label") or "", "kind": wp.get("kind") or "waypoint"},
                origin,
            ) for wp in coerced],
            "execution_allowed": False,
            "required_operator_approval": True,
        }

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_mission_revisions (
                  id, operation_id, draft_id, parent_revision_id, status,
                  mission_json, intent_json, target_resolution_json, validation_json,
                  review_context_json, provenance_json, client_version,
                  created_at, updated_at, approved_at, rejected_at
                ) VALUES (?, ?, '', ?, 'proposed', ?, '{}', '{}', '{}', '{}', ?, 0, ?, ?, NULL, NULL)
                """,
                (revision_id, operation_id, parent_revision_id, _json(mission), _json(provenance), now, now),
            )
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET active_revision_id = ?, status = 'proposed', updated_at = ?
                WHERE id = ?
                """,
                (revision_id, now, operation_id),
            )
            conn.commit()

        revision = self.get_revision(revision_id)
        return {"ok": True, "revision": revision}

    def create_blank_operation(
        self,
        *,
        name: str = "",
        waypoints: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a blank operation + revision for manual mission authoring.

        Used by the "➕ New mission" button (no waypoints) and JSON import
        (waypoints supplied). The operation has no session/source.
        """
        operation_id = f"mission-op-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_mission_operations (
                  id, session_id, source_message_id, status, active_revision_id,
                  policy_json, created_at, updated_at
                ) VALUES (?, '', '', 'proposed', '', '{}', ?, ?)
                """,
                (operation_id, now, now),
            )
            conn.commit()
        result = self.create_client_revision(
            operation_id=operation_id,
            waypoints=waypoints if waypoints is not None else [],
            label=name or "New mission",
        )
        if not result.get("ok"):
            return result
        revision = result.get("revision") or {}
        return {
            "ok": True,
            "operation_id": operation_id,
            "revision_id": str(revision.get("id") or ""),
        }

    def delete_operation(self, operation_id: str) -> None:
        """Delete an operation and all its revisions (compensating action for failed create)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM ai_mission_revisions WHERE operation_id = ?", (operation_id,))
            conn.execute("DELETE FROM ai_mission_operations WHERE id = ?", (operation_id,))
            conn.commit()

    def _create_rebased_revision_from_controller_state(
        self,
        revision: dict[str, Any],
        *,
        conn: sqlite3.Connection,
        controller_state: dict[str, Any],
        observed_controller_version: int,
        expected_controller_version: int | None,
    ) -> dict[str, Any] | None:
        verified_snapshot = controller_state.get("verified_snapshot")
        if not isinstance(verified_snapshot, dict) or not verified_snapshot:
            return None
        base_mission = verified_snapshot.get("mission")
        if not isinstance(base_mission, dict) or not base_mission:
            return None

        base_revision_id = str(controller_state.get("active_revision_id") or verified_snapshot.get("revision_id") or "").strip()
        if base_revision_id and base_revision_id == str(revision.get("id") or "").strip():
            return None

        now = time.time()
        rebased_revision_id = f"mission-rev-{uuid.uuid4().hex[:12]}"
        rebased_mission = _rebased_mission_payload(
            revision.get("mission") if isinstance(revision.get("mission"), dict) else {},
            self._resolve_origin(revision.get("operation_id")),
        )
        review_context = dict(revision.get("review_context") or {})
        review_context["rebase"] = {
            "reason": "stale_controller_version",
            "rebased_from_revision_id": str(revision.get("id") or ""),
            "rebased_from_operation_id": str(revision.get("operation_id") or ""),
            "expected_controller_version": expected_controller_version,
            "observed_controller_version": observed_controller_version,
            "base_controller_version": int(verified_snapshot.get("controller_version") or observed_controller_version),
            "base_operation_id": str(controller_state.get("active_operation_id") or verified_snapshot.get("operation_id") or ""),
            "base_revision_id": base_revision_id,
            "base_draft_id": str(controller_state.get("active_draft_id") or verified_snapshot.get("draft_id") or ""),
            "rebased_at": now,
        }
        review_context.setdefault(
            "review_notes",
            "Reapproval required after stale controller-version rejection.",
        )
        provenance = dict(revision.get("provenance") or {})

        source_operation_id = str(revision.get("operation_id") or "").strip()
        base_operation_id = str(controller_state.get("active_operation_id") or verified_snapshot.get("operation_id") or "").strip()
        operation_id = source_operation_id
        parent_revision_id = str(revision.get("id") or "").strip()

        source_operation = conn.execute(
            "SELECT * FROM ai_mission_operations WHERE id = ?",
            (source_operation_id,),
        ).fetchone()
        if source_operation is None:
            return None

        if base_operation_id and base_operation_id != source_operation_id:
            operation_id = f"mission-op-{uuid.uuid4().hex[:12]}"
            parent_revision_id = base_revision_id
            conn.execute(
                """
                INSERT INTO ai_mission_operations (
                  id, session_id, source_message_id, status, active_revision_id,
                  policy_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    str(source_operation["session_id"] or ""),
                    str(source_operation["source_message_id"] or ""),
                    rebased_revision_id,
                    str(source_operation["policy_json"] or "{}"),
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET active_revision_id = ?, status = 'proposed', updated_at = ?
                WHERE id = ?
                """,
                (rebased_revision_id, now, operation_id),
            )

        conn.execute(
            """
            INSERT INTO ai_mission_revisions (
              id, operation_id, draft_id, parent_revision_id, status,
              mission_json, intent_json, target_resolution_json, validation_json,
              review_context_json, provenance_json, client_version,
              created_at, updated_at, approved_at, rejected_at
            ) VALUES (?, ?, '', ?, 'proposed', ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL)
            """,
            (
                rebased_revision_id,
                operation_id,
                parent_revision_id,
                _json(rebased_mission),
                _json(revision.get("intent") if isinstance(revision.get("intent"), dict) else {}),
                _json(revision.get("target_resolution") if isinstance(revision.get("target_resolution"), dict) else {}),
                _json(revision.get("validation") if isinstance(revision.get("validation"), dict) else {}),
                _json(review_context),
                _json(provenance),
                now,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT
              r.*,
              o.session_id AS operation_session_id,
              o.source_message_id AS operation_source_message_id,
              o.status AS operation_status,
              o.policy_json AS operation_policy_json,
              o.active_revision_id AS operation_active_revision_id
            FROM ai_mission_revisions r
            JOIN ai_mission_operations o ON o.id = r.operation_id
            WHERE r.id = ?
            """,
            (rebased_revision_id,),
        ).fetchone()
        return _revision_row_to_dict(row) if row else None

    def update_waypoint(
        self,
        revision_id: str,
        waypoint_index: int,
        *,
        point: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        result = self._load_mutable_revision(revision_id, expected_version)
        if not result.get("ok"):
            return result
        revision = result["revision"]

        origin = self._resolve_origin(revision.get("operation_id"))
        waypoints = _collect_waypoints(revision.get("mission") or {}, origin)
        idx = int(waypoint_index) - 1
        if idx < 0 or idx >= len(waypoints):
            return {
                "ok": False,
                "status": "invalid_index",
                "error": f"waypoint_index {waypoint_index} is out of range (revision has {len(waypoints)} waypoints)",
            }

        new_point = _coerce_scene_point(point, origin, fallback_id=waypoints[idx].get("id") or f"wp-{waypoint_index}")
        if new_point is None:
            return {"ok": False, "status": "invalid_waypoint", "error": "point must have numeric x, y, z fields"}

        existing_id = waypoints[idx].get("id") or f"mission-wp-{waypoint_index}"
        new_point["id"] = existing_id
        new_point["label"] = point.get("label") or waypoints[idx].get("label") or ""
        new_point["kind"] = point.get("kind") or waypoints[idx].get("kind") or "waypoint"
        waypoints[idx] = new_point

        provenance = dict(revision.get("provenance") or {})
        old_prov = provenance.get(existing_id, "ai")
        provenance[existing_id] = "user" if old_prov == "user" else "ai+edited"

        return self._save_waypoint_mutation(revision, waypoints, provenance)

    def insert_waypoint(
        self,
        revision_id: str,
        *,
        after_index: int,
        point: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        result = self._load_mutable_revision(revision_id, expected_version)
        if not result.get("ok"):
            return result
        revision = result["revision"]

        origin = self._resolve_origin(revision.get("operation_id"))
        waypoints = _collect_waypoints(revision.get("mission") or {}, origin)
        new_point = _coerce_scene_point(point, origin, fallback_id=f"client-wp-{uuid.uuid4().hex[:8]}")
        if new_point is None:
            return {"ok": False, "status": "invalid_waypoint", "error": "point must have numeric x, y, z fields"}

        new_id = f"client-wp-{uuid.uuid4().hex[:8]}"
        new_point["id"] = new_id
        new_point["label"] = point.get("label") or ""
        new_point["kind"] = point.get("kind") or "waypoint"

        insert_pos = len(waypoints) if after_index < 0 else min(after_index, len(waypoints))
        waypoints.insert(insert_pos, new_point)

        provenance = dict(revision.get("provenance") or {})
        provenance[new_id] = "user"

        return self._save_waypoint_mutation(revision, waypoints, provenance)

    def delete_waypoint(
        self,
        revision_id: str,
        waypoint_index: int,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        result = self._load_mutable_revision(revision_id, expected_version)
        if not result.get("ok"):
            return result
        revision = result["revision"]

        waypoints = _collect_waypoints(
            revision.get("mission") or {}, self._resolve_origin(revision.get("operation_id"))
        )
        idx = int(waypoint_index) - 1
        if idx < 0 or idx >= len(waypoints):
            return {
                "ok": False,
                "status": "invalid_index",
                "error": f"waypoint_index {waypoint_index} is out of range (revision has {len(waypoints)} waypoints)",
            }

        removed_id = waypoints[idx].get("id") or f"mission-wp-{waypoint_index}"
        waypoints.pop(idx)

        provenance = dict(revision.get("provenance") or {})
        provenance.pop(removed_id, None)

        return self._save_waypoint_mutation(revision, waypoints, provenance)

    def _load_mutable_revision(self, revision_id: str, expected_version: int) -> dict[str, Any]:
        revision = self.get_revision(str(revision_id or "").strip())
        if revision is None:
            return {"ok": False, "status": "revision_not_found", "error": "mission revision not found"}

        status = str(revision.get("status") or "")
        LOCKED = frozenset({"exported", "cutover_pending", "executing"})
        if status in LOCKED:
            return {
                "ok": False,
                "status": "revision_locked",
                "error": f"revision status '{status}' does not allow waypoint mutations; "
                         "create a new client revision via POST /api/ai/mission-revisions",
            }

        current_version = int(revision.get("client_version") or 0)
        if int(expected_version) != current_version:
            return {
                "ok": False,
                "status": "version_conflict",
                "error": f"expected client_version {expected_version} but revision is at {current_version}",
                "current_version": current_version,
            }

        return {"ok": True, "revision": revision}

    def _save_waypoint_mutation(
        self,
        revision: dict[str, Any],
        waypoints: list[dict[str, Any]],
        provenance: dict[str, str],
    ) -> dict[str, Any]:
        mission = dict(revision.get("mission") or {})
        origin = self._resolve_origin(revision.get("operation_id"))
        mission["waypoints"] = [
            _stored_waypoint(
                {"id": wp["id"], "x": wp["x"], "y": wp["y"], "z": wp["z"],
                 "label": wp.get("label") or "", "kind": wp.get("kind") or "waypoint"},
                origin,
            )
            for wp in waypoints
        ]
        mission.pop("route_artifacts", None)
        mission.pop("steps", None)

        new_version = int(revision.get("client_version") or 0) + 1
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_mission_revisions
                SET mission_json = ?, provenance_json = ?, client_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (_json(mission), _json(provenance), new_version, now, revision["id"]),
            )
            conn.commit()
        updated = self.get_revision(revision["id"])
        return {"ok": True, "revision": updated, "client_version": new_version}

    def _set_revision_status(self, draft_id: str, *, status: str, note: str, timestamp_field: str) -> dict[str, Any] | None:
        revision = self.get_revision_by_draft_id(draft_id)
        if revision is None:
            return None
        return self._set_revision_status_row(revision, status=status, note=note, timestamp_field=timestamp_field)

    def _set_revision_status_by_revision_id(
        self,
        revision_id: str,
        *,
        status: str,
        note: str,
        timestamp_field: str,
    ) -> dict[str, Any] | None:
        revision = self.get_revision(str(revision_id or "").strip())
        if revision is None:
            return None
        return self._set_revision_status_row(revision, status=status, note=note, timestamp_field=timestamp_field)

    def _set_revision_status_row(
        self,
        revision: dict[str, Any],
        *,
        status: str,
        note: str,
        timestamp_field: str,
    ) -> dict[str, Any] | None:
        review_context = dict(revision.get("review_context") or {})
        review_context["approval_note"] = str(note or "")
        review_context["reviewed_at"] = time.time()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE ai_mission_revisions
                SET status = ?, review_context_json = ?, updated_at = ?, {timestamp_field} = ?
                WHERE id = ?
                """,
                (status, _json(review_context), now, now, revision["id"]),
            )
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, revision["operation_id"]),
            )
            conn.commit()
        return self.get_revision(revision["id"])

    def _ensure_controller_state_row(self, conn: sqlite3.Connection) -> sqlite3.Row:
        now = time.time()
        row = conn.execute(
            """
            SELECT * FROM ai_mission_controller_state
            WHERE controller_id = ?
            """,
            (MISSION_CONTROLLER_ID,),
        ).fetchone()
        if row is not None:
            return row
        conn.execute(
            """
            INSERT INTO ai_mission_controller_state (
              controller_id, current_version, active_operation_id, active_revision_id,
              active_draft_id, status, verified_snapshot_json,
              previous_verified_snapshot_json, pending_snapshot_json,
              last_cutover_attempt_json, last_error, last_cutover_at,
              verified_at, updated_at
            ) VALUES (?, 0, '', '', '', 'idle', '{}', '{}', '{}', '{}', '', NULL, NULL, ?)
            """,
            (MISSION_CONTROLLER_ID, now),
        )
        row = conn.execute(
            """
            SELECT * FROM ai_mission_controller_state
            WHERE controller_id = ?
            """,
            (MISSION_CONTROLLER_ID,),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to initialize mission controller state")
        return row

    def _controller_state_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        verified_snapshot = _load_json(row["verified_snapshot_json"])
        previous_verified_snapshot = _load_json(row["previous_verified_snapshot_json"])
        pending_snapshot = _load_json(row["pending_snapshot_json"])
        last_cutover_attempt = _load_json(row["last_cutover_attempt_json"])
        version = int(row["current_version"] or 0)
        status = str(row["status"] or "idle")
        active_revision_id = str(row["active_revision_id"] or "")
        summary = f"Controller mission state: {status}."
        if version:
            summary = f"{summary} Version: {version}."
        if active_revision_id:
            summary = f"{summary} Active revision: {active_revision_id}."
        return {
            "available": True,
            "controller_id": str(row["controller_id"] or MISSION_CONTROLLER_ID),
            "controller_version": version,
            "active_operation_id": str(row["active_operation_id"] or ""),
            "active_revision_id": active_revision_id,
            "active_draft_id": str(row["active_draft_id"] or ""),
            "status": status,
            "summary": summary,
            "verified_snapshot": _controller_snapshot_to_public(verified_snapshot),
            "previous_verified_snapshot": _controller_snapshot_to_public(previous_verified_snapshot),
            "pending_snapshot": _controller_snapshot_to_public(pending_snapshot),
            "last_cutover_attempt": last_cutover_attempt if isinstance(last_cutover_attempt, dict) else {},
            "last_error": str(row["last_error"] or ""),
            "last_cutover_at": row["last_cutover_at"],
            "verified_at": row["verified_at"],
            "updated_at": row["updated_at"],
            "adapter": self._controller_adapter.adapter_name,
        }

    def _project_controller_state(
        self,
        conn: sqlite3.Connection,
        *,
        adapter_state: ControllerMissionAdapterState,
        verified_snapshot: dict[str, Any],
        previous_verified_snapshot: dict[str, Any],
        pending_snapshot: dict[str, Any],
        last_cutover_attempt: dict[str, Any],
        last_error: str,
        last_cutover_at: float,
        verified_at: float | None = None,
    ) -> None:
        conn.execute(
            """
            UPDATE ai_mission_controller_state
            SET current_version = ?,
                active_operation_id = ?,
                active_revision_id = ?,
                active_draft_id = ?,
                status = ?,
                verified_snapshot_json = ?,
                previous_verified_snapshot_json = ?,
                pending_snapshot_json = ?,
                last_cutover_attempt_json = ?,
                last_error = ?,
                last_cutover_at = ?,
                verified_at = ?,
                updated_at = ?
            WHERE controller_id = ?
            """,
            (
                int(adapter_state.controller_version or 0),
                adapter_state.operation_id,
                adapter_state.revision_id,
                adapter_state.draft_id,
                str(adapter_state.status or "idle"),
                _json(verified_snapshot),
                _json(previous_verified_snapshot),
                _json(pending_snapshot),
                _json(last_cutover_attempt),
                str(last_error or ""),
                last_cutover_at,
                verified_at,
                time.time(),
                MISSION_CONTROLLER_ID,
            ),
        )

    def _insert_execution_attempt(
        self,
        conn: sqlite3.Connection,
        *,
        attempt_id: str,
        revision: dict[str, Any],
        expected_controller_version: int | None,
        observed_controller_version: int,
        installed_controller_version: int | None,
        status: str,
        request_payload: dict[str, Any],
        result_payload: dict[str, Any],
        error_text: str,
        now: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ai_mission_execution_attempts (
              id, operation_id, revision_id, expected_controller_version,
              observed_controller_version, installed_controller_version, status,
              error_text, request_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                revision.get("operation_id", ""),
                revision.get("id", ""),
                expected_controller_version,
                observed_controller_version,
                installed_controller_version,
                status,
                error_text,
                _json(request_payload),
                _json(result_payload),
                now,
                now,
            ),
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            apply_ai_store_migrations(conn)
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def _revision_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for field in (
        "mission_json",
        "intent_json",
        "target_resolution_json",
        "validation_json",
        "review_context_json",
        "operation_policy_json",
        "provenance_json",
    ):
        key = field.removesuffix("_json")
        out[key] = _load_json(out.pop(field, "{}"))
    out["session_id"] = out.pop("operation_session_id", "")
    out["source_message_id"] = out.pop("operation_source_message_id", "")
    out["operation_status"] = out.get("operation_status", "")
    out["active_revision_id"] = out.pop("operation_active_revision_id", "")
    out.setdefault("client_version", 0)
    return out
