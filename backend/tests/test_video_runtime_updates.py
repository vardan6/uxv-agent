from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from backend.config import AppConfig
from backend.routers import device_config, settings
from backend.tests.runtime_stub import make_stub_runtime


class FakeStateStore:
    def __init__(self) -> None:
        self.modes: dict[str, Any] | None = None
        self.broker_snapshot = {
            "status": "connected",
            "connected": True,
            "last_telemetry_ts": 1.0,
            "last_camera_ts": 1.0,
            "telemetry_stale": False,
            "camera_stale": False,
        }

    async def set_video_modes(self, enabled: bool, ingest_mode: str, delivery_mode: str) -> dict[str, Any]:
        self.modes = {
            "enabled": enabled,
            "ingest_mode": ingest_mode,
            "delivery_mode": delivery_mode,
        }
        return dict(self.modes)

    async def snapshot(self) -> dict[str, Any]:
        return {
            "broker": dict(self.broker_snapshot),
        }


class FakeWebSocketManager:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


class FakeRequest:
    def __init__(self, runtime: object, payload: dict[str, Any]) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _config() -> AppConfig:
    return AppConfig(
        raw={
            "mqtt": {},
            "simulation": {},
            "video": {
                "enabled": True,
                "ingest_mode": "mqtt_frames",
                "delivery_mode": "websocket_mjpeg",
            },
            "osd_presets": [
                {
                    "id": "default",
                    "name": "Default Overlay",
                    "lines": ["position", "speed_heading"],
                    "corner": "top-right",
                    "opacity": 0.92,
                    "compact": False,
                }
            ],
            "logging": {},
            "gcs": {},
            "key_bindings": {},
            "map": {},
        },
        settings_path=Path("test.json"),
    )


def _runtime() -> SimpleNamespace:
    return make_stub_runtime(
        config=_config(),
        state_store=FakeStateStore(),
        ws_manager=FakeWebSocketManager(),
        reconfigure_mqtt=_async_noop,
    )


