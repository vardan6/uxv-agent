from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_GCS_SETTINGS: dict[str, Any] = {
    "mqtt": {},
    "video": {},
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
    return AppConfig(raw=merged, settings_path=settings_path)


def save_config(config: AppConfig) -> None:
    config.settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config.settings_path, "w", encoding="utf-8") as fh:
        json.dump(config.raw, fh, indent=2)
        fh.write("\n")
