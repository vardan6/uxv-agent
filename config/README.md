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
