"""Injectable fake TTS engine for HTTP-boundary tests.

`tts_service/app.py` talks to whatever object is assigned to its module-level
`engine` name through three methods: `status()`, `voices()`, and
`synthesize_wav()`. `FakeTTSEngine` implements that surface without loading a
real Kokoro model, so tests can assert on the HTTP contract (status codes,
content-type, error mapping) without any model download or audio inference.
"""

from __future__ import annotations

import io
import wave
from typing import Any


def make_wav_bytes(*, sample_rate: int = 22050, num_samples: int = 10) -> bytes:
    """Build a minimal, structurally valid WAV file (silence) for assertions."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * num_samples)
    return buffer.getvalue()


class FakeTTSEngine:
    """Stand-in for `KokoroEngine` matching its public interface."""

    def __init__(self, *, ready: bool = True, voices: list[str] | None = None) -> None:
        self.ready = ready
        self._voices = voices if voices is not None else ["af_sky", "af_bella"]
        self.calls: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None
        self.wav_bytes = make_wav_bytes()

    def status(self) -> dict[str, Any]:
        return {
            "engine": "fake",
            "ready": self.ready,
            "model_path": "fake-model.onnx",
            "voices_path": "fake-voices.bin",
            "missing_files": [] if self.ready else ["fake-model.onnx"],
        }

    def voices(self) -> list[dict[str, str]]:
        return [{"id": voice, "name": voice} for voice in self._voices]

    def synthesize_wav(self, text: str, *, voice: str, speed: float, language: str) -> bytes:
        self.calls.append({"text": text, "voice": voice, "speed": speed, "language": language})
        if self.fail_with is not None:
            raise self.fail_with
        return self.wav_bytes
