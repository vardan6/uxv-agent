from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

try:
    from gcs_server.config import load_config, save_config
    from gcs_server.runtime import AppRuntime, build_runtime
    from gcs_server.scene_map import get_scene_map_payload
except ModuleNotFoundError:
    from config import load_config, save_config
    from runtime import AppRuntime, build_runtime
    from scene_map import get_scene_map_payload

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

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

MODEL_CATEGORIES = {"chat", "reasoning", "planner", "reporting", "embeddings", "vision", "tool_calling"}

ROUTING_PURPOSES = {
    "general_chat": "General Chat",
    "rover_intent_parser": "Rover Intent Parser",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    runtime = await build_runtime(config)
    app.state.runtime = runtime
    await runtime.control_service.start()
    await runtime.mqtt_runtime.start()
    try:
        yield
    finally:
        if runtime.replay_store.current_session_id:
            runtime.replay_store.finish_session(runtime.replay_store.current_session_id, reason="runtime_shutdown")
        await runtime.control_service.stop()
        await runtime.mqtt_runtime.stop()


app = FastAPI(title="Remote Rover GCS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/setup/") or path.startswith("/settings") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _runtime(request_or_socket: Request | WebSocket) -> AppRuntime:
    return request_or_socket.app.state.runtime


def _connectivity_payload(config) -> dict[str, Any]:
    return {
        "mqtt": {
            "broker_host": config.mqtt.get("broker_host", ""),
            "broker_port": int(config.mqtt.get("broker_port", 1883)),
            "topic_prefix": config.mqtt.get("topic_prefix", ""),
            "client_id": config.mqtt.get("client_id", ""),
            "control_topic": config.mqtt.get("control_topic", "control/manual"),
            "state_topic": config.mqtt.get("state_topic", "telemetry/state"),
            "camera_topic": config.mqtt.get("camera_topic", "camera-feed"),
            "control_hz": int(config.mqtt.get("control_hz", 20)),
        },
        "simulation": {
            "backend": str(config.simulation.get("backend", "3d-env")) or "3d-env",
        },
    }


def _resolve_backend_config_path(path_text: str) -> Path:
    cleaned = (path_text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="path is required")

    raw_path = Path(cleaned)
    resolved = raw_path.resolve(strict=False) if raw_path.is_absolute() else (CONFIG_DIR / raw_path).resolve(strict=False)
    config_root = CONFIG_DIR.resolve(strict=False)
    try:
        resolved.relative_to(config_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path must stay inside the config directory") from exc
    return resolved


def _load_existing_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON at {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="backend config file must contain a top-level JSON object")
    return data


def _provider_public(provider: dict[str, Any]) -> dict[str, Any]:
    out = dict(provider)
    out["secret_ref"] = _sanitize_secret_ref(out.get("secret_ref", ""))
    if out.get("secret_value"):
        out["secret_value"] = "********"
    return out


def _provider_export(provider: dict[str, Any]) -> dict[str, Any]:
    out = _provider_public(provider)
    out.pop("last_check", None)
    out.pop("secret_value", None)
    return out


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
    if auth_mode not in {"env_var", "none"}:
        raise HTTPException(status_code=400, detail="auth_mode must be env_var or none")

    base_url = str(payload.get("base_url", current.get("base_url", ""))).strip()
    model_id = str(payload.get("model_id", current.get("model_id", ""))).strip()
    if provider_type != "ollama" and not model_id:
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
        "last_check": current.get("last_check") or {"status": "not_tested"},
    }
    if auth_mode == "env_var" and not normalized["secret_ref"]:
        raise HTTPException(status_code=400, detail="secret_ref is required for env_var auth")
    return normalized


def _find_provider(runtime: AppRuntime, provider_id: str) -> tuple[int, dict[str, Any]]:
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    for index, provider in enumerate(providers):
        if isinstance(provider, dict) and provider.get("id") == provider_id:
            return index, provider
    raise HTTPException(status_code=404, detail="provider not found")


def _http_json_probe(url: str, secret: str | None = None) -> tuple[bool, str]:
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = UrlRequest(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=8) as response:
            if 200 <= response.status < 300:
                return True, f"HTTP {response.status}"
            return False, f"HTTP {response.status}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, str(exc.reason)
    except TimeoutError:
        return False, "request timed out"


def _check_provider(provider: dict[str, Any]) -> dict[str, Any]:
    if provider.get("auth_mode") == "env_var":
        secret_ref = str(provider.get("secret_ref", "")).strip()
        if not secret_ref:
            return {"status": "missing_key", "ok": False, "message": "missing environment variable name"}
        secret = os.environ.get(secret_ref)
        if not secret:
            return {"status": "missing_key", "ok": False, "message": f"environment variable {secret_ref} is not set"}
    else:
        secret = None

    provider_type = str(provider.get("provider_type", ""))
    base_url = str(provider.get("base_url", "")).strip()
    if provider_type == "ollama":
        probe_url = urljoin(base_url.rstrip("/") + "/", "api/tags") if base_url else "http://localhost:11434/api/tags"
    else:
        if not base_url:
            return {"status": "invalid", "ok": False, "message": "base_url is required"}
        probe_url = urljoin(base_url.rstrip("/") + "/", "models")

    ok, message = _http_json_probe(probe_url, secret)
    return {
        "status": "available" if ok else "unavailable",
        "ok": ok,
        "message": message,
        "checked_url": probe_url,
    }


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


def _default_routing(providers: list[dict[str, Any]]) -> dict[str, Any]:
    enabled_ids = [str(provider.get("id")) for provider in providers if isinstance(provider, dict) and provider.get("enabled", True)]
    first = enabled_ids[0] if enabled_ids else ""
    return {
        purpose: {
            "primary_provider_id": first,
            "fallback_provider_ids": enabled_ids[1:3],
            "allow_runtime_override": True,
        }
        for purpose in ROUTING_PURPOSES
    }


def _selected_sections(payload: dict[str, Any]) -> list[str]:
    raw_sections = payload.get("sections", [])
    if not isinstance(raw_sections, list):
        raise HTTPException(status_code=400, detail="sections must be a list")
    allowed = {"connectivity", "video", "appearance", "llm_providers", "model_routing"}
    sections = []
    for raw_section in raw_sections:
        section = str(raw_section)
        if section in allowed and section not in sections:
            sections.append(section)
    if not sections:
        raise HTTPException(status_code=400, detail="at least one valid section is required")
    return sections


def _settings_export_payload(config, sections: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": 1}
    if "connectivity" in sections:
        out["connectivity"] = _connectivity_payload(config)
    if "video" in sections:
        out["video"] = dict(config.video)
    if "appearance" in sections:
        out["appearance"] = dict(config.raw.get("appearance", {})) if isinstance(config.raw.get("appearance"), dict) else {}
    if "llm_providers" in sections:
        providers = config.raw.get("llm_providers", [])
        out["llm_providers"] = [_provider_export(provider) for provider in providers if isinstance(provider, dict)]
    if "model_routing" in sections:
        out["model_routing"] = dict(config.raw.get("model_routing", {})) if isinstance(config.raw.get("model_routing"), dict) else {}
    return out


def _extract_section_payload(payload: dict[str, Any], section: str) -> Any:
    if section == "connectivity":
        if "connectivity" in payload and isinstance(payload["connectivity"], dict):
            return payload["connectivity"]
        if "mqtt" in payload:
            return {"mqtt": payload.get("mqtt"), "simulation": payload.get("simulation", {})}
        return None
    return payload.get(section)


def _apply_settings_sections(config, payload: dict[str, Any], sections: list[str]) -> list[str]:
    applied: list[str] = []
    if "connectivity" in sections:
        connectivity = _extract_section_payload(payload, "connectivity")
        if isinstance(connectivity, dict) and isinstance(connectivity.get("mqtt"), dict):
            config.raw["mqtt"] = dict(connectivity["mqtt"])
            simulation = connectivity.get("simulation", {})
            if isinstance(simulation, dict):
                config.raw.setdefault("simulation", {}).update(simulation)
            applied.append("connectivity")
    if "video" in sections:
        video = _extract_section_payload(payload, "video")
        if isinstance(video, dict):
            config.raw["video"] = dict(video)
            applied.append("video")
    if "appearance" in sections:
        appearance = _extract_section_payload(payload, "appearance")
        if isinstance(appearance, dict):
            config.raw["appearance"] = dict(appearance)
            applied.append("appearance")
    if "llm_providers" in sections:
        providers_payload = _extract_section_payload(payload, "llm_providers")
        if isinstance(providers_payload, list):
            config.raw["llm_providers"] = [
                _normalize_provider(provider) for provider in providers_payload if isinstance(provider, dict)
            ]
            applied.append("llm_providers")
    if "model_routing" in sections:
        routing_payload = _extract_section_payload(payload, "model_routing")
        if isinstance(routing_payload, dict):
            providers = [provider for provider in config.raw.get("llm_providers", []) if isinstance(provider, dict)]
            config.raw["model_routing"] = _normalize_routing(routing_payload, providers)
            applied.append("model_routing")
    return applied


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/settings")
async def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    snapshot = await runtime.state_store.snapshot()
    return {"ok": True, "broker": snapshot["broker"]}


@app.get("/api/snapshot")
async def snapshot(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    data = await runtime.state_store.snapshot()
    data["simulation"] = runtime.config.simulation
    return data


@app.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return runtime.config.raw


@app.get("/api/llm-providers")
async def get_llm_providers(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    return {"providers": [_provider_public(provider) for provider in providers if isinstance(provider, dict)]}


@app.post("/api/llm-providers")
async def create_llm_provider(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    providers = runtime.config.raw.setdefault("llm_providers", [])
    if not isinstance(providers, list):
        runtime.config.raw["llm_providers"] = []
        providers = runtime.config.raw["llm_providers"]
    providers.append(provider)
    save_config(runtime.config)
    return JSONResponse({"ok": True, "provider": _provider_public(provider)})


@app.put("/api/llm-providers/{provider_id}")
async def update_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    index, current = _find_provider(runtime, provider_id)
    provider = _normalize_provider(payload, current)
    provider["id"] = provider_id
    runtime.config.raw["llm_providers"][index] = provider
    save_config(runtime.config)
    return JSONResponse({"ok": True, "provider": _provider_public(provider)})


@app.post("/api/llm-providers/{provider_id}/check")
async def check_llm_provider(provider_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    index, provider = _find_provider(runtime, provider_id)
    check = _check_provider(provider)
    provider["last_check"] = check
    runtime.config.raw["llm_providers"][index] = provider
    save_config(runtime.config)
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider), "check": check})


@app.post("/api/llm-providers/check-draft")
async def check_llm_provider_draft(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="provider payload must be an object")
    provider = _normalize_provider(payload)
    check = _check_provider(provider)
    provider["last_check"] = check
    return JSONResponse({"ok": check["ok"], "provider": _provider_public(provider), "check": check})


@app.get("/api/model-routing")
async def get_model_routing(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    current = runtime.config.raw.setdefault("model_routing", {})
    if not isinstance(current, dict) or not current:
        current = _default_routing(providers)
        runtime.config.raw["model_routing"] = current
    return {"purposes": ROUTING_PURPOSES, "routing": current}


@app.put("/api/model-routing")
async def set_model_routing(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    routing_payload = payload.get("routing") if isinstance(payload, dict) else None
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="routing object is required")
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = _normalize_routing(routing_payload, providers)
    runtime.config.raw["model_routing"] = routing
    save_config(runtime.config)
    return JSONResponse({"ok": True, "purposes": ROUTING_PURPOSES, "routing": routing})


@app.get("/api/llm-settings")
async def get_llm_settings(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    providers = [provider for provider in runtime.config.raw.setdefault("llm_providers", []) if isinstance(provider, dict)]
    routing = runtime.config.raw.setdefault("model_routing", {})
    if not isinstance(routing, dict) or not routing:
        routing = _default_routing(providers)
        runtime.config.raw["model_routing"] = routing
    return {
        "providers": [_provider_public(provider) for provider in providers],
        "purposes": ROUTING_PURPOSES,
        "routing": routing,
    }


@app.put("/api/llm-settings")
async def set_llm_settings(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="settings payload must be an object")
    providers_payload = payload.get("llm_providers", payload.get("providers", []))
    if not isinstance(providers_payload, list):
        raise HTTPException(status_code=400, detail="llm_providers must be a list")
    providers = [_normalize_provider(provider) for provider in providers_payload if isinstance(provider, dict)]
    routing_payload = payload.get("model_routing", payload.get("routing", {}))
    if not isinstance(routing_payload, dict):
        raise HTTPException(status_code=400, detail="model_routing must be an object")
    runtime.config.raw["llm_providers"] = providers
    runtime.config.raw["model_routing"] = _normalize_routing(routing_payload, providers) if routing_payload else _default_routing(providers)
    save_config(runtime.config)
    return JSONResponse({
        "ok": True,
        "providers": [_provider_public(provider) for provider in providers],
        "routing": runtime.config.raw["model_routing"],
    })


@app.post("/api/settings/export")
async def export_settings_sections(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="export payload must be an object")
    sections = _selected_sections(payload)
    return JSONResponse(_settings_export_payload(runtime.config, sections))


@app.post("/api/settings/load-from-path")
async def load_settings_sections_from_path(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="load payload must be an object")
    sections = _selected_sections(payload)
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="config file not found")
    data = _load_existing_json_dict(resolved_path)
    found = [section for section in sections if _extract_section_payload(data, section) is not None]
    missing = [section for section in sections if section not in found]
    selected_payload = {"schema_version": data.get("schema_version", 1)}
    for section in found:
        selected_payload[section] = _extract_section_payload(data, section)
    return JSONResponse({
        "ok": True,
        "resolved_path": str(resolved_path),
        "found_sections": found,
        "missing_sections": missing,
        "settings": selected_payload,
    })


@app.post("/api/settings/save-to-path")
async def save_settings_sections_to_path(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="save payload must be an object")
    sections = _selected_sections(payload)
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    settings_payload = payload.get("settings")
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="settings object is required")
    existing = _load_existing_json_dict(resolved_path)
    merged = dict(existing)
    for section in sections:
        section_payload = _extract_section_payload(settings_payload, section)
        if section_payload is None:
            continue
        if section == "connectivity":
            if isinstance(section_payload, dict) and isinstance(section_payload.get("mqtt"), dict):
                merged["mqtt"] = section_payload["mqtt"]
                if isinstance(section_payload.get("simulation"), dict):
                    merged["simulation"] = section_payload["simulation"]
            merged["connectivity"] = section_payload
        else:
            merged[section] = section_payload
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
        fh.write("\n")
    return JSONResponse({"ok": True, "resolved_path": str(resolved_path), "saved_sections": sections})


@app.post("/api/settings/apply")
async def apply_settings_sections(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="apply payload must be an object")
    sections = _selected_sections(payload)
    settings_payload = payload.get("settings")
    if not isinstance(settings_payload, dict):
        raise HTTPException(status_code=400, detail="settings object is required")
    applied = _apply_settings_sections(runtime.config, settings_payload, sections)
    save_config(runtime.config)
    if "connectivity" in applied:
        await runtime.reconfigure_mqtt(runtime.config.mqtt)
    if "video" in applied:
        video = runtime.config.video
        await runtime.state_store.set_video_modes(
            bool(video.get("enabled", True)),
            str(video.get("ingest_mode", "mqtt_frames")),
            str(video.get("delivery_mode", "websocket_mjpeg")),
        )
    return JSONResponse({"ok": True, "applied_sections": applied})


@app.get("/api/simulation-config")
async def get_simulation_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "simulation": runtime.config.simulation,
        "logging": {
            "replay_db_path": str(runtime.replay_store.db_path),
            "current_session_id": runtime.replay_store.current_session_id,
        },
    }


@app.post("/api/simulation-config")
async def set_simulation_config(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    simulation_payload = payload.get("simulation")
    if not isinstance(simulation_payload, dict):
        raise HTTPException(status_code=400, detail="simulation object is required")

    current = dict(runtime.config.simulation)
    updated = {
        "backend": str(simulation_payload.get("backend", current.get("backend", "3d-env"))).strip() or "3d-env",
        "backend_version": str(simulation_payload.get("backend_version", current.get("backend_version", "dev"))).strip() or "dev",
        "available_backends": list(current.get("available_backends", ["3d-env", "rover-sim-next"])),
    }
    runtime.config.raw["simulation"] = updated
    save_config(runtime.config)
    runtime.replay_store.update_backend(updated["backend"], updated["backend_version"])
    runtime.replay_store.rollover_session(reason=f"backend_change:{updated['backend']}")
    runtime.replay_store.log_runtime_event("simulation_backend_changed", updated)
    await runtime.ws_manager.broadcast({"type": "simulation_config", "data": updated})
    return JSONResponse({"ok": True, "simulation": updated})


@app.get("/api/mqtt-config")
async def get_mqtt_config(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "mqtt": runtime.config.mqtt,
        "settings_path": str(runtime.config.settings_path),
    }


@app.post("/api/mqtt-config")
async def set_mqtt_config(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    mqtt_payload = payload.get("mqtt")
    if not isinstance(mqtt_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt object is required")

    current = dict(runtime.config.mqtt)
    updated = {
        "broker_host": str(mqtt_payload.get("broker_host", current.get("broker_host", ""))).strip(),
        "broker_port": int(mqtt_payload.get("broker_port", current.get("broker_port", 1883))),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", current.get("topic_prefix", ""))).strip(),
        "client_id": str(mqtt_payload.get("client_id", current.get("client_id", ""))).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", current.get("control_topic", "control/manual"))).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", current.get("state_topic", "telemetry/state"))).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", current.get("camera_topic", "camera-feed"))).strip(),
        "control_hz": int(mqtt_payload.get("control_hz", current.get("control_hz", 20))),
    }
    if not updated["broker_host"]:
        raise HTTPException(status_code=400, detail="broker_host is required")
    if updated["broker_port"] <= 0:
        raise HTTPException(status_code=400, detail="broker_port must be positive")
    if updated["control_hz"] <= 0:
        raise HTTPException(status_code=400, detail="control_hz must be positive")

    runtime.config.raw.setdefault("mqtt", {}).update(updated)
    save_config(runtime.config)
    await runtime.reconfigure_mqtt(runtime.config.mqtt)
    snapshot = await runtime.state_store.snapshot()
    await runtime.ws_manager.broadcast({"type": "broker", "data": snapshot["broker"]})
    return JSONResponse({
        "ok": True,
        "mqtt": runtime.config.mqtt,
        "settings_path": str(runtime.config.settings_path),
    })


@app.post("/api/connectivity/load-from-path")
async def load_connectivity_from_path(request: Request) -> JSONResponse:
    payload = await request.json()
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))
    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="config file not found")

    config = load_config(resolved_path)
    result = _connectivity_payload(config)
    result["resolved_path"] = str(resolved_path)
    return JSONResponse(result)