async def _async_noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def test_video_mode_route_broadcasts_runtime_video_update(monkeypatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(device_config, "save_config", lambda _config: None)

    async def run() -> None:
        await device_config.set_video_mode(
            FakeRequest(
                runtime,
                {
                    "enabled": False,
                    "ingest_mode": "off",
                    "delivery_mode": "disabled",
                },
            )
        )

    asyncio.run(run())

    assert runtime.state_store.modes == {
        "enabled": False,
        "ingest_mode": "off",
        "delivery_mode": "disabled",
    }
    assert runtime.ws_manager.messages == [
        {
            "type": "video",
            "data": {
                "enabled": False,
                "ingest_mode": "off",
                "delivery_mode": "disabled",
            },
        }
    ]


def test_simulation_config_route_rejects_unsupported_backend() -> None:
    runtime = _runtime()

    async def run() -> None:
        with pytest.raises(HTTPException, match="only '3d-env' is supported") as exc_info:
            await device_config.set_simulation_config(
                FakeRequest(runtime, {"simulation": {"backend": "unsupported-backend"}})
            )
        assert exc_info.value.status_code == 400

    asyncio.run(run())


def test_settings_apply_rejects_unsupported_simulation_backend() -> None:
    config = _config()

    with pytest.raises(HTTPException, match="only '3d-env' is supported") as exc_info:
        settings._apply_settings_sections(
            config,
            {"simulation": {"backend": "unsupported-backend"}},
            ["simulation"],
        )

    assert exc_info.value.status_code == 400
    assert config.raw["simulation"] == {}


def test_settings_apply_video_section_broadcasts_runtime_video_update(monkeypatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(settings, "save_config", lambda _config: None)

    async def run() -> None:
        await settings.apply_settings_sections(
            FakeRequest(
                runtime,
                {
                    "sections": ["video"],
                    "settings": {
                        "video": {
                            "enabled": False,
                            "ingest_mode": "file",
                            "delivery_mode": "disabled",
                        },
                    },
                },
            )
        )

    asyncio.run(run())

    assert runtime.state_store.modes == {
        "enabled": False,
        "ingest_mode": "file",
        "delivery_mode": "disabled",
    }
    assert runtime.ws_manager.messages == [
        {
            "type": "video",
            "data": {
                "enabled": False,
                "ingest_mode": "file",
                "delivery_mode": "disabled",
            },
        }
    ]


def test_video_osd_presets_route_broadcasts_shared_catalog_update(monkeypatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(settings, "save_config", lambda _config: None)

    async def run() -> None:
        await settings.put_video_osd_presets(
            FakeRequest(
                runtime,
                {
                    "osd_presets": [
                        {
                            "id": "pilot",
                            "name": "Pilot Overlay",
                            "lines": ["position", "gps", "camera"],
                            "corner": "bottom-left",
                            "opacity": 0.75,
                            "compact": True,
                        }
                    ],
                },
            )
        )

    asyncio.run(run())

    assert runtime.config.raw["osd_presets"] == [
        {
            "id": "pilot",
            "name": "Pilot Overlay",
            "lines": ["position", "gps", "camera"],
            "corner": "bottom-left",
            "opacity": 0.75,
            "compact": True,
        }
    ]
    assert runtime.ws_manager.messages == [
        {
            "type": "video_osd_presets",
            "data": runtime.config.raw["osd_presets"],
        }
    ]


def test_settings_apply_osd_presets_section_broadcasts_shared_catalog_update(monkeypatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(settings, "save_config", lambda _config: None)

    async def run() -> None:
        await settings.apply_settings_sections(
            FakeRequest(
                runtime,
                {
                    "sections": ["osd_presets"],
                    "settings": {
                        "osd_presets": [
                            {
                                "id": "compact",
                                "name": "Compact Overlay",
                                "lines": ["speed_heading", "camera"],
                                "corner": "top-left",
                                "opacity": 0.6,
                                "compact": True,
                            }
                        ],
                    },
                },
            )
        )

    asyncio.run(run())

    assert runtime.config.raw["osd_presets"] == [
        {
            "id": "compact",
            "name": "Compact Overlay",
            "lines": ["speed_heading", "camera"],
            "corner": "top-left",
            "opacity": 0.6,
            "compact": True,
        }
    ]
    assert runtime.ws_manager.messages == [
        {
            "type": "video_osd_presets",
            "data": runtime.config.raw["osd_presets"],
        }
    ]


def test_mqtt_config_route_updates_vehicle_availability_policy(monkeypatch) -> None:
    runtime = _runtime()
    runtime.config.raw["mqtt"] = {
        "broker_host": "demo-broker",
        "broker_port": 1883,
        "topic_prefix": "/demo",
        "client_id": "gcs-web",
        "control_topic": "control/manual",
        "state_topic": "telemetry/state",
        "camera_topic": "camera-feed",
        "control_hz": 20,
        "vehicle_availability": {
            "connected_threshold_seconds": 2,
            "unavailable_threshold_seconds": 60,
            "rollover_on_reconnect": True,
        },
    }
    monkeypatch.setattr(device_config, "save_config", lambda _config: None)

    async def run() -> None:
        await device_config.set_mqtt_config(
            FakeRequest(
                runtime,
                {
                    "mqtt": {
                        "broker_host": "demo-broker",
                        "broker_port": 1884,
                        "topic_prefix": "/demo",
                        "client_id": "gcs-web",
                        "control_topic": "control/manual",
                        "state_topic": "telemetry/state",
                        "camera_topic": "camera-feed",
                        "control_hz": 10,
                        "vehicle_availability": {
                            "connected_threshold_seconds": 5,
                            "unavailable_threshold_seconds": 3,
                            "rollover_on_reconnect": False,
                        },
                    },
                },
            )
        )

    asyncio.run(run())

    assert runtime.config.raw["mqtt"]["broker_port"] == 1884
    assert runtime.config.raw["mqtt"]["control_hz"] == 10
    assert runtime.config.raw["mqtt"]["vehicle_availability"] == {
        "connected_threshold_seconds": 5,
        "unavailable_threshold_seconds": 5,
        "rollover_on_reconnect": False,
    }
    assert runtime.ws_manager.messages == [
        {
            "type": "broker",
            "data": runtime.state_store.broker_snapshot,
        }
    ]
