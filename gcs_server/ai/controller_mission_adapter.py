from __future__ import annotations

import json
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


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


class ControllerMissionAdapterError(RuntimeError):
    pass


def _normalize_plan_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    mission = plan.get("mission") if isinstance(plan, dict) else {}
    items = mission.get("items") if isinstance(mission, dict) else []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        params = item.get("params") if isinstance(item.get("params"), list) else []
        while len(params) < 7:
            params.append(0)
        normalized.append({
            "seq": index,
            "frame": int(item.get("frame") or 0),
            "command": int(item.get("command") or 0),
            "current": int(bool(item.get("current", 0))),
            "autocontinue": int(bool(item.get("autoContinue", True))),
            "param1": float(params[0] or 0.0),
            "param2": float(params[1] or 0.0),
            "param3": float(params[2] or 0.0),
            "param4": float(params[3] or 0.0),
            "x": int(round(float(params[4] or 0.0) * 1e7)),
            "y": int(round(float(params[5] or 0.0) * 1e7)),
            "z": float(params[6] or 0.0),
        })
    return normalized


def _normalize_downloaded_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        normalized.append({
            "seq": index,
            "frame": int(item.get("frame") or 0),
            "command": int(item.get("command") or 0),
            "current": int(bool(item.get("current", 0))),
            "autocontinue": int(bool(item.get("autocontinue", item.get("autocontinue", 1)))),
            "param1": float(item.get("param1") or 0.0),
            "param2": float(item.get("param2") or 0.0),
            "param3": float(item.get("param3") or 0.0),
            "param4": float(item.get("param4") or 0.0),
            "x": int(item.get("x") or 0),
            "y": int(item.get("y") or 0),
            "z": float(item.get("z") or 0.0),
        })
    return normalized


def _mission_items_equivalent(expected: list[dict[str, Any]], observed: list[dict[str, Any]]) -> bool:
    clean_expected = _normalize_downloaded_items(expected)
    clean_observed = _normalize_downloaded_items(observed)
    if clean_expected == clean_observed:
        return True
    # ArduPilot may expose a leading home item on read-back; accept that shape.
    if len(clean_observed) == len(clean_expected) + 1 and clean_observed[1:] == clean_expected:
        return True
    return False