@app.post("/api/connectivity/save-to-path")
async def save_connectivity_to_path(request: Request) -> JSONResponse:
    payload = await request.json()
    resolved_path = _resolve_backend_config_path(str(payload.get("path", "")))

    mqtt_payload = payload.get("mqtt")
    simulation_payload = payload.get("simulation")
    if not isinstance(mqtt_payload, dict):
        raise HTTPException(status_code=400, detail="mqtt object is required")
    if simulation_payload is not None and not isinstance(simulation_payload, dict):
        raise HTTPException(status_code=400, detail="simulation must be an object")

    existing = _load_existing_json_dict(resolved_path)
    mqtt_out = dict(existing.get("mqtt", {})) if isinstance(existing.get("mqtt"), dict) else {}
    mqtt_out.update({
        "broker_host": str(mqtt_payload.get("broker_host", "")).strip(),
        "broker_port": int(mqtt_payload.get("broker_port", 1883)),
        "topic_prefix": str(mqtt_payload.get("topic_prefix", "")).strip(),
        "client_id": str(mqtt_payload.get("client_id", "")).strip(),
        "control_topic": str(mqtt_payload.get("control_topic", "control/manual")).strip(),
        "state_topic": str(mqtt_payload.get("state_topic", "telemetry/state")).strip(),
        "camera_topic": str(mqtt_payload.get("camera_topic", "camera-feed")).strip(),
        "control_hz": int(mqtt_payload.get("control_hz", 20)),
    })
    existing["mqtt"] = mqtt_out

    simulation_out = dict(existing.get("simulation", {})) if isinstance(existing.get("simulation"), dict) else {}
    simulation_backend = str((simulation_payload or {}).get("backend", simulation_out.get("backend", "3d-env"))).strip() or "3d-env"
    simulation_out["backend"] = simulation_backend
    existing["simulation"] = simulation_out

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
        fh.write("\n")

    return JSONResponse({
        "ok": True,
        "resolved_path": str(resolved_path),
        "mqtt": mqtt_out,
        "simulation": {"backend": simulation_backend},
    })


