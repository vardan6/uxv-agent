# mav-sim — Design

## Protocol decisions

### Why protocol-agnostic name — RESEARCHED

**Source:** MAVLink, MAVSDK, and ROS2/MAVROS documentation, confirmed 2026-06-03.

The directory name `mav-sim` (not `mavlink-sim` or `mavlink-monitor`) reflects that the simulator
will eventually speak multiple protocols:

| Protocol | Status | Notes |
|---|---|---|
| MAVLink UDP | Phase 1 | Raw packets via pymavlink, port 14550 |
| MAVSDK gRPC | Phase 5 | Real `grpc.aio` server (off by default) serving a minimal self-contained proto — NOT the official MAVSDK plugin proto set (that is the large C++ `mavsdk_server` API). MAVSDK is its own gRPC+protobuf layer, not a thin MAVLink wrapper. See Phase 5 section below. |
| ROS2 / MAVROS | Stub | Registered as a disabled transport only; MAVROS is a MAVLink-to-ROS gateway needing a full ROS2 install, not a separate wire protocol. |
| MSP | Not planned | MultiWii Serial Protocol — FPV racing only, not relevant here |

MAVLink (ArduPilot + PX4) is the dominant GCS↔FC protocol for both aerial and ground
vehicles. ArduPilot Rover uses MAVLink identically to ArduCopter.

### MAVLink UDP port

**14550** — confirmed standard for PX4, ArduPilot, QGroundControl, and MAVProxy.
GCS adapters connect with `udpout:` and the receiver binds with `udpin:`.

In pymavlink: `mavutil.mavlink_connection('udpin:0.0.0.0:14550')`.

### Mission upload wire sequence — RESEARCHED

**Source:** MAVLink mission protocol specification, confirmed 2026-06-03.

```
GCS → FC   MISSION_COUNT (msg 44)        count = N items
FC  → GCS  MISSION_REQUEST_INT (msg 51)  seq = 0
GCS → FC   MISSION_ITEM_INT (msg 73)     seq = 0, lat/lon as int32×10⁷
FC  → GCS  MISSION_REQUEST_INT           seq = 1
GCS → FC   MISSION_ITEM_INT             seq = 1
...repeat for each item...
FC  → GCS  MISSION_ACK (msg 47)          type = 0 (MAV_MISSION_ACCEPTED)
```

Error: FC sends `MISSION_ACK` with `type ≠ 0` at any point to abort.

Key display fields per message: `message_id`, `system_id`, `component_id`, `seq`,
and for mission items: `command` (MAV_CMD enum), `lat`/`lon` (int32), `alt` (float m).

### Mission start

`COMMAND_LONG` (msg 76) with `command = 300` (MAV_CMD_MISSION_START) on PX4, or
`SET_MODE` to AUTO on ArduPilot.

### Pause mechanism — RESEARCHED

**Source:** QGroundControl and ArduPilot Mission Planner behaviour, confirmed 2026-06-03.

Both QGC and Mission Planner pause via **mode switch to Hold/Loiter** — not via
`MAV_CMD_DO_PAUSE_CONTINUE` (cmd 193). The latter has inconsistent firmware support
across ArduPilot and PX4 firmware versions.

- pymavlink: `SET_MODE → HOLD`
- MAVSDK: `system.action.hold()`

Resume = switch back to AUTO. Firmware continues from **next waypoint in sequence**
(both ArduPilot and PX4 default — no rewind). This is consistent across ArduCopter,
ArduPlane, and ArduRover.

### Stop behavior

Hold in place (same mode switch as pause). Does not trigger RTL. Operator takes manual
control after stop. GCS marks mission `aborted`.

---

## Architecture

```
UDP:14550
    │
    ▼
mavlink_listener.py
  - pymavlink mavutil.mavlink_connection('udpin:0.0.0.0:14550')
  - decode incoming packets into message dicts
  - push to in-memory queue
    │
    ▼
app.py (FastAPI + uvicorn + native WebSocket)
  - async drain task pulls from queue, broadcasts to all connected browser clients
  - transport manager reports active protocol services and owns future multi-protocol startup
  - serves static web UI on port 9010
    │
    ▼
Browser (port 9010)
  - WebSocket client receives message events
  - renders message feed (newest on top)
```

