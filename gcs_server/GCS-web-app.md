# Ground Control Station (GCS) Web App

## Purpose

The Ground Control Station is the browser-based operator interface for the Remote Rover system.

It is intended to:
- display rover telemetry and status
- provide manual control from the browser
- show rover camera output
- expose MQTT/broker health information
- support multiple browser clients, with one active controller and additional observers

## Current Implementation Status

Implemented:
- separate `gcs_server/` application outside `3d-env/`
- FastAPI backend with static browser UI
- MQTT telemetry subscription
- MQTT control publication
- browser controller lock
- keyboard and on-screen controls
- broker state and freshness display
- configurable video ingest/delivery modes
- MQTT camera frame subscription and browser rendering path

Not implemented yet:
- simulator camera frame publishing
- WebRTC transport
- Redis-backed state sharing
- authentication

## Current Architecture

```text
Browser
  -> WebSocket / HTTP
GCS (`gcs_server/`)
  -> MQTT
Simulator (`3d-env/simulator/`) and future real rover
```

The GCS is the control-plane server for browser clients.
Browsers do not publish directly to MQTT.

## Key Features

- Live rover dashboard
- Manual driving controls
- Keyboard bindings: arrow keys and `W/A/S/D`
- On-screen control buttons with active press indication
- Broker connection/freshness visibility without artificial ping traffic
- One active controller, multiple monitoring clients
- Video transport modeled as separate ingest and delivery modes

## Video Design

Current implemented video model:
- ingest: `mqtt_frames`
- delivery: `websocket_mjpeg`

Planned modes:
- ingest: `rtp_udp`, `rtsp`, `whip`, `disabled`
- delivery: `webrtc_direct`, `webrtc_sfu`, `disabled`

Current MQTT camera topic:
- `{topic_prefix}/{camera_topic}`
- default: `/projects/remote-rover/camera-feed`

## Shared Config

The GCS currently reads from:
- `config/common.local.json` if present
- otherwise `config/common.example.json`

Important config sections:
- `mqtt.*`
- `video.*`
- `gcs.*`

## Main Gap To Close Next

The highest-value next implementation step is adding simulator camera frame publication to `mqtt.camera_topic` so the current GCS video path becomes fully end-to-end.
