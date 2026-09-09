from __future__ import annotations

from pathlib import Path

from config import AppConfig
from ai.controller_mission_adapter_factory import build_controller_mission_adapter


def _config(logging_overrides: dict[str, object]) -> AppConfig:
    return AppConfig(
        raw={
            "mqtt": {},
            "video": {},
            "gcs": {},
            "key_bindings": {},
            "simulation": {},
            "logging": {
                "controller_mission_state_path": "data/controller_mission_adapter.json",
                **logging_overrides,
            },
            "map": {},
        },
        settings_path=Path("test.json"),
    )


def test_build_controller_mission_adapter_defaults_to_json_file() -> None:
    adapter = build_controller_mission_adapter(_config({}).logging, path_resolver=Path)

    assert adapter.adapter_name == "json_file_controller"


def test_build_controller_mission_adapter_uses_mavlink_settings() -> None:
    adapter = build_controller_mission_adapter(
        _config({
            "controller_mission_adapter": "mavlink",
            "controller_mission_mavlink_url": "udp:127.0.0.1:14550",
            "controller_mission_heartbeat_timeout_s": 7.5,
            "controller_mission_request_timeout_s": 8.5,
            "controller_mission_source_system": 201,
            "controller_mission_source_component": 55,
        }).logging,
        path_resolver=Path,
    )

    assert adapter.adapter_name == "mavlink_controller"
    assert adapter._connection_url == "udp:127.0.0.1:14550"
    assert adapter._heartbeat_timeout_s == 7.5
    assert adapter._request_timeout_s == 8.5
    assert adapter._source_system == 201
    assert adapter._source_component == 55


def test_build_controller_mission_adapter_requires_mavlink_url() -> None:
    try:
        build_controller_mission_adapter(
            _config({"controller_mission_adapter": "mavlink"}).logging,
            path_resolver=Path,
        )
    except Exception as exc:
        assert "controller_mission_mavlink_url" in str(exc)
    else:
        raise AssertionError("expected missing MAVLink URL to fail")
