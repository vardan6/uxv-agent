# Run And Config Guide

## Repository Layout

Repository root:
- `/mnt/c/Users/vardana/Documents/Proj/remote-uxv`

Main subprojects:
- `3d-env/`
- `backend/`
- `scene/`
- `config/`
- `docs/`

## Shared Configuration

Shared runtime config files:
- `config/common.example.json`: tracked template
- `config/common.local.json`: local environment-specific override

Current shared config covers:
- MQTT broker host and port
- MQTT topic prefix and topic names
- control and telemetry rates
- telemetry publish policy
- GCS presence topic and timeout
- video mode defaults
- GCS host and port
- LLM provider definitions
- model routing for AI Chat and future rover-agent workflows

## Terrain Scene Manifest

Terrain and static world-object data live in:
- `scene/scenes/terrain_scene.v1.json`

This manifest is consumed by:
- `3d-env/simulator/terrain.py`
- `3d-env/simulator/main.py`
- `scene/scene_map.py`

The manifest contains explicit final objects and terrain data. Runtime scripts should not hard-code terrain object names, object counts, coordinates, or dimensions.

Regenerate and validate it from the repository root when terrain definitions change:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv
python3 scene/pipeline/generate_terrain_scene.py
python3 scene/pipeline/validate_terrain_scene.py
```

Detailed manifest notes:
- [Terrain Scene Manifest](../../components/simulator/design.md)

Important rule:
- keep real environment-specific values only in `config/common.local.json`
- keep `common.example.json` safe for commit

## Current Important Shared Keys

### MQTT

- `mqtt.broker_host`
- `mqtt.broker_port`
- `mqtt.topic_prefix`
- `mqtt.client_id`
- `mqtt.control_topic`
- `mqtt.state_topic`
- `mqtt.camera_topic`
- `mqtt.control_hz`
- `mqtt.telemetry_hz`
- `mqtt.telemetry_policy`
- `mqtt.gcs_presence_topic`
- `mqtt.gcs_presence_timeout_ms`
- `mqtt.failsafe_timeout_ms`

### Video

- `video.enabled`
- `video.ingest_mode`
- `video.delivery_mode`

### GCS

- `gcs.host`
- `gcs.port`
- `gcs.telemetry_stale_ms`

### LLM Provider Foundation

- `llm_providers`
- `model_routing`
- `logging.ai_sessions_db_path`
- `logging.agent_trace_dir`

LLM provider records should store secret reference names such as environment variable names.
Do not store raw API key values in tracked config or exported JSON intended for commit.

## Running The Simulator

From `3d-env/` using Linux or WSL Python:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv/3d-env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python simulator/main.py
```

Helper launcher:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv/3d-env
./run.sh
```

Windows GPU launcher:

```powershell
cd C:\Users\vardana\Documents\Proj\remote-uxv\3d-env
python -m venv .venv-gpu
.\.venv-gpu\Scripts\python -m pip install -r requirements.txt
.\run.bat
```

WSL bridge to the Windows GPU environment:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv/3d-env
./run_gpu.sh
```

WSL note:
- `run_gpu.sh` requires WSL interop to be enabled so the shell can invoke Windows executables
- if WSL interop is disabled, launch the simulator from Windows directly with `run.bat`

### Simulator Launcher Environment Variables

Read only by the `3d-env` launchers and `simulator/gpu_probe.py`. They select a
launch route; none of them names a vehicle, which is why they carry the `UXV_`
product prefix rather than the simulator's `Rover` kind name.

| Variable | Default | Meaning |
|---|---|---|
| `UXV_GPU_PREFERENCE` | `nvidia` | GPU routing preference; any other value disables NVIDIA-first routing and falls back to native |
| `UXV_LAUNCH_PATH` | `direct` | Set by the launcher, read back by `gpu_probe`; one of `linux-native`, `windows-venv`, `wsl-windows-venv`, `wsl-linux-fallback` |
| `UXV_OPTIMUS_HINT` | unset | Path to `optimus_hint.dll`, passed by `run.bat` to `main.py` when the DLL is present |
| `UXV_PYTHON` | `python` | Interpreter used to build the Windows GPU venv |

Renamed from `ROVER_*` on 2026-09-18 under
[ADR 0037](../decisions/0037-project-naming-and-directory-restructure.md)'s
`UXV_*` env-var convention — these are Tier A product-prefix variables, not part
of the Tier D `rover` → `vehicle` rename.

## Running The GCS

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv
pip install -r backend/requirements-gcs.txt
python -m backend
```

Open:
- `http://127.0.0.1:8080` from `config/common.example.json` by default

