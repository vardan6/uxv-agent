from __future__ import annotations

import json
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .mission_safety import (
    MISSION_TYPE_FENCE,
    MISSION_TYPE_RALLY,
    Geofence,
    parse_geofence,
)

# MAVLink command/frame values for the FENCE (type 1) and RALLY (type 2) mission
# stores. Kept here — not in mission_safety — so the safety core stays MAVLink-free
# (ADR 0023 Phase 5): mission_safety owns the projection-free geometry, this module
# owns the wire encoding.
_MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION = 5001
_MAV_CMD_NAV_RALLY_POINT = 5100
_MAV_FRAME_GLOBAL = 0


def _mission_item_int(
    *,
    seq: int,
    command: int,
    lat: float,
    lon: float,
    alt: float = 0.0,
    param1: float = 0.0,
    param2: float = 0.0,
    param3: float = 0.0,
    param4: float = 0.0,
) -> dict[str, Any]:
    """Build one MISSION_ITEM_INT in the normalized download shape (lat/lon as
    1e7 ints), the same dict the download path emits so read-back compares cleanly."""
    return {
        "seq": int(seq),
        "frame": _MAV_FRAME_GLOBAL,
        "command": int(command),
        "current": 0,
        "autocontinue": 1,
        "param1": float(param1),
        "param2": float(param2),
        "param3": float(param3),
        "param4": float(param4),
        "x": int(round(float(lat) * 1e7)),
        "y": int(round(float(lon) * 1e7)),
        "z": float(alt),
    }


def _geofence_upload_items(geofence: Geofence) -> dict[int, list[dict[str, Any]]]:
    """Encode an inclusion fence + rally points as per-``mission_type`` item lists.

    Each polygon vertex becomes a FENCE_POLYGON_VERTEX_INCLUSION item carrying the
    total vertex count in ``param1`` (ArduPilot/PX4 use it to delimit the polygon);
    each rally point becomes a RALLY_POINT item. Empty lists are returned for a
    store with nothing to upload so the caller can skip untouched mission types.
    """
    vertex_count = len(geofence.polygon)
    fence_items = [
        _mission_item_int(
            seq=seq,
            command=_MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION,
            param1=float(vertex_count),
            lat=vertex.lat,
            lon=vertex.lon,
        )
        for seq, vertex in enumerate(geofence.polygon)
    ]
    rally_items = [
        _mission_item_int(
            seq=seq,
            command=_MAV_CMD_NAV_RALLY_POINT,
            lat=rally.lat,
            lon=rally.lon,
            alt=rally.alt,
        )
        for seq, rally in enumerate(geofence.rally_points)
    ]
    return {MISSION_TYPE_FENCE: fence_items, MISSION_TYPE_RALLY: rally_items}


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


@dataclass(slots=True)
class ControllerLinkHealth:
    """Liveness probe for a controller link (heartbeat + mission readability)."""

    ok: bool
    adapter: str
    connected: bool
    detail: str = ""
    controller_version: int = 0
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "adapter": self.adapter,
            "connected": bool(self.connected),
            "detail": self.detail,
            "controller_version": int(self.controller_version),
            "error": self.error,
            "raw": dict(self.raw),
        }


