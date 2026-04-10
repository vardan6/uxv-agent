# Ground Control Station (GCS) Web App

> Historical product/spec note.
> For the current documentation set, start with:
> - `../docs/README.md`
> - `../docs/gcs_server/README.md`
> - `../docs/gcs_server/technical-details.md`

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
- automatic control request on dashboard connect
- keyboard and on-screen controls
- broker state and freshness display
- configurable video ingest/delivery modes
- MQTT camera frame subscription and browser rendering path
- simulator-side MQTT camera frame publication
- dedicated MQTT setup page (`/setup/mqtt`)
- live broker/topic/control-rate update API (`/api/mqtt-config`) with runtime reconnect
- appearance settings (theme mode + light/dark theme variants) persisted in browser storage

Not implemented yet:
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
- Dashboard status banner for control, broker, and theme state feedback
- Broker connection/freshness visibility without artificial ping traffic
- One active controller, multiple monitoring clients
- Video transport modeled as separate ingest and delivery modes
- Browser-based MQTT setup and runtime reconnect workflow
- Persisted light/dark/system theme preferences

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

The setup page can update the live `mqtt.*` section and the GCS reconnects without process restart.

## Main Gap To Close Next

The next gap is not feature bootstrap but hardening:
- validate the current MQTT-frame video path under disconnect/reconnect conditions
- keep `mqtt_frames -> websocket_mjpeg` as a bootstrap/debug path
- add a production media path later without breaking the current fallback
- move from memory-only state/lock backend to Redis if multi-instance operation is needed
