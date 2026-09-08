from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.ai.execution_mode import normalize_mission_lifecycle_settings, resolve_build_default_mode
from backend.config import normalize_osd_presets, normalize_simulation_config, save_config
from backend.provider_normalizers import (
    _normalize_ai_settings,
    _normalize_provider,
    _normalize_routing,
    _sanitize_secret_ref,
    _sanitize_stored_secret_ref,
)
from backend.runtime import AppRuntime

router = APIRouter()

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _resolve_backend_config_path(path_text: str) -> Path:
    cleaned = (path_text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="path is required")
    raw_path = Path(cleaned)
    resolved = raw_path.resolve(strict=False) if raw_path.is_absolute() else (_CONFIG_DIR / raw_path).resolve(strict=False)
    config_root = _CONFIG_DIR.resolve(strict=False)
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


def _extract_section_payload(payload: dict[str, Any], section: str) -> Any:
    return payload.get(section)


def _selected_sections(payload: dict[str, Any]) -> list[str]:
    raw_sections = payload.get("sections", [])
    if not isinstance(raw_sections, list):
        raise HTTPException(status_code=400, detail="sections must be a list")
    allowed = {
        "mqtt",
        "simulation",
        "video",
        "osd_presets",
        "appearance",
        "mission_lifecycle",
        "ai_settings",
        "llm_providers",
        "model_routing",
    }
    sections = []
    for raw_section in raw_sections:
        section = str(raw_section)
        if section in allowed and section not in sections:
            sections.append(section)
    if not sections:
        raise HTTPException(status_code=400, detail="at least one valid section is required")
    return sections


def _provider_export(provider: dict[str, Any]) -> dict[str, Any]:
    out = dict(provider)
    auth_mode = str(out.get("auth_mode", "")).strip()
    if auth_mode == "stored_secret":
        out["secret_ref"] = _sanitize_stored_secret_ref(out.get("secret_ref", ""))
    else:
        out["secret_ref"] = _sanitize_secret_ref(out.get("secret_ref", ""))
    out["has_secret"] = False
    out.pop("last_check", None)
    out.pop("secret_value", None)
    return out


