from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any


DRAFT_STATUSES = frozenset({
    "draft",
    "proposed",
    "needs_clarification",
    "validation_failed",
    "exported",
    "rejected",
    "superseded",
})

_EXECUTION_LIKE_FIELDS = frozenset({"execute", "start", "publish", "send_command", "stage"})
_TELEMETRY_STALE_SECONDS = 30.0


def validate_draft_payload(
    intent: dict[str, Any],
    target_resolution: dict[str, Any],
    draft_payload: dict[str, Any],
    rover_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic validation of a mission draft.

    Returns a validation dict with status, blockers, warnings, and notes.
    Status values: valid, warning, needs_clarification, blocked, unsafe.
    """
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # execution_allowed must be false — hard blocker if someone snuck it in
    if draft_payload.get("execution_allowed") is True:
        blockers.append("execution_allowed must be false in the planning-shell phase")

    # check for execution-like top-level fields in draft
    for field in _EXECUTION_LIKE_FIELDS:
        if field in draft_payload:
            blockers.append(f"draft contains disallowed execution field: '{field}'")

    # check steps for execution-like content
    for step in (draft_payload.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for field in _EXECUTION_LIKE_FIELDS:
            if field in step:
                blockers.append(f"draft step contains disallowed execution field: '{field}'")

    # require operator approval for rover motion
    if intent.get("requires_rover_motion") and not draft_payload.get("required_operator_approval", True):
        blockers.append("required_operator_approval must be true when rover motion is involved")

    # spatial navigation requires resolved target
    requires_motion = bool(intent.get("requires_rover_motion"))
    has_spatial_target = _has_spatial_target(intent)
    if requires_motion and has_spatial_target:
        resolved = _target_resolved(target_resolution)
        if resolved == "blocked":
            blockers.append("spatial navigation requires a resolved target; scene or rover pose unavailable")
        elif resolved == "ambiguous":
            notes.append("spatial target is ambiguous; clarification may be needed")
            if not blockers:
                return _validation_result("needs_clarification", blockers, warnings, notes)

    # stale telemetry check
    if rover_state is not None:
        freshness = rover_state.get("freshness_seconds")
        if freshness is None:
            if requires_motion:
                warnings.append("rover telemetry freshness is unknown; draft risk elevated for motion tasks")
        elif float(freshness) > _TELEMETRY_STALE_SECONDS:
            if requires_motion:
                warnings.append(
                    f"rover telemetry is stale ({freshness:.0f}s old); "
                    "draft requires fresh rover pose before execution can be considered"
                )
            else:
                notes.append(f"rover telemetry is stale ({freshness:.0f}s old)")

    # unavailable scene data is a blocker for spatial missions
    if requires_motion and has_spatial_target:
        scene_ok = target_resolution.get("ok", False)
        scene_error = str(target_resolution.get("error", "")).lower()
        if not scene_ok and ("scene" in scene_error or "unavailable" in scene_error or "no pose" in scene_error):
            blockers.append("scene or map data unavailable; spatial mission cannot be validated")

    if blockers:
        status = "blocked"
    elif warnings:
        status = "warning"
    else:
        status = "valid"

    return _validation_result(status, blockers, warnings, notes)


def _has_spatial_target(intent: dict[str, Any]) -> bool:
    target = intent.get("target") or {}
    if not isinstance(target, dict):
        return False
    return any(
        target.get(k) not in (None, "")
        for k in ("description", "kind", "side", "relative_bearing_deg")
    )


def _target_resolved(target_resolution: dict[str, Any]) -> str:
    if not target_resolution.get("ok", False):
        error = str(target_resolution.get("error", "")).lower()
        if "unavailable" in error or "no pose" in error or "scene" in error:
            return "blocked"
        return "ambiguous"
    candidates = target_resolution.get("candidates") or target_resolution.get("objects") or []
    if len(candidates) == 0:
        return "ambiguous"
    return "resolved"


def _validation_result(
    status: str,
    blockers: list[str],
    warnings: list[str],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "notes": notes,
        "validated_at": time.time(),
    }


def _draft_status_from_validation(validation: dict[str, Any]) -> str:
    status = str(validation.get("status", "valid"))
    if status in ("blocked", "unsafe"):
        return "validation_failed"
    if status == "needs_clarification":
        return "needs_clarification"
    return "proposed"


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


class MissionDraftService:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)

    def create_draft(
        self,
        *,
        session_id: str,
        source_message_id: str = "",
        intent: dict[str, Any],
        target_resolution: dict[str, Any],
        draft_payload: dict[str, Any],
        rover_state: dict[str, Any] | None = None,
        draft_id: str = "",
    ) -> dict[str, Any]:
        validation = validate_draft_payload(intent, target_resolution, draft_payload, rover_state)
        status = _draft_status_from_validation(validation)

        # enforce execution_allowed = false regardless of input
        draft_payload = dict(draft_payload)
        draft_payload["execution_allowed"] = False

        draft_id = str(draft_id or "").strip() or f"ai-draft-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_mission_drafts (
                  id, session_id, source_message_id, status,
                  intent_json, target_resolution_json, draft_json, validation_json,
                  created_at, updated_at, approved_at, rejected_at, approval_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '')
                """,
                (
                    draft_id,
                    session_id,
                    source_message_id or "",
                    status,
                    _json(intent),
                    _json(target_resolution),
                    _json(draft_payload),
                    _json(validation),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_draft(draft_id) or {}

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_mission_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list_drafts(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status_filter is not None:
            clauses.append("status = ?")
            params.append(status_filter)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM ai_mission_drafts {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def reject_draft(self, draft_id: str, *, note: str = "") -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_mission_drafts
                SET status = 'rejected', rejected_at = ?, updated_at = ?, approval_note = ?
                WHERE id = ? AND status IN ('proposed', 'needs_clarification')
                """,
                (now, now, str(note or ""), draft_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_draft(draft_id)

    def mark_exported(self, draft_id: str, *, export_result: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_draft(draft_id)
        if current is None or current.get("status") in ("rejected", "superseded", "validation_failed"):
            return None

        draft_payload = dict(current.get("draft") or {})
        draft_payload["mission_export"] = {
            "file_path": str(export_result.get("file_path") or ""),
            "waypoint_count": int(export_result.get("waypoint_count") or 0),
            "vehicle_type": int(export_result.get("vehicle_type") or 0),
            "exported_at": time.time(),
        }

        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_mission_drafts
                SET status = 'exported', draft_json = ?, updated_at = ?
                WHERE id = ? AND status NOT IN ('rejected', 'superseded', 'validation_failed')
                """,
                (_json(draft_payload), now, draft_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_draft(draft_id)

    def supersede_draft(self, draft_id: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE ai_mission_drafts
                SET status = 'superseded', updated_at = ?
                WHERE id = ? AND status IN ('draft', 'proposed', 'needs_clarification')
                """,
                (now, draft_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for field in ("intent_json", "target_resolution_json", "draft_json", "validation_json"):
        key = field.removesuffix("_json")
        out[key] = _load_json(out.pop(field, "{}"))
    return out
