from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ai.vehicle_profile import resolve_active_profile
from config import AppConfig, load_config
from routers.ai import (
    get_active_vehicle_profile,
    list_vehicle_profiles,
    set_active_vehicle_profile,
)
from tests.runtime_stub import make_stub_runtime


def _config(tmp_path: Path, profile_id: str | None = None) -> AppConfig:
    config = load_config(tmp_path / "settings.json")
    if profile_id is None:
        config.raw.pop("vehicle_profile", None)
    else:
        config.raw["vehicle_profile"] = {"active_profile_id": profile_id}
    return config


def _request(path: str, config: AppConfig | None = None, body: object = None) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(runtime=make_stub_runtime(config=config)))
    scope = {
        "type": "http",
        "method": "POST" if body is not None else "GET",
        "path": path,
        "headers": [],
        "app": app,
    }
    if body is None:
        return Request(scope)

    payload = json.dumps(body).encode()
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(scope, receive)


def test_default_settings_select_rover_default(tmp_path: Path) -> None:
    config = load_config(tmp_path / "settings.json")

    assert config.vehicle_profile["active_profile_id"] == "rover_default"
    assert resolve_active_profile(config).id == "rover_default"


def test_resolve_active_profile_reads_the_persisted_selection(tmp_path: Path) -> None:
    assert resolve_active_profile(_config(tmp_path, "quad_x500")).id == "quad_x500"


@pytest.mark.parametrize("stored", [None, "no_such_profile", ""])
def test_resolve_active_profile_falls_back_on_missing_or_unknown(
    tmp_path: Path, stored: str | None
) -> None:
    assert resolve_active_profile(_config(tmp_path, stored)).id == "rover_default"


def test_get_active_vehicle_profile_returns_the_selection(tmp_path: Path) -> None:
    config = _config(tmp_path, "fixed_wing_default")
    response = asyncio.run(
        get_active_vehicle_profile(_request("/api/vehicle-profile/active", config))
    )
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert payload["profile"]["id"] == "fixed_wing_default"
    assert payload["profile"]["kind"] == "fixed_wing"


def test_set_active_vehicle_profile_persists_the_selection(tmp_path: Path) -> None:
    config = _config(tmp_path, "rover_default")
    response = asyncio.run(
        set_active_vehicle_profile(
            _request("/api/vehicle-profile/active", config, {"profile_id": "quad_x500"})
        )
    )
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert payload["profile"]["id"] == "quad_x500"
    assert resolve_active_profile(config).id == "quad_x500"
    # Survives a restart: the selection is on disk, not just in memory.
    assert load_config(config.settings_path).vehicle_profile["active_profile_id"] == "quad_x500"


@pytest.mark.parametrize("body", [{}, {"profile_id": ""}, {"profile_id": "no_such_profile"}])
def test_set_active_vehicle_profile_rejects_bad_ids(tmp_path: Path, body: dict) -> None:
    config = _config(tmp_path, "rover_default")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            set_active_vehicle_profile(_request("/api/vehicle-profile/active", config, body))
        )

    assert excinfo.value.status_code == 400
    # A rejected write leaves the previous selection untouched.
    assert resolve_active_profile(config).id == "rover_default"
    assert not config.settings_path.exists()


def test_list_vehicle_profiles_returns_known_profiles(tmp_path: Path) -> None:
    response = asyncio.run(
        list_vehicle_profiles(_request("/api/vehicle-profiles", _config(tmp_path)))
    )
    payload = json.loads(response.body)
    profile_ids = [profile["id"] for profile in payload["profiles"]]

    assert payload["ok"] is True
    assert profile_ids == ["rover_default", "quad_x500", "fixed_wing_default"]
