from __future__ import annotations

from fastapi.testclient import TestClient

from fakes import FakeTTSEngine


def test_missing_input_field_returns_422(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"voice": "af_sky"})

    assert response.status_code == 422


def test_empty_input_string_returns_422(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": ""})

    assert response.status_code == 422


def test_unsupported_format_returns_422(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello", "format": "mp3"})

    assert response.status_code == 422


def test_speed_below_minimum_returns_422(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello", "speed": 0.1})

    assert response.status_code == 422


def test_speed_above_maximum_returns_422(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello", "speed": 5.0})

    assert response.status_code == 422


def test_non_json_body_returns_422(client: TestClient) -> None:
    response = client.post(
        "/v1/audio/speech",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_input_over_max_text_chars_returns_413(client: TestClient) -> None:
    from tts import app as app_module

    too_long = "a" * (app_module.config.max_text_chars + 1)

    response = client.post("/v1/audio/speech", json={"input": too_long})

    assert response.status_code == 413
    assert str(app_module.config.max_text_chars) in response.json()["detail"]


def test_valid_minimal_request_is_accepted(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello rover"})

    assert response.status_code == 200
    assert fake_engine.calls == [
        {"text": "hello rover", "voice": "af_sky", "speed": 1.0, "language": "en-us"}
    ]
