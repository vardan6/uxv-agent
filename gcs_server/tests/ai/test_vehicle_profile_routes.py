from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from routers.ai import get_active_vehicle_profile, list_vehicle_profiles


def _request(path: str) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_get_active_vehicle_profile_returns_rover_default() -> None:
    response = asyncio.run(get_active_vehicle_profile(_request("/api/vehicle-profile/active")))
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert payload["profile"]["id"] == "rover_default"
    assert payload["profile"]["kind"] == "ground"


def test_list_vehicle_profiles_returns_known_profiles() -> None:
    response = asyncio.run(list_vehicle_profiles(_request("/api/vehicle-profiles")))
    payload = json.loads(response.body)
    profile_ids = [profile["id"] for profile in payload["profiles"]]

    assert payload["ok"] is True
    assert profile_ids == ["rover_default", "quad_x500", "fixed_wing_default"]
