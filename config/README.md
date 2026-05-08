# Shared Config

This directory stores shared runtime configuration used by both the simulator and the GCS.

## Files

- `common.example.json`: tracked safe template with placeholder/default values
- `common.local.json`: local override file for real broker/IP/port and other environment-specific values
- `terrain_scene.v1.json`: tracked explicit terrain and object scene manifest
- `terrain_scene.schema.json`: tracked validation schema for the terrain scene manifest
- `terrain_scene.json`: legacy compact terrain seed used by `tools/generate_terrain_scene.py`

## Commit Policy

Commit:
- `common.example.json`
- this README

Do not commit:
- `common.local.json`

The root `.gitignore` excludes `config/common.local.json`.

## Important Safety Rule

Real broker endpoints, IP addresses, hostnames, ports, credentials, and other environment-specific values must be stored only in:
- `config/common.local.json`

They must never be copied into:
- `config/common.example.json`
- tracked documentation
- tracked code defaults
- screenshots or pasted examples intended for commit

Before every push, run a quick search for sensitive endpoint values and confirm that only `config/common.local.json` contains them.

## Current Usage

- Simulator loads shared runtime settings from `common.local.json` if present, otherwise from `common.example.json`
- Simulator keeps its UI-only settings in `3d-env/simulator/settings.json`
- GCS reads and persists shared runtime settings in `common.local.json`, falling back to `common.example.json`
- Simulator and GCS read terrain/map/static-object data from `terrain_scene.v1.json`
- Simulator GPS telemetry is artificial and derived from `terrain_scene.v1.json` `coordinate_system.georeference`; it is not read from the laptop/browser location
- AI Chat current-context providers use `terrain_scene.v1.json` through the GCS scene-map service for exact terrain/object facts
- GCS stores LLM provider records under `llm_providers` and purpose-based model routing under `model_routing`
- GCS stores AI chat sessions in SQLite at `logging.ai_sessions_db_path`
- GCS settings JSON export/import can operate on selected sections without clearing missing sections from older files

## LLM Provider Secrets

LLM provider settings should use `secret_ref` values that name environment variables.
Tracked config and exported JSON intended for commit must not contain raw API key values.

Example:

```json
{
  "llm_providers": [
    {
      "display_name": "Local Ollama",
      "provider_type": "ollama",
      "auth_mode": "none",
      "secret_ref": "",
      "base_url": "http://localhost:11434",
      "model_id": "llama3.1",
      "capabilities": ["chat"],
      "enabled": true
    }
  ]
}
```

## Terrain Scene Regeneration

From the repository root:

```bash
python3 tools/generate_terrain_scene.py
python3 tools/validate_terrain_scene.py
```

More detail:
- `docs/terrain-scene.md`

## First-Time Setup

```bash
cp config/common.example.json config/common.local.json
```

Then edit `config/common.local.json` with your real broker host/port and any machine-specific values.
