"""Read seam over `ai_mission_revisions` joined to `ai_mission_operations`.

The revision-row-with-operation-context `SELECT` was previously duplicated
verbatim four times across `MissionExecutionService` (O3, architecture review
A2). This repository owns that query and the row shape; it takes a live
connection rather than a `db_path` so callers can share a transaction
(`execute_revision`'s multi-statement rebase) or point it at `:memory:` in
tests.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_REVISION_SELECT = """
    SELECT
      r.*,
      o.session_id AS operation_session_id,
      o.source_message_id AS operation_source_message_id,
      o.status AS operation_status,
      o.policy_json AS operation_policy_json,
      o.active_revision_id AS operation_active_revision_id
    FROM ai_mission_revisions r
    JOIN ai_mission_operations o ON o.id = r.operation_id
"""


def _load_json(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def revision_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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


class MissionRevisionRepository:
    """Revision/operation reads, bound to a connection rather than a db_path."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"{_REVISION_SELECT} WHERE r.id = ?", (revision_id,)
        ).fetchone()
        return revision_row_to_dict(row) if row else None

    def get_revision_by_draft_id(self, draft_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"""{_REVISION_SELECT}
            WHERE r.draft_id = ?
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            (draft_id,),
        ).fetchone()
        return revision_row_to_dict(row) if row else None

    def get_operation_active_revision_id(self, operation_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT active_revision_id FROM ai_mission_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        return str(row["active_revision_id"] or "") if row else None

    def get_operation_status(self, operation_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, status FROM ai_mission_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM ai_mission_operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_revision_provenance(self, revision_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT provenance_json FROM ai_mission_revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        return _load_json(row["provenance_json"]) if row else None

    def get_current_operation_with_revision(
        self, *, session_id: str = ""
    ) -> dict[str, Any] | None:
        """Latest operation (by `updated_at`), left-joined to its active revision.

        Distinct row shape from `_REVISION_SELECT` (aliases `o.status` as
        `operation_status`, includes no `operation_*` prefix on revision
        columns) — used only by `get_current_mission_state`.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if str(session_id or "").strip():
            clauses.append("o.session_id = ?")
            params.append(str(session_id).strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._conn.execute(
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
        return dict(row) if row else None

    def get_active_revision_fields(
        self, operation_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Batch-resolve each operation's active revision id/status/mission_json.

        Used by `MissionStore.list_missions` to resolve every Mission's active
        revision in one round trip instead of N+1 per-mission queries.
        """
        ids = [str(i) for i in operation_ids if str(i or "").strip()]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"""
            SELECT o.id AS operation_id,
                   COALESCE(r.id, '') AS active_revision_id,
                   COALESCE(r.status, '') AS active_revision_status,
                   COALESCE(r.mission_json, '{{}}') AS active_revision_mission_json
            FROM ai_mission_operations o
            LEFT JOIN ai_mission_revisions r ON r.id = o.active_revision_id
            WHERE o.id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        return {row["operation_id"]: dict(row) for row in rows}

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
        rows = self._conn.execute(
            f"""{_REVISION_SELECT}
            {where}
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [revision_row_to_dict(row) for row in rows]
