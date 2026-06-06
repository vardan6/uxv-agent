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

    def start(self) -> None:
        with self._lock:
            if not self.enabled:
                self._state = "disabled"
                self._summary = "disabled in config"
                return
            self._state = "stub"
            self._summary = (
                f"configured for {config.MAVSDK_GRPC_HOST}:{config.MAVSDK_GRPC_PORT}; "
                "service methods not implemented yet"
            )

    def stop(self) -> None:
        with self._lock:
            if self.enabled:
                self._state = "stopped"
                self._summary = "stopped before gRPC server implementation"

    def status(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "enabled": self.enabled,
                "state": self._state,
                "summary": self._summary,
                "details": {
                    "host": config.MAVSDK_GRPC_HOST,
                    "port": config.MAVSDK_GRPC_PORT,
                    "proto": config.MAVSDK_GRPC_PROTO,
                },
            }


class TransportManager:
    def __init__(self) -> None:
        self._services: list[TransportService] = [
            MavlinkUdpService(),
            MavsdkGrpcService(),
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
