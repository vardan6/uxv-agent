from __future__ import annotations

from typing import Any


class MissionControl:
    """Single park->call->rollback owner for mission pause/resume/stop.

    Parks the executor-thread session state (`MissionExecutionSessions`), then
    calls the FC/DB-backed `MissionExecutionService`; if the service call
    fails, the session park is rolled back. The HTTP routes
    (`routers/ai.py`) and the AI tool (`ai/tool_registry.py`) are thin
    adapters over this.
    """

    _ACTIONS: dict[str, tuple[str, str, str | None]] = {
        "pause": ("pause_for_mission", "pause_mission", "resume_for_mission"),
        "resume": ("resume_for_mission", "resume_mission", "pause_for_mission"),
        "stop": ("abort_for_mission", "abort_mission", None),
    }

    def __init__(self, sessions: Any, service: Any, mission_store: Any) -> None:
        self._sessions = sessions
        self._service = service
        self._mission_store = mission_store

    def pause(self, mission_id: str) -> dict[str, Any]:
        return self._apply("pause", mission_id)

    def resume(self, mission_id: str) -> dict[str, Any]:
        return self._apply("resume", mission_id)

    def stop(self, mission_id: str) -> dict[str, Any]:
        return self._apply("stop", mission_id)

    def _apply(self, action: str, mission_id: str) -> dict[str, Any]:
        session_method, service_method, rollback_method = self._ACTIONS[action]
        result = getattr(self._sessions, session_method)(mission_id)
        if not result.get("ok"):
            return result
        op_id = self._operation_id_for_mission(mission_id)
        if self._service is not None and op_id:
            svc_result = getattr(self._service, service_method)(op_id)
            if not svc_result.get("ok"):
                if rollback_method is not None:
                    getattr(self._sessions, rollback_method)(mission_id)
                return svc_result
        return result

    def _operation_id_for_mission(self, mission_id: str) -> str:
        """Return the active_operation_id for a flat Mission, or '' if unavailable."""
        if self._mission_store is None:
            return ""
        mission = self._mission_store.get_mission(str(mission_id or "").strip())
        if not isinstance(mission, dict):
            return ""
        return str(mission.get("active_operation_id") or "").strip()


def mission_control_for(runtime: Any) -> "MissionControl | None":
    """Build a `MissionControl` from a runtime's collaborators, or None if the
    executor-thread session registry is unavailable."""
    sessions = runtime.mission_execution_sessions
    if sessions is None:
        return None
    return MissionControl(sessions, runtime.mission_execution_service, runtime.mission_store)
