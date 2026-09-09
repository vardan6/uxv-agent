from __future__ import annotations

from ai.execution_mode import CONFIRM
from ai.mission_execution_session import MissionExecutionSessions
from ai.mission_executor import MissionExecutor
from ai.mission_tree import NAV_LEAF, Node


def _prepared(sessions: MissionExecutionSessions, session_id: str = "sess-1") -> None:
    executor = MissionExecutor(mode=CONFIRM, leaf_driver=lambda wps: True)
    root = Node(type=NAV_LEAF, id="a", waypoints=[{"lat": 1.0, "lon": 2.0}])
    sessions.prepare(session_id, executor=executor, root=root, mission_id="mission-1", mode=CONFIRM)


def test_confirm_window_counts_down_against_the_injected_clock():
    now = {"t": 1000.0}
    sessions = MissionExecutionSessions(clock=lambda: now["t"])
    _prepared(sessions)

    result = sessions.arm_confirm("sess-1", timeout_s=30)
    assert result["ok"] is True
    assert result["confirm_remaining_s"] == 30.0

    now["t"] += 10.0
    active = sessions.get("sess-1")
    assert active is not None
    assert active.confirm_remaining_s() == 20.0


def test_confirm_expires_once_the_injected_clock_passes_the_deadline():
    now = {"t": 1000.0}
    sessions = MissionExecutionSessions(clock=lambda: now["t"])
    _prepared(sessions)
    sessions.arm_confirm("sess-1", timeout_s=5)

    now["t"] += 5.1
    result = sessions.confirm("sess-1")

    assert result["ok"] is False
    assert result["error"] == "confirm window elapsed"
    assert sessions.get("sess-1").status == "expired"


def test_confirm_within_the_window_starts_the_run():
    now = {"t": 1000.0}
    sessions = MissionExecutionSessions(clock=lambda: now["t"])
    _prepared(sessions)
    sessions.arm_confirm("sess-1", timeout_s=5)

    now["t"] += 1.0
    result = sessions.confirm("sess-1")
    assert result["ok"] is True

    active = sessions.get("sess-1")
    assert active is not None and active.thread is not None
    active.thread.join(timeout=2.0)
    assert active.status == "succeeded"


def test_list_active_includes_non_terminal_sessions_and_stamps_transitions():
    now = {"t": 1000.0}
    sessions = MissionExecutionSessions(clock=lambda: now["t"])
    _prepared(sessions, session_id="sess-armed")

    now["t"] = 1005.0
    sessions.arm("sess-armed")

    rows = sessions.list_active()
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "sess-armed"
    assert row["mission_id"] == "mission-1"
    assert row["status"] == "armed"
    assert row["last_transition_at"] == 1005.0


def test_list_active_excludes_terminal_sessions():
    now = {"t": 1000.0}
    sessions = MissionExecutionSessions(clock=lambda: now["t"])
    _prepared(sessions, session_id="sess-done")
    sessions.arm_confirm("sess-done", timeout_s=5)

    now["t"] += 1.0
    result = sessions.confirm("sess-done")
    assert result["ok"] is True
    sessions.get("sess-done").thread.join(timeout=2.0)

    assert sessions.list_active() == []
