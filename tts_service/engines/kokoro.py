from __future__ import annotations

import io
import wave
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

DEFAULT_VOICES = [
    "af",
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
]


class KokoroEngineError(RuntimeError):
    """Raised when Kokoro cannot synthesize audio."""


class KokoroEngine:
    def __init__(self, model_path: Path, voices_path: Path) -> None:
        self.model_path = model_path
        self.voices_path = voices_path
        self._kokoro: Any | None = None
        self._lock = Lock()

    @property
    def ready(self) -> bool:
        return self.model_path.is_file() and self.voices_path.is_file()

    def status(self) -> dict[str, Any]:
        missing = []
        if not self.model_path.is_file():
            missing.append(str(self.model_path))
        if not self.voices_path.is_file():
            missing.append(str(self.voices_path))
        return {
            "engine": "kokoro-onnx",
            "ready": not missing,
            "model_path": str(self.model_path),
            "voices_path": str(self.voices_path),
            "missing_files": missing,
        }

    def voices(self) -> list[dict[str, str]]:
        return [{"id": voice, "name": voice} for voice in DEFAULT_VOICES]

    def synthesize_wav(self, text: str, *, voice: str, speed: float, language: str) -> bytes:
        if not self.ready:
            missing = ", ".join(self.status()["missing_files"])
            raise KokoroEngineError(f"Kokoro model files are missing: {missing}")
        kokoro = self._load()
        try:
            samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang=language)
        except TypeError:
            samples, sample_rate = kokoro.create(text, voice=voice, speed=speed)
        except Exception as exc:  # pragma: no cover - depends on model/runtime internals
            raise KokoroEngineError(str(exc)) from exc
        return _samples_to_wav(samples, int(sample_rate))

    def _load(self) -> Any:
        with self._lock:
            if self._kokoro is None:
                try:
                    from kokoro_onnx import Kokoro
                except ImportError as exc:  # pragma: no cover - environment dependent
                    raise KokoroEngineError("kokoro-onnx is not installed") from exc
                self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
            return self._kokoro


def _samples_to_wav(samples: Any, sample_rate: int) -> bytes:
    audio = np.asarray(samples)
    if audio.ndim > 1:
        audio = audio.reshape(-1)
    if audio.dtype.kind == "f":
        audio = np.clip(audio, -1.0, 1.0)
        audio = (audio * 32767.0).astype(np.int16)
    elif audio.dtype != np.int16:
        audio = audio.astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())
    return buffer.getvalue()
