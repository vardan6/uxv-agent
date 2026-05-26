from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .migrations import apply_ai_store_migrations


VALID_ORIGINS = ("manual", "ai_chat")


@dataclass(frozen=True)
class Mission:
    """Flat first-class Mission per ADR 0021 §2."""

    id: int  # stable, monotonic, never reused (SQLite AUTOINCREMENT)
    name: str
    origin: str  # "manual" | "ai_chat"
    origin_chat_id: str | None
    created_at: float
    created_by_user_id: str
    client_version: int  # ADR 0020 optimistic concurrency
    mission_json: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin,
            "origin_chat_id": self.origin_chat_id,
            "created_at": self.created_at,
            "created_by_user_id": self.created_by_user_id,
            "client_version": self.client_version,
            "mission_json": self.mission_json,
        }


class MissionVersionConflict(Exception):
    """Raised when an update's expected client_version does not match storage."""

    def __init__(self, mission_id: int, expected: int, actual: int) -> None:
        super().__init__(
            f"mission {mission_id} version conflict: expected {expected}, actual {actual}"
        )
        self.mission_id = mission_id
        self.expected = expected
        self.actual = actual


class MissionNotFound(Exception):
    def __init__(self, mission_id: int) -> None:
        super().__init__(f"mission {mission_id} not found")
        self.mission_id = mission_id


