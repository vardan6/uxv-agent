from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .controller_mission_adapter import (
    ControllerMissionAdapter,
    JsonFileControllerMissionAdapter,
)


MISSION_CONTROLLER_ID = "primary"


class MissionExecutionService:
    """Controller handoff boundary for flat ADR 0021 Missions.

    Owns the controller adapter only — mission persistence belongs to
    `MissionRepository`. This service is a thin facade over `install_mission`
    and `cancel_mission` with mode-specific bookkeeping (`arm` vs `execute`).
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        controller_adapter: ControllerMissionAdapter | None = None,
    ):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._controller_adapter = controller_adapter or JsonFileControllerMissionAdapter(
            self._db_path.parent / "controller_mission_adapter.json"
        )

    def execute_mission_by_id(
        self,
        *,
        mission_id: int,
        mission_json: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> dict[str, Any]:
        """ADR 0021 mode-aware execute: hand a flat Mission to the controller.

        Builds an in-memory plan via MissionExportService and calls
        install_mission on the configured controller adapter. No DB writes —
        flat-mission audit trail is an Open Question on ADR 0021.
        """
        try:
            from .mission_export_service import MissionExportService
        except ImportError:
            return {
                "ok": False,
                "status": "mission_export_unavailable",
                "error": "MissionExportService is unavailable",
            }

        try:
            mid = int(mission_id)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "status": "invalid_mission_id",
                "error": f"mission_id must be an integer, got {mission_id!r}",
            }

        if not isinstance(mission_json, dict) or not mission_json:
            return {"ok": False, "status": "mission_empty", "error": "mission_json is empty"}

        export_draft = {
            "id": f"mission-{mid}",
            "status": "approved",
            "mission": mission_json,
        }
        export_result = MissionExportService().export(export_draft)
        if not export_result.get("ok"):
            return {
                "ok": False,
                "status": "mission_export_invalid",
                "error": str(export_result.get("error") or "mission export failed"),
                "mission_id": mid,
            }

        plan = export_result.get("plan") if isinstance(export_result.get("plan"), dict) else {}
        pending_snapshot = {
            "operation_id": "",
            "revision_id": "",
            "draft_id": f"mission-{mid}",
            "mission_id": mid,
            "captured_at": time.time(),
            "mission_export": {
                "file_path": str(export_result.get("file_path") or ""),
                "waypoint_count": int(export_result.get("waypoint_count") or 0),
                "vehicle_type": str(export_result.get("vehicle_type") or ""),
            },
            "mission": mission_json,
            "plan": plan,
        }

        try:
            install_result = self._controller_adapter.install_mission(
                pending_snapshot=pending_snapshot,
                expected_controller_version=expected_controller_version,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "cutover_failed",
                "error": str(exc),
                "mission_id": mid,
                "controller_state": self.get_controller_state(),
            }

        final_state = install_result.controller_state
        return {
            "ok": bool(install_result.ok),
            "status": str(install_result.status or ("executing" if install_result.ok else "cutover_failed")),
            "error": install_result.error or "",
            "mission_id": mid,
            "controller_state": final_state.to_public_dict() if final_state is not None else {},
            "adapter_result": install_result.raw_result,
        }

    def arm_execution_by_id(
        self,
        *,
        mission_id: int,
        mission_json: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> dict[str, Any]:
        """ADR 0021 § 1 Confirm-mode arm: install the mission after operator confirm.

        Mechanically identical to `execute_mission_by_id` today — the distinction
        exists at the AI-tool boundary (only bound in Confirm mode) so the chat
        operator's explicit confirm is what triggers this path, not the model.
        """
        result = self.execute_mission_by_id(
            mission_id=mission_id,
            mission_json=mission_json,
            expected_controller_version=expected_controller_version,
        )
        if result.get("ok") and result.get("status") == "executing":
            result["status"] = "armed"
        return result

    def cancel_execution_by_id(
        self,
        *,
        mode: str = "clear",
        expected_controller_version: int | None = None,
    ) -> dict[str, Any]:
        """ADR 0021 § 1 cancel: abort the controller mission via the adapter."""
        cancel = getattr(self._controller_adapter, "cancel_mission", None)
        if not callable(cancel):
            return {
                "ok": False,
                "status": "cancel_unsupported",
                "error": f"adapter {getattr(self._controller_adapter, 'adapter_name', '?')} does not implement cancel_mission",
                "controller_state": self.get_controller_state(),
            }
        try:
            result = cancel(mode=mode, expected_controller_version=expected_controller_version)
        except Exception as exc:
            return {
                "ok": False,
                "status": "cutover_failed",
                "error": str(exc),
                "controller_state": self.get_controller_state(),
            }
        final_state = result.controller_state
        return {
            "ok": bool(result.ok),
            "status": str(result.status or ("cancelled" if result.ok else "cutover_failed")),
            "error": result.error or "",
            "cancel_mode": str(mode or "clear"),
            "controller_state": final_state.to_public_dict() if final_state is not None else {},
            "adapter_result": result.raw_result,
        }

    def get_controller_state(self) -> dict[str, Any]:
        adapter_state = self._controller_adapter.get_controller_state()
        summary = f"Controller mission state: {adapter_state.status}."
        if adapter_state.controller_version:
            summary = f"{summary} Version: {adapter_state.controller_version}."
        if adapter_state.revision_id:
            summary = f"{summary} Active revision: {adapter_state.revision_id}."
        return {
            "available": True,
            "controller_id": MISSION_CONTROLLER_ID,
            "controller_version": int(adapter_state.controller_version or 0),
            "active_operation_id": adapter_state.operation_id,
            "active_revision_id": adapter_state.revision_id,
            "active_draft_id": adapter_state.draft_id,
            "status": str(adapter_state.status or "idle"),
            "summary": summary,
            "verified_snapshot": adapter_state.to_snapshot(),
            "previous_verified_snapshot": {},
            "pending_snapshot": {},
            "last_cutover_attempt": {},
            "last_error": "",
            "last_cutover_at": None,
            "verified_at": adapter_state.captured_at,
            "updated_at": adapter_state.captured_at,
            "adapter": self._controller_adapter.adapter_name,
        }


