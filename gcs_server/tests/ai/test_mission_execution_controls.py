from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from ai.mission_execution_service import MissionExecutionService
from routers.ai import pause_mission_endpoint, resume_mission_endpoint, stop_mission_endpoint
from tests.runtime_stub import make_stub_runtime


class _RecordingControllerAdapter:
    adapter_name = "recording_adapter"

    def __init__(
        self,
        *,
        pause_error: Exception | None = None,
        resume_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        self.pause_error = pause_error
        self.resume_error = resume_error
        self.stop_error = stop_error
        self.calls: list[str] = []

    def pause_mission(self) -> None:
        self.calls.append("pause")
        if self.pause_error is not None:
            raise self.pause_error

    def resume_mission(self) -> None:
        self.calls.append("resume")
        if self.resume_error is not None:
            raise self.resume_error

    def stop_mission(self) -> None:
        self.calls.append("stop")
        if self.stop_error is not None:
            raise self.stop_error

    def get_controller_state(self):
        raise AssertionError("get_controller_state should not be called in execution-control tests")

    def install_mission(self, *, pending_snapshot: dict, expected_controller_version: int | None = None):
        raise AssertionError("install_mission should not be called in execution-control tests")


class _FakeMissionStore:
    def __init__(self, mission_id: str, operation_id: str) -> None:
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


def _make_service_with_operation(
    *, adapter: _RecordingControllerAdapter, db_path: Path
) -> tuple[MissionExecutionService, str, Path]:
    svc = MissionExecutionService(db_path, controller_adapter=adapter)
    proposal = svc.create_proposal(
        session_id="sess-1",
        source_message_id="msg-1",
        draft_id="draft-1",
        intent={},
        target_resolution={},
        draft_payload={
            "goal": "test mission",
            "waypoints": [{"x": 0.0, "y": 0.0, "z": 0.0}],
            "steps": [],
            "constraints": [],
            "assumptions": [],
        },
        validation={},
        draft_status="proposed",
    )
    return svc, proposal["operation_id"], db_path


def _operation_status(db_path: Path, operation_id: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM ai_mission_operations WHERE id = ?", (operation_id,)).fetchone()
    assert row is not None
    return str(row[0])


def _request(runtime: object, path: str, method: str = "POST") -> Request:
    app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_pause_mission_updates_operation_status_after_adapter_hold(mission_db_path: Path) -> None:
    adapter = _RecordingControllerAdapter()
    svc, operation_id, db_path = _make_service_with_operation(adapter=adapter, db_path=mission_db_path)

    result = svc.pause_mission(operation_id)

    assert result == {"ok": True, "status": "paused", "operation_id": operation_id}
    assert adapter.calls == ["pause"]
    assert _operation_status(db_path, operation_id) == "paused"


def test_pause_mission_returns_adapter_error_without_db_mutation(mission_db_path: Path) -> None:
    adapter = _RecordingControllerAdapter(pause_error=RuntimeError("hold failed"))
    svc, operation_id, db_path = _make_service_with_operation(adapter=adapter, db_path=mission_db_path)
    before = _operation_status(db_path, operation_id)

    result = svc.pause_mission(operation_id)

    assert result == {"ok": False, "status": "adapter_error", "error": "hold failed", "operation_id": operation_id}
    assert adapter.calls == ["pause"]
    assert _operation_status(db_path, operation_id) == before


def test_resume_mission_updates_operation_status_after_adapter_auto(mission_db_path: Path) -> None:
    adapter = _RecordingControllerAdapter()
    svc, operation_id, db_path = _make_service_with_operation(adapter=adapter, db_path=mission_db_path)

    result = svc.resume_mission(operation_id)

    assert result == {"ok": True, "status": "running", "operation_id": operation_id}
    assert adapter.calls == ["resume"]
    assert _operation_status(db_path, operation_id) == "running"


def test_abort_mission_updates_operation_status_after_adapter_hold(mission_db_path: Path) -> None:
    adapter = _RecordingControllerAdapter()
    svc, operation_id, db_path = _make_service_with_operation(adapter=adapter, db_path=mission_db_path)

    result = svc.abort_mission(operation_id)

    assert result == {"ok": True, "status": "aborted", "operation_id": operation_id}
    assert adapter.calls == ["stop"]
    assert _operation_status(db_path, operation_id) == "aborted"


def test_pause_endpoint_rolls_back_session_pause_when_service_pause_fails() -> None:
    mission_id = "mission-1"
    operation_id = "op-1"
    sessions = _FakeSessions()
    service = _FakeService(pause_ok=False)
    runtime = make_stub_runtime(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, operation_id),
    )

    response = asyncio.run(pause_mission_endpoint(mission_id, _request(runtime, f"/api/ai/missions/{mission_id}/pause")))
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["status"] == "adapter_error"
    assert sessions.calls == [("pause", mission_id), ("resume", mission_id)]
    assert service.calls == [("pause", operation_id)]


def test_resume_endpoint_rolls_back_session_resume_when_service_resume_fails() -> None:
    mission_id = "mission-1"
    operation_id = "op-1"
    sessions = _FakeSessions()
    service = _FakeService(resume_ok=False)
    runtime = make_stub_runtime(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, operation_id),
    )

    response = asyncio.run(
        resume_mission_endpoint(mission_id, _request(runtime, f"/api/ai/missions/{mission_id}/resume"))
    )
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["status"] == "adapter_error"
    assert sessions.calls == [("resume", mission_id), ("pause", mission_id)]
    assert service.calls == [("resume", operation_id)]


def test_stop_endpoint_forwards_abort_to_service_without_rollback() -> None:
    mission_id = "mission-1"
    operation_id = "op-1"
    sessions = _FakeSessions()
    service = _FakeService()
    runtime = make_stub_runtime(
        mission_execution_sessions=sessions,
        mission_execution_service=service,
        mission_store=_FakeMissionStore(mission_id, operation_id),
    )

    response = asyncio.run(stop_mission_endpoint(mission_id, _request(runtime, f"/api/ai/missions/{mission_id}/stop")))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "aborted"
    assert sessions.calls == [("abort", mission_id)]
    assert service.calls == [("abort", operation_id)]
