# Remote Rover GCS

`gcs_server/` is the browser-facing Ground Control Station for the Remote Rover project.

It is a Python FastAPI application with a static frontend. It connects to the same MQTT broker as the simulator, subscribes to rover telemetry and camera topics, publishes control commands, and serves a browser UI for monitoring and manual driving.

## Current Features

- Live telemetry dashboard
- Broker status and topic freshness status
- Controller lock: one active browser controls, others observe
- Keyboard control via arrow keys and `W/A/S/D`
- On-screen control buttons with immediate active-state feedback
- Configurable video pipeline modes
- MQTT camera-frame ingest and WebSocket MJPEG-style browser delivery

## Current Limitations

- Simulator camera frame publishing is not implemented yet, so the GCS video panel will remain empty until a publisher sends frames to `mqtt.camera_topic`
- State backend is in-memory only
- No authentication or authorization
- No WebRTC transport yet

## Dependencies

Install from the workspace root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
pip install -r requirements-gcs.txt
```

## Run

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python -m gcs_server
```

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
    "telemetry_stale_ms": 2000,
    "controller_lease_ms": 3000
  }
}
```

## Runtime Structure

Main modules:

- `app.py`: FastAPI app, HTTP routes, WebSocket endpoint, lifespan wiring
- `runtime.py`: runtime assembly for services
- `mqtt_service.py`: MQTT connect/subscribe/publish logic
- `control.py`: control loop, held-button publishing, controller lease renewal
- `state.py`: local in-memory runtime state and freshness tracking
- `ws.py`: WebSocket connection manager
- `video.py`: MQTT camera frame decoding helper
- `static/`: browser UI assets

## Browser Control Flow

1. Browser opens `/ws`
2. GCS sends initial runtime snapshot
3. User clicks `Take Control`
4. Browser sends control button states over WebSocket
5. GCS publishes digital control frames to MQTT at `control_hz`
6. Active controller lease is renewed while held input is being published
7. Telemetry and camera frames received from MQTT are broadcast to connected browsers

## Video Pipeline Model

The GCS uses separate ingest and delivery modes.

Current implemented mode:
- ingest: `mqtt_frames`
- delivery: `websocket_mjpeg`

Planned future modes:
- ingest: `rtp_udp`, `rtsp`, `whip`
- delivery: `webrtc_direct`, `webrtc_sfu`

## Repository Note

`gcs_server/` is now tracked under the parent `remote-rover/` repository root.

That is the intended structure for ongoing development.
