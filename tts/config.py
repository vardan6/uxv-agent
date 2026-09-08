from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
MODEL_DIR = ROOT_DIR / "models"

DEFAULT_MODEL_PATH = MODEL_DIR / "kokoro-v1.0.onnx"
DEFAULT_VOICES_PATH = MODEL_DIR / "voices-v1.0.bin"


@dataclass(frozen=True, slots=True)
class TTSConfig:
    host: str
    port: int
    model_path: Path
    voices_path: Path
    default_voice: str
    default_language: str
    max_text_chars: int

    @property
    def model_ready(self) -> bool:
        return self.model_path.is_file() and self.voices_path.is_file()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def load_config() -> TTSConfig:
    return TTSConfig(
        host=os.environ.get("REMOTE_ROVER_TTS_HOST", "127.0.0.1"),
        port=_int_env("REMOTE_ROVER_TTS_PORT", 9101),
        model_path=Path(os.environ.get("REMOTE_ROVER_TTS_MODEL", DEFAULT_MODEL_PATH)).expanduser(),
        voices_path=Path(os.environ.get("REMOTE_ROVER_TTS_VOICES", DEFAULT_VOICES_PATH)).expanduser(),
        default_voice=os.environ.get("REMOTE_ROVER_TTS_VOICE", "af_sky"),
        default_language=os.environ.get("REMOTE_ROVER_TTS_LANGUAGE", "en-us"),
        max_text_chars=_int_env("REMOTE_ROVER_TTS_MAX_TEXT_CHARS", 6000),
    )
