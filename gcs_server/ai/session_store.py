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


def _provider_snapshot(provider: dict[str, Any] | None) -> dict[str, Any]:
    source = provider if isinstance(provider, dict) else {}
    return {
        "id": str(source.get("id") or "").strip(),
        "display_name": str(source.get("display_name") or "").strip(),
        "provider_type": str(source.get("provider_type") or "").strip(),
        "model_id": str(source.get("model_id") or "").strip(),
        "context_window": source.get("context_window"),
    }


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

    def clear_provider_selection(self, provider_id: str) -> int:
        clean_provider_id = provider_id.strip()
        if not clean_provider_id:
            return 0
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE ai_sessions SET provider_id = '', updated_at = ? WHERE provider_id = ?",
                (time.time(), clean_provider_id),
            )
            conn.commit()
        return int(cursor.rowcount or 0)

    def preserve_deleted_provider_history(self, provider: dict[str, Any]) -> dict[str, int]:
        snapshot = _provider_snapshot(provider)
        clean_provider_id = snapshot["id"]
        if not clean_provider_id:
            return {"sessions": 0, "messages": 0}

        updated_sessions = 0
        updated_messages = 0
        with self._connect() as conn:
            session_rows = conn.execute(
                "SELECT id, meta_json FROM ai_sessions WHERE provider_id = ?",
                (clean_provider_id,),
            ).fetchall()
            for row in session_rows:
                meta = _load_json(row["meta_json"])
                meta["deleted_provider_snapshot"] = snapshot
                conn.execute(
                    "UPDATE ai_sessions SET meta_json = ?, updated_at = ? WHERE id = ?",
                    (_json(_session_meta(meta)), time.time(), row["id"]),
                )
                updated_sessions += 1

            message_rows = conn.execute(
                "SELECT id, meta_json FROM ai_messages WHERE provider_id = ?",
                (clean_provider_id,),
            ).fetchall()
            for row in message_rows:
                meta = _load_json(row["meta_json"])
                meta["provider_snapshot"] = snapshot
                conn.execute(
                    "UPDATE ai_messages SET meta_json = ? WHERE id = ?",
                    (_json(meta), row["id"]),
                )
                updated_messages += 1
            conn.commit()

        return {"sessions": updated_sessions, "messages": updated_messages}

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

    def list_session_messages(
        self,
        session_id: str,
        *,
        limit: int = 20,
        before_message_id: str = "",
        role: str = "",
    ) -> list[dict[str, Any]]:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return []
        clean_role = str(role or "").strip().lower()
        with self._connect() as conn:
            before_row = None
            clean_before_id = str(before_message_id or "").strip()
            if clean_before_id:
                before_row = conn.execute(
                    "SELECT id, created_at FROM ai_messages WHERE id = ? AND session_id = ?",
                    (clean_before_id, clean_session_id),
                ).fetchone()
            where = ["session_id = ?"]
            params: list[Any] = [clean_session_id]
            if clean_role:
                where.append("lower(role) = ?")
                params.append(clean_role)
            if before_row is not None:
                where.append("(created_at < ? OR (created_at = ? AND id < ?))")
                params.extend([before_row["created_at"], before_row["created_at"], before_row["id"]])
            params.append(max(1, int(limit)))
            rows = conn.execute(
                f"""
                SELECT * FROM ai_messages
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._message_dict(row) for row in reversed(rows)]

    def search_messages(
        self,
        query: str,
        *,
        limit: int = 20,
        session_id: str = "",
        include_archived: bool = False,
        role: str = "",
    ) -> list[dict[str, Any]]:
        clean_query = " ".join(str(query or "").split()).strip()
        if not clean_query:
            return []
        clean_session_id = str(session_id or "").strip()
        clean_role = str(role or "").strip().lower()
        with self._connect() as conn:
            where = ["lower(m.content) LIKE ?"]
            params: list[Any] = [f"%{clean_query.lower()}%"]
            if clean_session_id:
                where.append("m.session_id = ?")
                params.append(clean_session_id)
            if clean_role:
                where.append("lower(m.role) = ?")
                params.append(clean_role)
            if not include_archived:
                where.append("s.archived_at IS NULL")
            params.append(max(1, int(limit)))
            rows = conn.execute(
                f"""
                SELECT
                  m.*,
                  s.title AS session_title,
                  s.mode AS session_mode,
                  s.archived_at AS session_archived_at
                FROM ai_messages m
                JOIN ai_sessions s ON s.id = m.session_id
                WHERE {' AND '.join(where)}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            message = self._message_dict(row)
            message["session_title"] = row["session_title"]
            message["session_mode"] = row["session_mode"]
            message["session_archived_at"] = row["session_archived_at"]
            results.append(message)
        return results

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
