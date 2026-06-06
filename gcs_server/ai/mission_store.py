from __future__ import annotations

import difflib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .coordinate_frame import Origin, load_scene_origin


# Provenance of a Mission (ADR 0021 §2), distinct from ADR 0022's
# coordinate-datum Origin which lands in a later slice.
MISSION_ORIGINS = frozenset({"manual", "ai_chat"})

# ADR 0021 §5 chat reference resolution. A reference that is purely an integer
# handle ("#26", "mission 26", "26") resolves by index; a bare pronoun resolves
# to the most-recent Mission of the current chat.
_INDEX_REFERENCE_RE = re.compile(r"^(?:mission\s*)?#?\s*(\d+)$", re.IGNORECASE)
_PRONOUN_REFERENCES = frozenset({
    "it", "this", "that", "the mission", "this mission", "that mission",
    "the current mission", "current mission", "the active mission",
    "active mission", "the last mission", "last mission",
})
# difflib ratio at or above this counts as a fuzzy name hit.
_FUZZY_NAME_THRESHOLD = 0.6


def _default_origin_datum() -> Origin:
    """The Origin datum (ADR 0022) a new Mission inherits when none is supplied.

    Seeded from the simulator terrain scene's georeference; falls back to a zero
    Origin (0,0,0) if the scene is unavailable (e.g. a real-rover build with no
    scene file). A zero Origin is a valid datum, not a sentinel — read paths
    honor it as-is so the pipeline is testable without seeding a real GPS home.
    """
    try:
        return load_scene_origin()
    except (OSError, ValueError, KeyError):
        return Origin(lat=0.0, lon=0.0, alt=0.0)


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vehicle_profile_id_from_mission_json(value: str | None) -> str:
    return str(_load_json(value).get("vehicle_profile_id") or "").strip()


def _waypoint_count_from_mission_json(value: str | None) -> int:
    mission = _load_json(value)
    if not mission:
        return 0

    direct = mission.get("waypoints")
    if isinstance(direct, list):
        return sum(1 for wp in direct if isinstance(wp, dict))

    route_artifacts = mission.get("route_artifacts")
    if isinstance(route_artifacts, list):
        route_count = 0
        for artifact in route_artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_waypoints = artifact.get("waypoints")
            if isinstance(artifact_waypoints, list):
                route_count += sum(1 for wp in artifact_waypoints if isinstance(wp, dict))
                continue
            route_count += max(0, int(artifact.get("waypoint_count") or 0))
        if route_count:
            return route_count

    steps = mission.get("steps")
    if isinstance(steps, list):
        step_count = 0
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_waypoints = step.get("waypoints")
            if isinstance(step_waypoints, list):
                step_count += sum(1 for wp in step_waypoints if isinstance(wp, dict))
                continue
            step_count += max(0, int(step.get("waypoint_count") or 0))
        if step_count:
            return step_count

    tree = mission.get("tree")
    if isinstance(tree, dict):
        def _count_tree_waypoints(node: dict[str, Any]) -> int:
            total = 0
            if node.get("type") == "nav_leaf" and isinstance(node.get("waypoints"), list):
                total += sum(1 for wp in node["waypoints"] if isinstance(wp, dict))
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    total += _count_tree_waypoints(child)
            return total

        return _count_tree_waypoints(tree)

    return 0


