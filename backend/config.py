from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VIDEO_OSD_LINE_IDS = ("position", "speed_heading", "gps", "power", "camera")
VIDEO_OSD_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
SUPPORTED_SIMULATION_BACKENDS = ("3d-env",)
DEFAULT_VIDEO_OSD_PRESETS: list[dict[str, Any]] = [
    {
        "id": "default",
        "name": "Default Overlay",
        "lines": ["position", "speed_heading", "gps", "power", "camera"],
        "corner": "top-right",
        "opacity": 0.92,
        "compact": False,
    }
]

DEFAULT_GCS_SETTINGS: dict[str, Any] = {
    "mqtt": {},
    "video": {},
    "osd_presets": copy.deepcopy(DEFAULT_VIDEO_OSD_PRESETS),
    "gcs": {},
    "key_bindings": {},
    "simulation": {},
    "logging": {},
    "map": {},
    "ai_settings": {
        "tts": {
            "enabled": True,
            "engine": "kokoro_service",
            "auto_read": False,
            "service_url": "http://127.0.0.1:9101",
            "voice": "af_sky",
            "format": "wav",
            "speed": 1.0,
            "browser_fallback": True,
            "voice_name": "",
            "rate": 1.0,
            "pitch": 1.0,
        },
        "ai_context_budget_chars": 24000,
    },
    "vehicle_profile": {
        # The operator's persisted selection. Unknown or absent IDs resolve to
        # rover_default at read time (ai/vehicle_profile.py).
        "active_profile_id": "rover_default",
    },
    "mission_lifecycle": {
        # execution_mode is intentionally absent so a fresh config inherits the
        # build-time default (sim -> autonomous, real-rover -> strict) resolved
        # at read time. See ai/execution_mode.py (ADR 0021 §1 / §6).
        "confirm_timeout_s": 10,
        "auto_overlay_new_missions": True,
        "steal_map_focus": True,
        "default_name_template": "Untitled mission",
    },
    "llm_providers": [
        {
            "id": "provider-default-ollama",
            "display_name": "Ollama Local (Default)",
            "provider_type": "ollama",
            "auth_mode": "none",
            "secret_ref": "",
            "base_url": "http://localhost:11434",
            "model_id": "llama3:latest",
            "enabled": True,
            "capabilities": ["chat"],
            "context_window": None,
        }
    ],
    "model_routing": {},
}

DEFAULT_LLM_PROVIDERS: list[dict[str, Any]] = copy.deepcopy(DEFAULT_GCS_SETTINGS["llm_providers"])

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = ROOT_DIR / "config" / "common.local.json"
FALLBACK_SETTINGS_PATH = ROOT_DIR / "config" / "common.example.json"

DEFAULT_GCS_SETTINGS["logging"] = {
    "replay_db_path": "data/gcs_replay.sqlite3",
    "ai_sessions_db_path": "data/gcs_ai_sessions.sqlite3",
    "llm_secrets_db_path": "data/gcs_llm_secrets.sqlite3",
    "agent_trace_dir": "data/agent_traces",
    "controller_mission_state_path": "data/controller_mission_adapter.json",
    "controller_mission_adapter": "json_file",
    "controller_mission_mavlink_url": "",
    "controller_mission_mavsdk_url": "",
    "controller_mission_heartbeat_timeout_s": 5.0,
    "controller_mission_request_timeout_s": 5.0,
    "controller_mission_source_system": 245,
    "controller_mission_source_component": 190,
    "auto_start_session": True,
}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def normalize_osd_presets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return copy.deepcopy(DEFAULT_VIDEO_OSD_PRESETS)

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        preset_id = str(item.get("id") or f"preset-{index + 1}").strip() or f"preset-{index + 1}"
        if preset_id in seen_ids:
            preset_id = f"{preset_id}-{index + 1}"
        seen_ids.add(preset_id)
        seen_lines: set[str] = set()
        raw_lines = item.get("lines")
        lines = []
        if isinstance(raw_lines, list):
            for line in raw_lines:
                line_id = str(line).strip()
                if line_id in VIDEO_OSD_LINE_IDS and line_id not in seen_lines:
                    seen_lines.add(line_id)
                    lines.append(line_id)
        corner = str(item.get("corner") or "top-right").strip()
        try:
            opacity = float(item.get("opacity", 0.92))
        except (TypeError, ValueError):
            opacity = 0.92
        normalized.append({
            "id": preset_id,
            "name": str(item.get("name") or "Untitled Preset").strip() or "Untitled Preset",
            "lines": lines,
            "corner": corner if corner in VIDEO_OSD_CORNERS else "top-right",
            "opacity": round(min(1.0, max(0.2, opacity)), 2),
            "compact": bool(item.get("compact", False)),
        })
    return normalized


