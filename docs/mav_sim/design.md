# mav_sim — Design

## Protocol decisions

### Why protocol-agnostic name — RESEARCHED

**Source:** MAVLink, MAVSDK, and ROS2/MAVROS documentation, confirmed 2026-06-03.

The name `mav_sim` (not `mavlink_sim` or `mavlink_monitor`) reflects that the simulator
will eventually speak multiple protocols:

| Protocol | Status | Notes |
|---|---|---|
| MAVLink UDP | Phase 1 | Raw packets via pymavlink, port 14550 |
| MAVSDK gRPC | Future | MAVSDK is NOT a thin MAVLink wrapper — it has its own gRPC+protobuf layer (C++ core with language bindings). Requires separate gRPC server implementation. |
| ROS2 / MAVROS | Future | MAVROS is a MAVLink-to-ROS gateway; still MAVLink underneath. Not a separate wire protocol. |
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
app.py (Flask + Flask-SocketIO)
  - background thread drains queue
  - broadcasts message events to all connected browser clients via WebSocket
  - serves static web UI on port 9010
    │
    ▼
Browser (port 9010)
  - WebSocket client receives message events
  - renders message feed (newest on top)
```

### Phase 1 only (monitor, no response)

The listener decodes and displays. It does NOT send `MISSION_ACK` or any response back
to the GCS. The GCS adapter will time out waiting for an ACK — this is expected in
monitor-only mode.

To use as a drop-in FC substitute (full handshake), Phase 2+ will add response logic.

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

When `mav_sim` grows into a full simulator it will:

1. Complete the MAVLink handshake (send `MISSION_ACK` after upload)
2. Track current waypoint index, advance on simulated arrival
3. Emit `GLOBAL_POSITION_INT` telemetry to GCS (simulated vehicle position on map)
4. Emit `MISSION_ITEM_REACHED` when each waypoint is hit
5. Implement MAVSDK gRPC server interface
6. Render vehicle model on GCS map widget

At that point `mav_sim` becomes a SITL-equivalent without requiring ArduPilot or PX4
build toolchains.
