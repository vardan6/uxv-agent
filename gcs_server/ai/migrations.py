from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable


Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


# ADR 0021 §Slice 1: drop the legacy mission-draft/revision/operation/controller
# tables and replace them with a single flat `missions` table.
_LEGACY_AI_MISSION_TABLES = (
    "ai_mission_drafts",
    "ai_mission_operations",
    "ai_mission_revisions",
    "ai_mission_controller_state",
    "ai_mission_execution_attempts",
)


def _migration_010_adr_0021_flat_missions(conn: sqlite3.Connection) -> None:
    for table in _LEGACY_AI_MISSION_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS missions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          origin TEXT NOT NULL CHECK(origin IN ('manual', 'ai_chat')),
          origin_chat_id TEXT,
          created_at REAL NOT NULL,
          created_by_user_id TEXT NOT NULL DEFAULT '',
          client_version INTEGER NOT NULL DEFAULT 0,
          approval_status TEXT NOT NULL DEFAULT 'approved',
          mission_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_created_at ON missions(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_origin_chat ON missions(origin_chat_id)"
    )


def _migration_011_add_mission_approval_status(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(missions)").fetchall()
    }
    if "approval_status" not in columns:
        conn.execute(
            "ALTER TABLE missions ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'"
        )
    conn.execute(
        "UPDATE missions SET approval_status = 'approved' "
        "WHERE approval_status IS NULL OR TRIM(approval_status) = ''"
    )


def _migration_012_add_mission_deleted_at(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(missions)").fetchall()
    }
    if "deleted_at" not in columns:
        conn.execute(
            "ALTER TABLE missions ADD COLUMN deleted_at REAL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_deleted_at ON missions(deleted_at)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    (10, "adr_0021_flat_missions", _migration_010_adr_0021_flat_missions),
    (11, "add_mission_approval_status", _migration_011_add_mission_approval_status),
    (12, "add_mission_deleted_at", _migration_012_add_mission_deleted_at),
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
