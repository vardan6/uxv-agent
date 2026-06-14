# mav_sim

MAVLink simulator and monitor. Starts as a mission upload monitor with a live web UI;
roadmap target is a full bidirectional autopilot simulator (receive missions, simulate
vehicle position, stream telemetry back to GCS).

## Ports

| Service | Port | Protocol |
|---|---|---|
| MAVLink UDP listener | 14550 | UDP (standard FC port) |
| Web UI | 9010 | HTTP + WebSocket |
| MAVSDK gRPC server | 50051 | gRPC (`grpc.aio`), disabled by default |

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

## Phase 5 transports (multi-protocol)

- `GET /api/transports` returns the live snapshot of all registered transports.
- Raw MAVLink UDP is the always-on transport.
- **MAVSDK gRPC** is a real `grpc.aio` server (`grpc_service.py`), **off by default**.
  Set `MAVSDK_GRPC_ENABLED = True` in `config.py` and install `grpcio` to boot it
  on port 50051. It serves the small `proto/mav_sim.proto` surface (`GetInfo`,
  `GetMission`, `SubscribeTelemetry`) — not the full MAVSDK plugin API. Regenerate
  stubs with:
  `python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/mav_sim.proto`
- **ROS2 / MAVROS** is a disabled stub (`ROS2_BRIDGE_ENABLED`); MAVROS needs a full
  ROS2 install and is advertised but not implemented.

See [`docs/mav_sim/design.md`](../docs/mav_sim/design.md) for protocol and architecture decisions.

## Structure

```
mav_sim/
├── app.py          — FastAPI app + native WebSocket server (port 9010)
├── config.py       — port config, MAVLink settings
├── mavlink_listener.py  — UDP listener, packet decoder (pymavlink)
├── transport_manager.py — protocol-service registry (UDP / gRPC / ROS2)
├── grpc_service.py  — real grpc.aio server for the MAVSDK seam (Phase 5)
├── proto/
│   └── mav_sim.proto    — gRPC service definition
├── mav_sim_pb2.py / mav_sim_pb2_grpc.py — generated stubs (committed)
├── requirements.txt
├── run.sh
└── docs/
    └── design.md   — protocol decisions, architecture
```
