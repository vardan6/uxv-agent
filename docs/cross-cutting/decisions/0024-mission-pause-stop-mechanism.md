# 0024. Mission Pause/Stop: Mode Switch Over MAV_CMD_DO_PAUSE_CONTINUE

Date: 2026-06-03
Status: Accepted

## Context

The mission execution controls feature (planned 2026-06-03) adds play, pause, and stop
buttons to the mission sidebar. Pause must command the FC to hold the vehicle at its
current position mid-mission. Two MAVLink mechanisms exist:

**Option A — `MAV_CMD_DO_PAUSE_CONTINUE` (command 193)**
A dedicated pause command. `param1=0` pauses, `param1=1` resumes. Designed exactly for
this use case — pauses the mission sequencer without exiting AUTO mode.

**Option B — Mode switch to HOLD/LOITER**
Send `SET_MODE` (or equivalent) to switch the vehicle out of AUTO into a holding flight
mode. The vehicle hovers or holds position. To resume, switch back to AUTO.

## Research

QGroundControl and ArduPilot Mission Planner were reviewed (2026-06-03). Both pause via
**mode switch to HOLD/Loiter**, not via `MAV_CMD_DO_PAUSE_CONTINUE`. Community reports
confirm `DO_PAUSE_CONTINUE` has inconsistent support across ArduPilot and PX4 firmware
versions — some versions ignore it, others handle it differently per vehicle type
(Copter vs Plane vs Rover).

MAVSDK exposes `system.action.hold()` which maps to the mode-switch approach, not
`DO_PAUSE_CONTINUE`.

## Decision

Use **mode switch to HOLD** for pause and stop:

- **Pause:** `SET_MODE → HOLD` (pymavlink) / `system.action.hold()` (MAVSDK)
- **Resume:** switch back to AUTO; firmware continues from the next waypoint in sequence
  (confirmed default for ArduPilot and PX4 — no rewind)
- **Stop:** same HOLD mode switch; GCS marks mission `aborted`; does not trigger RTL

For mock adapters (`json_file`, `file_sink`, `mav_sim`): pause and stop are no-ops or
logged events — no FC command is sent.

## Consequences

- Pause exits AUTO mode, matching industry GCS behaviour (QGC, Mission Planner)
- Resume continues from next waypoint — the vehicle may skip part of the segment it was
  on when paused; this is the firmware default and matches operator expectations from
  other GCS tools.
  **Caveat (added 2026-06-04):** resume-from-next is *parameter-dependent*, not
  unconditional. On ArduPilot it is governed by `MIS_RESTART` / `AUTO_RESUME` — if those
  select restart, switching back to AUTO replays the mission from the beginning. The
  MAVLink adapter must read (and assert/set) this parameter on connect rather than
  assuming the default, or a real FC may restart on resume.
- `MAV_CMD_DO_PAUSE_CONTINUE` is not used here and should not be added without a firmware
  compatibility audit. (Note: ArduPilot Copter later added support via PR #19317; the
  inconsistency across firmware/vehicle types is what we are avoiding, not a claim it is
  universally absent.)
- MAVSDK implementation is straightforward (`action.hold()` / back to mission)
- pymavlink implementation requires a `SET_MODE` send + confirmation

## Alternatives Considered

- **`MAV_CMD_DO_PAUSE_CONTINUE`** — rejected: inconsistent firmware support confirmed
  by research; QGC and Mission Planner both abandoned it in favour of mode switches.
- **RTL on stop** — rejected: RTL causes autonomous motion in potentially unexpected
  direction. Hold is safer — vehicle stays put until operator takes manual control.
- **GCS-side only pause (no FC command)** — rejected: vehicle continues executing its
  loaded mission autonomously; a GCS-side state change has no effect on the rover.
