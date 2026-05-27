# 0022. Drop The Per-Mission Operator Approval Gate; Modes Do The Gating

Date: 2026-05-28
Status: Accepted

## Context

[ADR 0002](./0002-two-approval-model.md) introduced the two-approval model:
the AI proposed a mission, the operator explicitly approved it, and only then
could it execute. That model was lifted to a configurable policy by
[ADR 0021](./0021-mission-lifecycle.md): Strict gates execution via the
operator clicking `▶`, Confirm via a banner click, Autonomous via an AI tool
call. None of the three modes need a *separate* per-Mission approval step in
front of the gate.

Despite that, the `Mission.approval_status` field and its `awaiting_approval
/ approved / rejected / validation_failed / needs_clarification` vocabulary
survived in code, in the API row, in the chat context blocks the LLM reads,
and in the requirements doc. The frontend stopped surfacing approve/reject
affordances during Slice 4, but the field stayed live.

Practical effect: every manually-created Mission was born `awaiting_approval`
and stayed there, while every operator-facing surface treated it as
playable. The flag had no operator meaning and no downstream consumer was
acting on its value.

## Decision

Drop the per-Mission approval gate from every operator-facing surface. The
execution mode (Strict / Confirm / Autonomous) and the executing-mission
edit lock together carry the safety story; no per-Mission flag does.

### Removed in this ADR

- `POST /api/ai/missions/{id}/approve` and `/reject` HTTP endpoints
- `approval_status` field from the API row helper (`_mission_to_api_row`)
- `approval_status` / `status` field driven by the column in
  `_overlay_for_mission` and `AIContextService.get_current_mission_overlay`
- `approval_status` field from the chat-context Mission summary
  (`_mission_to_state`)
- The "Approve a mission for execution" requirement and the "Approve draft /
  Execute mission / Export plan" three-verb framing in
  `docs/components/gcs/requirements.md`
- `map-widget.md` invariant "approval is not execution" (ADR 0012 §1) and
  the Approval/Rejection design section

### Default behaviour after this ADR

- `create_mission` defaults newly-created Missions to `approval_status =
  "approved"` so they appear immediately playable. The column survives so
  the AI planning graph (see below) keeps working.
- The frontend `status` field comes from controller state when the
  controller has the mission (`executing` / `armed`) and is `"approved"`
  otherwise.
- Strict mode = operator clicks `▶` on the row. Confirm = banner click.
  Autonomous = AI tool call. All three are unchanged.

### Deliberately *not* removed (follow-up scope)

The AI planning graph (`planning_shell_graph.py`) still drives nodes,
prompts, and validation traces off `approval_status`
(`record_approval` / `record_rejection` / `validation_failed`). Ripping that
out is bigger surgery and risks AI flows that have not been exercised in
this slice. Listed below as follow-ups; not gated on this ADR:

- `Mission.approval_status` column and `MissionRepository.create(
  approval_status=...)` parameter
- `record_approval` / `record_rejection` graph nodes
- `approval_status` references in `planning_shell_graph.py` validate /
  store-draft / summary builders
- `graph_state.PlanningShellGraphState.approval_status`

When those land, the column itself can be dropped via a new migration.

## Consequences

- ADR 0012 invariant 1 ("Approval is not execution") is formally retired.
  Invariants 2–4 (no client-side mutation of executing missions, no silent
  overwrites, no inventing backend contracts) remain.
- ADR 0002's two-approval framing is fully retired; ADR 0021 already
  superseded it structurally, this ADR finishes the cleanup on the operator
  surface.
- Manually-created Missions are immediately playable. Without execution-mode
  gating they would now hand the AI direct play authority, but tool binding
  + the controller `▶` already enforce that.
- The AI planning graph keeps reading and writing `approval_status` as
  internal validation state. Operator-facing surfaces ignore it. This is a
  temporary asymmetry tracked by the follow-ups above.

## Alternatives Considered

- **Rip out `approval_status` everywhere in one slice, including the
  planning graph.** Rejected: the graph touches LLM prompts and validation
  flows the operator has not exercised this session; the blast radius is
  too large for one slice. ADR captures the follow-up rather than gambling.
- **Keep the field; just hide it in the UI.** Rejected: that is the state
  before this ADR. The field accumulates meaning by inertia.
- **Reverse ADR 0021 and re-enable approval gating.** Rejected: ADR 0021's
  modes already serve the safety story this would re-introduce.

## Follow-Ups

- Planning-graph removal of `approval_status` (see *Deliberately not
  removed*).
- Migration to drop the column from the `missions` table, after the
  planning graph stops writing it.
- ADR 0021 §6 stays as-is; this ADR does not touch execution modes or the
  Confirm timeout setting.
