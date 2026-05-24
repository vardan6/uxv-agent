from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .controller_mission_adapter import (
    ControllerMissionAdapter,
    ControllerMissionAdapterState,
    JsonFileControllerMissionAdapter,
)
from .migrations import apply_ai_store_migrations


MISSION_OPERATION_ACTIVE_STATUSES = frozenset({
    "planning",
    "awaiting_approval",
    "approved",
    "exported",
    "cutover_pending",
    "executing",
})

MISSION_EXECUTION_READY_STATUSES = frozenset({"approved", "exported", "executing"})
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
    if clean in {
        "awaiting_approval",
        "approved",
        "exported",
        "cutover_pending",
        "executing",
        "rejected",
        "validation_failed",
        "needs_clarification",
    }:
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
    provenance_map = revision.get("provenance") if isinstance(revision.get("provenance"), dict) else {}
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
    ):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._controller_adapter = controller_adapter or JsonFileControllerMissionAdapter(
            self._db_path.parent / "controller_mission_adapter.json"
        )
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
        parent_operation_id: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        revision_id = f"mission-rev-{uuid.uuid4().hex[:12]}"
        mission = _canonicalize_mission_payload(draft_payload)
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
                parent_revision_id = str(
                    (conn.execute(
                        "SELECT active_revision_id FROM ai_mission_operations WHERE id = ?",
                        (parent_op,),
                    ).fetchone() or {}).get("active_revision_id") or ""
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
                conn.commit()
                return {
                    "ok": False,
                    "status": "stale_controller_version",
                    "error": "expected controller mission version does not match the latest verified version",
                    "controller_state": self.get_controller_state(),
                    "attempt_id": attempt_id,
                    "revision": revision,
                }

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

    def get_controller_state(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._ensure_controller_state_row(conn)
            conn.commit()
        return self._controller_state_from_row(row)

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
            "approved_at": row["approved_at"],
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
        overlay = _build_mission_overlay_payload(revision)
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

        coerced: list[dict[str, Any]] = []
        for i, wp in enumerate(waypoints or [], start=1):
            point = _coerce_scene_point(wp, fallback_id=f"client-wp-{i}")
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
            "waypoints": [{"id": wp["id"], "x": wp["x"], "y": wp["y"], "z": wp["z"],
                           "label": wp.get("label") or "", "kind": wp.get("kind") or "waypoint"}
                          for wp in coerced],
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
                ) VALUES (?, ?, '', ?, 'awaiting_approval', ?, '{}', '{}', '{}', '{}', ?, 0, ?, ?, NULL, NULL)
                """,
                (revision_id, operation_id, parent_revision_id, _json(mission), _json(provenance), now, now),
            )
            conn.execute(
                """
                UPDATE ai_mission_operations
                SET active_revision_id = ?, status = 'awaiting_approval', updated_at = ?
                WHERE id = ?
                """,
                (revision_id, now, operation_id),
            )
            conn.commit()

        revision = self.get_revision(revision_id)
        return {"ok": True, "revision": revision}

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

        waypoints = _collect_waypoints(revision.get("mission") or {})
        idx = int(waypoint_index) - 1
        if idx < 0 or idx >= len(waypoints):
            return {
                "ok": False,
                "status": "invalid_index",
                "error": f"waypoint_index {waypoint_index} is out of range (revision has {len(waypoints)} waypoints)",
            }

        new_point = _coerce_scene_point(point, fallback_id=waypoints[idx].get("id") or f"wp-{waypoint_index}")
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

        waypoints = _collect_waypoints(revision.get("mission") or {})
        new_point = _coerce_scene_point(point, fallback_id=f"client-wp-{uuid.uuid4().hex[:8]}")
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

        waypoints = _collect_waypoints(revision.get("mission") or {})
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
        LOCKED = frozenset({"approved", "exported", "cutover_pending", "executing"})
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
        mission["waypoints"] = [
            {"id": wp["id"], "x": wp["x"], "y": wp["y"], "z": wp["z"],
             "label": wp.get("label") or "", "kind": wp.get("kind") or "waypoint"}
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
