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
}

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = ROOT_DIR / "config" / "common.local.json"
FALLBACK_SETTINGS_PATH = ROOT_DIR / "config" / "common.example.json"


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
    return AppConfig(raw=merged, settings_path=settings_path)


def save_config(config: AppConfig) -> None:
    config.settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config.settings_path, "w", encoding="utf-8") as fh:
        json.dump(config.raw, fh, indent=2)
        fh.write("\n")
