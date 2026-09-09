from __future__ import annotations

from pathlib import Path

import pytest

from config import AppConfig, normalize_simulation_config


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


def test_simulation_config_rejects_unsupported_backend() -> None:
    with pytest.raises(ValueError, match="only '3d-env' is supported"):
        normalize_simulation_config({"backend": "unsupported-backend"})
