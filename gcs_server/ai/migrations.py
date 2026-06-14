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
    if _table_exists(conn, "ai_sessions") and not _column_exists(conn, "ai_sessions", "meta_json"):
        conn.execute("ALTER TABLE ai_sessions ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")


def _migration_004_create_ai_mission_controller_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_controller_state (
          controller_id TEXT PRIMARY KEY,
          current_version INTEGER NOT NULL DEFAULT 0,
          active_operation_id TEXT NOT NULL DEFAULT '',
          active_revision_id TEXT NOT NULL DEFAULT '',
          active_draft_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'idle',
          verified_snapshot_json TEXT NOT NULL DEFAULT '{}',
          previous_verified_snapshot_json TEXT NOT NULL DEFAULT '{}',
          pending_snapshot_json TEXT NOT NULL DEFAULT '{}',
          last_cutover_attempt_json TEXT NOT NULL DEFAULT '{}',
          last_error TEXT NOT NULL DEFAULT '',
          last_cutover_at REAL,
          verified_at REAL,
          updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_execution_attempts (
          id TEXT PRIMARY KEY,
          operation_id TEXT NOT NULL DEFAULT '',
          revision_id TEXT NOT NULL DEFAULT '',
          expected_controller_version INTEGER,
          observed_controller_version INTEGER NOT NULL DEFAULT 0,
          installed_controller_version INTEGER,
          status TEXT NOT NULL,
          error_text TEXT NOT NULL DEFAULT '',
          request_json TEXT NOT NULL DEFAULT '{}',
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_execution_attempts_revision ON ai_mission_execution_attempts(revision_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_execution_attempts_operation ON ai_mission_execution_attempts(operation_id, created_at DESC)"
    )


def _migration_005_add_revision_mutation_fields(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "ai_mission_revisions", "client_version"):
        conn.execute(
            "ALTER TABLE ai_mission_revisions ADD COLUMN client_version INTEGER NOT NULL DEFAULT 0"
        )
    if not _column_exists(conn, "ai_mission_revisions", "provenance_json"):
        conn.execute(
            "ALTER TABLE ai_mission_revisions ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'"
        )


def _migration_006_create_missions(conn: sqlite3.Connection) -> None:
    # Flat Mission entity (ADR 0021 §2): one row = one Mission. The existing
    # draft/operation/revision tables become this Mission's internal payload;
    # `mission_index` is the stable, never-reused per-user handle (allocation
    # logic lands with MissionStore). `origin` here is provenance
    # (manual|ai_chat), distinct from ADR 0022's coordinate-datum Origin.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS missions (
          id TEXT PRIMARY KEY,
          created_by_user_id TEXT NOT NULL DEFAULT '',
          mission_index INTEGER NOT NULL,
          name TEXT NOT NULL DEFAULT '',
          origin TEXT NOT NULL DEFAULT 'manual',
          origin_chat_id TEXT NOT NULL DEFAULT '',
          client_version INTEGER NOT NULL DEFAULT 0,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          color TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_user_index ON missions(created_by_user_id, mission_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_user_created ON missions(created_by_user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_origin_chat ON missions(origin_chat_id, created_at DESC)"
    )


def _migration_007_create_mission_index_counters(conn: sqlite3.Connection) -> None:
    # Per-user high-water mark for `mission_index`. Allocation reads and bumps
    # `next_index` here rather than `MAX(mission_index)` over live rows, so a
    # deleted Mission's handle is never reused (ADR 0021 §2).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mission_index_counters (
          user_id TEXT PRIMARY KEY,
          next_index INTEGER NOT NULL
        )
        """
    )


def _migration_008_add_mission_active_operation(conn: sqlite3.Connection) -> None:
    # Bridge the flat Mission to its internal payload (ADR 0021 §2): a Mission
    # points at one `ai_mission_operations` row, whose `active_revision_id`
    # resolves to the current revision's `mission_json` content. The
    # draft/operation/revision tables stay internal; `missions` is the public
    # one-row-per-Mission handle.
    if _table_exists(conn, "missions") and not _column_exists(conn, "missions", "active_operation_id"):
        conn.execute(
            "ALTER TABLE missions ADD COLUMN active_operation_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_missions_active_operation ON missions(active_operation_id)"
        )


def _migration_009_add_mission_origin_datum(conn: sqlite3.Connection) -> None:
    # ADR 0022 GPS-master coordinate frame: each Mission carries its own
    # coordinate-datum Origin (the WGS84 point local scene metres are measured
    # from). Distinct from ADR 0021's provenance `origin` (manual|ai_chat) on the
    # same table. These columns give per-Mission Origin a real home; read/write
    # paths that derive metres via `wgs84_to_local` migrate onto them in a later
    # slice. Default 0.0 (null island) is a valid datum, honored as-is by read
    # paths so missions are testable without a seeded GPS home.
    for column in ("origin_lat", "origin_lon", "origin_alt"):
        if _table_exists(conn, "missions") and not _column_exists(conn, "missions", column):
            conn.execute(
                f"ALTER TABLE missions ADD COLUMN {column} REAL NOT NULL DEFAULT 0.0"
            )


def _migration_011_restore_mission_execution_tables(conn: sqlite3.Connection) -> None:
    # Migration 10 (adr_0021_flat_missions, applied from master) dropped these
    # tables, but this branch still uses them. Recreate them if absent so the
    # server starts cleanly against a DB that has version 10 stamped.
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
          client_version INTEGER NOT NULL DEFAULT 0,
          provenance_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          approved_at REAL,
          rejected_at REAL,
          FOREIGN KEY(operation_id) REFERENCES ai_mission_operations(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_controller_state (
          controller_id TEXT PRIMARY KEY,
          current_version INTEGER NOT NULL DEFAULT 0,
          active_operation_id TEXT NOT NULL DEFAULT '',
          active_revision_id TEXT NOT NULL DEFAULT '',
          active_draft_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'idle',
          verified_snapshot_json TEXT NOT NULL DEFAULT '{}',
          previous_verified_snapshot_json TEXT NOT NULL DEFAULT '{}',
          pending_snapshot_json TEXT NOT NULL DEFAULT '{}',
          last_cutover_attempt_json TEXT NOT NULL DEFAULT '{}',
          last_error TEXT NOT NULL DEFAULT '',
          last_cutover_at REAL,
          verified_at REAL,
          updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_mission_execution_attempts (
          id TEXT PRIMARY KEY,
          operation_id TEXT NOT NULL DEFAULT '',
          revision_id TEXT NOT NULL DEFAULT '',
          expected_controller_version INTEGER,
          observed_controller_version INTEGER NOT NULL DEFAULT 0,
          installed_controller_version INTEGER,
          status TEXT NOT NULL,
          error_text TEXT NOT NULL DEFAULT '',
          request_json TEXT NOT NULL DEFAULT '{}',
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_execution_attempts_revision ON ai_mission_execution_attempts(revision_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_mission_execution_attempts_operation ON ai_mission_execution_attempts(operation_id, created_at DESC)"
    )


def _migration_017_reconcile_missions_schema(conn: sqlite3.Connection) -> None:
    # Master's migration 16 (rebuild_missions_adr0021_schema) rewrote `missions`
    # with INTEGER AUTOINCREMENT id and dropped `mission_index`,
    # `active_operation_id`, and `origin_*` columns. This branch needs the
    # TEXT-id schema with those columns. Rebuild if the master shape is present
    # (detected by absence of `active_operation_id`).
    if not _table_exists(conn, "missions"):
        return
    if _column_exists(conn, "missions", "active_operation_id"):
        return  # already the branch schema — nothing to do

    import uuid as _uuid
    conn.execute("ALTER TABLE missions RENAME TO missions_pre17")
    conn.execute(
        """
        CREATE TABLE missions (
          id TEXT PRIMARY KEY,
          created_by_user_id TEXT NOT NULL DEFAULT '',
          mission_index INTEGER NOT NULL,
          name TEXT NOT NULL DEFAULT '',
          origin TEXT NOT NULL DEFAULT 'manual',
          origin_chat_id TEXT NOT NULL DEFAULT '',
          client_version INTEGER NOT NULL DEFAULT 0,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          active_operation_id TEXT NOT NULL DEFAULT '',
          origin_lat REAL NOT NULL DEFAULT 0.0,
          origin_lon REAL NOT NULL DEFAULT 0.0,
          origin_alt REAL NOT NULL DEFAULT 0.0,
          color TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_user_index ON missions(created_by_user_id, mission_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_user_created ON missions(created_by_user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_origin_chat ON missions(origin_chat_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_active_operation ON missions(active_operation_id)"
    )
    # Migrate existing rows; use the INTEGER id as mission_index and generate
    # a stable TEXT id so the sidebar can still reference migrated missions.
    old_rows = conn.execute(
        """
        SELECT id, name, origin, COALESCE(origin_chat_id, '') AS origin_chat_id,
               client_version, created_at, COALESCE(created_by_user_id, '') AS created_by_user_id
        FROM missions_pre17
        ORDER BY id
        """
    ).fetchall()
    for row in old_rows:
        new_id = f"mission-migrated-{row[0]}"
        conn.execute(
            """
            INSERT INTO missions (
              id, created_by_user_id, mission_index, name, origin, origin_chat_id,
              client_version, created_at, updated_at,
              active_operation_id, origin_lat, origin_lon, origin_alt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0.0, 0.0, 0.0)
            """,
            (
                new_id,
                row["created_by_user_id"],
                int(row["id"]),
                str(row["name"] or ""),
                str(row["origin"] or "manual"),
                str(row["origin_chat_id"] or ""),
                int(row["client_version"] or 0),
                float(row["created_at"]),
                float(row["created_at"]),
            ),
        )
    # Update the index counter so new missions get fresh indices.
    if old_rows:
        max_index = max(int(r["id"]) for r in old_rows)
        users = set(str(r["created_by_user_id"] or "") for r in old_rows)
        for uid in users:
            conn.execute(
                """
                INSERT INTO mission_index_counters (user_id, next_index)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET next_index = MAX(next_index, excluded.next_index)
                """,
                (uid, max_index + 1),
            )
    conn.execute("DROP TABLE missions_pre17")


def _migration_019_normalize_awaiting_approval_status(conn: sqlite3.Connection) -> None:
    # Phase A removed awaiting_approval from all active status sets and the
    # approve_revision() call path, but existing DB rows may still carry it.
    # Promote those revisions to 'exported' (the closest equivalent — the
    # revision was ready to run, just pending a gate that no longer exists).
    if _table_exists(conn, "ai_mission_revisions"):
        conn.execute(
            "UPDATE ai_mission_revisions SET status = 'exported' WHERE status = 'awaiting_approval'"
        )


def _migration_018_add_mission_color(conn: sqlite3.Connection) -> None:
    # Per-Mission colour override, persisted server-side so a user's colour
    # choice survives reloads and is shared across clients. Empty string means
    # "no override" — the sidebar falls back to its by-visibility auto palette.
    # Ports master's server-side mission colour onto this branch's flat-Mission
    # store (master kept it on `mission_repository`, dropped here).
    if _table_exists(conn, "missions") and not _column_exists(conn, "missions", "color"):
        conn.execute("ALTER TABLE missions ADD COLUMN color TEXT NOT NULL DEFAULT ''")


def _migration_020_create_operational_constraints(conn: sqlite3.Connection) -> None:
    # ADR 0025 (V2 contract): operational planning constraints — allowed
    # corridors (stay-inside) and blockages (stay-outside). Backend-owned
    # planning data, deliberately isolated from mission revisions and the
    # per-mission geofence. V1 is a small contract: WGS84 polygon geometry only,
    # hard|soft rule, enable/disable lifecycle, deployment-wide scope (no
    # project/scene identity exists yet), optimistic-concurrency `version`.
    # Speculative fields (cost_multiplier, effective windows, vehicle profiles,
    # coordinate_frame, creator identity) are intentionally absent — a schema
    # migration is cheaper than freezing meanings the product cannot yet honor.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operational_constraints (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          name TEXT NOT NULL DEFAULT '',
          polygon_json TEXT NOT NULL DEFAULT '[]',
          rule TEXT NOT NULL DEFAULT 'hard',
          enabled INTEGER NOT NULL DEFAULT 1,
          version INTEGER NOT NULL DEFAULT 1,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_operational_constraints_kind ON operational_constraints(kind, updated_at DESC)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "create_ai_mission_drafts", _migration_001_create_ai_mission_drafts),
    (2, "add_ai_session_meta_json", _migration_002_add_ai_session_meta_json),
    (3, "create_ai_mission_execution_tables", _migration_003_create_ai_mission_execution_tables),
    (4, "create_ai_mission_controller_tables", _migration_004_create_ai_mission_controller_tables),
    (5, "add_revision_mutation_fields", _migration_005_add_revision_mutation_fields),
    (6, "create_missions", _migration_006_create_missions),
    (7, "create_mission_index_counters", _migration_007_create_mission_index_counters),
    (8, "add_mission_active_operation", _migration_008_add_mission_active_operation),
    (9, "add_mission_origin_datum", _migration_009_add_mission_origin_datum),
    (11, "restore_mission_execution_tables", _migration_011_restore_mission_execution_tables),
    (17, "reconcile_missions_schema", _migration_017_reconcile_missions_schema),
    (18, "add_mission_color", _migration_018_add_mission_color),
    (19, "normalize_awaiting_approval_status", _migration_019_normalize_awaiting_approval_status),
    (20, "create_operational_constraints", _migration_020_create_operational_constraints),
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
