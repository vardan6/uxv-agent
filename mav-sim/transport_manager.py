from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

import config


class TransportService(Protocol):
    name: str

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def status(self) -> dict:
        ...


@dataclass
class _BaseService:
    name: str
    enabled: bool

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def status(self) -> dict:
        raise NotImplementedError


class MavlinkUdpService(_BaseService):
    def __init__(self) -> None:
        super().__init__(name="mavlink_udp", enabled=True)

    def status(self) -> dict:
        return {
            "name": self.name,
            "enabled": True,
            "state": "running",
            "summary": f"listening on udp:{config.MAVLINK_HOST}:{config.MAVLINK_PORT}",
            "details": {
                "host": config.MAVLINK_HOST,
                "port": config.MAVLINK_PORT,
                "dialect": config.MAVLINK_DIALECT,
            },
        }


class MavsdkGrpcService(_BaseService):
    def __init__(self) -> None:
        super().__init__(name="mavsdk_grpc", enabled=config.MAVSDK_GRPC_ENABLED)
        self._lock = threading.Lock()
        self._state = "disabled" if not self.enabled else "configured"
        self._summary = "disabled in config"
        self._server = None  # lazily created GrpcServer when enabled

    def start(self) -> None:
        with self._lock:
            if not self.enabled:
                self._state = "disabled"
                self._summary = "disabled in config"
                return
            from grpc_service import GrpcServer

            self._server = GrpcServer()
            self._server.start()
            self._state = "running"
            self._summary = f"gRPC server starting on {self._server.address}"

    def stop(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.stop()
                self._state = "stopped"
                self._summary = "gRPC server stopped"
            elif self.enabled:
                self._state = "stopped"
                self._summary = "stopped before startup"

    def status(self) -> dict:
        with self._lock:
            state, summary = self._state, self._summary
            if self._server is not None:
                if self._server.error is not None:
                    state = "error"
                    summary = self._server.error
                elif self._server.running:
                    state = "running"
                    summary = f"gRPC server listening on {self._server.address}"
            return {
                "name": self.name,
                "enabled": self.enabled,
                "state": state,
                "summary": summary,
                "details": {
                    "host": config.MAVSDK_GRPC_HOST,
                    "port": config.MAVSDK_GRPC_PORT,
                    "proto": config.MAVSDK_GRPC_PROTO,
                },
            }


class RosBridgeService(_BaseService):
    """ROS2 / MAVROS bridge — disabled stub.

    MAVROS is a MAVLink-to-ROS gateway, not a separate wire protocol, and pulls
    in a full ROS2 install. It is registered here only so /api/transports can
    advertise it as a planned, not-yet-implemented transport.
    """

    def __init__(self) -> None:
        super().__init__(name="ros2_mavros", enabled=config.ROS2_BRIDGE_ENABLED)

    def status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "state": "disabled",
            "summary": (
                "ROS2/MAVROS bridge not implemented; requires a ROS2 install"
            ),
            "details": {"requires": "ros2 + mavros"},
        }


class TransportManager:
    def __init__(self) -> None:
        self._services: list[TransportService] = [
            MavlinkUdpService(),
            MavsdkGrpcService(),
            RosBridgeService(),
        ]

    def start(self) -> None:
        for service in self._services:
            service.start()

    def stop(self) -> None:
        for service in reversed(self._services):
            service.stop()

    def snapshot(self) -> dict:
        services = [service.status() for service in self._services]
        return {"services": services}
