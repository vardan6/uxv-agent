# Remote Rover GCS

> Note:
> For the current documentation set and high-level project context, start with:
> - `../docs/README.md`
> - `../docs/gcs_server/README.md`
> - `../docs/gcs_server/technical-details.md`

`gcs_server/` is the browser-facing Ground Control Station for the Remote Rover project.

It is a Python FastAPI application with a static frontend. It connects to the same MQTT broker as the simulator, subscribes to rover telemetry and camera topics, publishes control commands, and serves a browser UI for monitoring and manual driving.

## Current Features

- Live telemetry dashboard
- Broker status and topic freshness status
- Config-backed simulator backend identity: `3d-env` or `rover-sim-next`
- Controller lock: one active browser controls, others observe
- Focus-driven browser control activation
- Keyboard control via arrow keys and `W/A/S/D`
- On-screen control buttons with immediate active-state feedback
- Configurable video pipeline modes
- MQTT camera-frame ingest and WebSocket MJPEG-style browser delivery
- End-to-end simulator POV JPEG publication over MQTT
- Dedicated MQTT setup page (`/setup/mqtt`) for broker/topic/control-rate editing
- Live MQTT reconfiguration via API without restarting the GCS process
- SQLite-backed replay/session logging
- Replay session APIs
- Separate replay page with first Leaflet-based map playback
- Replay scene map loaded from `config/terrain_scene.v1.json`
- Theme controls with persisted mode + light/dark theme variants

## Current Limitations

- State backend is in-memory only
- No authentication or authorization
- No WebRTC transport yet
- MQTT settings are persisted to local shared config only (no secrets manager)
- Live dashboard map is not implemented yet
- Replay currently covers telemetry, control, runtime events, and camera timing metadata; recorded video playback is not implemented yet

## Dependencies

Install from the workspace root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r gcs_server/requirements-gcs.txt
```

## Run

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m gcs_server
```

From inside the `gcs_server/` directory:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server
.venv/bin/python app.py
```

Using the helper script inside `gcs_server/`:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover/gcs_server
./run.sh
```

`python -m gcs_server` does not work from inside `gcs_server/` itself because Python needs the parent directory on `sys.path` to resolve the `gcs_server` package.

Default URL:
- `http://localhost:8080`

## Config Source

The GCS currently reads shared settings from:
- `../config/common.local.json` if present
- otherwise `../config/common.example.json`

Main config sections it consumes:

```json
{
  "mqtt": {
    "broker_host": "127.0.0.1",
    "broker_port": 1883,
    "topic_prefix": "/projects/remote-rover",
    "control_topic": "control/manual",
    "state_topic": "telemetry/state",
    "camera_topic": "camera-feed"
  },
  "video": {
    "enabled": true,
    "ingest_mode": "mqtt_frames",
    "delivery_mode": "websocket_mjpeg"
  },
  "gcs": {
    "host": "127.0.0.1",
    "port": 8080,
    "telemetry_stale_ms": 2000
  },
  "simulation": {
    "backend": "3d-env",
    "available_backends": ["3d-env", "rover-sim-next"]
  },
  "logging": {
    "replay_db_path": "data/gcs_replay.sqlite3"
  }
}
```

## Runtime Structure

Main modules:

- `app.py`: FastAPI app, HTTP routes, WebSocket endpoint, lifespan wiring
- `runtime.py`: runtime assembly for services
- `scene_map.py`: replay scene-map payload from the shared terrain manifest
- `mqtt_service.py`: MQTT connect/subscribe/publish logic
- `control.py`: control loop and held-button publishing
- `state.py`: local in-memory runtime state and freshness tracking
- `replay_store.py`: SQLite session logging and replay data access
- `telemetry.py`: normalized telemetry shaping for replay and UI consistency
- `ws.py`: WebSocket connection manager
- `video.py`: MQTT camera frame decoding helper
- `static/`: browser UI assets
  - `index.html` + `app.js`: dashboard UI
  - `mqtt-setup.html` + `mqtt-setup.js`: MQTT setup/config UI
  - `replay.html` + `replay.js`: replay page and playback UI

## Browser Control Flow

1. Browser opens `/ws`
2. GCS sends initial runtime snapshot
3. Focused and visible browser dashboard becomes the active controller
4. Browser sends control button states over WebSocket while it remains the active controller
5. GCS publishes digital control frames to MQTT at `control_hz`
6. Browser blur or hidden state clears inputs and deactivates browser control
7. Telemetry is normalized and persisted for replay
8. Telemetry and camera frames received from MQTT are broadcast to connected browsers

## Control Regression Notes

See [docs/gcs_server/regressions.md](../docs/gcs_server/regressions.md) for pinned one-line control invariants that should not regress.

## MQTT Setup Flow

1. Browser opens `/setup/mqtt`
2. GCS returns current MQTT config from shared settings file (`/api/mqtt-config`)
3. User edits host/port/topics/control rate and saves
4. User can also select the active simulator backend identity
5. GCS writes updated shared config and reconnects MQTT runtime immediately
6. Dashboard broker status updates via WebSocket broadcast

## Replay Model

Implemented now:
- GCS records sessions to SQLite
- telemetry, control frames, runtime events, and camera timing metadata are recorded
- `/api/replay/sessions` lists sessions
- `/api/replay/sessions/{session_id}` returns session timeline detail
- `/replay` provides the first playback UI

Not implemented yet:
- recorded video playback
- simulator-origin log import path
- live dashboard map sharing the same playback/live model

## Video Pipeline Model

The GCS uses separate ingest and delivery modes.

Current implemented mode:
- ingest: `mqtt_frames`
- delivery: `websocket_mjpeg`

Planned future modes:
- ingest: `rtp_udp`, `rtsp`, `whip`
- delivery: `webrtc_direct`, `webrtc_sfu`

## Current Priority

The current bootstrap path is functional:
- browser sends control to GCS
- GCS publishes MQTT control frames
- simulator publishes telemetry and JPEG camera frames
- GCS relays telemetry and frames to browsers

The next work is:
- simulator-side logging
- live map on the main dashboard
- actual `rover-sim-next` backend implementation
- future synchronized recorded video support

## Repository Note

`gcs_server/` is tracked under the parent `remote-rover/` repository root.

That is the intended structure for ongoing development.
