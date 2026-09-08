from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from backend.ai.controller_mission_adapter_factory import build_controller_mission_adapter
from backend.ai.execution_mode import normalize_mission_lifecycle_settings, resolve_build_default_mode
from backend.config import save_config
from backend.provider_normalizers import _bounded_float, _normalize_ai_settings
from backend.runtime import AppRuntime, GCS_DIR

router = APIRouter()

_VALID_ADAPTER_TYPES = frozenset({"json_file", "file_sink", "mavlink", "mavsdk"})


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _resolve_gcs_data_path(path: object) -> Path:
    data_path = Path(str(path or ""))
    if data_path.is_absolute():
        return data_path
    return GCS_DIR / data_path


def _read_controller_adapter_config(logging_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(logging_config.get("controller_mission_adapter", "json_file") or "json_file").strip().lower(),
        "mavlink_url": str(logging_config.get("controller_mission_mavlink_url") or ""),
        "mavsdk_url": str(logging_config.get("controller_mission_mavsdk_url") or ""),
        "heartbeat_timeout_s": float(logging_config.get("controller_mission_heartbeat_timeout_s", 5.0) or 5.0),
        "request_timeout_s": float(logging_config.get("controller_mission_request_timeout_s", 5.0) or 5.0),
    }


def _tts_fetch_sync(service_url: str, service_payload: dict[str, Any]) -> tuple[str, bytes]:
    request = UrlRequest(
        service_url,
        data=json.dumps(service_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return response.headers.get("Content-Type", "audio/wav"), response.read()


@router.get("/api/mission-lifecycle")
async def get_mission_lifecycle(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    config = runtime.config
    return {
        "mission_lifecycle": normalize_mission_lifecycle_settings(
            config.mission_lifecycle,
            build_default=resolve_build_default_mode(config),
        ),
        "controller_adapter": _read_controller_adapter_config(config.logging),
        "build_default_mode": resolve_build_default_mode(config),
    }


@router.post("/api/mission-lifecycle")
async def save_mission_lifecycle(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    config = runtime.config
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Mission lifecycle payload must be an object")
    settings_payload = payload.get("mission_lifecycle", payload)
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="mission_lifecycle must be an object")
    config.raw["mission_lifecycle"] = normalize_mission_lifecycle_settings(
        settings_payload,
        build_default=resolve_build_default_mode(config),
    )
    if "controller_adapter" in payload:
        adapter_payload = payload["controller_adapter"]
        if not isinstance(adapter_payload, dict):
            raise HTTPException(status_code=400, detail="controller_adapter must be an object")
        adapter_type = str(adapter_payload.get("type", "json_file") or "json_file").strip().lower()
        if adapter_type not in _VALID_ADAPTER_TYPES:
            raise HTTPException(status_code=400, detail=f"unsupported adapter type: {adapter_type}")
        logging_cfg = dict(config.raw.get("logging", {}))
        logging_cfg["controller_mission_adapter"] = adapter_type
        logging_cfg["controller_mission_mavlink_url"] = str(adapter_payload.get("mavlink_url") or "")
        logging_cfg["controller_mission_mavsdk_url"] = str(adapter_payload.get("mavsdk_url") or "")
        logging_cfg["controller_mission_heartbeat_timeout_s"] = float(adapter_payload.get("heartbeat_timeout_s") or 5.0)
        logging_cfg["controller_mission_request_timeout_s"] = float(adapter_payload.get("request_timeout_s") or 5.0)
        config.raw["logging"] = logging_cfg
        try:
            new_adapter = build_controller_mission_adapter(config.logging, path_resolver=_resolve_gcs_data_path)
            runtime.mission_execution_service.set_controller_adapter(new_adapter)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_config(config)
    return JSONResponse(
        {
            "ok": True,
            "mission_lifecycle": config.raw["mission_lifecycle"],
            "controller_adapter": _read_controller_adapter_config(config.logging),
            "build_default_mode": resolve_build_default_mode(config),
        }
    )


@router.get("/api/ai-settings")
async def get_ai_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {"ai_settings": _normalize_ai_settings(runtime.config.raw.get("ai_settings", {}))}


@router.post("/api/ai-settings")
async def save_ai_settings(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="AI settings payload must be an object")
    settings_payload = payload.get("ai_settings", payload)
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="ai_settings must be an object")
    runtime.config.raw["ai_settings"] = _normalize_ai_settings(settings_payload)
    save_config(runtime.config)
    return JSONResponse({"ok": True, "ai_settings": runtime.config.raw["ai_settings"]})


@router.post("/api/ai-tts/speech")
async def create_ai_tts_speech(request: Request) -> Response:
    runtime = _runtime(request)
    settings = _normalize_ai_settings(runtime.config.raw.get("ai_settings", {}))
    tts = settings["tts"]
    if not tts["enabled"]:
        raise HTTPException(status_code=400, detail="text to speech is disabled")
    if tts["engine"] != "kokoro_service":
        raise HTTPException(status_code=400, detail="local TTS service is not selected")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="speech payload must be an object")
    text = str(payload.get("input", payload.get("text", "")) or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="input text is required")
    if len(text) > 6000:
        raise HTTPException(status_code=413, detail="input exceeds 6000 characters")

    service_payload = {
        "input": text,
        "voice": str(payload.get("voice", tts["voice"]) or tts["voice"]),
        "format": str(payload.get("format", tts["format"]) or tts["format"]),
        "speed": _bounded_float(payload.get("speed", tts["speed"]), default=tts["speed"], minimum=0.5, maximum=2.0),
    }
    service_url = urljoin(str(tts["service_url"]).rstrip("/") + "/", "v1/audio/speech")
    loop = asyncio.get_running_loop()
    try:
        content_type, content = await loop.run_in_executor(
            None, _tts_fetch_sync, service_url, service_payload
        )
        return Response(content=content, media_type=content_type)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") or f"TTS service returned HTTP {exc.code}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"TTS service is unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="TTS service request timed out") from exc
