from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


def _snapshot_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "controller_version": int(value.get("controller_version") or 0),
        "operation_id": str(value.get("operation_id") or ""),
        "revision_id": str(value.get("revision_id") or ""),
        "draft_id": str(value.get("draft_id") or ""),
        "captured_at": value.get("captured_at"),
        "mission_export": value.get("mission_export") if isinstance(value.get("mission_export"), dict) else {},
        "mission": value.get("mission") if isinstance(value.get("mission"), dict) else {},
        "plan": value.get("plan") if isinstance(value.get("plan"), dict) else {},
    }


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(slots=True)
class ControllerMissionAdapterState:
    controller_version: int = 0
    status: str = "idle"
    operation_id: str = ""
    revision_id: str = ""
    draft_id: str = ""
    captured_at: float | None = None
    mission_export: dict[str, Any] = field(default_factory=dict)
    mission: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    raw_state: dict[str, Any] = field(default_factory=dict)

    def to_snapshot(self) -> dict[str, Any]:
        if not (
            self.controller_version
            or self.operation_id
            or self.revision_id
            or self.draft_id
            or self.mission_export
            or self.mission
            or self.plan
        ):
            return {}
        return {
            "controller_version": int(self.controller_version),
            "operation_id": self.operation_id,
            "revision_id": self.revision_id,
            "draft_id": self.draft_id,
            "captured_at": self.captured_at,
            "mission_export": dict(self.mission_export),
            "mission": dict(self.mission),
            "plan": dict(self.plan),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "controller_version": int(self.controller_version),
            "status": self.status,
            "operation_id": self.operation_id,
            "revision_id": self.revision_id,
            "draft_id": self.draft_id,
            "captured_at": self.captured_at,
            "mission_export": dict(self.mission_export),
            "mission": dict(self.mission),
            "plan": dict(self.plan),
        }


@dataclass(slots=True)
class ControllerMissionInstallResult:
    ok: bool
    status: str
    controller_state: ControllerMissionAdapterState
    error: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)


class ControllerMissionAdapter(Protocol):
    adapter_name: str

    def get_controller_state(self) -> ControllerMissionAdapterState:
        ...

    def install_mission(
        self,
        *,
        pending_snapshot: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        ...


class JsonFileControllerMissionAdapter:
    """Local stand-in for an external controller boundary.

    The adapter keeps controller-owned mission state outside the SQLite mission
    execution tables so the backend can treat install/read-back as an external
    handoff while still projecting durable audit state into SQLite.
    """

    adapter_name = "json_file_controller"

    def __init__(self, state_path: str | Path):
        self._state_path = Path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    def get_controller_state(self) -> ControllerMissionAdapterState:
        return self._state_from_record(self._load_record())

    def install_mission(
        self,
        *,
        pending_snapshot: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        current_record = self._load_record()
        current_state = self._state_from_record(current_record)
        if expected_controller_version is not None and current_state.controller_version != int(expected_controller_version):
            return ControllerMissionInstallResult(
                ok=False,
                status="stale_controller_version",
                controller_state=current_state,
                error="expected controller mission version does not match the live controller state",
                raw_result={
                    "expected_controller_version": expected_controller_version,
                    "observed_controller_version": current_state.controller_version,
                },
            )

        next_record = {
            "controller_version": int(pending_snapshot.get("controller_version") or current_state.controller_version + 1),
            "status": "executing",
            "verified_snapshot": _snapshot_dict(pending_snapshot),
            "updated_at": time.time(),
        }
        snapshot = next_record["verified_snapshot"]
        next_record["operation_id"] = str(snapshot.get("operation_id") or "")
        next_record["revision_id"] = str(snapshot.get("revision_id") or "")
        next_record["draft_id"] = str(snapshot.get("draft_id") or "")

        try:
            self._write_record(next_record)
            verified_record = self._load_record()
        except Exception as exc:
            return ControllerMissionInstallResult(
                ok=False,
                status="cutover_failed",
                controller_state=current_state,
                error=str(exc),
                raw_result={"stage": "install"},
            )

        verified_state = self._state_from_record(verified_record)
        expected_snapshot = _snapshot_dict(pending_snapshot)
        verified = (
            verified_state.controller_version == int(expected_snapshot.get("controller_version") or 0)
            and verified_state.to_snapshot() == expected_snapshot
        )
        if verified:
            return ControllerMissionInstallResult(
                ok=True,
                status="executing",
                controller_state=verified_state,
                raw_result={"verified": True},
            )

        rollback_status = "rolled_back" if current_state.to_snapshot() else "cutover_failed"
        try:
            self._write_record(current_record)
            rollback_state = self.get_controller_state()
        except Exception as exc:
            rollback_status = "cutover_failed"
            rollback_state = verified_state
            return ControllerMissionInstallResult(
                ok=False,
                status=rollback_status,
                controller_state=rollback_state,
                error=f"controller mission read-back verification failed; rollback failed: {exc}",
                raw_result={"verified": False, "rollback_failed": True},
            )

        return ControllerMissionInstallResult(
            ok=False,
            status=rollback_status,
            controller_state=rollback_state,
            error="controller mission read-back verification failed",
            raw_result={"verified": False},
        )

    def _load_record(self) -> dict[str, Any]:
        return _load_json_file(self._state_path)

    def _write_record(self, record: dict[str, Any]) -> None:
        self._state_path.write_text(json.dumps(record, indent=2) + "\n")

    def _state_from_record(self, record: dict[str, Any]) -> ControllerMissionAdapterState:
        snapshot = _snapshot_dict(record.get("verified_snapshot"))
        return ControllerMissionAdapterState(
            controller_version=int(record.get("controller_version") or snapshot.get("controller_version") or 0),
            status=str(record.get("status") or "idle"),
            operation_id=str(record.get("operation_id") or snapshot.get("operation_id") or ""),
            revision_id=str(record.get("revision_id") or snapshot.get("revision_id") or ""),
            draft_id=str(record.get("draft_id") or snapshot.get("draft_id") or ""),
            captured_at=snapshot.get("captured_at"),
            mission_export=snapshot.get("mission_export") if isinstance(snapshot.get("mission_export"), dict) else {},
            mission=snapshot.get("mission") if isinstance(snapshot.get("mission"), dict) else {},
            plan=snapshot.get("plan") if isinstance(snapshot.get("plan"), dict) else {},
            raw_state=dict(record),
        )
