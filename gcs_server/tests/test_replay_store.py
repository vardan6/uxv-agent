from __future__ import annotations

import sqlite3

import pytest

from replay_store import ReplayStore


def test_list_session_events_treats_percent_and_underscore_as_literal_text(tmp_path) -> None:
    store = ReplayStore(tmp_path / "replay.sqlite3", backend_type="test")
    session_id = store.start_session("test")
    store.log_runtime_event("cpu_100%", {"message": "cpu_100% threshold"})
    store.log_runtime_event("plain", {"message": "ordinary event"})

    percent_results = store.list_session_events(session_id, text="100%")
    underscore_results = store.list_session_events(session_id, text="cpu_")

    assert [event["event_type"] for event in percent_results] == ["cpu_100%"]
    assert [event["event_type"] for event in underscore_results] == ["cpu_100%"]


def test_ensure_column_rejects_unapproved_schema_identifiers(tmp_path) -> None:
    store = ReplayStore(tmp_path / "replay.sqlite3", backend_type="test")
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(ValueError, match="unsupported schema migration target"):
            store._ensure_column(conn, "replay_sessions", "notes", "TEXT")
