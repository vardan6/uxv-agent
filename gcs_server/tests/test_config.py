from __future__ import annotations

from pathlib import Path

from config import AppConfig


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
    assert raw == {
        "mqtt": {},
        "video": {},
        "gcs": {},
        "key_bindings": {},
        "simulation": {},
        "logging": {},
        "map": {},
    }
