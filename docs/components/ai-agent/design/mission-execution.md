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

Revision/operation statuses currently used by the backend include:

- `planning`
- `awaiting_approval`
- `approved`
- `exported`
- `cutover_pending`
- `executing`
- `rejected`
- `validation_failed`
- `needs_clarification`

Controller-state statuses currently used include:

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

- when execution rejects on stale controller version, the system creates a rebased `awaiting_approval` revision for re-review against latest verified controller state

## Adapter Boundary Contract

Mission installation and read-back verification must pass through a controller adapter boundary.
This boundary is the seam for controller transport implementations.

Required adapter semantics:

- compare controller mission version before cutover
- install mission payload
- verify installed mission by read-back
- clear the controller-owned mission (Read → empty Write → read-back verify), resetting to an idle version-0 state
- probe link health (heartbeat reachable + mission readable) without mutating controller state
- surface failure details for audit and rollback logic

Transports: a local JSON-file stand-in (default), plus real external links over
pymavlink and MAVSDK (`MissionRaw`). External links take a connection URL +
heartbeat/request timeouts; the version compared before cutover is a CRC over the
normalized mission items. The default local adapter is implementation detail;
contract behavior is stable regardless of transport.

Navigation-leaf command subset (export): a `.plan` waypoint may carry optional
per-leaf fields that emit additional MAVLink items — `speed_mps` → `DO_CHANGE_SPEED`,
`roi:{lat,lon[,alt]}` → `DO_SET_ROI` (both inserted ahead of the nav leaf), and
`loiter_time_s` → the nav leaf becomes `NAV_LOITER_TIME` instead of `NAV_WAYPOINT`.
`DO_JUMP` is intentionally not emitted — loop structure belongs to the behavior tree
(ADR 0023). `doJumpId` is a single 1-based running sequence across all emitted items.
