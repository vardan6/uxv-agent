"""TA7 — replay selection and analytics boundary (audit item 4).

Exercises `ReplayAnalyticsService` (which backs `/api/replay/sessions*`)
directly against a real `ReplayStore` on a tmp sqlite file: selector
parsing/resolution, missing-session handling, and aggregation over an empty
or partial data set.
"""

from __future__ import annotations

from replay_analytics import ReplayAnalyticsService
from replay_store import ReplayStore


def _service(tmp_path) -> ReplayAnalyticsService:
    store = ReplayStore(tmp_path / "replay.sqlite3", backend_type="test")
    return ReplayAnalyticsService(store)


def test_resolve_sessions_with_no_selector_and_no_active_session_is_empty(tmp_path) -> None:
    service = _service(tmp_path)

    selection = service.resolve_sessions(None)

    assert selection["selector_type"] == "default_recent"
    assert selection["resolved_session_ids"] == []


def test_resolve_sessions_with_no_selector_prefers_active_session(tmp_path) -> None:
    service = _service(tmp_path)

    selection = service.resolve_sessions(None, active_session_id="session-abc123")

    assert selection["selector_type"] == "active_session"
    assert selection["resolved_session_ids"] == ["session-abc123"]


def test_resolve_sessions_extracts_explicit_session_id_from_free_text(tmp_path) -> None:
    service = _service(tmp_path)
    store = service._store
    session_id = store.start_session("test")

    selection = service.resolve_sessions(f"show me {session_id} please")

    assert session_id in selection["resolved_session_ids"]


def test_resolve_sessions_falls_back_gracefully_for_unknown_timezone(tmp_path) -> None:
    service = _service(tmp_path)

    # Must not raise even though "Not/ARealZone" is not a valid IANA name.
    selection = service.resolve_sessions("", timezone_name="Not/ARealZone")

    assert selection["resolution_basis"]["timezone"] != "Not/ARealZone"


def test_get_session_summary_and_metrics_are_none_for_missing_session(tmp_path) -> None:
    service = _service(tmp_path)

    assert service.get_session_summary("session-does-not-exist") is None
    assert service.get_session_metrics("session-does-not-exist") is None
    assert service.get_session_path("session-does-not-exist") is None
    assert service.search_session_events("session-does-not-exist") is None


def test_search_session_events_with_no_matching_events_returns_zero_count(tmp_path) -> None:
    # `start_session` itself logs a "session_started" event, so a session is
    # never truly empty; the boundary case is a filter that matches nothing.
    service = _service(tmp_path)
    session_id = service._store.start_session("test")

    result = service.search_session_events(session_id, event_type="no_such_event_type")

    assert result["count"] == 0
    assert result["events"] == []


def test_aggregate_sessions_with_explicit_ids_skips_unknown_sessions(tmp_path) -> None:
    service = _service(tmp_path)
    known_id = service._store.start_session("test")

    result = service.aggregate_sessions(session_ids=[known_id, "session-unknown000"])

    assert result["selection"]["selector_type"] == "explicit_id_list"
    # The unknown id has no summary/metrics and must be dropped, not error.
    assert result["session_ids"] == [known_id]
    assert result["session_count"] == 1


def test_aggregate_sessions_with_no_sessions_at_all_is_empty_not_an_error(tmp_path) -> None:
    service = _service(tmp_path)

    result = service.aggregate_sessions(session_ids=["session-unknown000"])

    assert result["session_count"] == 0
    assert result["sessions"] == []


def test_compare_sessions_skips_sessions_missing_summary_or_metrics(tmp_path) -> None:
    service = _service(tmp_path)
    known_id = service._store.start_session("test")

    result = service.compare_sessions([known_id, "session-unknown000"])

    assert result["session_ids"] == [known_id, "session-unknown000"]
    assert len(result["comparisons"]) == 1
