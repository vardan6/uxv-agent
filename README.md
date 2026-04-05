# Remote Rover

Current workspace layout:

- `3d-env/`: Panda3D rover simulator and simulator-specific docs
- `gcs_server/`: browser-based Ground Control Station (GCS) backend and static frontend
- `requirements-gcs.txt`: Python dependencies for the GCS app
- `gcs_server/GCS-web-app.md`: GCS product/spec document, updated to current state
- `remote_rover_architecture_and_implementation_plan.md`: current architecture and implementation roadmap

## Current Status

Implemented:
- 3D rover simulator in Python with Panda3D + Bullet physics
- MQTT bridge in the simulator for manual control input and telemetry output
- Ground Control Station web app in a separate `gcs_server/` directory
- Shared config model centered on `config/common.example.json` with local overrides in `config/common.local.json`
- Browser-side controller lock, telemetry dashboard, and MQTT camera-frame subscription path in the GCS

Not yet implemented:
- Simulator camera frame publishing to MQTT
- Redis-backed shared GCS state
- Production WebRTC media path
- Authentication / authorization

## Directory Overview

```text
remote-rover/
  3d-env/
    simulator/
    requirements.txt
    mqtt-plan-canonical-2026-04-05_00-58-36.md
    phase1-3D-Simulator.md
    initial-hl-design.md
  gcs_server/
    app.py
    mqtt_service.py
    GCS-web-app.md
    static/
    README.md
  config/
    common.example.json
    README.md
  requirements-gcs.txt
  remote_rover_architecture_and_implementation_plan.md
  PROJECT_REVIEW_AND_CURRENT_STATE.md
```

## Run The Simulator

```bash
cd 3d-env
pip install -r requirements.txt
python simulator/main.py
```

## Run The GCS

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r requirements-gcs.txt
python -m gcs_server
```

Open `http://localhost:8080` in a browser.

## Config Source Of Truth

Current shared runtime configuration lives in:
- `config/common.example.json` (tracked safe template)
- `config/common.local.json` (local override, ignored)

The simulator reads shared runtime config through `simulator/settings.py` and keeps UI-only settings in `3d-env/simulator/settings.json`.
The GCS reads shared config through `gcs_server/config.py` using:
- `remote-rover/config/common.local.json` (preferred writable local file)
- `remote-rover/config/common.example.json` (tracked fallback template)

Important shared keys:
- `mqtt.broker_host`
- `mqtt.broker_port`
- `mqtt.topic_prefix`
- `mqtt.control_topic`
- `mqtt.state_topic`
- `mqtt.camera_topic`
- `video.enabled`
- `video.ingest_mode`
- `video.delivery_mode`
- `gcs.host`
- `gcs.port`

## Repository Status

The active git repository root is now `remote-rover/`.

That is the correct direction for this project because:
- `3d-env/` remains focused on the simulator
- `gcs_server/` is tracked in the same repository without nesting problems
- project-level docs now live at the workspace root