class MissionStore:
    """Per-user CRUD over the flat `missions` table (ADR 0021 §2).

    One row = one Mission. `mission_index` is a stable, never-reused per-user
    handle: allocation bumps a per-user high-water counter
    (`mission_index_counters`) rather than reusing the max live index, so
    deleting a Mission never frees its number. The existing
    draft/operation/revision tables remain the Mission's internal payload;
    bridging that payload is layered on top of this store, not here.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)

    def create_mission(
        self,
        *,
        user_id: str,
        name: str = "",
        origin: str = "manual",
        origin_chat_id: str = "",
        client_version: int = 0,
        mission_id: str = "",
        origin_datum: Origin | None = None,
    ) -> dict[str, Any]:
        origin = str(origin or "manual")
        if origin not in MISSION_ORIGINS:
            raise ValueError(f"invalid mission origin: {origin!r}")
        # ADR 0022 coordinate-datum Origin: inherit the scene georeference when
        # the caller does not pin one. Distinct from `origin` (provenance) above.
        datum = origin_datum if origin_datum is not None else _default_origin_datum()
        user_id = str(user_id or "")
        mission_id = str(mission_id or "").strip() or f"mission-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._connect() as conn:
            mission_index = self._allocate_index(conn, user_id)
            conn.execute(
                """
                INSERT INTO missions (
                  id, created_by_user_id, mission_index, name,
                  origin, origin_chat_id, client_version, created_at, updated_at,
                  origin_lat, origin_lon, origin_alt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission_id,
                    user_id,
                    mission_index,
                    str(name or ""),
                    origin,
                    str(origin_chat_id or ""),
                    int(client_version),
                    now,
                    now,
                    float(datum.lat),
                    float(datum.lon),
                    float(datum.alt),
                ),
            )
            conn.commit()
        return self.get_mission(mission_id) or {}

    def get_origin_datum(self, mission_id: str) -> Origin | None:
        """Resolve a Mission's ADR 0022 coordinate-datum Origin.

        Returns None only if the Mission does not exist. A stored 0,0,0 is a
        valid datum (not a sentinel) and is returned as-is, so missions are
        testable without a real GPS home. The conversion paths that derive local
        metres via ``wgs84_to_local`` read the datum through here.
        """
        mission = self.get_mission(mission_id)
        if mission is None:
            return None
        return Origin(
            lat=float(mission.get("origin_lat") or 0.0),
            lon=float(mission.get("origin_lon") or 0.0),
            alt=float(mission.get("origin_alt") or 0.0),
        )

    def set_origin_datum(self, mission_id: str, *, datum: Origin) -> dict[str, Any] | None:
        """Pin a Mission's ADR 0022 coordinate-datum Origin (e.g. from the
        rover's home GPS once it is known)."""
        return self._update_fields(
            mission_id,
            {
                "origin_lat": float(datum.lat),
                "origin_lon": float(datum.lon),
                "origin_alt": float(datum.alt),
            },
        )

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE id = ?", (mission_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_by_index(self, *, user_id: str, mission_index: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE created_by_user_id = ? AND mission_index = ?",
                (str(user_id or ""), int(mission_index)),
            ).fetchone()
        return dict(row) if row else None

    def get_by_operation_id(self, operation_id: str) -> dict[str, Any] | None:
        """Resolve the flat Mission bridged to an internal operation (ADR 0021
        §2/§3). The planner creates operations+revisions first; this lets the
        bridge wiring find the Mission an appended revision belongs to so it can
        bump `client_version` instead of spawning a duplicate row."""
        operation_id = str(operation_id or "").strip()
        if not operation_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM missions WHERE active_operation_id = ?",
                (operation_id,),
            ).fetchone()
        return dict(row) if row else None

    def resolve_reference(
        self,
        *,
        user_id: str,
        reference: str,
        current_chat_id: str = "",
    ) -> dict[str, Any]:
        """Resolve a chat-driven Mission reference (ADR 0021 §5).

        Resolution order, first hit wins:
          1. Explicit index — ``#26``, ``mission 26``, ``26``.
          2. Exact name match (case-insensitive, whitespace-folded).
          3. Fuzzy name match — one strong candidate resolves; several remain
             ``ambiguous`` for the caller to disambiguate.
          4. Pronoun (``it``, ``this``, ``the mission``) → the most-recent
             Mission with ``origin_chat_id == current_chat_id``.

        Returns ``{"status", "mission", "candidates", "reason"}`` where status
        is ``resolved`` | ``ambiguous`` | ``not_found`` | ``empty``. ``mission``
        is populated only when ``resolved``; ``candidates`` carries the shortlist
        when ``ambiguous``.
        """
        raw = str(reference or "")
        folded = " ".join(raw.split()).strip()
        if not folded:
            return {"status": "empty", "mission": None, "candidates": [], "reason": "empty reference"}

        lowered = folded.lower()

        # 1. Explicit index.
        index_match = _INDEX_REFERENCE_RE.match(folded)
        if index_match:
            mission = self.get_by_index(user_id=user_id, mission_index=int(index_match.group(1)))
            if mission is not None:
                return {"status": "resolved", "mission": mission, "candidates": [], "reason": "explicit_index"}
            return {
                "status": "not_found",
                "mission": None,
                "candidates": [],
                "reason": f"no mission with index #{index_match.group(1)}",
            }

        missions = self.list_missions(user_id=user_id, limit=500)

        # 2. Exact name match.
        exact = [m for m in missions if " ".join(str(m.get("name") or "").split()).lower() == lowered]
        if len(exact) == 1:
            return {"status": "resolved", "mission": exact[0], "candidates": [], "reason": "exact_name"}
        if len(exact) > 1:
            return {"status": "ambiguous", "mission": None, "candidates": exact, "reason": "multiple exact name matches"}

        # 3. Fuzzy name match. Substring hits and close-ratio hits both qualify.
        scored: list[tuple[float, dict[str, Any]]] = []
        for m in missions:
            name = " ".join(str(m.get("name") or "").split()).lower()
            if not name:
                continue
            if lowered in name or name in lowered:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, lowered, name).ratio()
            if score >= _FUZZY_NAME_THRESHOLD:
                scored.append((score, m))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            top_score = scored[0][0]
            leaders = [m for score, m in scored if top_score - score < 1e-9]
            if len(leaders) == 1:
                return {"status": "resolved", "mission": leaders[0], "candidates": [], "reason": "fuzzy_name"}
            return {
                "status": "ambiguous",
                "mission": None,
                "candidates": [m for _, m in scored],
                "reason": "multiple fuzzy name matches",
            }

        # 4. Pronoun → most-recent Mission of the current chat.
        if lowered in _PRONOUN_REFERENCES:
            chat_id = str(current_chat_id or "").strip()
            if chat_id:
                # `missions` come back ordered by created_at DESC, so the first
                # chat-scoped row is the most recent.
                for m in missions:
                    if str(m.get("origin_chat_id") or "") == chat_id:
                        return {"status": "resolved", "mission": m, "candidates": [], "reason": "pronoun_current_chat"}
            return {
                "status": "not_found",
                "mission": None,
                "candidates": [],
                "reason": "no mission found for the current chat",
            }

        return {"status": "not_found", "mission": None, "candidates": [], "reason": "no matching mission"}

    def list_missions(self, *, user_id: str, limit: int = 200) -> list[dict[str, Any]]:
        # Resolve each Mission to its active revision in one pass (ADR 0021 §2:
        # mission -> active operation -> active revision). The flat-Mission list
        # surface needs the active revision's id (overlay/execute target) and
        # status (edit/execute/locked affordances) without an N+1 round-trip.
        # Also surface the revision's vehicle binding so each sidebar row can
        # render its own vehicle icon instead of reusing the active profile.
        # Missions with no bridged operation/revision get empty strings.
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*,
                       COALESCE(r.id, '') AS active_revision_id,
                       COALESCE(r.status, '') AS active_revision_status,
                       COALESCE(r.mission_json, '{}') AS active_revision_mission_json
                FROM missions m
                LEFT JOIN ai_mission_operations o ON o.id = m.active_operation_id
                LEFT JOIN ai_mission_revisions r ON r.id = o.active_revision_id
                WHERE m.created_by_user_id = ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (str(user_id or ""), max(1, int(limit))),
            ).fetchall()
        missions: list[dict[str, Any]] = []
        for row in rows:
            mission = dict(row)
            active_revision_mission_json = mission.pop("active_revision_mission_json", None)
            mission["vehicle_profile_id"] = _vehicle_profile_id_from_mission_json(
                active_revision_mission_json
            )
            mission["waypoint_count"] = _waypoint_count_from_mission_json(active_revision_mission_json)
            missions.append(mission)
        return missions

    def rename_mission(self, mission_id: str, *, name: str) -> dict[str, Any] | None:
        return self._update_fields(mission_id, {"name": str(name or "")})

    def set_color(self, mission_id: str, *, color: str) -> dict[str, Any] | None:
        # Persist the per-Mission colour override. Empty string clears it (the
        # sidebar then falls back to its by-visibility auto palette).
        return self._update_fields(mission_id, {"color": str(color or "")})

    def set_origin(
        self,
        mission_id: str,
        *,
        origin: str,
        origin_chat_id: str | None = None,
    ) -> dict[str, Any] | None:
        origin = str(origin or "")
        if origin not in MISSION_ORIGINS:
            raise ValueError(f"invalid mission origin: {origin!r}")
        fields: dict[str, Any] = {"origin": origin}
        if origin_chat_id is not None:
            fields["origin_chat_id"] = str(origin_chat_id or "")
        return self._update_fields(mission_id, fields)

    def bump_client_version(self, mission_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE missions
                SET client_version = client_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (now, mission_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_mission(mission_id)

    def set_active_operation(
        self, mission_id: str, *, operation_id: str
    ) -> dict[str, Any] | None:
        """Bridge a Mission to its internal payload (ADR 0021 §2).

        The Mission points at one `ai_mission_operations` row; that operation's
        `active_revision_id` resolves to the current revision content. The
        draft/operation/revision plumbing stays internal to the store.
        """
        return self._update_fields(
            mission_id, {"active_operation_id": str(operation_id or "")}
        )

    def get_mission_content(self, mission_id: str) -> dict[str, Any] | None:
        """Resolve a Mission's internal payload: mission -> active operation ->
        active revision's `mission_json`.

        Returns the parsed mission content dict, an empty dict if the Mission
        exists but has no resolvable content yet, or None if the Mission does
        not exist.
        """
        mission = self.get_mission(mission_id)
        if mission is None:
            return None
        operation_id = str(mission.get("active_operation_id") or "")
        if not operation_id:
            return {}
        with self._connect() as conn:
            op = conn.execute(
                "SELECT active_revision_id FROM ai_mission_operations WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if op is None:
                return {}
            revision_id = str(op["active_revision_id"] or "")
            if not revision_id:
                return {}
            rev = conn.execute(
                "SELECT mission_json FROM ai_mission_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        if rev is None:
            return {}
        return _load_json(rev["mission_json"])

    def get_active_revision_id(self, mission_id: str) -> str | None:
        """Resolve a Mission to its active revision id: mission -> active
        operation -> `active_revision_id`.

        Returns the revision id string, an empty string if the Mission exists
        but has no resolvable revision yet, or None if the Mission does not
        exist. The mission-level overlay endpoint feeds this into the existing
        per-revision overlay builder (ADR 0021 §2).
        """
        mission = self.get_mission(mission_id)
        if mission is None:
            return None
        operation_id = str(mission.get("active_operation_id") or "")
        if not operation_id:
            return ""
        with self._connect() as conn:
            op = conn.execute(
                "SELECT active_revision_id FROM ai_mission_operations WHERE id = ?",
                (operation_id,),
            ).fetchone()
        if op is None:
            return ""
        return str(op["active_revision_id"] or "")

    def delete_mission(self, mission_id: str) -> bool:
        # The per-user counter is not rewound, so the deleted Mission's
        # `mission_index` is permanently retired.
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
            conn.commit()
        return cursor.rowcount > 0

    def _update_fields(
        self, mission_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not fields:
            return self.get_mission(mission_id)
        fields = dict(fields)
        fields["updated_at"] = time.time()
        assignments = ", ".join(f"{column} = ?" for column in fields)
        params = list(fields.values())
        params.append(mission_id)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE missions SET {assignments} WHERE id = ?", params
            )
            conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_mission(mission_id)

    def _allocate_index(self, conn: sqlite3.Connection, user_id: str) -> int:
        row = conn.execute(
            "SELECT next_index FROM mission_index_counters WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        next_index = int(row[0]) if row else 1
        conn.execute(
            """
            INSERT INTO mission_index_counters (user_id, next_index)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET next_index = excluded.next_index
            """,
            (user_id, next_index + 1),
        )
        return next_index

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
