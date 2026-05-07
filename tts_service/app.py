from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import load_config
from .engines.kokoro import KokoroEngine, KokoroEngineError

config = load_config()
engine = KokoroEngine(config.model_path, config.voices_path)
app = FastAPI(title="Remote Rover TTS Service")


class SpeechRequest(BaseModel):
    input: str = Field(..., min_length=1)
    voice: str | None = None
    format: Literal["wav"] = "wav"
    speed: float = Field(1.0, ge=0.5, le=2.0)
    language: str | None = None


@app.get("/")
def root() -> dict[str, object]:
    return health()


@app.get("/health")
def health() -> dict[str, object]:
    status = engine.status()
    return {
        "ok": True,
        "service": "remote-rover-tts",
        "ready": status["ready"],
        "host": config.host,
        "port": config.port,
        "engine": status,
    }


@app.get("/voices")
def voices() -> dict[str, object]:
    return {
        "default_voice": config.default_voice,
        "voices": engine.voices(),
    }


@app.post("/v1/audio/speech")
def create_speech(payload: SpeechRequest) -> Response:
    text = payload.input.strip()
    if len(text) > config.max_text_chars:
        raise HTTPException(
            status_code=413,
            detail=f"input exceeds {config.max_text_chars} characters",
        )
    try:
        audio = engine.synthesize_wav(
            text,
            voice=(payload.voice or config.default_voice).strip() or config.default_voice,
            speed=payload.speed,
            language=(payload.language or config.default_language).strip() or config.default_language,
        )
    except KokoroEngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="speech.wav"'},
    )
