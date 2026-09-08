"""TA6 — transport lifecycle and dependency degradation.

Covers `transport_manager.py`'s `TransportManager` and its three services:
lifecycle ordering (start forward, stop reverse), and that an unavailable
optional dependency (grpc/MAVSDK not installed, or misconfigured) produces
an explicit degraded status rather than crashing unrelated transports.
"""

from __future__ import annotations

import config
import transport_manager as tm


def test_transport_manager_starts_services_in_order_and_stops_in_reverse():
    order: list[str] = []

    class RecordingService:
        def __init__(self, name: str) -> None:
            self.name = name

        def start(self) -> None:
            order.append(f"start:{self.name}")

        def stop(self) -> None:
            order.append(f"stop:{self.name}")

        def status(self) -> dict:
            return {"name": self.name}

    manager = tm.TransportManager()
    manager._services = [RecordingService("a"), RecordingService("b"), RecordingService("c")]

    manager.start()
    manager.stop()

    assert order == [
        "start:a", "start:b", "start:c",
        "stop:c", "stop:b", "stop:a",
    ]


def test_snapshot_reports_status_from_every_registered_service():
    manager = tm.TransportManager()

    snapshot = manager.snapshot()

    names = {service["name"] for service in snapshot["services"]}
    assert names == {"mavlink_udp", "mavsdk_grpc", "ros2_mavros"}


def test_mavlink_udp_service_always_reports_enabled_and_running():
    service = tm.MavlinkUdpService()

    status = service.status()

    assert status["enabled"] is True
    assert status["state"] == "running"
    assert status["details"]["host"] == config.MAVLINK_HOST
    assert status["details"]["port"] == config.MAVLINK_PORT


def test_ros_bridge_service_reports_disabled_stub_regardless_of_start_stop():
    service = tm.RosBridgeService()

    service.start()
    status = service.status()
    service.stop()

    assert status["enabled"] == config.ROS2_BRIDGE_ENABLED
    assert status["state"] == "disabled"
    assert "not implemented" in status["summary"]


def test_mavsdk_grpc_service_defaults_to_disabled_and_start_is_a_no_op(monkeypatch):
    monkeypatch.setattr(config, "MAVSDK_GRPC_ENABLED", False)
    service = tm.MavsdkGrpcService()

    assert service.status()["state"] == "disabled"

    service.start()
    status = service.status()

    assert status["state"] == "disabled"
    assert status["summary"] == "disabled in config"
    assert status["enabled"] is False


def test_mavsdk_grpc_service_reports_error_when_grpc_dependency_is_unavailable(monkeypatch):
    """Dependency degradation: grpcio missing/broken must not crash the
    transport manager — it must surface as an explicit `state == "error"`."""
    monkeypatch.setattr(config, "MAVSDK_GRPC_ENABLED", True)
    service = tm.MavsdkGrpcService()

    class FailingGrpcServer:
        def __init__(self) -> None:
            self.address = "0.0.0.0:50051"
            self.error = "grpc unavailable: No module named 'grpc'"
            self.running = False

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    import grpc_service as grpc_service_module
    monkeypatch.setattr(grpc_service_module, "GrpcServer", FailingGrpcServer)

    service.start()
    status = service.status()

    assert status["state"] == "error"
    assert "grpc unavailable" in status["summary"]


def test_mavsdk_grpc_service_stop_before_start_is_safe_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "MAVSDK_GRPC_ENABLED", True)
    service = tm.MavsdkGrpcService()

    service.stop()

    status = service.status()
    assert status["state"] == "stopped"
    assert status["summary"] == "stopped before startup"
