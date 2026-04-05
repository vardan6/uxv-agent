from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BrokerSnapshot:
    status: str = "disconnected"
    connected: bool = False
    last_error: str = ""
    last_event_ts: float = 0.0
    last_telemetry_ts: float = 0.0
    last_camera_ts: float = 0.0


class LocalStateBackend:
    def __init__(self, telemetry_stale_ms: int, controller_lease_ms: int):
        self._lock = asyncio.Lock()
        self._telemetry_stale_ms = telemetry_stale_ms
        self._controller_lease_ms = controller_lease_ms
        self._latest_telemetry: dict[str, Any] = {}
        self._latest_video_frame: dict[str, Any] | None = None
        self._broker = BrokerSnapshot(status="connecting", last_event_ts=time.time())
        self._video_modes = {
            "enabled": True,
            "ingest_mode": "mqtt_frames",
            "delivery_mode": "websocket_mjpeg",
        }
        self._controller = {
            "active_client_id": None,
            "lease_expires_at": 0.0,
            "last_input_ts": 0.0,
        }

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            self._expire_controller_locked()
            return {
                "telemetry": copy.deepcopy(self._latest_telemetry),
                "broker": self._broker_payload_locked(),
                "controller": copy.deepcopy(self._controller),
                "video": {
                    **copy.deepcopy(self._video_modes),
                    "latest_frame": copy.deepcopy(self._latest_video_frame),
                },
            }

    async def set_telemetry(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._latest_telemetry = copy.deepcopy(payload)
            self._broker.last_telemetry_ts = time.time()

    async def set_broker_state(self, status: str, connected: bool, error: str = "") -> None:
        async with self._lock:
            self._broker.status = status
            self._broker.connected = connected
            self._broker.last_error = error
            self._broker.last_event_ts = time.time()

    async def set_video_frame(self, frame: dict[str, Any]) -> None:
        async with self._lock:
            self._latest_video_frame = copy.deepcopy(frame)
            self._broker.last_camera_ts = time.time()

    async def get_video_modes(self) -> dict[str, Any]:
        async with self._lock:
            return copy.deepcopy(self._video_modes)

    async def set_video_modes(self, enabled: bool, ingest_mode: str, delivery_mode: str) -> dict[str, Any]:
        async with self._lock:
            self._video_modes = {
                "enabled": bool(enabled),
                "ingest_mode": ingest_mode,
                "delivery_mode": delivery_mode,
            }
            return copy.deepcopy(self._video_modes)

    async def try_claim_controller(self, client_id: str) -> bool:
        async with self._lock:
            self._expire_controller_locked()
            owner = self._controller["active_client_id"]
            if owner not in (None, client_id):
                return False
            self._controller["active_client_id"] = client_id
            self._controller["lease_expires_at"] = time.time() + (self._controller_lease_ms / 1000.0)
            self._controller["last_input_ts"] = time.time()
            return True

    async def renew_controller(self, client_id: str) -> bool:
        async with self._lock:
            self._expire_controller_locked()
            if self._controller["active_client_id"] != client_id:
                return False
            self._controller["lease_expires_at"] = time.time() + (self._controller_lease_ms / 1000.0)
            self._controller["last_input_ts"] = time.time()
            return True

    async def release_controller(self, client_id: str) -> bool:
        async with self._lock:
            if self._controller["active_client_id"] != client_id:
                return False
            self._controller = {
                "active_client_id": None,
                "lease_expires_at": 0.0,
                "last_input_ts": 0.0,
            }
            return True

    async def controller_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            self._expire_controller_locked()
            return copy.deepcopy(self._controller)

    def _expire_controller_locked(self) -> None:
        if self._controller["active_client_id"] and time.time() >= self._controller["lease_expires_at"]:
            self._controller = {
                "active_client_id": None,
                "lease_expires_at": 0.0,
                "last_input_ts": 0.0,
            }

    def _broker_payload_locked(self) -> dict[str, Any]:
        now = time.time()
        stale_after_s = self._telemetry_stale_ms / 1000.0
        telemetry_age = (now - self._broker.last_telemetry_ts) if self._broker.last_telemetry_ts else None
        camera_age = (now - self._broker.last_camera_ts) if self._broker.last_camera_ts else None
        return {
            "status": self._broker.status,
            "connected": self._broker.connected,
            "last_error": self._broker.last_error,
            "last_event_ts": self._broker.last_event_ts,
            "last_telemetry_ts": self._broker.last_telemetry_ts,
            "last_camera_ts": self._broker.last_camera_ts,
            "telemetry_stale": telemetry_age is None or telemetry_age > stale_after_s,
            "camera_stale": camera_age is None or camera_age > stale_after_s,
        }
