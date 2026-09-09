from __future__ import annotations

from fastapi.testclient import TestClient

from fakes import FakeTTSEngine
from tts.engines.kokoro import KokoroEngineError


def test_engine_error_maps_to_503_with_message(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    fake_engine.fail_with = KokoroEngineError("Kokoro model files are missing: model.onnx")

    response = client.post("/v1/audio/speech", json={"input": "hello"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Kokoro model files are missing: model.onnx"}


def test_engine_error_does_not_leak_a_stack_trace(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    fake_engine.fail_with = KokoroEngineError("synthesis failed")

    response = client.post("/v1/audio/speech", json={"input": "hello"})

    body = response.text
    assert "Traceback" not in body
    assert response.status_code == 503


def test_unexpected_engine_exception_is_not_swallowed_as_a_client_error(
    client: TestClient, fake_engine: FakeTTSEngine
) -> None:
    """Characterize current behavior: only `KokoroEngineError` is caught by the
    route. Any other exception type propagates — FastAPI's TestClient
    re-raises it rather than returning a response, matching the ASGI app's
    real behavior of turning it into an unhandled-error 500 in production.
    """
    fake_engine.fail_with = RuntimeError("unexpected engine crash")

    try:
        client.post("/v1/audio/speech", json={"input": "hello"})
    except RuntimeError as exc:
        assert str(exc) == "unexpected engine crash"
    else:
        raise AssertionError("expected the unhandled RuntimeError to propagate")


def test_health_reports_engine_not_ready(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    fake_engine.ready = False

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["engine"]["ready"] is False
