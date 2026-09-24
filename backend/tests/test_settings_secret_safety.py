"""TA7 — settings/secret safety boundary (audit item 2).

Covers the operator-facing settings surface directly against
`backend/routers/settings.py`'s module functions: secret redaction on
export, allow-listed section selection, path-escape rejection for the
load/save-to-path flow, and all-or-nothing application of a settings patch
when one section is malformed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from config import AppConfig
from routers.settings import (
    _apply_settings_sections,
    _provider_export,
    _resolve_backend_config_path,
    _selected_sections,
)


def _make_config(**raw_overrides) -> AppConfig:
    raw = {
        "mqtt": {"host": "localhost"},
        "simulation": {"backend": "3d-env"},
        "video": {"enabled": True},
        "osd_presets": [],
        "appearance": {},
        "mission_lifecycle": {},
        "ai_settings": {},
        "llm_providers": [],
        "model_routing": {},
    }
    raw.update(raw_overrides)
    return AppConfig(raw=raw, settings_path=Path("unused-settings.json"))


def test_provider_export_redacts_secret_value_and_never_reports_has_secret() -> None:
    provider = {
        "id": "openai-1",
        "auth_mode": "stored_secret",
        "secret_ref": "secret://provider-openai-1",
        "secret_value": "sk-super-secret",
        "last_check": {"ok": True},
    }

    exported = _provider_export(provider)

    assert exported["secret_ref"] == "secret://provider-openai-1"
    assert "secret_value" not in exported
    assert "last_check" not in exported
    assert exported["has_secret"] is False


def test_provider_export_drops_malformed_stored_secret_ref() -> None:
    provider = {
        "id": "openai-1",
        "auth_mode": "stored_secret",
        "secret_ref": "not-a-secret-uri",
    }

    exported = _provider_export(provider)

    assert exported["secret_ref"] == ""
    assert exported["has_secret"] is False


def test_selected_sections_rejects_non_list_payload() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _selected_sections({"sections": "mqtt"})
    assert exc_info.value.status_code == 400


def test_selected_sections_filters_unknown_and_dedups() -> None:
    sections = _selected_sections(
        {"sections": ["mqtt", "mqtt", "not_a_real_section", "video"]}
    )
    assert sections == ["mqtt", "video"]


def test_selected_sections_requires_at_least_one_valid_section() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _selected_sections({"sections": ["not_a_real_section"]})
    assert exc_info.value.status_code == 400


def test_resolve_backend_config_path_rejects_path_escaping_the_config_dir() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_backend_config_path("../../etc/passwd")
    assert exc_info.value.status_code == 400
    assert "config directory" in exc_info.value.detail


def test_resolve_backend_config_path_rejects_empty_path() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_backend_config_path("   ")
    assert exc_info.value.status_code == 400


def test_resolve_backend_config_path_accepts_relative_path_inside_config_dir() -> None:
    resolved = _resolve_backend_config_path("common.local.json")
    assert resolved.name == "common.local.json"
    assert resolved.parent.name == "config"


def test_apply_settings_sections_updates_only_selected_sections() -> None:
    config = _make_config()
    applied = _apply_settings_sections(
        config,
        {"mqtt": {"host": "10.0.0.5"}, "video": {"enabled": False}},
        ["mqtt"],
    )
    assert applied == ["mqtt"]
    assert config.raw["mqtt"] == {"host": "10.0.0.5"}
    # video was not in the selected sections, so it must be untouched.
    assert config.raw["video"] == {"enabled": True}


def test_apply_settings_sections_rolls_back_all_changes_on_malformed_section() -> None:
    config = _make_config()
    original = {k: dict(v) if isinstance(v, dict) else v for k, v in config.raw.items()}

    with pytest.raises(HTTPException):
        _apply_settings_sections(
            config,
            {
                "mqtt": {"host": "10.0.0.5"},
                "simulation": {"backend": "unsupported-backend"},
            },
            ["mqtt", "simulation"],
        )

    # mqtt was applied before simulation failed; the except-clause must
    # discard that partial write rather than leaving it committed.
    assert config.raw["mqtt"] == original["mqtt"]
    assert config.raw["simulation"] == original["simulation"]
