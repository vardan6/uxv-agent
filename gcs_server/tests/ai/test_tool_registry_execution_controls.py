from __future__ import annotations

from types import SimpleNamespace

from ai.tool_registry import ToolInvocationContext, ToolRegistry


class _FakeMissionStore:
    def __init__(self, mission_id: str, operation_id: str = "") -> None:
        self._mission_id = mission_id
        self._operation_id = operation_id

    def get_mission(self, mission_id: str) -> dict | None:
        if mission_id != self._mission_id:
            return None
        return {"id": mission_id, "active_operation_id": self._operation_id}


class _FakeSessions:
    def __init__(self, *, pause_ok: bool = True, resume_ok: bool = True, abort_ok: bool = True) -> None:
        self.pause_ok = pause_ok
        self.resume_ok = resume_ok
        self.abort_ok = abort_ok
        self.calls: list[tuple[str, str]] = []

    def pause_for_mission(self, mission_id: str) -> dict:
        self.calls.append(("pause", mission_id))
        if not self.pause_ok:
            return {"ok": False, "error": "pause rejected"}
        return {"ok": True, "status": "paused", "mission_id": mission_id}

    def resume_for_mission(self, mission_id: str) -> dict:
        self.calls.append(("resume", mission_id))
        if not self.resume_ok:
            return {"ok": False, "error": "resume rejected"}
        return {"ok": True, "status": "running", "mission_id": mission_id}

    def abort_for_mission(self, mission_id: str) -> dict:
        self.calls.append(("abort", mission_id))
        if not self.abort_ok:
            return {"ok": False, "error": "abort rejected"}
        return {"ok": True, "status": "aborted", "mission_id": mission_id}


class _FakeService:
    def __init__(self, *, pause_ok: bool = True, resume_ok: bool = True, abort_ok: bool = True) -> None:
        self.pause_ok = pause_ok
        self.resume_ok = resume_ok
        self.abort_ok = abort_ok
        self.calls: list[tuple[str, str]] = []

    def pause_mission(self, operation_id: str) -> dict:
        self.calls.append(("pause", operation_id))
        if not self.pause_ok:
            return {"ok": False, "status": "adapter_error", "error": "pause failed", "operation_id": operation_id}
        return {"ok": True, "status": "paused", "operation_id": operation_id}

    def resume_mission(self, operation_id: str) -> dict:
        self.calls.append(("resume", operation_id))
        if not self.resume_ok:
            return {"ok": False, "status": "adapter_error", "error": "resume failed", "operation_id": operation_id}
        return {"ok": True, "status": "running", "operation_id": operation_id}

    def abort_mission(self, operation_id: str) -> dict:
        self.calls.append(("abort", operation_id))
        if not self.abort_ok:
            return {"ok": False, "status": "adapter_error", "error": "stop failed", "operation_id": operation_id}
        return {"ok": True, "status": "aborted", "operation_id": operation_id}


def _context(runtime: object) -> ToolInvocationContext:
    return ToolInvocationContext(
        runtime=runtime,
        context_snapshot={},
        timezone_name="",
        permissions=frozenset(),
        source_controls={},
        session_id="sess-1",
        user_id="user-1",
    )


def test_pause_tool_rolls_back_session_pause_when_service_pause_fails() -> None:
    mission_id = "mission-1"
    sessions = _FakeSessions()
    service = _FakeService(pause_ok=False)
    runtime = SimpleNamespace(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, "op-1"),
    )

    result = ToolRegistry()._pause_mission_execution(_context(runtime), mission_id)

    assert result["ok"] is False
    assert result["status"] == "adapter_error"
    assert sessions.calls == [("pause", mission_id), ("resume", mission_id)]
    assert service.calls == [("pause", "op-1")]


def test_resume_tool_rolls_back_session_resume_when_service_resume_fails() -> None:
    mission_id = "mission-1"
    sessions = _FakeSessions()
    service = _FakeService(resume_ok=False)
    runtime = SimpleNamespace(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, "op-1"),
    )

    result = ToolRegistry()._resume_mission_execution(_context(runtime), mission_id)

    assert result["ok"] is False
    assert result["status"] == "adapter_error"
    assert sessions.calls == [("resume", mission_id), ("pause", mission_id)]
    assert service.calls == [("resume", "op-1")]


def test_stop_tool_forwards_abort_without_session_rollback() -> None:
    mission_id = "mission-1"
    sessions = _FakeSessions()
    service = _FakeService(abort_ok=False)
    runtime = SimpleNamespace(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, "op-1"),
    )

    result = ToolRegistry()._stop_mission_execution(_context(runtime), mission_id)

    assert result["ok"] is False
    assert result["status"] == "adapter_error"
    assert sessions.calls == [("abort", mission_id)]
    assert service.calls == [("abort", "op-1")]


def test_pause_tool_skips_service_when_mission_has_no_active_operation() -> None:
    mission_id = "mission-1"
    sessions = _FakeSessions()
    service = _FakeService()
    runtime = SimpleNamespace(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, ""),
    )

    result = ToolRegistry()._pause_mission_execution(_context(runtime), mission_id)

    assert result == {"ok": True, "status": "paused", "mission_id": mission_id}
    assert sessions.calls == [("pause", mission_id)]
    assert service.calls == []
