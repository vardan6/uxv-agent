# mav_sim

MAVLink simulator and monitor. Starts as a mission upload monitor with a live web UI;
roadmap target is a full bidirectional autopilot simulator (receive missions, simulate
vehicle position, stream telemetry back to GCS).

## Ports

| Service | Port | Protocol |
|---|---|---|
| MAVLink UDP listener | 14550 | UDP (standard FC port) |
| Web UI | 9010 | HTTP + WebSocket |
| MAVSDK gRPC seam | 50051 | gRPC placeholder, disabled by default |

Point the GCS adapter at `udp:127.0.0.1:14550` to route mission uploads here instead
of (or alongside) a real FC.

## Current phase: monitor

Receives MAVLink packets, decodes them, streams to a browser-based message feed.
Phase 5 now also boots a transport manager that reports protocol status and reserves
the MAVSDK gRPC integration point without pretending the service surface exists yet.

### Web UI features

**Phase 1 (first implementation):**
- Message feed — newest message on top, one line per message
- Timestamp per message
- Message type + summary on each line
- Flash animation when a new message arrives
- Clear all button

**Phase 2:**
- Expandable lines — click to see all decoded MAVLink fields
- Message selection (checkbox per line)
- Delete selected messages
- Cleanup by date

## Roadmap: full autopilot simulator

Future phases will turn `mav_sim` into a full MAVLink node that:
- Responds to mission uploads with proper `MISSION_ACK` handshake
- Simulates vehicle position and streams `GLOBAL_POSITION_INT` telemetry back to GCS
- Renders vehicle position on the GCS map widget
- Supports mission execution: advances waypoints, emits `MISSION_ITEM_REACHED`
- Adds MAVSDK gRPC interface alongside raw MAVLink
- Potentially adds ROS2/MAVROS bridge

## Phase 5 transport seam

- `GET /api/transports` returns the active transport snapshot
- Raw MAVLink UDP is reported as the running transport
- MAVSDK gRPC is represented as a disabled-by-default stub service
- Set `MAVSDK_GRPC_ENABLED = True` in `config.py` to exercise the stubbed startup path

See [`docs/mav_sim/design.md`](../docs/mav_sim/design.md) for protocol and architecture decisions.

## Structure

```
mav_sim/
├── app.py          — FastAPI app + native WebSocket server (port 9010)
├── config.py       — port config, MAVLink settings
├── mavlink_listener.py  — UDP listener, packet decoder (pymavlink)
├── transport_manager.py — protocol-service registry and Phase 5 MAVSDK seam
├── requirements.txt
├── run.sh
└── docs/
    └── design.md   — protocol decisions, architecture
```
