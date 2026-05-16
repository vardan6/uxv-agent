from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .migrations import apply_ai_store_migrations


MISSION_OPERATION_ACTIVE_STATUSES = frozenset({
    "planning",
    "awaiting_approval",
    "approved",
    "exported",
})


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


def _canonicalize_mission_payload(draft_payload: dict[str, Any]) -> dict[str, Any]:
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

    return mission


def _operation_status_from_revision(status: str) -> str:
    clean = str(status or "").strip().lower()
    if clean in {"awaiting_approval", "approved", "exported", "rejected", "validation_failed", "needs_clarification"}:
        return clean
    return "planning"


def _coerce_scene_point(value: Any, *, fallback_id: str = "") -> dict[str, Any] | None:
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


def _collect_waypoints(mission: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(mission, dict):
        return []
    if isinstance(mission.get("waypoints"), list):
        direct = [
            _coerce_scene_point(wp, fallback_id=f"wp-{index}")
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
                fallback_id=f"step-{step_index}-wp-{waypoint_index}",
            )
            if point is not None:
                step_waypoints.append(point)
    return step_waypoints


def _route_overlay_features(mission: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for artifact_index, artifact in enumerate(mission.get("route_artifacts") or [], start=1):
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("route_id") or f"route-{artifact_index}")
        waypoints = [
            point
            for point in (
                _coerce_scene_point(wp, fallback_id=f"{artifact_id}-wp-{waypoint_index}")
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
            "points": [{"x": point["x"], "y": point["y"], "z": point["z"]} for point in waypoints],
        })
    return features


def _build_mission_overlay_payload(revision: dict[str, Any]) -> dict[str, Any]:
    mission = revision.get("mission") if isinstance(revision.get("mission"), dict) else {}
    waypoints = _collect_waypoints(mission)
    route_features = _route_overlay_features(mission)
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
        "mission_export": mission.get("mission_export") if isinstance(mission.get("mission_export"), dict) else {},
    }


class MissionExecutionService:
    """First backend-owned mission lifecycle boundary.

    This service does not perform controller handoff yet. It owns canonical
    proposal/revision storage so planning output can move away from draft-only
    ownership before execution integration lands.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
    ) -> dict[str, Any]:
        now = time.time()
        operation_id = f"mission-op-{uuid.uuid4().hex[:12]}"
        revision_id = f"mission-rev-{uuid.uuid4().hex[:12]}"
        mission = _canonicalize_mission_payload(draft_payload)
        operation_status = _operation_status_from_revision(draft_status)
        policy = {
            "execution_allowed": False,
            "approval_required": bool(mission.get("required_operator_approval", True)),
            "approval_scope": "planning_artifact_only",
        }

        with self._connect() as conn:
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

    def approve_revision_for_draft(self, draft_id: str, *, note: str = "") -> dict[str, Any] | None:
        return self._set_revision_status(draft_id, status="approved", note=note, timestamp_field="approved_at")

    def reject_revision_for_draft(self, draft_id: str, *, note: str = "") -> dict[str, Any] | None:
        return self._set_revision_status(draft_id, status="rejected", note=note, timestamp_field="rejected_at")

    def mark_revision_exported(self, draft_id: str, *, export_result: dict[str, Any]) -> dict[str, Any] | None:
        revision = self.get_revision_by_draft_id(draft_id)
        if revision is None:
            return None
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
                  r.approved_at,
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
            "approved_at": row["approved_at"],
            "rejected_at": row["rejected_at"],
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
        overlay = _build_mission_overlay_payload(revision)
        overlay["summary"] = (
            f"Mission overlay for {overlay.get('status') or 'planning'} revision with "
            f"{int(overlay.get('waypoint_count') or 0)} waypoint"
            f"{'' if int(overlay.get('waypoint_count') or 0) == 1 else 's'}."
        )
        return overlay

    def _set_revision_status(self, draft_id: str, *, status: str, note: str, timestamp_field: str) -> dict[str, Any] | None:
        revision = self.get_revision_by_draft_id(draft_id)
        if revision is None:
            return None
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
    ):
        key = field.removesuffix("_json")
        out[key] = _load_json(out.pop(field, "{}"))
    out["session_id"] = out.pop("operation_session_id", "")
    out["source_message_id"] = out.pop("operation_source_message_id", "")
    out["operation_status"] = out.get("operation_status", "")
    out["active_revision_id"] = out.pop("operation_active_revision_id", "")
    return out
