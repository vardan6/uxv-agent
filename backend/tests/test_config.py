from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import AppConfig, _migrate_legacy_config_keys, load_config, normalize_simulation_config


def test_optional_config_getters_do_not_mutate_raw_when_keys_are_missing() -> None:
    raw = {
        "mqtt": {},
        "video": {},
        "gcs": {},
        "key_bindings": {},
        "simulation": {},
        "logging": {},
        "map": {},
    }
    config = AppConfig(raw=raw, settings_path=Path("test.json"))

    assert config.ai_settings == {}
    assert config.llm_providers == []
    assert config.model_routing == {}
    assert config.osd_presets == []
    assert raw == {
        "mqtt": {},
        "video": {},
        "gcs": {},
        "key_bindings": {},
        "simulation": {},
        "logging": {},
        "map": {},
    }


def test_legacy_routing_purpose_is_read_under_its_new_name(caplog: pytest.LogCaptureFixture) -> None:
    rule = {"primary_provider_id": "p1", "fallback_provider_ids": []}
    raw = {"model_routing": {"rover_intent_parser": rule}}

    with caplog.at_level("WARNING"):
        _migrate_legacy_config_keys(raw)

    assert raw["model_routing"] == {"vehicle_intent_parser": rule}
    assert "deprecated" in caplog.text


def test_legacy_routing_purpose_loses_to_the_new_name_when_both_are_set() -> None:
    old = {"primary_provider_id": "old", "fallback_provider_ids": []}
    new = {"primary_provider_id": "new", "fallback_provider_ids": []}
    raw = {"model_routing": {"rover_intent_parser": old, "vehicle_intent_parser": new}}

    _migrate_legacy_config_keys(raw)

    assert raw["model_routing"] == {"vehicle_intent_parser": new}


def test_legacy_availability_policy_is_read_under_its_new_name() -> None:
    policy = {"connected_threshold_seconds": 5, "unavailable_threshold_seconds": 30}
    raw = {"mqtt": {"host": "localhost", "rover_availability": policy}}

    _migrate_legacy_config_keys(raw)

    assert raw["mqtt"] == {"host": "localhost", "vehicle_availability": policy}


def test_operator_legacy_availability_policy_survives_the_example_defaults(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"mqtt": {"rover_availability": {"connected_threshold_seconds": 99}}}),
        encoding="utf-8",
    )

    config = load_config(settings)

    assert config.raw["mqtt"]["vehicle_availability"]["connected_threshold_seconds"] == 99
    assert "rover_availability" not in config.raw["mqtt"]


def test_config_without_the_legacy_routing_purpose_is_untouched() -> None:
    raw = {"model_routing": {"general_chat": {}}}

    _migrate_legacy_config_keys(raw)

    assert raw == {"model_routing": {"general_chat": {}}}


def test_simulation_config_rejects_unsupported_backend() -> None:
    with pytest.raises(ValueError, match="only '3d-env' is supported"):
        normalize_simulation_config({"backend": "unsupported-backend"})
