# Mission Execution

## Purpose

This document defines the backend-owned `mission_execution` boundary.
See [../requirements.md](../requirements.md) for product behavior and
[../design.md](../design.md) (§ "Mission Execution Boundary") for system context.

## Data Model

Primary tables:

- `ai_mission_operations`
  - top-level mission-affecting operation record
  - tracks `status`, `active_revision_id`, and stored policy JSON
- `ai_mission_revisions`
  - canonical stored revision records and mission payload
  - `client_version`: monotonically incremented on each waypoint mutation; used for optimistic stale-edit detection
  - `provenance_json`: `{waypoint_id: "ai" | "user" | "ai+edited"}` map; returned per-waypoint in overlay payloads
- `ai_mission_controller_state`
  - backend projection of controller mission state and cutover lifecycle
  - tracks current controller mission version, active revision, verified snapshot, previous verified snapshot, pending snapshot, and last cutover metadata
- `ai_mission_execution_attempts`
  - append-only execution/cutover attempt log
  - tracks expected version, observed version, installed version, status, request payload, result payload, and error text

## Status Model

User-facing states and sidebar button layout: see [GCS requirements §Mission Row Button Layout](../../gcs/requirements.md#mission-row-button-layout).

### Internal revision/operation statuses (backend pipeline)

Used by the execution service and adapter pipeline. Not shown in the sidebar UI.

- `planning`
- `exported`
- `cutover_pending` — transient: set immediately before `install_mission()` is called; lasts milliseconds, transitions to `executing` or rolls back on failure
- `executing`
- `paused` — vehicle holding at current position; GCS-side pause state
- `aborted` — stopped by operator; terminal
- `rejected`
- `validation_failed`
- `needs_clarification`

**Removed:** `awaiting_approval` and `approved` — dropped per ADR 0021. The
two-approval model (ADR 0002) is superseded. The `approved_at` DB column is retained
as a dead no-op (SQLite full-table rebuild not justified). No new code should reference
these statuses.

### Controller-state statuses

- `idle`
- `verifying`
- `executing`
- `rolled_back`
- `cutover_failed`

## Provenance State Machine (Per Waypoint)

Waypoints use a strict provenance model:

- `ai`: created by planning output without manual edits
- `user`: created directly by the operator
- `ai+edited`: originally AI-created, then operator-modified

Promotion rule:

- any operator edit to an `ai` waypoint promotes it to `ai+edited`

Regeneration guard:

- AI regeneration that would overwrite `ai+edited` waypoints is blocked
  unless the operator explicitly confirms replacement via clarification flow

## Concurrency Rules

Two optimistic concurrency controls protect mission state:

- `client_version` guards revision mutation:
  mutation requests must target the latest client version, else the request is rejected as stale
- `controller_version` guards execution cutover:
  execution checks expected live controller version before install/read-back

Stale-cutover handling:

- when execution rejects on stale controller version, the system creates a rebased revision for re-review against latest verified controller state

## Adapter Boundary Contract

Mission installation and read-back verification must pass through a controller adapter boundary.
This boundary is the seam for controller transport implementations.

Required adapter semantics:

- compare controller mission version before cutover
- install mission payload
- verify installed mission by read-back
- clear the controller-owned mission (Read → empty Write → read-back verify), resetting to an idle version-0 state
- probe link health (heartbeat reachable + mission readable) without mutating controller state
- **pause** — hold vehicle in place mid-mission (mode switch to HOLD, see [ADR 0024](../../../cross-cutting/decisions/0024-mission-pause-stop-mechanism.md))
- **resume** — continue from next waypoint in sequence (firmware default)
- **stop** — hold in place, GCS marks mission `aborted`; does not trigger RTL (ADR 0024)
- surface failure details for audit and rollback logic

Transports: `json_file` (local simulation, default), `file_sink` (write uploads to
`data/fc_sink/` as timestamped JSON files, for development without a real FC or
`mav_sim`), plus real external links over pymavlink and MAVSDK (`MissionRaw`). External
links take a connection URL + heartbeat/request timeouts; the version compared before
cutover is a CRC over the normalized mission items. The default local adapter is
implementation detail; contract behavior is stable regardless of transport.

The adapter type and connection URL are configurable from `Settings → Mission Lifecycle`.
The AI chat tool `set_session_adapter` overrides the adapter for the current session only (in-memory, reverts on session end, does not change persisted config).
For development monitoring, point the mavlink adapter at `mav_sim` (UDP 14550) to see
all mission traffic in the `mav_sim` web UI (port 9010). See [`docs/mav_sim/design.md`](../../../mav_sim/design.md).

Navigation-leaf command subset (export): a `.plan` waypoint may carry optional
per-leaf fields that emit additional MAVLink items — `speed_mps` → `DO_CHANGE_SPEED`,
`roi:{lat,lon[,alt]}` → `DO_SET_ROI` (both inserted ahead of the nav leaf), and
`loiter_time_s` → the nav leaf becomes `NAV_LOITER_TIME` instead of `NAV_WAYPOINT`.
`DO_JUMP` is intentionally not emitted — loop structure belongs to the behavior tree
(ADR 0023). `doJumpId` is a single 1-based running sequence across all emitted items.
