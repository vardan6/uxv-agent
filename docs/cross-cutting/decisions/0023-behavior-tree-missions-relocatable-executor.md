# 0023. Behavior-Tree Missions With A Relocatable Server-Side Executor; FC Mission Upload Is The Navigation-Leaf Layer

Date: 2026-05-30
Status: Accepted

Extends [ADR 0021](./0021-mission-lifecycle.md). Builds on [ADR 0022](./0022-gps-master-coordinate-frame.md).

## Context

Planning the "remake the mission planner, better" effort surfaced a fork in the
mission-content model. Classic GCS missions (ArduPilot/PX4, QGC `.plan`) are a
**linear ordered list** of commands the flight controller steps through, with
only limited conditionals (`DO_JUMP`, `CONDITION_DELAY`, `CONDITION_DISTANCE`).
Modern robot autonomy (e.g. ROS 2 Nav2) models missions as **behavior trees**:
branches, conditions, loops, recovery, operator check-ins.

A flight controller cannot execute a behavior tree — the tree must be run by an
orchestration/autonomy layer that drives the vehicle. Remote Rover already has
such a layer in spirit: the GCS server + AI agent that drives the rover live over
MQTT, governed by ADR 0021's Strict / Confirm / Autonomous modes.

The operator chose the richer model ("best support"), accepting that this
reframes the product from "upload a mission and walk away" to "continuously
execute missions and drive the rover."

## Decision

1. **A Mission's contents are a behavior tree**, not a flat linear list. Nodes
   include navigation leaves (drive waypoints), condition nodes, control-flow
   (sequence / fallback / loop), operator-interaction nodes (e.g. "ask and wait"),
   and recovery branches.

2. **The behavior tree is executed by a server-side executor** (the GCS/AI
   layer), driving the rover live over the existing transport. The executor is
   built as a **self-contained, relocatable module** so it can later be deployed
   onto a companion computer on the rover for true onboard autonomy (roadmap
   direction "(C)").

3. **Flight-controller mission upload is the navigation-leaf layer, not the whole
   mission.** Linear navigation segments (waypoint runs) are compiled down to a
   linear MAVLink/`.plan` mission and run on the FC; the executor orchestrates the
   tree (branches, conditions, loops, check-ins) around those segments. All prior
   FC-handoff work (command vocabulary, protocol adapter, geofence/rally upload)
   remains valid as this leaf layer.

4. **ADR 0021 execution modes now gate a continuous control loop**, not a one-shot
   execute. Strict / Confirm / Autonomous, `arm_execution` / `execute_mission` /
   `cancel_execution` / `abort`, and `expected_controller_version` apply to
   starting and supervising the executor.

5. **Intentional GCS shutdown is an explicit safety action when server-owned
   execution is active.** The GCS warns the operator, identifies the active
   Mission, and requires confirmation before shutdown proceeds. Browser/UI loss
   does not invoke this action. The confirmed post-action and bounded shutdown
   sequence are specified by the follow-up policy work.

## Consequences

- The product is now an autonomy-executing GCS, not just a mission uploader. The
  safety surface is larger: an "autonomous" mission runs as long as the executor
  and link are alive.
- **Link dependency (server-side phase):** until the executor relocates to rover
  hardware, autonomous behavior stops if the network/server drops. Acceptable for
  a connected remote rover and the simulator; a real-rover Open Question.
- ADR 0021 survives: one sidebar row = one Mission (a tree is still one row); flat
  identity, origin, UI states, and chat reference resolution are unchanged. The
  tree is the *inside* of a Mission, which ADR 0021 left unspecified.
- ADR 0019 (per-waypoint provenance) and ADR 0020 (optimistic concurrency) still
  apply to navigation leaves.
- `.plan` export becomes "flatten the navigable portion of the tree," not a
  whole-mission serialization.
- The AI agent must be able to author and edit tree structures, not just waypoint
  lists — a larger tool surface than ADR 0021 sketched.
- **Geofence is defense-in-depth (Phase 5):** the FC is authoritative (uploaded
  inclusion FENCE + RALLY), and the relocatable executor *also* validates every
  nav-leaf waypoint against the fence and refuses before driving. The fence is
  stored **inside mission content** under `geofence` (a
  `mission_safety.parse_geofence` shape) so it versions with the mission and
  `build_mission_executor` reads it with no extra plumbing. The leaf driver uploads
  the fence to the FC once before the first segment. Authored via the
  `set_mission_geofence` AI tool or the BasemapPanel `🛡 Fence` draw mode
  (`POST /api/ai/missions/{id}/geofence`). Storing the fence as a dedicated
  `missions` column instead (decoupled from revision history) is deferred — see
  `roadmap.md` Deferred (option C).
  - **Enforcement policy (decided; resolves the earlier ambiguity):** geofence
    enforcement engages **only when a usable inclusion fence is attached**
    (`enforce = bool(fence is not None and fence.is_usable)`; usable = ≥3 vertices).
    A *fenceless* mission is **allowed** and runs unconstrained — fenceless is not
    treated as "every waypoint violates". When a fence *is* attached it must be
    usable and is enforced fail-closed (validator refuses an out-of-fence waypoint;
    a failed FC fence upload refuses the segment). This is correct for the current
    sim / FC-authoritative stance. A fail-closed *fenceless* posture (refuse a
    mission that carries no fence) is a real-rover hardening option — make it a
    mode/build-target policy, not the executor default. See the Geofence follow-up
    below and the real-rover Open Questions.

