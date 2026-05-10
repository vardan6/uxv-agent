from __future__ import annotations

import sqlite3
import time

from ai.migrations import BOOTSTRAP_NAME, BOOTSTRAP_VERSION, apply_ai_store_migrations


def test_bootstrap_existing_ai_sessions_schema_without_rewriting_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE ai_sessions (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          mode TEXT NOT NULL,
          provider_id TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          archived_at REAL
        );
        INSERT INTO ai_sessions (id, title, mode, provider_id, created_at, updated_at, archived_at)
        VALUES ('s1', 'Existing', 'general_chat', '', 1.0, 1.0, NULL);
        """
    )

    apply_ai_store_migrations(conn)
    apply_ai_store_migrations(conn)

    rows = conn.execute("SELECT version, name FROM ai_schema_migrations").fetchall()
    session = conn.execute("SELECT title FROM ai_sessions WHERE id = 's1'").fetchone()
    assert [(row["version"], row["name"]) for row in rows] == [(BOOTSTRAP_VERSION, BOOTSTRAP_NAME)]
    assert session["title"] == "Existing"


def test_empty_migration_table_is_bootstrapped_when_ai_tables_exist() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE ai_messages (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          model_id TEXT NOT NULL DEFAULT '',
          provider_id TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          latency_ms INTEGER,
          meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE ai_schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at REAL NOT NULL
        );
        """
    )

    before = time.time()
    apply_ai_store_migrations(conn)
    row = conn.execute("SELECT * FROM ai_schema_migrations").fetchone()

    assert row["version"] == BOOTSTRAP_VERSION
    assert row["name"] == BOOTSTRAP_NAME
    assert row["applied_at"] >= before