class ControllerMissionAdapter(Protocol):
    adapter_name: str

    def get_controller_state(self) -> ControllerMissionAdapterState:
        ...

    def check_health(self) -> ControllerLinkHealth:
        ...

    def install_mission(
        self,
        *,
        pending_snapshot: dict[str, Any],
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        ...

    def clear_mission(
        self,
        *,
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        ...

    def upload_geofence(
        self,
        *,
        geofence: dict[str, Any],
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
    # Canonical JSON so NaN params (e.g. unspecified yaw) compare equal rather
    # than tripping float('nan') != float('nan').
    if _snapshots_equivalent({"items": clean_expected}, {"items": clean_observed}):
        return True
    # ArduPilot may expose a leading home item on read-back; accept that shape.
    if len(clean_observed) == len(clean_expected) + 1 and _snapshots_equivalent(
        {"items": clean_expected}, {"items": clean_observed[1:]}
    ):
        return True
    return False


def _snapshots_equivalent(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Compare two snapshots by canonical JSON rather than dict equality.

    Mission plans legitimately carry ``NaN`` floats (e.g. an unspecified
    waypoint yaw on a ground rover), and ``float('nan') != float('nan')`` makes
    a plain ``==`` reject an otherwise-identical read-back. Serializing both
    sides to sorted JSON folds ``NaN`` to the same token, so the comparison
    reflects the mission content, not float identity.
    """
    dumped_expected = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    dumped_observed = json.dumps(observed, sort_keys=True, separators=(",", ":"))
    return dumped_expected == dumped_observed


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

    def download_mission_items(self, *, mission_type: int = 0) -> list[dict[str, Any]]:
        self._connection.mav.mission_request_list_send(
            self._connection.target_system,
            self._connection.target_component,
            int(mission_type),
        )
        count_msg = self._recv(["MISSION_COUNT"])
        count = int(getattr(count_msg, "count", 0) or 0)
        items: list[dict[str, Any]] = []
        for seq in range(count):
            self._connection.mav.mission_request_int_send(
                self._connection.target_system,
                self._connection.target_component,
                seq,
                int(mission_type),
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
            int(mission_type),
        )
        return items

    def upload_mission_items(self, items: list[dict[str, Any]], *, mission_type: int = 0) -> None:
        self._connection.mav.mission_count_send(
            self._connection.target_system,
            self._connection.target_component,
            len(items),
            int(mission_type),
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
                int(mission_type),
            )
        ack_msg = self._recv(["MISSION_ACK"])
        ack_type = int(getattr(ack_msg, "type", self._mavutil.mavlink.MAV_MISSION_ACCEPTED))
        if ack_type != self._mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise ControllerMissionAdapterError(f"mission upload rejected with MAV_MISSION type={ack_type}")

    def clear_mission_items(self, *, mission_type: int = 0) -> None:
        self._connection.mav.mission_clear_all_send(
            self._connection.target_system,
            self._connection.target_component,
            int(mission_type),
        )
        ack_msg = self._recv(["MISSION_ACK"])
        ack_type = int(getattr(ack_msg, "type", self._mavutil.mavlink.MAV_MISSION_ACCEPTED))
        if ack_type != self._mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise ControllerMissionAdapterError(f"mission clear rejected with MAV_MISSION type={ack_type}")


class MavsdkMissionClient:
    """MAVSDK ``MissionRaw`` transport with the same sync surface as
    :class:`PymavlinkMissionClient`.

    MAVSDK is asyncio-native; this client owns a private event loop and drives
    each coroutine to completion synchronously so the adapter logic stays
    transport-agnostic. ``MissionRaw`` exchanges the same ``MISSION_ITEM_INT``
    field set the pymavlink client already normalises, so the dict shape is
    identical on both backends.
    """

    def __init__(
        self,
        connection_url: str,
        *,
        heartbeat_timeout_s: float = 5.0,
        request_timeout_s: float = 5.0,
        **_ignored: Any,
    ) -> None:
        try:
            import asyncio

            from mavsdk import System
            from mavsdk.mission_raw import MissionItem
        except ImportError as exc:
            raise ControllerMissionAdapterError(
                "mavsdk is not installed; install gcs_server/requirements-gcs.txt"
            ) from exc
        self._asyncio = asyncio
        self._mission_item_cls = MissionItem
        self._request_timeout_s = float(request_timeout_s)
        self._loop = asyncio.new_event_loop()
        self._system = System()
        self._run(self._connect(connection_url, float(heartbeat_timeout_s)))

    def _run(self, coro: Any) -> Any:
        return self._loop.run_until_complete(coro)

    async def _connect(self, connection_url: str, timeout_s: float) -> None:
        await self._system.connect(system_address=connection_url)

        async def _await_connected() -> bool:
            async for state in self._system.core.connection_state():
                if state.is_connected:
                    return True
            return False

        try:
            connected = await self._asyncio.wait_for(_await_connected(), timeout=timeout_s)
        except self._asyncio.TimeoutError as exc:
            raise ControllerMissionAdapterError("timed out waiting for MAVSDK connection") from exc
        if not connected:
            raise ControllerMissionAdapterError("MAVSDK connection closed before becoming ready")

    def close(self) -> None:
        try:
            self._loop.close()
        except Exception:
            pass

    def download_mission_items(self, *, mission_type: int = 0) -> list[dict[str, Any]]:
        if int(mission_type) != 0:
            # MAVSDK's MissionRaw plugin uploads FENCE/RALLY but exposes no
            # read-back for them; signal "unverifiable" so the adapter trusts the
            # upload rather than failing verification (FC stays authoritative).
            raise ControllerMissionAdapterError(
                f"MAVSDK MissionRaw cannot read back mission_type={mission_type} for verification"
            )
        raw_items = self._run(self._system.mission_raw.download_mission())
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_items or []):
            items.append({
                "seq": int(getattr(raw, "seq", index) or index),
                "frame": int(getattr(raw, "frame", 0) or 0),
                "command": int(getattr(raw, "command", 0) or 0),
                "current": int(getattr(raw, "current", 0) or 0),
                "autocontinue": int(getattr(raw, "autocontinue", 1) or 0),
                "param1": float(getattr(raw, "param1", 0.0) or 0.0),
                "param2": float(getattr(raw, "param2", 0.0) or 0.0),
                "param3": float(getattr(raw, "param3", 0.0) or 0.0),
                "param4": float(getattr(raw, "param4", 0.0) or 0.0),
                "x": int(getattr(raw, "x", 0) or 0),
                "y": int(getattr(raw, "y", 0) or 0),
                "z": float(getattr(raw, "z", 0.0) or 0.0),
            })
        return items

    def upload_mission_items(self, items: list[dict[str, Any]], *, mission_type: int = 0) -> None:
        mission_items = [
            self._mission_item_cls(
                int(item["seq"]),
                int(item["frame"]),
                int(item["command"]),
                int(item["current"]),
                int(item["autocontinue"]),
                float(item["param1"]),
                float(item["param2"]),
                float(item["param3"]),
                float(item["param4"]),
                int(item["x"]),
                int(item["y"]),
                float(item["z"]),
                int(mission_type),
            )
            for item in items
        ]
        if int(mission_type) == MISSION_TYPE_FENCE:
            self._run(self._system.mission_raw.upload_geofence(mission_items))
        elif int(mission_type) == MISSION_TYPE_RALLY:
            self._run(self._system.mission_raw.upload_rally_points(mission_items))
        else:
            self._run(self._system.mission_raw.upload_mission(mission_items))

    def clear_mission_items(self, *, mission_type: int = 0) -> None:
        # Honor mission_type so a FENCE/RALLY clear hits the typed store, not the
        # main mission. MAVSDK MissionRaw has no clear_geofence/clear_rally; the
        # MAVLink-standard typed clear is an empty upload of that type. Mirrors
        # upload_mission_items' branching and the pymavlink client's
        # mission_clear_all(mission_type).
        if int(mission_type) == MISSION_TYPE_FENCE:
            self._run(self._system.mission_raw.upload_geofence([]))
        elif int(mission_type) == MISSION_TYPE_RALLY:
            self._run(self._system.mission_raw.upload_rally_points([]))
        else:
            self._run(self._system.mission_raw.clear_mission())


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

    def check_health(self) -> ControllerLinkHealth:
        try:
            client = self._open_client()
        except Exception as exc:
            return ControllerLinkHealth(
                ok=False,
                adapter=self.adapter_name,
                connected=False,
                detail="failed to establish controller link",
                error=str(exc),
                raw={"connection_url": self._connection_url},
            )
        try:
            downloaded = client.download_mission_items()
        except Exception as exc:
            return ControllerLinkHealth(
                ok=False,
                adapter=self.adapter_name,
                connected=True,
                detail="link up but mission read failed",
                error=str(exc),
                raw={"connection_url": self._connection_url},
            )
        finally:
            self._close_client(client)
        return ControllerLinkHealth(
            ok=True,
            adapter=self.adapter_name,
            connected=True,
            detail="heartbeat ok; mission readable",
            controller_version=_controller_version_for_items(downloaded),
            raw={"connection_url": self._connection_url, "item_count": len(downloaded)},
        )

    def clear_mission(
        self,
        *,
        expected_controller_version: int | None = None,
    ) -> ControllerMissionInstallResult:
        client = self._open_client()
        try:
            previous_items = client.download_mission_items()
            observed_version = _controller_version_for_items(previous_items)
            if expected_controller_version is not None and observed_version != int(expected_controller_version):
                return ControllerMissionInstallResult(
                    ok=False,
                    status="stale_controller_version",
                    controller_state=self._state_for_items(previous_items),
                    error="expected controller mission version does not match the live controller state",
                    raw_result={
                        "expected_controller_version": int(expected_controller_version),
                        "observed_controller_version": observed_version,
                    },
                )

            try:
                client.clear_mission_items()
                downloaded_after = client.download_mission_items()
            except Exception as exc:
                rollback_result = self._rollback_previous(client, previous_items)
                return ControllerMissionInstallResult(
                    ok=False,
                    status=rollback_result["status"],
                    controller_state=rollback_result["state"],
                    error=str(exc),
                    raw_result={"stage": "clear", "rollback": rollback_result["status"]},
                )

            if downloaded_after:
                rollback_result = self._rollback_previous(client, previous_items)
                return ControllerMissionInstallResult(
                    ok=False,
                    status=rollback_result["status"],
                    controller_state=rollback_result["state"],
                    error="controller mission still present after clear",
                    raw_result={"stage": "verify", "rollback": rollback_result["status"]},
                )

            state = ControllerMissionAdapterState(
                controller_version=0,
                status="idle",
                raw_state={"downloaded_items": [], "connection_url": self._connection_url},
            )
            return ControllerMissionInstallResult(
                ok=True,
                status="cleared",
                controller_state=state,
                raw_result={"verified": True},
            )
        finally:
            self._close_client(client)

    def upload_geofence(
        self,
        *,
        geofence: dict[str, Any],
    ) -> ControllerMissionInstallResult:
        """Upload the inclusion FENCE (type 1) and RALLY (type 2) stores to the FC.

        Defense-in-depth (ADR 0023 Phase 5): the executor already refuses a
        breaching mission *early*; this makes the FC authoritative by uploading
        the same fence so the firmware enforces it independently. Each mission
        type is uploaded separately and verified by read-back where the transport
        supports it; a transport that cannot read fence/rally back (MAVSDK) is
        trusted on the upload ack. A non-usable fence (< 3 vertices) is refused
        fail-closed.

        **Store scoping = persistent site config (decided 2026-06-01).** A mission
        type with nothing to upload is intentionally left untouched — we do NOT
        clear stale FENCE/RALLY stores on an empty upload. The FC's fence/rally is
        treated as a site-wide safety boundary that persists across Missions, so a
        fenceless Mission inherits whatever fence is already loaded. This is a
        deliberate choice, not an oversight. Revisit when a first-class "scene"
        concept lands (choose the scene a fence is authored on / applies to): at
        that point fences become scene-scoped and an empty upload for the active
        scene should clear its stores."""
        fence = parse_geofence(geofence)
        if not fence.is_usable:
            return ControllerMissionInstallResult(
                ok=False,
                status="geofence_unusable",
                controller_state=self.get_controller_state(),
                error="inclusion fence has fewer than three vertices; refusing to upload",
            )
        by_type = _geofence_upload_items(fence)
        client = self._open_client()
        try:
            uploaded: dict[str, int] = {}
            for mission_type, items in by_type.items():
                if not items:
                    continue
                client.upload_mission_items(items, mission_type=mission_type)
                try:
                    downloaded = client.download_mission_items(mission_type=mission_type)
                except ControllerMissionAdapterError:
                    downloaded = None  # transport cannot read this store back
                if downloaded is not None and not _mission_items_equivalent(items, downloaded):
                    return ControllerMissionInstallResult(
                        ok=False,
                        status="geofence_verify_failed",
                        controller_state=self.get_controller_state(),
                        error=f"geofence read-back verification failed for mission_type={mission_type}",
                        raw_result={"mission_type": int(mission_type)},
                    )
                uploaded[str(mission_type)] = len(items)
        except Exception as exc:
            return ControllerMissionInstallResult(
                ok=False,
                status="geofence_upload_failed",
                controller_state=self.get_controller_state(),
                error=str(exc),
                raw_result={"stage": "geofence_upload"},
            )
        finally:
            self._close_client(client)
        return ControllerMissionInstallResult(
            ok=True,
            status="geofence_installed",
            controller_state=self.get_controller_state(),
            raw_result={"uploaded": uploaded},
        )

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


class MavsdkControllerMissionAdapter(MavlinkControllerMissionAdapter):
    """MAVSDK-backed controller link.

    Reuses the transport-agnostic install/verify/rollback/state machinery from
    :class:`MavlinkControllerMissionAdapter` and only swaps the transport client
    for :class:`MavsdkMissionClient`.
    """

    adapter_name = "mavsdk_controller"

    def _open_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return MavsdkMissionClient(
            self._connection_url,
            heartbeat_timeout_s=self._heartbeat_timeout_s,
            request_timeout_s=self._request_timeout_s,
        )


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

    def check_health(self) -> ControllerLinkHealth:
        state = self.get_controller_state()
        return ControllerLinkHealth(
            ok=True,
            adapter=self.adapter_name,
            connected=True,
            detail="local json-file controller stand-in",
            controller_version=int(state.controller_version),
            raw={"state_path": str(self._state_path)},
        )

    def clear_mission(
        self,
        *,
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
        try:
            self._write_record({
                "controller_version": 0,
                "status": "idle",
                "verified_snapshot": {},
                "operation_id": "",
                "revision_id": "",
                "draft_id": "",
                "updated_at": time.time(),
            })
            cleared_state = self.get_controller_state()
        except Exception as exc:
            return ControllerMissionInstallResult(
                ok=False,
                status="cutover_failed",
                controller_state=current_state,
                error=str(exc),
                raw_result={"stage": "clear"},
            )
        return ControllerMissionInstallResult(
            ok=True,
            status="cleared",
            controller_state=cleared_state,
            raw_result={"verified": True},
        )

    def upload_geofence(
        self,
        *,
        geofence: dict[str, Any],
    ) -> ControllerMissionInstallResult:
        """Persist the inclusion fence + rally points alongside the local mission
        record so the stand-in mirrors a controller that owns a FENCE/RALLY store.
        Refuses a non-usable fence (< 3 vertices) fail-closed, like the real link."""
        fence = parse_geofence(geofence)
        if not fence.is_usable:
            return ControllerMissionInstallResult(
                ok=False,
                status="geofence_unusable",
                controller_state=self.get_controller_state(),
                error="inclusion fence has fewer than three vertices; refusing to upload",
            )
        record = self._load_record()
        record["geofence"] = fence.to_dict()
        record["geofence_updated_at"] = time.time()
        try:
            self._write_record(record)
        except Exception as exc:
            return ControllerMissionInstallResult(
                ok=False,
                status="geofence_upload_failed",
                controller_state=self.get_controller_state(),
                error=str(exc),
                raw_result={"stage": "geofence_upload"},
            )
        return ControllerMissionInstallResult(
            ok=True,
            status="geofence_installed",
            controller_state=self.get_controller_state(),
            raw_result={"uploaded": {
                str(MISSION_TYPE_FENCE): len(fence.polygon),
                str(MISSION_TYPE_RALLY): len(fence.rally_points),
            }},
        )

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
            and _snapshots_equivalent(expected_snapshot, verified_state.to_snapshot())
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
