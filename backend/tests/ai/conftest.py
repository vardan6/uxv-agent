from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai.migrations import apply_ai_store_migrations


@pytest.fixture
def mission_db_path(tmp_path: Path) -> Path:
    """A migrated sqlite file for mission-domain tests.

    `MissionExecutionService` reopens `db_path` on every call rather than
    holding one connection, so tests that assert against a second, ad hoc
    connection (e.g. reading operation status directly) need a real file, not
    `:memory:`. Backed by `tmp_path` so pytest owns cleanup — no leaked
    tempfiles.
    """
    db_path = tmp_path / "ai.sqlite3"
    with sqlite3.connect(db_path) as conn:
        apply_ai_store_migrations(conn)
        conn.commit()
    return db_path