@app.get("/api/replay/sessions")
async def replay_sessions(request: Request, limit: int = 100) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "sessions": runtime.replay_store.list_sessions(limit=limit),
        "current_session_id": runtime.replay_store.current_session_id,
    }


@app.post("/api/replay/sessions/rollover")
async def rollover_replay_session(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason = str(payload.get("reason", "manual_rollover"))
    session_id = runtime.replay_store.rollover_session(reason=reason)
    return JSONResponse({"ok": True, "current_session_id": session_id})


@app.get("/api/replay/sessions/{session_id}")
async def replay_session_detail(session_id: str, request: Request, limit: int = 2000) -> dict[str, Any]:
    runtime = _runtime(request)
    session = runtime.replay_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session": session,
        "timeline": runtime.replay_store.get_session_timeline(session_id, limit=limit),
    }


@app.delete("/api/replay/sessions/{session_id}")
async def delete_replay_session(session_id: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    try:
        deleted = runtime.replay_store.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return JSONResponse({
        "ok": True,
        "deleted_session_id": session_id,
        "current_session_id": runtime.replay_store.current_session_id,
    })


@app.get("/api/replay/scene-map")
async def replay_scene_map(backend: str = "3d-env", grid_size: int = 128) -> dict[str, Any]:
    try:
        return get_scene_map_payload(backend=backend, grid_size=grid_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/video-mode")
async def set_video_mode(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    enabled = bool(payload.get("enabled", True))
    ingest_mode = str(payload.get("ingest_mode", runtime.config.video["ingest_mode"]))
    delivery_mode = str(payload.get("delivery_mode", runtime.config.video["delivery_mode"]))

    runtime.config.raw.setdefault("video", {})["enabled"] = enabled
    runtime.config.raw["video"]["ingest_mode"] = ingest_mode
    runtime.config.raw["video"]["delivery_mode"] = delivery_mode
    save_config(runtime.config)

    modes = await runtime.state_store.set_video_modes(enabled, ingest_mode, delivery_mode)
    await runtime.ws_manager.broadcast({"type": "video_mode", "data": modes})
    return JSONResponse({"ok": True, "video": modes})


@app.post("/api/controller/{action}")
async def controller_action(action: str, request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    if action == "take":
        ok = await runtime.state_store.try_claim_controller(client_id)
        runtime.replay_store.log_runtime_event("controller_take_attempt", {"client_id": client_id, "ok": ok})
    elif action == "release":
        ok = await runtime.state_store.release_controller(client_id)
        await runtime.control_service.clear_buttons(client_id)
        runtime.replay_store.log_runtime_event("controller_release_attempt", {"client_id": client_id, "ok": ok})
    else:
        raise HTTPException(status_code=404, detail="unknown action")

    controller = await runtime.state_store.controller_snapshot()
    await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
    await runtime.mqtt_runtime.publish_presence_snapshot()
    return JSONResponse({"ok": ok, "controller": controller})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    runtime = _runtime(websocket)
    client_id = websocket.query_params.get("client_id") or uuid.uuid4().hex[:12]
    await runtime.ws_manager.connect(client_id, websocket)
    await runtime.mqtt_runtime.publish_presence_snapshot()
    snapshot = await runtime.state_store.snapshot()
    snapshot["simulation"] = runtime.config.simulation
    await runtime.ws_manager.send(client_id, {
        "type": "snapshot",
        "client_id": client_id,
        "data": snapshot,
    })

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "control":
                ok = await runtime.control_service.set_buttons(client_id, message.get("buttons", {}))
                if not ok:
                    await runtime.ws_manager.send(client_id, {
                        "type": "error",
                        "message": "Control rejected: client is not the active controller.",
                    })
                controller = await runtime.state_store.controller_snapshot()
                await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
            elif msg_type == "control_release":
                await runtime.control_service.clear_buttons(client_id)
            elif msg_type == "ping":
                await runtime.ws_manager.send(client_id, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await runtime.control_service.clear_buttons(client_id)
        await runtime.state_store.release_controller(client_id)
        controller = await runtime.state_store.controller_snapshot()
        await runtime.ws_manager.broadcast({"type": "controller", "data": controller})
        await runtime.ws_manager.disconnect(client_id)
        await runtime.mqtt_runtime.publish_presence_snapshot()


@app.get("/setup/mqtt")
async def mqtt_setup_page() -> RedirectResponse:
    return RedirectResponse(url="/settings?tab=connectivity", status_code=307)


@app.get("/replay")
async def replay_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "replay.html")


if __name__ == "__main__":
    config = load_config()
    uvicorn.run(
        app,
        host=str(config.gcs["host"]),
        port=int(config.gcs["port"]),
        reload=False,
    )
