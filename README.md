# Remote Rover

Current workspace layout:

- `3d-env/`: Panda3D rover simulator and simulator-specific docs
- `gcs_server/`: browser-based Ground Control Station (GCS) backend and static frontend
- `gcs_server/requirements-gcs.txt`: Python dependencies for the GCS app
- `gcs_server/GCS-web-app.md`: GCS product/spec document
- `remote_rover_architecture_and_implementation_plan.md`: current architecture and implementation roadmap

## Current Status

Implemented:
- 3D rover simulator in Python with Panda3D + Bullet physics
- Redesigned 3D world (April 8, 2026): deterministic dual-valley map with two solar plants, a central operations building, drivable interconnecting roads, larger trees, and mixed-size stones
- MQTT bridge in the simulator for manual control input and telemetry output
- MQTT camera-frame publishing from the simulator POV buffer
- Ground Control Station web app in a separate `gcs_server/` directory
- Shared config model centered on `config/common.example.json` with local overrides in `config/common.local.json`
- Browser-side controller lock, telemetry dashboard, and MQTT camera-frame rendering path in the GCS
- GCS MQTT setup page (`/setup/mqtt`) with live broker/topic/control-rate reconfiguration
- Dashboard appearance/theme preferences persisted in browser storage

Not yet implemented:
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
    requirements-gcs.txt
    mqtt_service.py
    GCS-web-app.md
    static/
    README.md
  config/
    common.example.json
    README.md
  remote_rover_architecture_and_implementation_plan.md
  PROJECT_REVIEW_AND_CURRENT_STATE.md
```

## Run The Simulator

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/3d-env
pip install -r requirements.txt
python simulator/main.py
```

## 3D World Update (April 8, 2026)

The simulator map was upgraded with a major terrain and scene redesign:
- terrain extent increased to `400 x 400` world units (`2x` each side from `200 x 200`)
- terrain grid density doubled to preserve detail at larger scale (`160 -> 320`)
- deterministic terrain shaping with higher hills and two designed valleys
- one solar plant in each valley (dense procedural panel arrays)
- a central building between both plants
- flattened rover pathways:
  - loop road around each solar plant
  - connector road between plants
  - building-to-plant roads
- larger trees and a broader mix of small stones + large boulders

Primary implementation files:
- `3d-env/simulator/terrain.py`
- `3d-env/simulator/main.py`

## Run The GCS

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r gcs_server/requirements-gcs.txt
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

The GCS MQTT setup page (`/setup/mqtt`) updates `mqtt.*` in `common.local.json` and triggers immediate broker reconnect in the running GCS.

Important shared keys:
- `mqtt.broker_host`
- `mqtt.broker_port`
- `mqtt.topic_prefix`
- `mqtt.client_id`
- `mqtt.control_topic`
- `mqtt.state_topic`
- `mqtt.camera_topic`
- `mqtt.control_hz`
- `video.enabled`
- `video.ingest_mode`
- `video.delivery_mode`
- `gcs.host`
- `gcs.port`

## Current Priority

The codebase has reached the first end-to-end MQTT bootstrap:
- simulator receives MQTT control
- simulator publishes telemetry
- simulator publishes JPEG camera frames
- GCS renders telemetry and camera frames in the browser

The next work should focus on hardening that path:
- validate reconnect and freshness behavior under broker loss
- decide whether MQTT-frame video remains a debug/fallback path only
- add Redis if multi-instance GCS deployment is needed

## Repository Status

The active git repository root is now `remote-rover/`.

That is the correct direction for this project because:
- `3d-env/` remains focused on the simulator
- `gcs_server/` is tracked in the same repository without nesting problems
- project-level docs now live at the workspace root
