"""Operational constraints store (ADR 0025, V2 contract).

Allowed corridors (planner must stay inside) and blockages (planner must stay
outside) are backend-owned *planning* data — not live vehicle containment, and
deliberately separate from mission revisions and the per-mission geofence.

V1 is intentionally small: WGS84 polygon geometry only, a `hard`|`soft` rule, an
enable/disable lifecycle, deployment-wide scope, and an optimistic-concurrency
`version`. WGS84 is the only persisted truth (ADR 0022); no second
`coordinate_frame` field survives normalization. Deletion is guarded by
`expected_version`; disabling is the reversible path.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import polygon_geometry
from .migrations import apply_ai_store_migrations


KINDS = frozenset({"allowed_corridor", "blockage"})
RULES = frozenset({"hard", "soft"})


class ConstraintValidationError(ValueError):
    """Payload failed validation — maps to HTTP 400."""


class ConstraintConflict(Exception):
    """Stale `expected_version` — maps to HTTP 409. The client should refresh."""


class ConstraintNotFound(Exception):
    """No constraint with that id — maps to HTTP 404."""


def _normalize_polygon(value: Any) -> list[dict[str, float]]:
    """Validate and normalize a WGS84 polygon (ADR 0025 §Required validation).

    The ring is stored *open* — the V1 object in ADR 0025 lists three vertices
    without repeating the first, and the planner joins last→first itself. The
    "normalized closed polygon at the backend boundary" requirement is met by
    normalizing away a redundant closing vertex here rather than by persisting a
    duplicate. Rejects non-finite coordinates, out-of-range coordinates, stray
    duplicate vertices, fewer than three distinct vertices, degenerate
    (zero-area / collinear) rings, and self-intersecting rings."""
    if not isinstance(value, list):
        raise ConstraintValidationError("polygon must be a list of {lat, lon} vertices")
    raw: list[dict[str, float]] = []
    for vertex in value:
        if not isinstance(vertex, dict):
            raise ConstraintValidationError("each polygon vertex must be an object")
        try:
            lat = float(vertex.get("lat"))
            lon = float(vertex.get("lon"))
        except (TypeError, ValueError):
            raise ConstraintValidationError("polygon vertices need numeric lat/lon")
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ConstraintValidationError("polygon vertices must be finite")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ConstraintValidationError("polygon vertices out of WGS84 range")
        raw.append({"lat": lat, "lon": lon})

    def _key(v: dict[str, float]) -> tuple[float, float]:
        return (round(v["lat"], 9), round(v["lon"], 9))

    # Normalize a single redundant closing vertex (last == first). Only the
    # closing repeat is dropped — any *other* duplicate is treated as malformed
    # input and rejected, never silently removed (which would alter the shape).
    if len(raw) >= 2 and _key(raw[0]) == _key(raw[-1]):
        raw.pop()
    if len(raw) < 3:
        raise ConstraintValidationError("polygon needs at least 3 distinct vertices")
    seen: set[tuple[float, float]] = set()
    for v in raw:
        key = _key(v)
        if key in seen:
            raise ConstraintValidationError("polygon has duplicate vertices")
        seen.add(key)

    ring = [(v["lon"], v["lat"]) for v in raw]
    if polygon_geometry.is_degenerate(ring):
        raise ConstraintValidationError("polygon is degenerate (zero area / collinear vertices)")
    if polygon_geometry.self_intersects(ring):
        raise ConstraintValidationError("polygon edges must not self-intersect")
    return raw


def _normalize_kind(value: Any) -> str:
    kind = str(value or "").strip()
    if kind not in KINDS:
        raise ConstraintValidationError(f"kind must be one of {sorted(KINDS)}")
    return kind


def _normalize_rule(value: Any) -> str:
    rule = str(value or "").strip().lower()
    if rule not in RULES:
        raise ConstraintValidationError("rule must be 'hard' or 'soft'")
    return rule


def _normalize_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ConstraintValidationError("name is required")
    return name[:200]


class OperationalConstraintsStore:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            polygon = json.loads(row["polygon_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            polygon = []
        return {
            "id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "polygon": polygon if isinstance(polygon, list) else [],
            "rule": row["rule"],
            "enabled": bool(row["enabled"]),
            "version": int(row["version"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def list_constraints(self) -> list[dict[str, Any]]:
        """All constraints, enabled and disabled — the map renders both."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM operational_constraints ORDER BY created_at ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, constraint_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM operational_constraints WHERE id = ?",
                (str(constraint_id or ""),),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def create(
        self,
        *,
        kind: str,
        name: str,
        polygon: Any,
        rule: str = "hard",
        enabled: bool = True,
    ) -> dict[str, Any]:
        record = {
            "id": f"constraint-{uuid.uuid4().hex[:12]}",
            "kind": _normalize_kind(kind),
            "name": _normalize_name(name),
            "polygon": _normalize_polygon(polygon),
            "rule": _normalize_rule(rule),
            "enabled": bool(enabled),
        }
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO operational_constraints
                  (id, kind, name, polygon_json, rule, enabled, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    record["id"],
                    record["kind"],
                    record["name"],
                    json.dumps(record["polygon"]),
                    record["rule"],
                    1 if record["enabled"] else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        created = self.get(record["id"])
        assert created is not None
        return created

    def update(
        self,
        constraint_id: str,
        *,
        expected_version: int,
        name: Any = None,
        polygon: Any = None,
        rule: Any = None,
        enabled: Any = None,
    ) -> dict[str, Any]:
        """Patch mutable fields under optimistic concurrency. Only the fields
        supplied (non-None) change. Raises ConstraintConflict on a stale version."""
        current = self.get(constraint_id)
        if current is None:
            raise ConstraintNotFound(constraint_id)
        if int(expected_version) != current["version"]:
            raise ConstraintConflict(
                f"expected version {expected_version}, store has {current['version']}"
            )
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = _normalize_name(name)
        if polygon is not None:
            fields["polygon_json"] = json.dumps(_normalize_polygon(polygon))
        if rule is not None:
            fields["rule"] = _normalize_rule(rule)
        if enabled is not None:
            fields["enabled"] = 1 if bool(enabled) else 0
        now = time.time()
        new_version = current["version"] + 1
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        set_clause = f"{set_clause}, " if set_clause else ""
        params = list(fields.values()) + [new_version, now, constraint_id, int(expected_version)]
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE operational_constraints
                SET {set_clause}version = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                params,
            )
            conn.commit()
        if cursor.rowcount == 0:
            # Lost a concurrent race between the read and the write.
            raise ConstraintConflict("constraint changed concurrently; refresh and retry")
        updated = self.get(constraint_id)
        assert updated is not None
        return updated

    def delete(self, constraint_id: str, *, expected_version: int) -> None:
        current = self.get(constraint_id)
        if current is None:
            raise ConstraintNotFound(constraint_id)
        if int(expected_version) != current["version"]:
            raise ConstraintConflict(
                f"expected version {expected_version}, store has {current['version']}"
            )
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM operational_constraints WHERE id = ? AND version = ?",
                (str(constraint_id), int(expected_version)),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise ConstraintConflict("constraint changed concurrently; refresh and retry")
