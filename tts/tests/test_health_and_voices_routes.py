from __future__ import annotations

from fastapi.testclient import TestClient

from fakes import FakeTTSEngine


def test_health_reports_engine_ready_and_service_identity(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "remote-rover-tts"
    assert body["ready"] is True


def test_root_route_mirrors_health_route(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == client.get("/health").json()


def test_voices_route_lists_engine_voices_and_default(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    from tts_service import app as app_module

    response = client.get("/voices")

    assert response.status_code == 200
    body = response.json()
    assert body["default_voice"] == app_module.config.default_voice
    assert body["voices"] == fake_engine.voices()