## Alternatives Considered

- **Linear mission list only (what the FC accepts).** Rejected by the operator in
  favour of richer support, though it remains the leaf layer under the tree.
- **Behavior tree on a companion computer now.** Rejected for now: no rover
  hardware yet; deferred via the relocatable-executor design.
- **Full behavior tree compiled to FC-only conditionals (`DO_JUMP`/`CONDITION_*`).**
  Rejected: the FC conditional set is far too limited to express the intended
  branching/recovery/operator-interaction behavior.

## Open Questions

- **Failure-domain and shutdown policy.** Browser/UI disconnect must not stop a
  server-owned execution. Decide, per build target, what an *intentional GCS
  server shutdown* does to an active mission (for example: require an operator
  choice and then abort-and-hold, or refuse shutdown until a bounded handoff is
  complete), and whether that policy is configurable in Mission Lifecycle
  settings. A GCS **process crash** cannot continue this server-resident executor:
  its process is gone. Reliable continuation after that failure needs a
  supervisor/restart-and-reconciliation design or the already-planned onboard /
  companion-computer executor, not a UI setting. Browser crash/refresh is a
  different failure domain and must leave the GCS executor running.
- Tree specification format (custom JSON vs. an existing BT XML dialect) and
  whether it is human-editable, AI-authored, or both.
- Real-rover link-loss policy when the executor is still server-side.
- How navigation leaves are demarcated and compiled to `.plan` segments; whether
  the FC runs them in AUTO (uploaded mission) or GUIDED (live commands).
- Executor/runtime choice for the relocatable module (and language, given a
  future companion computer).
- Mapping of ADR 0021 Confirm/Autonomous gating onto per-node vs. per-mission
  granularity.

## Note — Map sidebar ▶ button stays the legacy linear-plan upload (2026-06-01)

The map mission-list ▶ ("Play") button is **not** wired to the behavior-tree
session executor introduced by this ADR. It remains the legacy direct upload:
`MapWidget._handleExecuteRequest` → `executeMission(revisionId)` →
`POST /api/ai/mission-revisions/{id}/execute` → `MissionExecutionService.execute_revision`,
which compiles the active revision's waypoints to a `.plan` and starts them on the
controller. Lifecycle BT execution (this ADR + ADR 0021 Strict/Confirm/Autonomous
gating) is reachable only through the AI execution tools
(`arm_execution`/`execute_mission`/`cancel_execution`/`abort`) and the
`/api/ai/execution/*` endpoints + Confirm banner.

Decision: keep the two paths separate for now and **relabel** the button/modal so
it no longer implies BT execution ("Upload linear plan to controller"), rather than
adding mission-keyed REST endpoints that route the ▶ button through the
execution-session path. The session executor is still maturing and lacks a real FC
target (SITL smoke deferred); routing a one-click UI button into it now would commit
to mode-gating/Confirm-banner UX on the map before that path is exercised end-to-end.
Revisit when a Mission can be run BT-style from the map is a product requirement —
at which point the ▶ button (or a new control) should call the same
execution-session path, honoring `mission_lifecycle.execution_mode`.

## Follow-Ups

- ADR 0021 → unchanged status (Accepted); this ADR extends its execution-mode
  semantics to a continuous executor. Note added there is not required, but
  `design.md` updates should cross-link.
- `docs/components/ai-agent/design.md` and `docs/components/gcs/design.md` to gain
  an executor + behavior-tree-mission section as implementation lands.
- **Geofence currently fails *open* for fenceless missions** (2026-06-01 review).
  `enforce_geofence` only engages when a mission carries a `geofence`
  (`ai/mission_execution_session.py`, `ai/mission_executor.py`); a mission with no
  fence runs unconstrained. Correct for sim and the current FC-authoritative
  defense-in-depth stance, but a real-rover Strict/Confirm build arguably wants a
  deployment-time policy that *refuses* a fenceless mission rather than running it
  open. Revisit alongside the real-rover hardening Open Questions before hardware.
- **Cooperative pause added to `MissionExecutor` (2026-06-04, Phase B.0).** `request_abort()` is joined by `request_pause()`/`resume()` backed by a `threading.Event` (`_pause_event`). The executor blocks inside `_tick()` while paused and unblocks on `resume()` or `request_abort()` (abort always unblocks). `MissionExecutionSessions` exposes `request_pause`/`resume` mirroring the existing `request_abort` surface. The `ControllerMissionAdapter` protocol gained matching `pause_mission()`/`stop_mission()` methods (no-op on all current adapters; real FC SET_MODE → HOLD per ADR 0024 is Phase B.3+).
