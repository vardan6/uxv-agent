# Mission Execution Implementation

Status date: 2026-05-22.
Status: backend foundation, controller adapter seam, and full waypoint mutation API surface implemented; real external controller transport still pending.

## Purpose

This document describes the current implementation of the backend-owned
`mission_execution` boundary in `gcs_server/`.

Use this document for implementation reality.
See [../requirements.md](../requirements.md) for the product requirement
and [../design.md](../design.md) (§ "Mission Execution Boundary") for
the broader design intent.

## What Exists Now

Implemented now:

- canonical mission revision storage in `gcs_server/ai/mission_execution_service.py`
- current mission-state lookup and current revision lookup
- overlay payload generation from stored revisions, now including per-waypoint `provenance` (`ai` / `user` / `ai+edited`)
- synchronization from draft approval/rejection/export into mission revision state
- durable controller mission snapshot state in SQLite
- durable execution-attempt records in SQLite
- optimistic controller-version compare-and-swap checks on execution
- optimistic client-version concurrency checks on waypoint mutation (stale-edit detection)
- rollback-ready verified/previous-verified controller snapshots
- injected controller mission adapter seam used for install/read-back verification
- client-authored revision creation with provenance inheritance
- waypoint update, insert, and delete with automatic provenance promotion
- explicit execution and mutation APIs in `gcs_server/app.py`

Current API surface:

- `GET /api/ai/mission-revisions`
- `GET /api/ai/mission-revisions/current`
- `GET /api/ai/mission-revisions/{revision_id}`
- `GET /api/ai/mission-revisions/{revision_id}/overlay`
- `GET /api/ai/mission-overlays/current`
- `GET /api/ai/controller-mission`
- `POST /api/ai/mission-revisions` — create client-authored revision
- `POST /api/ai/mission-revisions/{revision_id}/execute`
- `PATCH /api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}` — update geometry; promotes to `ai+edited`
- `POST /api/ai/mission-revisions/{revision_id}/waypoints` — insert waypoint; provenance = `user`
- `DELETE /api/ai/mission-revisions/{revision_id}/waypoints/{waypoint_index}`

Approval compatibility path:

- `POST /api/ai/mission-drafts/{draft_id}/approve`
  - still approves the legacy mission draft
  - synchronizes approval/export into `mission_execution`
  - can optionally call execution immediately with `execute_after_approval`

## What The Current Adapter Really Does

The current execution adapter is real in the sense that mission install and
read-back now happen through an explicit adapter boundary, but the default
adapter is still local and not yet connected to an external flight
controller.

Current execution flow:

1. Operator or caller approves a draft and exports it to QGC `.plan`.
2. A caller invokes `POST /api/ai/mission-revisions/{revision_id}/execute`
   with an optional `expected_controller_version`.
3. `MissionExecutionService.execute_revision()` loads the stored revision
   and exported `.plan` file.
4. The service checks the current live controller mission version through the
   configured controller adapter.
5. On version match, it records a pending controller snapshot and marks the
   revision/operation `cutover_pending`.
6. The adapter installs the mission and performs read-back verification
   against controller-owned state outside the SQLite audit tables.
7. On success, the controller mission version increments and the revision
   becomes `executing`, and SQLite is updated to reflect the verified
   controller state.
8. On failure, the service restores the previous verified snapshot if one
   exists at the adapter boundary when possible and records a
   failed/rolled-back execution attempt in SQLite.

This gives the codebase a real backend execution seam with:

- explicit version checks
- explicit install/read-back adapter boundary
- explicit execution attempts
- explicit verification state
- explicit rollback-ready snapshots

It does **not** yet provide:

- MAVLink upload
- autopilot read-back
- controller-native mission normalization
- external-controller truth
- automatic rebase after stale-version rejection

## Data Model

Implemented migrations:

- migration `003`: `ai_mission_operations`, `ai_mission_revisions`
- migration `004`: `ai_mission_controller_state`, `ai_mission_execution_attempts`
- migration `005`: `client_version INTEGER NOT NULL DEFAULT 0` and `provenance_json TEXT NOT NULL DEFAULT '{}'` added to `ai_mission_revisions`

Primary tables:

- `ai_mission_operations`
  - top-level mission-affecting operation record
  - tracks `status`, `active_revision_id`, and stored policy JSON
- `ai_mission_revisions`
  - canonical stored revision records
  - stores mission payload, intent, target resolution, validation, and review context
  - `client_version`: monotonically incremented on each waypoint mutation; used for stale-edit detection
  - `provenance_json`: `{waypoint_id: "ai" | "user" | "ai+edited"}` map; returned per-waypoint in overlay payloads
- `ai_mission_controller_state`
  - backend projection of controller mission state
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

## Main Files

- `gcs_server/ai/mission_execution_service.py`
  - mission revision lifecycle
  - overlay generation
  - controller mission projection
  - execution attempts
- `gcs_server/ai/controller_mission_adapter.py`
  - controller adapter protocol
  - default local file-backed adapter
- `gcs_server/ai/migrations.py`
  - schema migrations `003`, `004`, and `005`
- `gcs_server/app.py`
  - mission revision, overlay, controller-state, and execute endpoints
- `gcs_server/runtime.py`
  - wires `MissionExecutionService` and the default controller adapter into the app runtime
- `gcs_server/ai/planning_shell_graph.py`
  - synchronizes stored planning artifacts into `mission_execution`

## Relationship To Legacy Draft Flow

The codebase is in a migration period.

Current reality:

- `MissionDraftService` still exists and remains part of the current
  planning-shell approval/export flow
- `mission_execution` now owns backend mission revision state and execution
  state
- approval/export events are synchronized from the draft layer into the
  mission-execution layer

This means authoritative ownership is improved but not yet fully collapsed
into one path.

## Remaining Gaps

The most important missing pieces are:

- replace the default local file-backed adapter with real external
  controller/MAVLink upload + read-back verification
- route more approval/cutover behavior directly through `mission_execution`
  rather than legacy draft-flow compatibility code
- project controller mission state and execution status more directly into
  the `/ai` UI
- implement stale-version rebase/revision workflows
- make the planner-loop path the default mission-planning runtime
