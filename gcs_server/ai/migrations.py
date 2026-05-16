from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable


BOOTSTRAP_VERSION = 0
BOOTSTRAP_NAME = "bootstrap_existing_ai_sessions_schema"

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _migration_001_create_ai_mission_drafts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_drafts (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          source_message_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          intent_json TEXT NOT NULL DEFAULT '{}',
          target_resolution_json TEXT NOT NULL DEFAULT '{}',
          draft_json TEXT NOT NULL DEFAULT '{}',
          validation_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          approved_at REAL,
          rejected_at REAL,
          approval_note TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_drafts_session ON ai_mission_drafts(session_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_drafts_status ON ai_mission_drafts(status, updated_at DESC)"
    )


def _migration_003_create_ai_mission_execution_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_operations (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          source_message_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          active_revision_id TEXT NOT NULL DEFAULT '',
          policy_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_revisions (
          id TEXT PRIMARY KEY,
          operation_id TEXT NOT NULL,
          draft_id TEXT NOT NULL DEFAULT '',
          parent_revision_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          mission_json TEXT NOT NULL DEFAULT '{}',
          intent_json TEXT NOT NULL DEFAULT '{}',
          target_resolution_json TEXT NOT NULL DEFAULT '{}',
          validation_json TEXT NOT NULL DEFAULT '{}',
          review_context_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          approved_at REAL,
          rejected_at REAL,
          FOREIGN KEY(operation_id) REFERENCES ai_mission_operations(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_operations_session ON ai_mission_operations(session_id, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_operations_status ON ai_mission_operations(status, updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_revisions_operation ON ai_mission_revisions(operation_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_revisions_draft ON ai_mission_revisions(draft_id, created_at DESC)"
    )


def _migration_002_add_ai_session_meta_json(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "ai_sessions", "meta_json"):
        conn.execute("ALTER TABLE ai_sessions ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")


MIGRATIONS: tuple[Migration, ...] = (
    (1, "create_ai_mission_drafts", _migration_001_create_ai_mission_drafts),
    (2, "add_ai_session_meta_json", _migration_002_add_ai_session_meta_json),
    (3, "create_ai_mission_execution_tables", _migration_003_create_ai_mission_execution_tables),
)


def apply_ai_store_migrations(conn: sqlite3.Connection) -> None:
    """Apply AI store schema migrations exactly once."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at REAL NOT NULL
        )
        """
    )
    _stamp_bootstrap_if_needed(conn)

    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM ai_schema_migrations").fetchall()
    }
    for version, name, migrate in sorted(MIGRATIONS, key=lambda item: item[0]):
        if version in applied:
            continue
        migrate(conn)
        conn.execute(
            "INSERT INTO ai_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, time.time()),
        )
        applied.add(version)


def _stamp_bootstrap_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT 1 FROM ai_schema_migrations LIMIT 1").fetchone()
    if row is not None:
        return
    if not (_table_exists(conn, "ai_sessions") or _table_exists(conn, "ai_messages")):
        return
    conn.execute(
        "INSERT INTO ai_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (BOOTSTRAP_VERSION, BOOTSTRAP_NAME, time.time()),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row[1]) == column_name for row in rows)
