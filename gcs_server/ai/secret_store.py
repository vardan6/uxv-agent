from __future__ import annotations

import sqlite3
from pathlib import Path


class SecretStore:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_secrets (
                  secret_ref TEXT PRIMARY KEY,
                  secret_value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def set_secret(self, secret_ref: str, secret_value: str) -> None:
        ref = str(secret_ref or "").strip()
        value = str(secret_value or "").strip()
        if not ref:
            raise ValueError("secret_ref is required")
        if not value:
            raise ValueError("secret_value is required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_secrets (secret_ref, secret_value)
                VALUES (?, ?)
                ON CONFLICT(secret_ref) DO UPDATE SET secret_value=excluded.secret_value
                """,
                (ref, value),
            )
            conn.commit()

    def get_secret(self, secret_ref: str) -> str:
        ref = str(secret_ref or "").strip()
        if not ref:
            raise KeyError("secret_ref is required")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret_value FROM llm_secrets WHERE secret_ref = ?",
                (ref,),
            ).fetchone()
        if row is None:
            raise KeyError(f"secret not found: {ref}")
        return str(row[0]).strip()

    def has_secret(self, secret_ref: str) -> bool:
        ref = str(secret_ref or "").strip()
        if not ref:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM llm_secrets WHERE secret_ref = ?",
                (ref,),
            ).fetchone()
        return row is not None

    def delete_secret(self, secret_ref: str) -> None:
        ref = str(secret_ref or "").strip()
        if not ref:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM llm_secrets WHERE secret_ref = ?", (ref,))
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM llm_secrets").fetchone()
        return int(row[0] or 0) if row is not None else 0

    def migrate_from(self, legacy_db_path: Path) -> int:
        legacy_path = Path(legacy_db_path)
        if not legacy_path.exists() or legacy_path.resolve() == self._db_path.resolve():
            return 0

        with sqlite3.connect(legacy_path) as legacy_conn:
            rows = legacy_conn.execute(
                "SELECT secret_ref, secret_value FROM llm_secrets"
            ).fetchall()

        migrated = 0
        if not rows:
            return migrated

        with self._connect() as conn:
            for secret_ref, secret_value in rows:
                ref = str(secret_ref or "").strip()
                value = str(secret_value or "").strip()
                if not ref or not value:
                    continue
                conn.execute(
                    """
                    INSERT INTO llm_secrets (secret_ref, secret_value)
                    VALUES (?, ?)
                    ON CONFLICT(secret_ref) DO UPDATE SET secret_value=excluded.secret_value
                    """,
                    (ref, value),
                )
                migrated += 1
            conn.commit()
        return migrated