### Response behavior (Phases 1–4 implemented)

- **Phase 1 — monitor**: listener decodes and displays; no responses.
- **Phase 3 — handshake**: `mavlink_listener._handle_protocol` responds to `MISSION_COUNT` + `MISSION_ITEM_INT` with `MISSION_REQUEST_INT` per item then `MISSION_ACK(ACCEPTED)`; tracks upload state; `simulate_execution` emits `MISSION_ITEM_REACHED` + `GLOBAL_POSITION_INT` per waypoint.
- **Phase 4 — telemetry**: `GLOBAL_POSITION_INT` messages are also received by the GCS-side `MavlinkTelemetryBridge` (`backend/mavlink_telemetry.py`) and broadcast as normalized telemetry; `BasemapPanel` renders a live GPS vehicle marker via its own GCS WebSocket subscription.

### Phase 5 — multi-protocol (implemented)

- `transport_manager.py` is the protocol-service registry for `mav-sim`, holding three services: `mavlink_udp` (running), `mavsdk_grpc`, and `ros2_mavros`.
- MAVLink UDP remains the always-on transport implementation.
- **MAVSDK gRPC** is now a *real* `grpc.aio` server (`grpc_service.py`), gated by `config.MAVSDK_GRPC_ENABLED` (off by default). When enabled, `MavsdkGrpcService.start()` lazily imports grpc and boots the server on its own asyncio loop in a daemon thread; status flips to `running`/`error` based on liveness. `grpc` is imported lazily so the base monitor runs without grpcio installed.
- The gRPC surface is **deliberately not** the official MAVSDK plugin proto set (that is the large C++ `mavsdk_server` API). It is a small self-contained service in `proto/mav_sim.proto` (`GetInfo`, `GetMission`, `SubscribeTelemetry`) mirroring the simulator's in-memory state so a client can connect and read/stream real data. Regenerate stubs with `python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/mav_sim.proto`.
- **ROS2 / MAVROS** is registered as a disabled stub only (`RosBridgeService`, `config.ROS2_BRIDGE_ENABLED`). MAVROS is a MAVLink-to-ROS gateway, not a separate wire protocol, and needs a full ROS2 install; advertised via `/api/transports` but not implemented.
- `GET /api/transports` exposes the live transport snapshot for UI/runtime inspection.

---

## Message feed UI

Each line: `[timestamp] [MSG_TYPE] summary`

Example:
```
14:23:01.442  MISSION_COUNT        count=5  system=1  component=0   ← flash
14:23:01.448  MISSION_ITEM_INT     seq=0  cmd=16 (NAV_WAYPOINT)  lat=37.7749  lon=-122.4194
14:23:01.451  MISSION_ITEM_INT     seq=1  cmd=16  lat=37.7751  lon=-122.4201
...
14:23:01.471  MISSION_ACK          type=0 (ACCEPTED)
```

Flash animation: CSS `@keyframes` highlight fade on the new top row (green → transparent,
~800 ms). No JS animation library needed.

### Phase 1 features
- Message feed, newest message on top, one line per message
- Timestamp per message (HH:MM:SS.mmm)
- Message type + key field summary per line
- Flash animation on new message arrival
- Clear all button

### Phase 2 features
- Expandable lines — click to see all decoded MAVLink fields
- Message selection (checkbox per line)
- Delete selected messages
- Cleanup by date

---

## Future: full autopilot simulator

When `mav-sim` grows into a full simulator it will:

1. Complete the MAVLink handshake (send `MISSION_ACK` after upload)
2. Track current waypoint index, advance on simulated arrival
3. Emit `GLOBAL_POSITION_INT` telemetry to GCS (simulated vehicle position on map)
4. Emit `MISSION_ITEM_REACHED` when each waypoint is hit
5. Implement MAVSDK gRPC server interface
6. Render vehicle model on GCS map widget

At that point `mav-sim` becomes a SITL-equivalent without requiring ArduPilot or PX4
build toolchains.
