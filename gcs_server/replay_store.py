from __future__ import annotations

import json
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
        ts = float(payload.get("timestamp") or time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_telemetry (
                  session_id, ts, payload_json, position_x, position_y, position_z,
                  gps_lat, gps_lon, gps_alt, heading_deg, speed_m_s, speed_km_h
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    ts,
                    _json(payload),
                    float(pos.get("x") or 0.0),
                    float(pos.get("y") or 0.0),
                    float(pos.get("z") or 0.0),
                    float(gps.get("lat") or 0.0),
                    float(gps.get("lon") or 0.0),
                    float(gps.get("alt") or 0.0),
                    float(orientation.get("heading_deg") or 0.0),
                    float(speed.get("m_s") or 0.0),
                    float(speed.get("km_h") or 0.0),
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

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
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
                  (SELECT COUNT(*) FROM replay_runtime_events e WHERE e.session_id = s.session_id) AS runtime_event_count
                FROM replay_sessions s
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM replay_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

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
                CREATE INDEX IF NOT EXISTS idx_replay_telemetry_session_ts ON replay_telemetry(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_controls_session_ts ON replay_controls(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_runtime_events_session_ts ON replay_runtime_events(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_replay_media_refs_session_pts ON replay_media_refs(session_id, pts);
                """
            )
            conn.commit()