def _controller_version_for_items(items: list[dict[str, Any]]) -> int:
    encoded = json.dumps(_normalize_downloaded_items(items), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return zlib.crc32(encoded) & 0xFFFFFFFF


def _snapshot_from_pending(pending_snapshot: dict[str, Any], controller_version: int) -> dict[str, Any]:
    snapshot = _snapshot_dict(pending_snapshot)
    snapshot["controller_version"] = int(controller_version)
    return snapshot


class PymavlinkMissionClient:
    def __init__(
        self,
        connection_url: str,
        *,
        heartbeat_timeout_s: float = 5.0,
        request_timeout_s: float = 5.0,
        source_system: int = 245,
        source_component: int = 190,
    ) -> None:
        try:
            from pymavlink import mavutil
        except ImportError as exc:
            raise ControllerMissionAdapterError(
                "pymavlink is not installed; install gcs_server/requirements-gcs.txt"
            ) from exc
        self._mavutil = mavutil
        self._request_timeout_s = float(request_timeout_s)
        self._connection = mavutil.mavlink_connection(
            connection_url,
            source_system=int(source_system),
            source_component=int(source_component),
        )
        if self._connection.wait_heartbeat(timeout=float(heartbeat_timeout_s)) is None:
            raise ControllerMissionAdapterError("timed out waiting for MAVLink heartbeat")

    def close(self) -> None:
        close = getattr(self._connection, "close", None)
        if callable(close):
            close()

    def _recv(self, types: list[str] | tuple[str, ...], *, timeout_s: float | None = None) -> Any:
        msg = self._connection.recv_match(
            type=list(types),
            blocking=True,
            timeout=float(timeout_s if timeout_s is not None else self._request_timeout_s),
        )
        if msg is None:
            raise ControllerMissionAdapterError(f"timed out waiting for MAVLink message: {types}")
        return msg

    def download_mission_items(self) -> list[dict[str, Any]]:
        self._connection.mav.mission_request_list_send(
            self._connection.target_system,
            self._connection.target_component,
            0,
        )
        count_msg = self._recv(["MISSION_COUNT"])
        count = int(getattr(count_msg, "count", 0) or 0)
        items: list[dict[str, Any]] = []
        for seq in range(count):
            self._connection.mav.mission_request_int_send(
                self._connection.target_system,
                self._connection.target_component,
                seq,
                0,
            )
            item_msg = self._recv(["MISSION_ITEM_INT", "MISSION_ITEM"])
            payload = item_msg.to_dict() if hasattr(item_msg, "to_dict") else dict(item_msg)
            items.append({
                "seq": int(payload.get("seq") or seq),
                "frame": int(payload.get("frame") or 0),
                "command": int(payload.get("command") or 0),
                "current": int(payload.get("current") or 0),
                "autocontinue": int(payload.get("autocontinue") or payload.get("autocontinue", 1) or 0),
                "param1": float(payload.get("param1") or 0.0),
                "param2": float(payload.get("param2") or 0.0),
                "param3": float(payload.get("param3") or 0.0),
                "param4": float(payload.get("param4") or 0.0),
                "x": int(payload.get("x") or 0),
                "y": int(payload.get("y") or 0),
                "z": float(payload.get("z") or 0.0),
            })
        self._connection.mav.mission_ack_send(
            self._connection.target_system,
            self._connection.target_component,
            self._mavutil.mavlink.MAV_MISSION_ACCEPTED,
            0,
        )
        return items

    def upload_mission_items(self, items: list[dict[str, Any]]) -> None:
        self._connection.mav.mission_count_send(
            self._connection.target_system,
            self._connection.target_component,
            len(items),
            0,
        )
        for item in items:
            request_msg = self._recv(["MISSION_REQUEST_INT", "MISSION_REQUEST"])
            seq = int(getattr(request_msg, "seq", item["seq"]) or item["seq"])
            current = int(item["current"])
            self._connection.mav.mission_item_int_send(
                self._connection.target_system,
                self._connection.target_component,
                seq,
                item["frame"],
                item["command"],
                current,
                item["autocontinue"],
                item["param1"],
                item["param2"],
                item["param3"],
                item["param4"],
                item["x"],
                item["y"],
                item["z"],
                0,
            )
        ack_msg = self._recv(["MISSION_ACK"])
        ack_type = int(getattr(ack_msg, "type", self._mavutil.mavlink.MAV_MISSION_ACCEPTED))
        if ack_type != self._mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise ControllerMissionAdapterError(f"mission upload rejected with MAV_MISSION type={ack_type}")


class MavlinkControllerMissionAdapter:
    adapter_name = "mavlink_controller"

    def __init__(
        self,
        *,
        connection_url: str,
        state_path: str | Path,
        heartbeat_timeout_s: float = 5.0,
        request_timeout_s: float = 5.0,
        source_system: int = 245,
        source_component: int = 190,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._connection_url = str(connection_url or "").strip()
        if not self._connection_url:
            raise ControllerMissionAdapterError("connection_url is required for the MAVLink controller adapter")
        self._state_path = Path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._heartbeat_timeout_s = float(heartbeat_timeout_s)
        self._request_timeout_s = float(request_timeout_s)
        self._source_system = int(source_system)
        self._source_component = int(source_component)
        self._client_factory = client_factory

    def get_controller_state(self) -> ControllerMissionAdapterState:
        client = self._open_client()
        try:
            downloaded = client.download_mission_items()
        finally:
            self._close_client(client)
        controller_version = _controller_version_for_items(downloaded)
        mapping = self._load_mapping()
        metadata = mapping.get(str(controller_version), {})
        snapshot = metadata.get("verified_snapshot") if isinstance(metadata, dict) else {}
        base = _snapshot_dict(snapshot)
        base["controller_version"] = controller_version
        base["captured_at"] = time.time()
        base["plan"] = base.get("plan") or {"mission": {"items": downloaded}}
        return ControllerMissionAdapterState(
            controller_version=controller_version,
            status="executing" if downloaded else "idle",
            operation_id=str(base.get("operation_id") or ""),
            revision_id=str(base.get("revision_id") or ""),
            draft_id=str(base.get("draft_id") or ""),
            captured_at=base.get("captured_at"),
            mission_export=base.get("mission_export") if isinstance(base.get("mission_export"), dict) else {},
            mission=base.get("mission") if isinstance(base.get("mission"), dict) else {},
            plan=base.get("plan") if isinstance(base.get("plan"), dict) else {"mission": {"items": downloaded}},
            raw_state={"downloaded_items": downloaded, "connection_url": self._connection_url},
        )

    def install_mission(
        self,
        *,
        pending_snapshot: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        plan = pending_snapshot.get("plan") if isinstance(pending_snapshot, dict) else {}
        upload_items = _normalize_plan_items(plan if isinstance(plan, dict) else {})
        if not upload_items:
            return ControllerMissionInstallResult(
                ok=False,
                status="mission_export_invalid",
                controller_state=self.get_controller_state(),
                error="pending snapshot is missing uploadable mission items",
            )

        client = self._open_client()
        try:
            previous_items = client.download_mission_items()
            observed_version = _controller_version_for_items(previous_items)
            if expected_controller_version is not None and observed_version != int(expected_controller_version):
                state = self._state_for_items(previous_items)
                return ControllerMissionInstallResult(
                    ok=False,
                    status="stale_controller_version",
                    controller_state=state,
                    error="expected controller mission version does not match the live controller state",
                    raw_result={
                        "expected_controller_version": int(expected_controller_version),
                        "observed_controller_version": observed_version,
                    },
                )

            try:
                client.upload_mission_items(upload_items)
                downloaded_after = client.download_mission_items()
            except Exception as exc:
                rollback_result = self._rollback_previous(client, previous_items)
                return ControllerMissionInstallResult(
                    ok=False,
                    status=rollback_result["status"],
                    controller_state=rollback_result["state"],
                    error=str(exc),
                    raw_result={"stage": "upload", "rollback": rollback_result["status"]},
                )

            if not _mission_items_equivalent(upload_items, downloaded_after):
                rollback_result = self._rollback_previous(client, previous_items)
                return ControllerMissionInstallResult(
                    ok=False,
                    status=rollback_result["status"],
                    controller_state=rollback_result["state"],
                    error="controller mission read-back verification failed",
                    raw_result={"stage": "verify", "rollback": rollback_result["status"]},
                )

            installed_version = _controller_version_for_items(downloaded_after)
            verified_snapshot = _snapshot_from_pending(pending_snapshot, installed_version)
            self._record_verified_snapshot(installed_version, verified_snapshot)
            state = ControllerMissionAdapterState(
                controller_version=installed_version,
                status="executing",
                operation_id=str(verified_snapshot.get("operation_id") or ""),
                revision_id=str(verified_snapshot.get("revision_id") or ""),
                draft_id=str(verified_snapshot.get("draft_id") or ""),
                captured_at=verified_snapshot.get("captured_at"),
                mission_export=verified_snapshot.get("mission_export") if isinstance(verified_snapshot.get("mission_export"), dict) else {},
                mission=verified_snapshot.get("mission") if isinstance(verified_snapshot.get("mission"), dict) else {},
                plan=verified_snapshot.get("plan") if isinstance(verified_snapshot.get("plan"), dict) else {},
                raw_state={"downloaded_items": downloaded_after, "connection_url": self._connection_url},
            )
            return ControllerMissionInstallResult(
                ok=True,
                status="executing",
                controller_state=state,
                raw_result={"verified": True},
            )
        finally:
            self._close_client(client)

    def _open_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return PymavlinkMissionClient(
            self._connection_url,
            heartbeat_timeout_s=self._heartbeat_timeout_s,
            request_timeout_s=self._request_timeout_s,
            source_system=self._source_system,
            source_component=self._source_component,
        )

    def _close_client(self, client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def _load_mapping(self) -> dict[str, Any]:
        return _load_json_file(self._state_path)

    def _write_mapping(self, mapping: dict[str, Any]) -> None:
        self._state_path.write_text(json.dumps(mapping, indent=2) + "\n")

    def _record_verified_snapshot(self, controller_version: int, verified_snapshot: dict[str, Any]) -> None:
        mapping = self._load_mapping()
        mapping[str(controller_version)] = {
            "verified_snapshot": _snapshot_dict(verified_snapshot),
            "updated_at": time.time(),
            "connection_url": self._connection_url,
        }
        self._write_mapping(mapping)

    def _state_for_items(self, items: list[dict[str, Any]]) -> ControllerMissionAdapterState:
        controller_version = _controller_version_for_items(items)
        mapping = self._load_mapping()
        metadata = mapping.get(str(controller_version), {})
        snapshot = metadata.get("verified_snapshot") if isinstance(metadata, dict) else {}
        base = _snapshot_dict(snapshot)
        base["controller_version"] = controller_version
        base["plan"] = base.get("plan") or {"mission": {"items": items}}
        return ControllerMissionAdapterState(
            controller_version=controller_version,
            status="executing" if items else "idle",
            operation_id=str(base.get("operation_id") or ""),
            revision_id=str(base.get("revision_id") or ""),
            draft_id=str(base.get("draft_id") or ""),
            captured_at=base.get("captured_at"),
            mission_export=base.get("mission_export") if isinstance(base.get("mission_export"), dict) else {},
            mission=base.get("mission") if isinstance(base.get("mission"), dict) else {},
            plan=base.get("plan") if isinstance(base.get("plan"), dict) else {"mission": {"items": items}},
            raw_state={"downloaded_items": items, "connection_url": self._connection_url},
        )

    def _rollback_previous(self, client: Any, previous_items: list[dict[str, Any]]) -> dict[str, Any]:
        if not previous_items:
            return {"status": "cutover_failed", "state": self._state_for_items([])}
        try:
            client.upload_mission_items(previous_items)
            restored = client.download_mission_items()
        except Exception:
            return {"status": "cutover_failed", "state": self._state_for_items(previous_items)}
        if _mission_items_equivalent(previous_items, restored):
            return {"status": "rolled_back", "state": self._state_for_items(restored)}
        return {"status": "cutover_failed", "state": self._state_for_items(restored)}


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
