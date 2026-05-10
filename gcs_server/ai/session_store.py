from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .migrations import apply_ai_store_migrations


_AUTO_TITLE_MAX_CHARS = 54
_SOURCE_CONTROL_KEYS = (
    "project_docs",
    "mission_history",
    "replay_reports",
    "ai_chat_history",
    "settings_config",
    "sensor_context",
    "web_research",
)
_DEFAULT_SOURCE_CONTROLS = {
    "project_docs": True,
    "mission_history": True,
    "replay_reports": True,
    "ai_chat_history": False,
    "settings_config": False,
    "sensor_context": False,
    "web_research": False,
}


def _json(data: dict[str, Any] | list[Any] | None) -> str:
    if data is None:
        return "{}"
    return json.dumps(data, separators=(",", ":"))


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def default_source_controls() -> dict[str, bool]:
    return dict(_DEFAULT_SOURCE_CONTROLS)


def normalize_source_controls(value: Any) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    out = default_source_controls()
    for key in _SOURCE_CONTROL_KEYS:
        if key in source:
            out[key] = bool(source[key])
    return out


def _session_meta(meta: dict[str, Any] | None = None, source_controls: Any = None) -> dict[str, Any]:
    out = dict(meta) if isinstance(meta, dict) else {}
    out["source_controls"] = normalize_source_controls(
        source_controls if source_controls is not None else out.get("source_controls")
    )
    return out


class AISessionStore:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def list_sessions(
        self,
        limit: int = 100,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list[dict[str, Any]]:
        if archived_only:
            where = "WHERE s.archived_at IS NOT NULL"
        elif include_archived:
            where = ""
        else:
            where = "WHERE s.archived_at IS NULL"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  s.id,
                  s.title,
                  s.mode,
                  s.provider_id,
                  s.meta_json,
                  s.created_at,
                  s.updated_at,
                  s.archived_at,
                  (SELECT COUNT(*) FROM ai_messages m WHERE m.session_id = s.id) AS message_count,
                  (SELECT content FROM ai_messages m WHERE m.session_id = s.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message
                FROM ai_sessions s
                {where}
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._session_dict(row) for row in rows]

    def create_session(
        self,
        *,
        title: str = "New chat",
        mode: str = "general_chat",
        provider_id: str = "",
        source_controls: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = f"ai-session-{uuid.uuid4().hex[:12]}"
        now = time.time()
        clean_title = title.strip() or "New chat"
        session_meta = _session_meta(meta, source_controls)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_sessions (id, title, mode, provider_id, created_at, updated_at, archived_at, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    session_id,
                    clean_title,
                    mode.strip() or "general_chat",
                    provider_id.strip(),
                    now,
                    now,
                    _json(session_meta),
                ),
            )
            conn.commit()
        return self.get_session(session_id, include_messages=False) or {}

    def get_session(self, session_id: str, *, include_messages: bool = True) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            session = self._session_dict(row)
            if include_messages:
                messages = conn.execute(
                    """
                    SELECT * FROM ai_messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
                session["messages"] = [self._message_dict(message) for message in messages]
        return session

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        provider_id: str | None = None,
        mode: str | None = None,
        source_controls: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_session(session_id, include_messages=False)
        if current is None:
            return None
        next_title = current["title"] if title is None else (title.strip() or current["title"])
        next_provider_id = current["provider_id"] if provider_id is None else provider_id.strip()
        next_mode = current["mode"] if mode is None else (mode.strip() or current["mode"])
        next_meta = dict(current.get("meta") or {})
        if isinstance(meta, dict):
            next_meta.update(meta)
        if source_controls is not None:
            next_meta["source_controls"] = normalize_source_controls(source_controls)
        next_meta = _session_meta(next_meta)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_sessions
                SET title = ?, provider_id = ?, mode = ?, updated_at = ?, meta_json = ?
                WHERE id = ?
                """,
                (next_title, next_provider_id, next_mode, time.time(), _json(next_meta), session_id),
            )
            conn.commit()
        return self.get_session(session_id, include_messages=False)

    def archive_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE ai_sessions SET archived_at = ?, updated_at = ? WHERE id = ? AND archived_at IS NULL",
                (time.time(), time.time(), session_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def restore_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE ai_sessions SET archived_at = NULL, updated_at = ? WHERE id = ? AND archived_at IS NOT NULL",
                (time.time(), session_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def purge_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM ai_sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM ai_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM ai_sessions WHERE id = ?", (session_id,))
            conn.commit()
        return True

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        model_id: str = "",
        provider_id: str = "",
        latency_ms: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = f"ai-message-{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_messages (
                  id, session_id, role, content, model_id, provider_id, created_at, latency_ms, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    model_id,
                    provider_id,
                    now,
                    latency_ms,
                    _json(meta),
                ),
            )
            conn.execute("UPDATE ai_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.commit()
        message = self.get_message(message_id)
        return message or {}

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_messages WHERE id = ?", (message_id,)).fetchone()
        return self._message_dict(row) if row else None

    def latest_messages(self, session_id: str, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            ).fetchall()
        return [self._message_dict(row) for row in reversed(rows)]

    def delete_message(self, message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT session_id FROM ai_messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM ai_messages WHERE id = ?", (message_id,))
            conn.execute("UPDATE ai_sessions SET updated_at = ? WHERE id = ?", (time.time(), row["session_id"]))
            conn.commit()
        return True

    def maybe_auto_title(self, session_id: str, prompt: str) -> dict[str, Any] | None:
        words = " ".join(prompt.strip().split())
        if not words:
            return self.get_session(session_id, include_messages=False)
        title = words[:_AUTO_TITLE_MAX_CHARS].rstrip()
        if len(words) > len(title):
            title = f"{title}..."
        with self._connect() as conn:
            conn.execute(
                "UPDATE ai_sessions SET title = ?, updated_at = ? WHERE id = ? AND lower(title) = 'new chat'",
                (title, time.time(), session_id),
            )
            conn.commit()
        return self.get_session(session_id, include_messages=False)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS ai_sessions (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  mode TEXT NOT NULL,
                  provider_id TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  archived_at REAL,
                  meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS ai_messages (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  model_id TEXT NOT NULL DEFAULT '',
                  provider_id TEXT NOT NULL DEFAULT '',
                  created_at REAL NOT NULL,
                  latency_ms INTEGER,
                  meta_json TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(session_id) REFERENCES ai_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_ai_sessions_updated_at ON ai_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_messages_session_created_at ON ai_messages(session_id, created_at);
                """
            )
            apply_ai_store_migrations(conn)
            conn.commit()

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["meta"] = _load_json(out.pop("meta_json", "{}"))
        return out

    @staticmethod
    def _session_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["meta"] = _load_json(out.pop("meta_json", "{}"))
        out["source_controls"] = normalize_source_controls((out.get("meta") or {}).get("source_controls"))
        return out
