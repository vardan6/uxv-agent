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
    version_names = [(row["version"], row["name"]) for row in rows]
    assert (BOOTSTRAP_VERSION, BOOTSTRAP_NAME) in version_names
    assert (2, "add_ai_session_meta_json") in version_names
    assert (5, "add_revision_mutation_fields") in version_names
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

    rows = conn.execute("SELECT * FROM ai_schema_migrations ORDER BY version ASC").fetchall()
    assert rows[0]["version"] == BOOTSTRAP_VERSION
    assert rows[0]["name"] == BOOTSTRAP_NAME
    assert rows[0]["applied_at"] >= before
    version_names = [(row["version"], row["name"]) for row in rows[1:]]
    assert (2, "add_ai_session_meta_json") in version_names
    assert (5, "add_revision_mutation_fields") in version_names


def test_migration_002_adds_meta_json_to_existing_ai_sessions() -> None:
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
        CREATE TABLE ai_schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at REAL NOT NULL
        );
        INSERT INTO ai_schema_migrations (version, name, applied_at)
        VALUES (0, 'bootstrap_existing_ai_sessions_schema', 1.0);
        """
    )

    apply_ai_store_migrations(conn)

    columns = [row["name"] for row in conn.execute("PRAGMA table_info(ai_sessions)").fetchall()]
    assert "meta_json" in columns