class MissionRepository:
    """CRUD for the flat missions table.

    `id` is the operator-facing #index from ADR 0021 §2 — monotonic and
    never reused, guaranteed by SQLite's INTEGER PRIMARY KEY AUTOINCREMENT.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with self._connect() as conn:
            apply_ai_store_migrations(conn)
            conn.commit()

    def create(
        self,
        *,
        name: str,
        origin: str,
        mission_json: dict[str, Any] | None = None,
        origin_chat_id: str | None = None,
        created_by_user_id: str = "",
    ) -> Mission:
        if origin not in VALID_ORIGINS:
            raise ValueError(f"origin must be one of {VALID_ORIGINS}, got {origin!r}")
        created_at = time.time()
        payload = json.dumps(mission_json or {}, separators=(",", ":"))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO missions (
                  name, origin, origin_chat_id, created_at,
                  created_by_user_id, client_version, mission_json
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (name, origin, origin_chat_id, created_at, created_by_user_id, payload),
            )
            mission_id = int(cursor.lastrowid)
            conn.commit()
        return Mission(
            id=mission_id,
            name=name,
            origin=origin,
            origin_chat_id=origin_chat_id,
            created_at=created_at,
            created_by_user_id=created_by_user_id,
            client_version=0,
            mission_json=mission_json or {},
        )

    def get(self, mission_id: int) -> Mission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        return _row_to_mission(row) if row is not None else None

    def list(
        self,
        *,
        origin_chat_id: str | None = None,
        limit: int | None = None,
    ) -> list[Mission]:
        query = "SELECT * FROM missions"
        params: list[Any] = []
        if origin_chat_id is not None:
            query += " WHERE origin_chat_id = ?"
            params.append(origin_chat_id)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_mission(row) for row in rows]

    def update(
        self,
        mission_id: int,
        *,
        expected_client_version: int,
        name: str | None = None,
        mission_json: dict[str, Any] | None = None,
        origin: str | None = None,
        origin_chat_id: str | None = None,
    ) -> Mission:
        """Optimistic-concurrency update. Bumps client_version on success.

        Raises MissionNotFound or MissionVersionConflict.
        """
        if origin is not None and origin not in VALID_ORIGINS:
            raise ValueError(f"origin must be one of {VALID_ORIGINS}, got {origin!r}")
        sets: list[str] = ["client_version = client_version + 1"]
        params: list[Any] = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if mission_json is not None:
            sets.append("mission_json = ?")
            params.append(json.dumps(mission_json, separators=(",", ":")))
        if origin is not None:
            sets.append("origin = ?")
            params.append(origin)
        if origin_chat_id is not None:
            sets.append("origin_chat_id = ?")
            params.append(origin_chat_id)
        params.extend([mission_id, expected_client_version])
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE missions SET {', '.join(sets)} "
                "WHERE id = ? AND client_version = ?",
                params,
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT client_version FROM missions WHERE id = ?", (mission_id,)
                ).fetchone()
                if row is None:
                    raise MissionNotFound(mission_id)
                raise MissionVersionConflict(
                    mission_id, expected_client_version, int(row["client_version"])
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        return _row_to_mission(row)

    def delete(self, mission_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
            conn.commit()
        return cursor.rowcount > 0

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def validate_mission_json(mission_json: dict[str, Any] | None) -> dict[str, Any]:
    """Structural validation for a flat-Mission `mission_json` payload (ADR 0021).

    Mirrors the contract expected by MissionExportService: a Mission is
    executable iff at least one well-formed waypoint can be collected from
    `waypoints`, `route_artifacts[].waypoints`, or `steps[].waypoints`. Each
    waypoint needs numeric `x` and `y`; `z` defaults to 0.

    Returns {"blockers": [...], "warnings": [...], "status": "ok|warned|blocked"}.
    Callers route on `blockers`; warnings are advisory.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if not isinstance(mission_json, dict) or not mission_json:
        return {"blockers": ["mission_json is empty"], "warnings": [], "status": "blocked"}

    name = mission_json.get("name")
    if name is not None and not isinstance(name, str):
        warnings.append("mission_json.name should be a string")

    waypoints = _collect_waypoints_for_validation(mission_json)
    if not waypoints:
        blockers.append(
            "mission has no waypoints (expected mission_json.waypoints, "
            "mission_json.route_artifacts[].waypoints, or mission_json.steps[].waypoints)"
        )
    else:
        for idx, wp in enumerate(waypoints):
            if not isinstance(wp, dict):
                blockers.append(f"waypoint #{idx} is not an object")
                continue
            for axis in ("x", "y"):
                value = wp.get(axis)
                if value is None:
                    blockers.append(f"waypoint #{idx} is missing required field '{axis}'")
                else:
                    try:
                        float(value)
                    except (TypeError, ValueError):
                        blockers.append(f"waypoint #{idx} field '{axis}' is not numeric: {value!r}")
            if "z" in wp and wp["z"] is not None:
                try:
                    float(wp["z"])
                except (TypeError, ValueError):
                    warnings.append(f"waypoint #{idx} field 'z' is not numeric; defaulting to 0")

    steps = mission_json.get("steps")
    if steps is not None and not isinstance(steps, list):
        warnings.append("mission_json.steps should be a list")

    if blockers:
        status = "blocked"
    elif warnings:
        status = "warned"
    else:
        status = "ok"
    return {"blockers": blockers, "warnings": warnings, "status": status}


def _collect_waypoints_for_validation(mission_json: dict[str, Any]) -> list[Any]:
    if isinstance(mission_json.get("waypoints"), list):
        return list(mission_json["waypoints"])
    artifact_wps: list[Any] = []
    for artifact in (mission_json.get("route_artifacts") or []):
        if isinstance(artifact, dict) and isinstance(artifact.get("waypoints"), list):
            artifact_wps.extend(artifact["waypoints"])
    if artifact_wps:
        return artifact_wps
    step_wps: list[Any] = []
    for step in (mission_json.get("steps") or []):
        if isinstance(step, dict) and isinstance(step.get("waypoints"), list):
            step_wps.extend(step["waypoints"])
    return step_wps


def _row_to_mission(row: sqlite3.Row) -> Mission:
    try:
        payload = json.loads(row["mission_json"]) if row["mission_json"] else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return Mission(
        id=int(row["id"]),
        name=str(row["name"]),
        origin=str(row["origin"]),
        origin_chat_id=row["origin_chat_id"],
        created_at=float(row["created_at"]),
        created_by_user_id=str(row["created_by_user_id"]),
        client_version=int(row["client_version"]),
        mission_json=payload,
    )