def _settings_export_payload(config: Any, sections: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": 1}
    if "mqtt" in sections:
        out["mqtt"] = dict(config.mqtt)
    if "simulation" in sections:
        out["simulation"] = dict(config.simulation)
    if "video" in sections:
        out["video"] = dict(config.video)
    if "osd_presets" in sections:
        out["osd_presets"] = config.osd_presets
    if "appearance" in sections:
        out["appearance"] = dict(config.raw.get("appearance", {})) if isinstance(config.raw.get("appearance"), dict) else {}
    if "mission_lifecycle" in sections:
        out["mission_lifecycle"] = normalize_mission_lifecycle_settings(
            config.mission_lifecycle,
            build_default=resolve_build_default_mode(config),
        )
    if "ai_settings" in sections:
        out["ai_settings"] = _normalize_ai_settings(config.raw.get("ai_settings", {}))
    if "llm_providers" in sections:
        providers = config.raw.get("llm_providers", [])
        out["llm_providers"] = [_provider_export(provider) for provider in providers if isinstance(provider, dict)]
    if "model_routing" in sections:
        out["model_routing"] = dict(config.raw.get("model_routing", {})) if isinstance(config.raw.get("model_routing"), dict) else {}
    return out


def _apply_settings_sections(config: Any, payload: dict[str, Any], sections: list[str]) -> list[str]:
    snapshot = dict(config.raw)
    applied: list[str] = []
    try:
        if "mqtt" in sections:
            mqtt = _extract_section_payload(payload, "mqtt")
            if isinstance(mqtt, dict):
                config.raw["mqtt"] = dict(mqtt)
                applied.append("mqtt")
        if "simulation" in sections:
            simulation = _extract_section_payload(payload, "simulation")
            if isinstance(simulation, dict):
                try:
                    config.raw["simulation"] = normalize_simulation_config(simulation)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                applied.append("simulation")
        if "video" in sections:
            video = _extract_section_payload(payload, "video")
            if isinstance(video, dict):
                config.raw["video"] = dict(video)
                applied.append("video")
        if "osd_presets" in sections:
            osd_presets = _extract_section_payload(payload, "osd_presets")
            if isinstance(osd_presets, list):
                config.raw["osd_presets"] = normalize_osd_presets(osd_presets)
                applied.append("osd_presets")
        if "appearance" in sections:
            appearance = _extract_section_payload(payload, "appearance")
            if isinstance(appearance, dict):
                config.raw["appearance"] = dict(appearance)
                applied.append("appearance")
        if "mission_lifecycle" in sections:
            mission_lifecycle = _extract_section_payload(payload, "mission_lifecycle")
            if isinstance(mission_lifecycle, dict):
                config.raw["mission_lifecycle"] = normalize_mission_lifecycle_settings(
                    mission_lifecycle,
                    build_default=resolve_build_default_mode(config),
                )
                applied.append("mission_lifecycle")
        if "ai_settings" in sections:
            ai_settings = _extract_section_payload(payload, "ai_settings")
            if isinstance(ai_settings, dict):
                config.raw["ai_settings"] = _normalize_ai_settings(ai_settings)
                applied.append("ai_settings")
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
    except Exception:
        config.raw.clear()
        config.raw.update(snapshot)
        raise
    return applied


@router.get("/api/video-osd-presets")
async def get_video_osd_presets(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {"osd_presets": runtime.config.osd_presets}


@router.put("/api/video-osd-presets")
async def put_video_osd_presets(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    presets_payload = payload.get("osd_presets") if isinstance(payload, dict) else None
    if not isinstance(presets_payload, list):
        raise HTTPException(status_code=400, detail="osd_presets must be a list")
    runtime.config.raw["osd_presets"] = normalize_osd_presets(presets_payload)
    save_config(runtime.config)
    await runtime.ws_manager.broadcast({"type": "video_osd_presets", "data": runtime.config.osd_presets})
    return JSONResponse({"ok": True, "osd_presets": runtime.config.osd_presets})


@router.post("/api/settings/export")
async def export_settings_sections(request: Request) -> JSONResponse:
    runtime = _runtime(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="export payload must be an object")
    sections = _selected_sections(payload)
    return JSONResponse(_settings_export_payload(runtime.config, sections))


@router.post("/api/settings/load-from-path")
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


@router.post("/api/settings/save-to-path")
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
        if section == "llm_providers" and isinstance(section_payload, list):
            section_payload = [
                {k: v for k, v in p.items() if k != "secret_value"}
                for p in section_payload
                if isinstance(p, dict)
            ]
        merged[section] = section_payload
    if "mqtt" in sections or "simulation" in sections:
        merged.pop("connectivity", None)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
        fh.write("\n")
    return JSONResponse({"ok": True, "resolved_path": str(resolved_path), "saved_sections": sections})


@router.post("/api/settings/apply")
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
    if "mqtt" in applied:
        await runtime.reconfigure_mqtt(runtime.config.mqtt)
    if "simulation" in applied:
        simulation = runtime.config.simulation
        runtime.replay_store.update_backend(
            str(simulation.get("backend", "3d-env")),
            str(simulation.get("backend_version", "dev")),
        )
        runtime.replay_store.rollover_session(reason=f"backend_change:{simulation.get('backend', '3d-env')}")
        runtime.replay_store.log_runtime_event("simulation_backend_changed", dict(simulation))
        await runtime.ws_manager.broadcast({"type": "simulation_config", "data": simulation})
    if "video" in applied:
        video = runtime.config.video
        modes = await runtime.state_store.set_video_modes(
            bool(video.get("enabled", True)),
            str(video.get("ingest_mode", "mqtt_frames")),
            str(video.get("delivery_mode", "websocket_mjpeg")),
        )
        await runtime.ws_manager.broadcast({"type": "video", "data": modes})
    if "osd_presets" in applied:
        await runtime.ws_manager.broadcast({"type": "video_osd_presets", "data": runtime.config.osd_presets})
    return JSONResponse({"ok": True, "applied_sections": applied})
