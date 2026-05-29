from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


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
        try:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            row_count = None
        if row_count and row_count[0]:
            logger.warning(
                "ADR-0021 migration: dropping legacy table %s with %d row(s); "
                "data is not migrated to the new flat missions schema",
                table,
                row_count[0],
            )
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
    # Historical no-op. ADR 0022 removed the per-mission approval gate.
    return None


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


def _migration_013_add_mission_color(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(missions)").fetchall()
    }
    if "color" not in columns:
        conn.execute(
            "ALTER TABLE missions ADD COLUMN color TEXT NOT NULL DEFAULT ''"
        )


def _migration_014_drop_mission_approval_status(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(missions)").fetchall()
    }
    if "approval_status" not in columns:
        return

    conn.execute("ALTER TABLE missions RENAME TO missions_old")
    conn.execute(
        """
        CREATE TABLE missions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          origin TEXT NOT NULL CHECK(origin IN ('manual', 'ai_chat')),
          origin_chat_id TEXT,
          created_at REAL NOT NULL,
          created_by_user_id TEXT NOT NULL DEFAULT '',
          client_version INTEGER NOT NULL DEFAULT 0,
          mission_json TEXT NOT NULL DEFAULT '{}',
          deleted_at REAL,
          color TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO missions (
          id, name, origin, origin_chat_id, created_at,
          created_by_user_id, client_version, mission_json, deleted_at, color
        )
        SELECT
          id,
          name,
          origin,
          origin_chat_id,
          created_at,
          created_by_user_id,
          client_version,
          mission_json,
          deleted_at,
          color
        FROM missions_old
        """
    )
    conn.execute("DROP TABLE missions_old")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_created_at ON missions(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_origin_chat ON missions(origin_chat_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_deleted_at ON missions(deleted_at)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    (10, "adr_0021_flat_missions", _migration_010_adr_0021_flat_missions),
    (11, "add_mission_approval_status", _migration_011_add_mission_approval_status),
    (12, "add_mission_deleted_at", _migration_012_add_mission_deleted_at),
    (13, "add_mission_color", _migration_013_add_mission_color),
    (14, "drop_mission_approval_status", _migration_014_drop_mission_approval_status),
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
