# Planning Shell

## Purpose

This document describes the current planning shell. Its graph, state,
runtime, and REST routes use the `planning_shell` namespace.

Framing:

- the long-term target is one primary Agent experience
- the shell exists to provide durable human-in-the-loop planning behavior
  around the shared agent runtime
- the shell is not the right long-term place to own authoritative mission
  lifecycle state; that responsibility now lives in a backend mission
  execution subsystem, though the shell still uses legacy draft-flow
  compatibility paths in places (see
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

## Current Status In This Codebase

Implemented (Phases 1–6 are code-complete; Phase 6 removed the legacy
deterministic-DAG middle and made the planner loop the sole default path):

- planning is reached from `/ai` via the `/plan <prompt>` composer slash
  command; there is no dedicated mode button
- streaming planning endpoint with NDJSON lifecycle events
- durable `MemorySaver` checkpointer with stable
  `ai-session:{session_id}:run:{run_id}` thread IDs (see
  [ADR 0004](../../cross-cutting/decisions/0004-langgraph-checkpointer-choice.md))
- interrupt-driven approval gate (`request_planning_shell_approval`) —
  approve/reject buttons
- clarification loop (`prepare_clarification`) — when intent has missing
  information, graph pauses before drafting, operator answers questions,
  rover pose and scene are refreshed from live context on resume
- shared compact data-access manifest reused from
  `gcs_server/ai/data_access.py`
- shared tool-policy seam (`gcs_server/ai/policy_engine.py`) now matches
  Agent runtime metadata, though this path remains non-executing
- bounded retrieval/source metadata: source controls and recorded
  `retrieved_sources` / `loaded_data_refs` / `retrieval_citations`
- bounded planner-loop node (`planner_loop_node`) as the sole planning core;
  planner tools include route planning, clarification handoff, and draft
  submission; planner-loop JSONL traces are persisted through the shared
  trace store
- route planning and mission export: route-bearing drafts preserve route
  artifacts/waypoints, approval cards show a compact route summary, and
  approved route drafts are exported to QGC `.plan` files under
  `data/missions/`
- resume endpoint for approve/reject/continue/cancel decisions
- REST fallback for both approval and clarification when checkpointer is
  unavailable

Current next direction:

- mission planning stays universal-agent-driven
- authoritative mission revision state should move out of the graph and
  into a backend-owned `mission_execution` layer; that layer now exists,
  but the planning shell still keeps compatibility ties to
  `MissionDraftService` for approval/export flow
- the planning shell should become a durable proposal/review wrapper, not
  the final owner of mission approval effects or controller behavior
- execution cutover is available through mission-execution APIs, but the
  current planning-shell approval flow does not yet automatically invoke it
- **provenance-aware regeneration:** when the agent regenerates or refines
  waypoints, it must diff against per-waypoint provenance before
  overwriting. Waypoints with provenance `ai+edited` (operator-modified
  after AI proposal) are now blocked by server-side planning-shell
  validation until the operator explicitly confirms replacement through the
  clarification path. See [`mission-execution.md`](./mission-execution.md)
  for the provenance state machine and
  [`map-widget.md`](../../gcs/internals/map-widget.md) for the contract.

Code identifiers:

- `planning_shell_graph.py`
- `PlanningShellGraphState`
- `PlanningShellGraphRuntime`
- `/planning-shell/stream`
- `/planning-shell/thread/{thread_id}/resume`

## Current Flow Shape

`capture_request` → `retrieve_current_context` → `planner_loop_node`
→ [`prepare_clarification`] → `validate_draft` → `store_draft`
→ `request_planning_shell_approval`
→ `record_approval` | `record_rejection` → `finalize_response`

The deterministic DAG middle was removed in Phase 6. Intent parsing, target
resolution, lazy retrieval, route planning, clarification requests, and draft
submission now happen through tools selected by the shared agent runtime.
Deterministic validation/storage/approval/cutover remain outside free-form
model reasoning and continue moving under backend-owned mission execution.

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

## API Endpoints

Planning-shell endpoints:

- `POST /api/ai/sessions/{session_id}/planning-shell/stream`
- `POST /api/ai/sessions/{session_id}/planning-shell/thread/{thread_id}/resume`

General chat/agent endpoint:

- `POST /api/ai/sessions/{session_id}/messages/stream`

Important:

- the current planning-shell payloads still require the planning-shell
  endpoints
- the long-term product goal is to reduce how much callers need to care
  about this distinction

## Interrupt Types

Two interrupt types can appear in the stream. The UI distinguishes them by
`interrupt_value.type`:

| `interrupt_value.type` | UI card shown | Resume decisions | Where in graph |
|---|---|---|---|
| `planning_shell_draft_approval` | Approval card | `approve` / `reject` | `request_planning_shell_approval` |
| `clarification_request` | Clarification card | `continue` / `cancel` | `prepare_clarification` |

Both use the same resume endpoint:

- `POST /api/ai/sessions/{session_id}/planning-shell/thread/{thread_id}/resume`

## Why This Path Can Look Like It Hangs

Most "hang" reports are expected interrupt waits, not deadlocks.

Common causes:

- graph is paused at approval gate or clarification gate waiting for
  operator input
- pending interrupt card is present but operator has not acted yet
- thread ID or live session state got out of sync after mode/provider
  switching
- operator expects immediate chat-style completion rather than staged
  workflow pause

Operational interpretation:

- if an approval or clarification card is shown, the system is paused by
  design
- if no card appears and no events arrive, investigate UI state sync and
  stream lifecycle

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

## Implementation Map

Primary files:

| File | Responsibility |
|---|---|
| `static/ai.html` | hidden planning-shell plumbing; `/plan` is the live entry point |
| `static/ai.js` | slash-command routing, planning-shell send/resume handlers, approval/clarification rendering |
| `static/style.css` | approval/clarification card styles |
| `app.py` | planning-shell stream/resume routes |
| `ai/planning_shell_graph.py` | planning graph, routers, `stream_planning_shell_graph()`, `resume_planning_shell_graph()`, planner-loop integration |
| `ai/graph_state.py` | `PlanningShellGraphState` TypedDict |
| `ai/graph_runtime.py` | `PlanningShellGraphRuntime` immutable service container |

## Safety Model

This path is designed to preserve operator control:

- no direct command publication in the planning path
- explicit draft approval before continuation
- transparent inspection before approval

It is the bridge between free-form agent reasoning and future supervised
execution pipelines.