def normalize_simulation_config(value: Any) -> dict[str, Any]:
    """Return the only supported simulator configuration or raise clearly."""
    simulation = dict(value) if isinstance(value, dict) else {}
    backend = str(simulation.get("backend", "3d-env")).strip() or "3d-env"
    if backend not in SUPPORTED_SIMULATION_BACKENDS:
        raise ValueError(
            f"unsupported simulation backend {backend!r}; only '3d-env' is supported"
        )
    simulation["backend"] = backend
    simulation["available_backends"] = list(SUPPORTED_SIMULATION_BACKENDS)
    return simulation


@dataclass(slots=True)
class AppConfig:
    raw: dict[str, Any]
    settings_path: Path

    @property
    def mqtt(self) -> dict[str, Any]:
        return self.raw["mqtt"]

    @property
    def video(self) -> dict[str, Any]:
        return self.raw["video"]

    @property
    def gcs(self) -> dict[str, Any]:
        return self.raw["gcs"]

    @property
    def osd_presets(self) -> list[dict[str, Any]]:
        presets = self.raw.get("osd_presets")
        if presets is None:
            return []
        return normalize_osd_presets(presets)

    @property
    def key_bindings(self) -> dict[str, list[str]]:
        return self.raw["key_bindings"]

    @property
    def simulation(self) -> dict[str, Any]:
        return self.raw["simulation"]

    @property
    def logging(self) -> dict[str, Any]:
        return self.raw["logging"]

    @property
    def map(self) -> dict[str, Any]:
        return self.raw["map"]

    @property
    def ai_settings(self) -> dict[str, Any]:
        settings = self.raw.get("ai_settings", {})
        return settings if isinstance(settings, dict) else {}

    @property
    def vehicle_profile(self) -> dict[str, Any]:
        section = self.raw.get("vehicle_profile", {})
        return section if isinstance(section, dict) else {}

    @property
    def mission_lifecycle(self) -> dict[str, Any]:
        section = self.raw.get("mission_lifecycle", {})
        return section if isinstance(section, dict) else {}

    @property
    def llm_providers(self) -> list[dict[str, Any]]:
        providers = self.raw.get("llm_providers", [])
        return providers if isinstance(providers, list) else []

    @property
    def model_routing(self) -> dict[str, Any]:
        routing = self.raw.get("model_routing", {})
        return routing if isinstance(routing, dict) else {}


def load_config(path: str | Path | None = None) -> AppConfig:
    settings_path = Path(path) if path else DEFAULT_SETTINGS_PATH
    data: dict[str, Any] = {}
    if FALLBACK_SETTINGS_PATH.exists():
        with open(FALLBACK_SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    if settings_path.exists():
        with open(settings_path, encoding="utf-8") as fh:
            data = _deep_merge(data, json.load(fh))
    merged = _deep_merge(DEFAULT_GCS_SETTINGS, data)
    providers = merged.get("llm_providers")
    if not isinstance(providers, list) or not providers:
        merged["llm_providers"] = copy.deepcopy(DEFAULT_LLM_PROVIDERS)
    merged["simulation"] = normalize_simulation_config(merged.get("simulation"))
    return AppConfig(raw=merged, settings_path=settings_path)


def save_config(config: AppConfig) -> None:
    config.settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = copy.deepcopy(config.raw)
    payload.pop("connectivity", None)
    with open(config.settings_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
