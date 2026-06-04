# Planning Shell

## Purpose

This document defines the planning shell as a durable human-in-the-loop
planning wrapper around the shared agent runtime.

Framing:

- the long-term target is one primary Agent experience
- the shell exists to provide durable human-in-the-loop planning behavior
  around the shared agent runtime
- the shell is not the long-term owner of authoritative mission lifecycle
  state; that responsibility lives in backend mission execution (see
  [`mission-execution.md`](./mission-execution.md) and [`../design.md`](../design.md) § "Mission Execution Boundary")

The planning shell is intentionally:

- non-executing
- approval-gated
- resumable after pause/interrupt

It differs from ordinary chat/agent turns because it adds durable workflow
control around the core agent loop.

## When To Use This Path

Use the planning shell when the operator asks for:

- multi-step rover mission drafts
- safety-conscious navigation/inspection/search planning
- explicit review checkpoints before proceeding
- structured draft output that can be approved or rejected

Use ordinary Agent turns when the operator needs:

- interactive Q&A
- tool-assisted situational analysis
- fast iterative back-and-forth without approval gates

Long-term direction:

- more planning behavior should become reachable from the primary Agent
  experience without requiring a separate top-level product mode
- until that path is designed, `/plan` remains the explicit product entry
  point for this shell; do not expose a separate planning product mode
- this shell should remain a durable orchestration layer, not a separate
  reasoning system

## Flow Shape

`capture_request` → `retrieve_current_context` → `planner_loop_node`
→ [`prepare_clarification`] → `validate_draft` → `store_draft`
→ `request_planning_shell_approval`
→ `record_approval` | `record_rejection` → `finalize_response`

Design rule:

- the planner loop is the sole planning core; deterministic validation and
  approval/cutover boundaries remain outside free-form model reasoning

`store_draft` also owns the flat-Mission bridge (ADR 0021 §2/§3): after
persisting the operation/revision it creates or updates the operator-facing
flat Mission (`MissionStore`). A new operation creates a Mission
(`origin = ai_chat`) bridged via `set_active_operation`; an appended revision
bumps the existing Mission's `client_version`. Without this step AI output
never reaches the per-user Mission sidebar.

The §3 create / clone-and-edit / edit-in-place surface is a single
`mission_edit_mode` enum (`create` | `clone_and_edit` | `edit_in_place`) plus
`source_mission_id` on the terminal `propose_mission_draft` tool — not three
parallel tools (one tool schema is cheaper in prompt tokens and gives the model
a clearer, named lifecycle choice). `store_draft` maps the mode onto operation
reuse: `edit_in_place` reuses the source Mission's operation (mutating, bumps
`client_version`); `create`/`clone_and_edit` force a new operation + Mission so
the original is preserved. `clone_and_edit` is the default for AI edits;
`edit_in_place` is used only when the operator explicitly asks.

## High-Level Flow

Happy path:

1. Operator types `/plan <planning prompt>` in the `/ai` composer.
2. Frontend calls the planning-shell stream endpoint.
3. Backend runs the planning graph and streams NDJSON events.
4. The planner loop uses bounded tools to parse intent, retrieve or resolve
   needed context, propose a mission draft, and pass it to deterministic
   validation.
5. Graph reaches `request_planning_shell_approval` and interrupts.
6. UI shows an approval card.
7. Frontend calls the resume endpoint with operator decision.
8. Graph records the decision and emits final assistant response.

Clarification path:

1. Same initial flow.
2. The planner requests missing information through the clarification tool.
3. Graph reaches `prepare_clarification` and interrupts before drafting.
4. UI shows a clarification card.
5. Operator supplies answers and resumes.
6. Graph refreshes rover pose and scene, then continues to drafting and
   approval.

## Interrupt Types

Two interrupt types can appear in the stream. The UI distinguishes them by
`interrupt_value.type`:

| `interrupt_value.type` | UI card shown | Resume decisions | Where in graph |
|---|---|---|---|
| `planning_shell_draft_approval` | Approval card | `approve` / `reject` | `request_planning_shell_approval` |
| `clarification_request` | Clarification card | `continue` / `cancel` | `prepare_clarification` |

Both use the same resume endpoint:

- `POST /api/ai/sessions/{session_id}/planning-shell/thread/{thread_id}/resume`

## Relationship To Agent Mode

Agent mode:

- one request loop with optional tools
- optimized for interactive analysis and dialogue

Planning shell:

- durable workflow wrapper with clarification and approval checkpoints
- increasingly expected to route its reasoning through the shared
  `AgentLoopRuntime`

Both are non-executing today. The shell adds process control and
resumability, not a separate long-term AI brain.

## Provenance-Aware Regeneration Rule

When planning regenerates or refines waypoints, waypoint provenance must be
checked before overwrite:

- `ai` waypoints can be replaced by new AI output
- `user` and `ai+edited` waypoints require explicit operator confirmation
  when replacement is proposed

The `ai+edited` block is enforced through clarification flow prior to draft
replacement. See [`mission-execution.md`](./mission-execution.md) for the
provenance state machine and
[`map-widget.md`](../../gcs/design.md) for the UI contract.

## Safety Model

This path is designed to preserve operator control:

- no direct command publication in the planning path
- explicit draft approval before continuation
- transparent inspection before approval

It is the bridge between free-form agent reasoning and future supervised
execution pipelines.
