from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient

from fakes import FakeTTSEngine, make_wav_bytes


def test_successful_synth_returns_audio_wav_content_type(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello rover"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_successful_synth_returns_inline_wav_content_disposition(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello rover"})

    assert response.headers["content-disposition"] == 'inline; filename="speech.wav"'


def test_successful_synth_body_is_exactly_the_engines_wav_bytes(
    client: TestClient, fake_engine: FakeTTSEngine
) -> None:
    fake_engine.wav_bytes = make_wav_bytes(sample_rate=16000, num_samples=25)

    response = client.post("/v1/audio/speech", json={"input": "hello rover"})

    assert response.content == fake_engine.wav_bytes


def test_successful_synth_body_is_a_well_formed_wav_file(client: TestClient) -> None:
    response = client.post("/v1/audio/speech", json={"input": "hello rover"})

    with wave.open(io.BytesIO(response.content), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 10


def test_voice_speed_and_language_are_forwarded_to_the_engine(
    client: TestClient, fake_engine: FakeTTSEngine
) -> None:
    response = client.post(
        "/v1/audio/speech",
        json={"input": "hello rover", "voice": "bm_george", "speed": 1.5, "language": "fr-fr"},
    )

    assert response.status_code == 200
    assert fake_engine.calls == [
        {"text": "hello rover", "voice": "bm_george", "speed": 1.5, "language": "fr-fr"}
    ]


def test_blank_voice_falls_back_to_configured_default(client: TestClient, fake_engine: FakeTTSEngine) -> None:
    from tts_service import app as app_module

    response = client.post("/v1/audio/speech", json={"input": "hello rover", "voice": "   "})

    assert response.status_code == 200
    assert fake_engine.calls[0]["voice"] == app_module.config.default_voice
