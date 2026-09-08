# Remote Rover

Remote Rover is a rover-control platform built around these main local applications:
- `backend/`: a browser-based Ground Control Station (GCS)
- `3d-env/`: a Panda3D-based 3D rover simulator
- `tts_service/`: a local text-to-speech service for AI chat response playback

The high-level goal is broader than the current rover simulator: build a remote operations stack for rovers and later other robots. The current rover-in-simulator workflow is the prototype path toward real remotely controlled robots, where users can operate directly or ask AI agents by text or voice to generate missions, monitor execution, and escalate to a human when the robot encounters unexpected conditions.

The system already supports the full working control loop:
- browser control through the GCS
- MQTT control delivery to the simulator
- simulator telemetry publication
- simulator camera-frame publication
- browser telemetry and camera display through the GCS
- simulator-side outbound publish suppression when no active GCS is present

## Documentation

Main documentation entry point:
- [Documentation Portal](./docs/README.md)

Recommended reading order:
- [Vision](./docs/cross-cutting/vision.md)
- [Architecture](./docs/cross-cutting/architecture.md)
- [GCS Requirements](./docs/components/gcs/requirements.md)
- [AI Agent Requirements](./docs/components/ai-agent/requirements.md)
- [AI Agent Design](./docs/components/ai-agent/design.md)
- [AI Agent Graph Spec](./docs/components/ai-agent/design/graph-spec.md)
- [AI Current Context Layer](./docs/components/ai-agent/design/context-layer.md)
- [AI Spatial Tools](./docs/components/ai-agent/design/spatial-tools.md)
- [Simulator Design](./docs/components/simulator/design.md)
- [Run And Config Guide](./docs/cross-cutting/operations/run-and-config.md)

Subproject documentation:
- [Simulator Docs](./docs/components/simulator/README.md)
- [GCS Docs](./docs/components/gcs/README.md)
- [Terrain Scene Manifest](./docs/components/simulator/design/terrain-scene.md)

## Repository Layout

```text
remote-rover/
  backend/
  3d-env/
  tts_service/
  config/
  docs/
  tools/
```

## Quick Start

Remote Rover is currently run as separate local processes. Use separate terminals so each service stays visible and can be stopped independently.

### 1. Start MQTT

Make sure an MQTT broker is reachable using the host and port configured in:

```text
config/common.local.json
```

If you use a local Mosquitto broker, start it before the GCS and simulator.

### 2. Start The GCS

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements-gcs.txt
python -m backend
```

Open the GCS at the host and port configured under `gcs.host` and `gcs.port` in `config/common.local.json`.
The tracked template defaults to `http://127.0.0.1:8080`; this repo's local override may differ.

Alternative helper from inside `backend/`:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/backend
./run.sh
```

### 3. Start The TTS Service

Set up the local AI voice service from the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m venv tts_service/.venv
source tts_service/.venv/bin/activate
pip install -r tts_service/requirements.txt
python tts_service/scripts/download_kokoro_models.py
python -m uvicorn tts_service.app:app --host 127.0.0.1 --port 9101
```

Health check:

```text
http://127.0.0.1:9101/health
```

More details:
- [TTS Service README](./tts_service/README.md)

### 4. Start The Simulator

From `3d-env/`:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/3d-env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python simulator/main.py
```

Alternative helper:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/3d-env
./run.sh
```

### 5. Recommended Run Order

1. Start MQTT.
2. Start the GCS.
3. Start the TTS service when AI response voice playback is needed.
4. Open the GCS in the browser.
5. Start the simulator.
6. Confirm telemetry and camera data appear in the GCS.
7. Use AI Chat and test voice playback.

Regenerate the explicit terrain scene manifest when terrain/object definitions change:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python3 scene/pipeline/generate_terrain_scene.py
python3 scene/pipeline/validate_terrain_scene.py
```

For cross-platform launcher details, shared config behavior, and telemetry policy notes, use:
- [Run And Config Guide](./docs/cross-cutting/operations/run-and-config.md)

## Current Status In One Paragraph

The project is currently a working integrated prototype with a Panda3D simulator, a browser-based GCS, MQTT-based control and telemetry, GCS-side replay, and an MQTT-to-WebSocket bootstrap video path. The AI foundation already includes provider-backed chat, compact live context, a read-only Agent path, supervised intent parsing, planner-loop mission planning, and a backend-owned `mission_execution` boundary for revisions, overlays, and execution attempts. `3d-env` is the sole supported simulator backend.
