from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

PROVIDER_TYPES = {
    "openrouter",
    "nvidia_nim",
    "openai",
    "anthropic",
    "google_gemini",
    "ollama",
    "lm_studio",
    "mistral",
    "cohere",
    "together",
    "groq",
    "huggingface",
    "openai_compatible",
}

SECRET_REF_PREFIX = "secret://"

ROUTING_PURPOSES = {
    "general_chat": "General Chat",
    "vehicle_intent_parser": "Vehicle Intent Parser",
    "mission_planner": "Mission Planner",
    "reporter": "Reporter",
    "embeddings": "Embeddings",
    "vision_object_description": "Vision / Object Description",
}


def _sanitize_secret_ref(value: Any) -> str:
    secret_ref = str(value or "").strip()
    if "=" in secret_ref:
        secret_ref = secret_ref.split("=", 1)[0].strip()
    if not secret_ref:
        return ""
    if not (secret_ref[0].isalpha() or secret_ref[0] == "_"):
        return ""
    if any(not (char.isalnum() or char == "_") for char in secret_ref):
        return ""
    return secret_ref


def _sanitize_stored_secret_ref(value: Any) -> str:
    secret_ref = str(value or "").strip()
    if not secret_ref.startswith(SECRET_REF_PREFIX):
        return ""
    return secret_ref


def _default_provider_secret_ref(provider_id: str) -> str:
    return f"{SECRET_REF_PREFIX}provider-{provider_id}"


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bool_setting(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _normalize_context_window(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _normalize_capabilities(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value]
    else:
        items = []
    return sorted({item for item in items if item})


def _normalize_provider(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing or {}
    provider_type = str(payload.get("provider_type", current.get("provider_type", "openai_compatible"))).strip()
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=400, detail="unsupported provider_type")

    display_name = str(payload.get("display_name", current.get("display_name", ""))).strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")

    auth_mode = str(payload.get("auth_mode", current.get("auth_mode", "env_var"))).strip()
    if auth_mode not in {"env_var", "stored_secret", "none"}:
        raise HTTPException(status_code=400, detail="auth_mode must be env_var, stored_secret, or none")

    base_url = str(payload.get("base_url", current.get("base_url", ""))).strip()
    model_id = str(payload.get("model_id", current.get("model_id", ""))).strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")

    provider_id = str(current.get("id") or payload.get("id") or f"provider-{uuid.uuid4().hex[:12]}").strip()
    normalized = {
        "id": provider_id,
        "display_name": display_name,
        "provider_type": provider_type,
        "auth_mode": auth_mode,
        "secret_ref": _sanitize_secret_ref(payload.get("secret_ref", current.get("secret_ref", ""))),
        "base_url": base_url,
        "model_id": model_id,
        "capabilities": _normalize_capabilities(payload.get("capabilities", current.get("capabilities", []))),
        "enabled": bool(payload.get("enabled", current.get("enabled", True))),
        "context_window": _normalize_context_window(payload.get("context_window", current.get("context_window"))),
        "last_check": current.get("last_check") or {"status": "not_tested"},
    }
    if auth_mode == "env_var" and not normalized["secret_ref"]:
        raise HTTPException(status_code=400, detail="secret_ref is required for env_var auth")
    if auth_mode == "stored_secret":
        normalized["secret_ref"] = _sanitize_stored_secret_ref(payload.get("secret_ref", current.get("secret_ref", "")))
        if not normalized["secret_ref"]:
            normalized["secret_ref"] = _default_provider_secret_ref(provider_id)
    if auth_mode == "none":
        normalized["secret_ref"] = ""
    return normalized


def _normalize_routing(payload: dict[str, Any], providers: list[dict[str, Any]]) -> dict[str, Any]:
    provider_ids = {str(provider.get("id")) for provider in providers if isinstance(provider, dict)}
    out: dict[str, Any] = {}
    for purpose in ROUTING_PURPOSES:
        raw_rule = payload.get(purpose, {})
        if not isinstance(raw_rule, dict):
            raise HTTPException(status_code=400, detail=f"{purpose} routing rule must be an object")
        primary_id = str(raw_rule.get("primary_provider_id", "")).strip()
        fallback_ids = [str(item).strip() for item in raw_rule.get("fallback_provider_ids", []) if str(item).strip()]
        unknown = [item for item in [primary_id, *fallback_ids] if item and item not in provider_ids]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown provider ids in {purpose}: {', '.join(unknown)}")
        deduped_fallbacks: list[str] = []
        for fallback_id in fallback_ids:
            if fallback_id == primary_id or fallback_id in deduped_fallbacks:
                continue
            deduped_fallbacks.append(fallback_id)
        out[purpose] = {
            "primary_provider_id": primary_id,
            "fallback_provider_ids": deduped_fallbacks,
            "allow_runtime_override": bool(raw_rule.get("allow_runtime_override", True)),
        }
    return out


def _normalize_ai_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    tts = source.get("tts", {})
    if not isinstance(tts, dict):
        tts = {}
    engine = str(tts.get("engine", "kokoro_service") or "kokoro_service").strip()
    if engine not in {"browser", "kokoro_service"}:
        engine = "browser"
    rate = _bounded_float(tts.get("rate", 1.0), default=1.0, minimum=0.5, maximum=2.0)
    pitch = _bounded_float(tts.get("pitch", 1.0), default=1.0, minimum=0.0, maximum=2.0)
    speed = _bounded_float(tts.get("speed", 1.0), default=1.0, minimum=0.5, maximum=2.0)
    audio_format = str(tts.get("format", "wav") or "wav").strip().lower()
    if audio_format not in {"wav"}:
        audio_format = "wav"
    return {
        "tts": {
            "enabled": _bool_setting(tts.get("enabled", True), default=True),
            "engine": engine,
            "auto_read": _bool_setting(tts.get("auto_read", False), default=False),
            "service_url": str(tts.get("service_url", "http://127.0.0.1:9101") or "").strip() or "http://127.0.0.1:9101",
            "voice": str(tts.get("voice", "af_sky") or "").strip() or "af_sky",
            "format": audio_format,
            "speed": speed,
            "browser_fallback": _bool_setting(tts.get("browser_fallback", True), default=True),
            "voice_name": str(tts.get("voice_name", "") or "").strip(),
            "rate": rate,
            "pitch": pitch,
        },
        "ai_context_budget_chars": _bounded_int(
            source.get("ai_context_budget_chars", 24000),
            default=24000,
            minimum=4000,
            maximum=200000,
        ),
    }
