from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _json(data: dict[str, Any] | list[Any] | None) -> str:
    return json.dumps(data or {}, separators=(",", ":"))


class ReplayStore:
    def __init__(
        self,
        db_path: str | Path,
        backend_type: str,
        backend_version: str = "dev",
        source_node_id: str = "gcs",
        site_name: str = "default-site",
    ):
        self._db_path = Path(db_path)
        self._backend_type = backend_type
        self._backend_version = backend_version
        self._source_node_id = source_node_id
        self._site_name = site_name
        self._lock = threading.Lock()
        self._current_session_id: str | None = None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def update_backend(self, backend_type: str, backend_version: str | None = None) -> None:
        self._backend_type = str(backend_type)
        if backend_version is not None:
            self._backend_version = str(backend_version)

    def start_session(self, reason: str = "runtime_start") -> str:
        session_id = f"session-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_sessions (
                  session_id, started_at, ended_at, source_node_id, backend_type, backend_version,
                  site_name, recording_origin, capture_capabilities_json, notes
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    now,
                    self._source_node_id,
                    self._backend_type,
                    self._backend_version,
                    self._site_name,
                    "gcs",
                    _json({
                        "telemetry": True,
                        "control": True,
                        "runtime_events": True,
                        "camera_timing": True,
                    }),
                    reason,
                ),
            )
            conn.commit()
        self._current_session_id = session_id
        self.log_runtime_event("session_started", {"reason": reason, "session_id": session_id}, ts=now)
        return session_id

    def rollover_session(self, reason: str = "manual_rollover") -> str:
        old = self._current_session_id
        if old:
            self.finish_session(old, reason=reason)
        return self.start_session(reason=reason)

    def finish_session(self, session_id: str, reason: str = "runtime_stop") -> None:
        now = time.time()
        self.log_runtime_event("session_finished", {"reason": reason, "session_id": session_id}, ts=now)
        with self._connect() as conn:
            conn.execute(
                "UPDATE replay_sessions SET ended_at = COALESCE(ended_at, ?) WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()
        if self._current_session_id == session_id:
            self._current_session_id = None

    def ensure_session(self) -> str:
        if self._current_session_id is None:
            return self.start_session(reason="auto_start")
        return self._current_session_id

    def log_telemetry(self, payload: dict[str, Any]) -> None:
        session_id = self.ensure_session()
        pos = payload.get("position") or {}
        gps = payload.get("gps") or {}
        orientation = payload.get("orientation") or {}
        speed = payload.get("speed") or {}
        validity = payload.get("validity") or {}
        ts = float(payload.get("timestamp") or time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_telemetry (
                  session_id, ts, payload_json, position_x, position_y, position_z,
                  gps_lat, gps_lon, gps_alt, heading_deg, speed_m_s, speed_km_h,
                  has_position, has_gps, position_frame
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ts,
                    _json(payload),
                    _optional_float(pos.get("x")) if validity.get("has_position") else None,
                    _optional_float(pos.get("y")) if validity.get("has_position") else None,
                    _optional_float(pos.get("z")) if validity.get("has_position") else None,
                    _optional_float(gps.get("lat")) if validity.get("has_gps") else None,
                    _optional_float(gps.get("lon")) if validity.get("has_gps") else None,
                    _optional_float(gps.get("alt")) if validity.get("has_gps") else None,
                    _optional_float(orientation.get("heading_deg")) if validity.get("has_heading") else None,
                    _optional_float(speed.get("m_s")) if validity.get("has_speed") else None,
                    _optional_float(speed.get("km_h")) if validity.get("has_speed") else None,
                    1 if validity.get("has_position") else 0,
                    1 if validity.get("has_gps") else 0,
                    str(payload.get("position_frame") or "unknown"),
                ),
            )
            conn.commit()

    def log_control(self, payload: dict[str, Any], source: str = "gcs") -> None:
        session_id = self.ensure_session()
        ts = float(payload.get("timestamp") or time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO replay_controls (session_id, ts, source, payload_json) VALUES (?, ?, ?, ?)",
                (session_id, ts, source, _json(payload)),
            )
            conn.commit()

    def log_runtime_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        level: str = "info",
        ts: float | None = None,
    ) -> None:
        session_id = self.ensure_session()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_runtime_events (session_id, ts, level, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, float(ts or time.time()), level, event_type, _json(payload)),
            )
            conn.commit()

    def log_camera_timing(
        self,
        *,
        pts: float | None = None,
        frame_index: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        session_id = self.ensure_session()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_media_refs (
                  session_id, media_kind, pts, frame_index, path, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, "camera_timing", pts, frame_index, None, _json(meta)),
            )
            conn.commit()

    def list_sessions(
        self,
        limit: int = 100,
        *,
        started_at_from: float | None = None,
        started_at_to: float | None = None,
        order: str = "desc",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if started_at_from is not None:
            clauses.append("s.started_at >= ?")
            params.append(float(started_at_from))
        if started_at_to is not None:
            clauses.append("s.started_at < ?")
            params.append(float(started_at_to))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_sql = "ASC" if str(order).strip().lower() == "asc" else "DESC"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  s.session_id,
                  s.started_at,
                  s.ended_at,
                  s.source_node_id,
                  s.backend_type,
                  s.backend_version,
                  s.site_name,
                  s.recording_origin,
                  (SELECT COUNT(*) FROM replay_telemetry t WHERE t.session_id = s.session_id) AS telemetry_count,
                  (SELECT COUNT(*) FROM replay_controls c WHERE c.session_id = s.session_id) AS control_count,
                  (SELECT COUNT(*) FROM replay_runtime_events e WHERE e.session_id = s.session_id) AS runtime_event_count
                FROM replay_sessions s
                {where}
                ORDER BY s.started_at {order_sql}
                LIMIT ?
                """,
                (*params, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM replay_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  s.session_id,
                  s.started_at,
                  s.ended_at,
                  s.source_node_id,
                  s.backend_type,
                  s.backend_version,
                  s.site_name,
                  s.recording_origin,
                  (SELECT COUNT(*) FROM replay_telemetry t WHERE t.session_id = s.session_id) AS telemetry_count,
                  (SELECT COUNT(*) FROM replay_controls c WHERE c.session_id = s.session_id) AS control_count,
                  (SELECT COUNT(*) FROM replay_runtime_events e WHERE e.session_id = s.session_id) AS runtime_event_count,
                  (SELECT MAX(ts) FROM replay_telemetry t WHERE t.session_id = s.session_id) AS last_telemetry_ts,
                  (SELECT MAX(ts) FROM replay_controls c WHERE c.session_id = s.session_id) AS last_control_ts,
                  (SELECT MAX(ts) FROM replay_runtime_events e WHERE e.session_id = s.session_id) AS last_event_ts
                FROM replay_sessions s
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_telemetry(self, seconds: int = 120, limit: int = 20) -> list[dict[str, Any]]:
        session_id = self._current_session_id
        if not session_id:
            return []
        with self._connect() as conn:
            latest = conn.execute(
                "SELECT MAX(ts) AS max_ts FROM replay_telemetry WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            max_ts = float(latest["max_ts"] or 0.0) if latest else 0.0
            cutoff = max_ts - max(1, int(seconds))
            rows = conn.execute(
                """
                SELECT ts, payload_json FROM replay_telemetry
                WHERE session_id = ? AND ts >= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (session_id, cutoff, max(1, int(limit))),
            ).fetchall()
        return [
            {"ts": row["ts"], "payload": json.loads(row["payload_json"])}
            for row in reversed(rows)
        ]

    def delete_session(self, session_id: str) -> bool:
        if session_id == self._current_session_id:
            raise ValueError("cannot delete the active session")
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM replay_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM replay_media_refs WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM replay_runtime_events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM replay_controls WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM replay_telemetry WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM replay_sessions WHERE session_id = ?", (session_id,))
            conn.commit()
        return True

    def get_session_timeline(self, session_id: str, limit: int = 2000) -> dict[str, Any]:
        with self._connect() as conn:
            telemetry_rows = conn.execute(
                """
                SELECT ts, payload_json FROM replay_telemetry
                WHERE session_id = ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            ).fetchall()
            control_rows = conn.execute(
                """
                SELECT ts, source, payload_json FROM replay_controls
                WHERE session_id = ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            ).fetchall()
            event_rows = conn.execute(
                """
                SELECT ts, level, event_type, payload_json FROM replay_runtime_events
                WHERE session_id = ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            ).fetchall()
        return {
            "telemetry": [
                {"ts": row["ts"], "payload": json.loads(row["payload_json"])}
                for row in telemetry_rows
            ],
            "controls": [
                {"ts": row["ts"], "source": row["source"], "payload": json.loads(row["payload_json"])}
                for row in control_rows
            ],
            "events": [
                {
                    "ts": row["ts"],
                    "level": row["level"],
                    "event_type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                }
                for row in event_rows
            ],
        }

    def list_telemetry_samples(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT ts, payload_json, position_x, position_y, position_z, gps_lat, gps_lon, gps_alt,
                   heading_deg, speed_m_s, speed_km_h, has_position, has_gps, position_frame
            FROM replay_telemetry
            WHERE session_id = ?
            ORDER BY ts ASC
        """
        params: list[Any] = [session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "ts": row["ts"],
                "payload": json.loads(row["payload_json"]),
                "position": _row_position(row),
                "gps": _row_gps(row),
                "heading_deg": row["heading_deg"],
                "speed_m_s": row["speed_m_s"],
                "speed_km_h": row["speed_km_h"],
                "has_position": bool(row["has_position"]),
                "has_gps": bool(row["has_gps"]),
                "position_frame": row["position_frame"] or "unknown",
            }
            for row in rows
        ]

    def list_session_events(
        self,
        session_id: str,
        *,
        event_type: str = "",
        text: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["session_id = ?"]
        params: list[Any] = [session_id]
        if event_type.strip():
            clauses.append("event_type = ?")
            params.append(event_type.strip())
        if text.strip():
            pattern = f"%{text.strip().lower()}%"
            clauses.append("(LOWER(event_type) LIKE ? OR LOWER(payload_json) LIKE ?)")
            params.extend([pattern, pattern])
        query = f"""
            SELECT ts, level, event_type, payload_json
            FROM replay_runtime_events
            WHERE {' AND '.join(clauses)}
            ORDER BY ts DESC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {
                "ts": row["ts"],
                "level": row["level"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in reversed(rows)
        ]

    def save_session_metrics(self, session_id: str, metrics: dict[str, Any]) -> None:
        now = time.time()
        metrics_payload = dict(metrics)
        metrics_payload["computed_at"] = now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_session_metrics (
                  session_id, computed_at, telemetry_sample_count, position_sample_count,
                  duration_s, path_length_m, net_displacement_m, max_distance_from_start_m,
                  max_speed_m_s, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  computed_at = excluded.computed_at,
                  telemetry_sample_count = excluded.telemetry_sample_count,
                  position_sample_count = excluded.position_sample_count,
                  duration_s = excluded.duration_s,
                  path_length_m = excluded.path_length_m,
                  net_displacement_m = excluded.net_displacement_m,
                  max_distance_from_start_m = excluded.max_distance_from_start_m,
                  max_speed_m_s = excluded.max_speed_m_s,
                  metrics_json = excluded.metrics_json
                """,
                (
                    session_id,
                    now,
                    metrics.get("telemetry_sample_count"),
                    metrics.get("position_sample_count"),
                    metrics.get("duration_s"),
                    metrics.get("path_length_m"),
                    metrics.get("net_displacement_m"),
                    metrics.get("max_distance_from_start_m"),
                    metrics.get("max_speed_m_s"),
                    _json(metrics_payload),
                ),
            )
            conn.commit()

    def get_cached_session_metrics(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM replay_session_metrics WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        if isinstance(payload, dict):
            if payload.get("computed_at") in {None, ""}:
                payload["computed_at"] = row["computed_at"]
            payload.setdefault("session_id", session_id)
            return payload
        return None

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS replay_sessions (
                  session_id TEXT PRIMARY KEY,
                  started_at REAL NOT NULL,
                  ended_at REAL,
                  source_node_id TEXT NOT NULL,
                  backend_type TEXT NOT NULL,
                  backend_version TEXT NOT NULL,
                  site_name TEXT NOT NULL,
                  recording_origin TEXT NOT NULL,
                  capture_capabilities_json TEXT NOT NULL,
                  notes TEXT
                );
                CREATE TABLE IF NOT EXISTS replay_telemetry (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  ts REAL NOT NULL,
                  payload_json TEXT NOT NULL,
                  position_x REAL,
                  position_y REAL,
                  position_z REAL,
                  gps_lat REAL,
                  gps_lon REAL,
                  gps_alt REAL,
                  heading_deg REAL,
                  speed_m_s REAL,
                  speed_km_h REAL,
                  has_position INTEGER NOT NULL DEFAULT 0,
                  has_gps INTEGER NOT NULL DEFAULT 0,
                  position_frame TEXT NOT NULL DEFAULT 'unknown',
                  FOREIGN KEY(session_id) REFERENCES replay_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS replay_controls (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  ts REAL NOT NULL,
                  source TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES replay_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS replay_runtime_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  ts REAL NOT NULL,
                  level TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES replay_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS replay_media_refs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  media_kind TEXT NOT NULL,
                  pts REAL,
                  frame_index INTEGER,
                  path TEXT,
                  metadata_json TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES replay_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS replay_session_metrics (
                  session_id TEXT PRIMARY KEY,
                  computed_at REAL NOT NULL,
                  telemetry_sample_count INTEGER,
                  position_sample_count INTEGER,
                  duration_s REAL,
                  path_length_m REAL,
                  net_displacement_m REAL,
                  max_distance_from_start_m REAL,
                  max_speed_m_s REAL,
                  metrics_json TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(session_id) REFERENCES replay_sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_replay_telemetry_session_ts ON replay_telemetry(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_controls_session_ts ON replay_controls(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_runtime_events_session_ts ON replay_runtime_events(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_media_refs_session_pts ON replay_media_refs(session_id, pts);
                CREATE INDEX IF NOT EXISTS idx_replay_session_metrics_computed_at ON replay_session_metrics(computed_at DESC);
                """
            )
            self._ensure_column(conn, "replay_telemetry", "has_position", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "replay_telemetry", "has_gps", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "replay_telemetry", "position_frame", "TEXT NOT NULL DEFAULT 'unknown'")
            self._backfill_telemetry_validity(conn)
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column in columns:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _backfill_telemetry_validity(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, payload_json, position_x, position_y, position_z, gps_lat, gps_lon, gps_alt,
                   heading_deg, speed_m_s, speed_km_h, has_position, has_gps, position_frame
            FROM replay_telemetry
            WHERE position_frame = 'unknown' AND has_position = 0 AND has_gps = 0
            """
        ).fetchall()
        updates: list[tuple[Any, ...]] = []
        for row in rows:
            payload = _load_json_value(row["payload_json"])
            validity = payload.get("validity") if isinstance(payload.get("validity"), dict) else {}
            position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
            gps = payload.get("gps") if isinstance(payload.get("gps"), dict) else {}
            orientation = payload.get("orientation") if isinstance(payload.get("orientation"), dict) else {}
            speed = payload.get("speed") if isinstance(payload.get("speed"), dict) else {}

            has_position = bool(validity.get("has_position")) or (
                _optional_float(position.get("x")) is not None and _optional_float(position.get("y")) is not None
            )
            has_gps = bool(validity.get("has_gps")) or (
                _optional_float(gps.get("lat")) is not None and _optional_float(gps.get("lon")) is not None
            )
            heading = row["heading_deg"] if row["heading_deg"] is not None else _optional_float(orientation.get("heading_deg"))
            speed_m_s = row["speed_m_s"] if row["speed_m_s"] is not None else _optional_float(speed.get("m_s"))
            speed_km_h = row["speed_km_h"] if row["speed_km_h"] is not None else _optional_float(speed.get("km_h"))
            position_frame = "local_xy" if has_position else ("gps_wgs84" if has_gps else "unknown")
            updates.append(
                (
                    _optional_float(position.get("x")) if has_position else row["position_x"],
                    _optional_float(position.get("y")) if has_position else row["position_y"],
                    _optional_float(position.get("z")) if has_position else row["position_z"],
                    _optional_float(gps.get("lat")) if has_gps else row["gps_lat"],
                    _optional_float(gps.get("lon")) if has_gps else row["gps_lon"],
                    _optional_float(gps.get("alt")) if has_gps else row["gps_alt"],
                    heading,
                    speed_m_s,
                    speed_km_h,
                    1 if has_position else 0,
                    1 if has_gps else 0,
                    position_frame,
                    row["id"],
                )
            )
        if not updates:
            return
        conn.executemany(
            """
            UPDATE replay_telemetry
            SET position_x = ?, position_y = ?, position_z = ?,
                gps_lat = ?, gps_lon = ?, gps_alt = ?,
                heading_deg = ?, speed_m_s = ?, speed_km_h = ?,
                has_position = ?, has_gps = ?, position_frame = ?
            WHERE id = ?
            """,
            updates,
        )


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _load_json_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _row_position(row: sqlite3.Row) -> dict[str, Any] | None:
    if not bool(row["has_position"]):
        return None
    if row["position_x"] is None or row["position_y"] is None:
        return None
    return {
        "x": float(row["position_x"]),
        "y": float(row["position_y"]),
        "z": float(row["position_z"] or 0.0),
    }


def _row_gps(row: sqlite3.Row) -> dict[str, Any] | None:
    if not bool(row["has_gps"]):
        return None
    if row["gps_lat"] is None or row["gps_lon"] is None:
        return None
    return {
        "lat": float(row["gps_lat"]),
        "lon": float(row["gps_lon"]),
        "alt": float(row["gps_alt"] or 0.0),
    }