Alternative helper:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-uxv/backend
./run.sh
```

## Current Operational Sequence

For the current end-to-end demo flow:
1. make sure the MQTT broker is reachable
2. start the GCS
3. open the GCS in a browser
4. start the simulator
5. keep the GCS dashboard tab focused to drive
6. confirm telemetry and camera are visible

## Telemetry Publish Policy Operations

Current simulator policy options:
- `auto`
- `force_on`
- `force_off`

Meaning:
- `auto`: simulator publishes only while fresh GCS presence exists
- `force_on`: simulator always publishes outbound data
- `force_off`: simulator never publishes outbound data

Current places to control it:
- simulator menu: `Settings -> Telemetry Policy`
- simulator MQTT settings dialog
- shared config file under `mqtt.telemetry_policy`

Current auto-mode behavior:
- if no GCS browser is connected, the GCS presence becomes inactive or stale
- once no fresh active GCS remains, the simulator stops publishing telemetry and camera frames

## MQTT Setup Through The GCS

The GCS exposes a setup page:
- `/setup/mqtt`

Current behavior:
- reads current `mqtt.*` config
- allows broker/topic/control-rate editing
- writes back to shared config
- reconnects the GCS MQTT runtime without restarting the process

## Settings Through The GCS

The main settings page is:
- `/settings`

Current tabs:
- Connectivity
- Video
- Appearance
- Add LLM Provider
- JSON

The LLM Provider tab can add, edit, enable/disable, list, and check configured providers.
The routing panel assigns primary and fallback providers to AI purposes.

## Rover Tuning Baseline Use

The accepted `3d-env` rover baseline includes a simulator-side tuning reminder in the HUD.

Current operator usage:
- open `Simulation -> Physics debug` to show or hide the physics/tuning overlay
- when visible, the HUD shows:
  - pitch, roll, wheel contacts, throttle, steering
  - the four-checkpoint route reminder: straight bump, uphill climb, side-slope traverse, downhill turn
  - the condensed pass/fail reminder used during the accepted tuning loop

Operational meaning:
- this overlay is the repeatable manual-validation surface for future rover changes
- if a future rover change makes climb worse or reintroduces unstable bouncing/washout, treat that as a regression against the current accepted baseline
These settings are used by `/ai` Chat/Agent mode and remain the foundation for future rover-agent workflows.
Provider health checks are endpoint probes only; they do not send prompts or control the rover.

## AI Chat Through The GCS

The AI Chat page is:
- `/ai`

Current behavior:
- provider-backed Chat and read-only Agent modes
- persistent AI sessions and messages
- streaming responses
- retry last assistant response
- archive/restore/purge sessions
- per-session provider override
- compact live current-context injection from GCS state
- context metadata stored on assistant messages
- read-only agent tools for current rover state, scene summary, front/near/by-kind object queries, mission state, and replay analytics

The AI Chat system prompt is read-only. It must not publish rover control commands, start missions, or bypass the GCS control boundary.

Current live context includes:
- latest rover telemetry and freshness
- broker/runtime state
- active controller summary
- video mode state
- scene-map summary and deterministic object facts
- active replay summary and recent telemetry hooks
- backend-owned current mission state and controller mission state when mission revisions exist

Planned follow-up work:
- keep always-on context compact and expose larger details through on-demand tools
- extract spatial query logic into a reusable service
- add a permissioned agent-ready tool registry with read-only and planning tools
- current-context debug visibility
- later RAG source controls
- document upload and session-linked sources
- web research/search
- structured rover intent parsing
- LangGraph mission planning with operator approval checkpoints

The JSON tab can export, load, preview, save, and apply selected settings sections.
When importing older JSON files, missing sections are ignored rather than clearing existing settings.

## Current Troubleshooting Notes

### Simulator Still Publishing In Auto Mode

Check:
- whether a retained active GCS presence is still fresh
- whether the simulator policy is set to `force_on`
- whether the GCS still has a connected browser session

Immediate stop option:
- set simulator telemetry policy to `force_off`

### WSL GPU Launcher Cannot Run Windows Python

Likely cause:
- WSL interop is disabled or unavailable in the current shell

Current workaround:
- run `run.bat` directly from Windows

### No Browser Video

Check:
- `video.enabled`
- `video.ingest_mode == mqtt_frames`
- `video.delivery_mode == websocket_mjpeg`
- broker connectivity
- whether simulator publish policy is currently allowing outbound data

### Frontend Vitest Is Slow, Not Hanging (WSL)

A full `frontend/` `npm test` costs 60–68s under WSL (environment setup
dominates); a single file is ~30s. Focused runs do complete — batch
verification into one run at the end of a change instead of after each edit.

### `rtk` And Frontend Tooling

- `rtk` cannot parse Vitest output (`[RTK:PASSTHROUGH] vitest parser: All
  parsing tiers failed`) and swallows it entirely for single-file runs — use
  `rtk proxy npx vitest run <file>` to see results.
- The `rtk` git proxy has intermittently returned the **wrong commit's** data
  and flattens merge commits. Use `git cat-file -p` raw object reads for any
  ancestry-critical work.
- Vite dev-server `EPIPE`/`ECONNRESET` websocket proxy logs are benign.
- React `act(...)` warnings in a Vitest run are harness noise if the targeted
  suite and `npm run build` are both green — not a real signal on their own.
