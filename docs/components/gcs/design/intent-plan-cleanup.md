# Cleanup Plan: Remove `/intent` and `/plan`

Status date: 2026-06-17.

Implementation status:

- Slice 0 complete: keep/delete boundary documented here.
- Slice 1 complete in code: shared `ToolRegistry` now lives on direct app state;
  normal AI routes no longer reach it through `planning_shell_runtime`.
- Slice 2 complete in code/docs: the dedicated `/intent` slash path, endpoint,
  and active product docs were removed; shared parsing internals remain.
- Slice 3 complete in code: dedicated `request_clarification` and planner-only
  interrupt/resume behavior are removed.
- Slice 4 complete in code: `/plan` frontend/backend entry points are removed.
- Slice 5 complete in code: planning-shell runtime/graph files and app wiring
  are deleted.
- Remaining work is Slice 6: finish the active doc/state cleanup pass.

This document defines a safe cleanup plan for removing the `/intent` and
`/plan` slash-command entry points, their dedicated frontend/backend surfaces,
and any now-dead supporting code, without accidentally deleting shared
planning/intent infrastructure that the current Agent and mission-authoring
stack still uses.

This is a cleanup and simplification plan. It is not a product expansion plan.

## Goal

Reduce surface area, remove low-value legacy or intermediate entry points that
are not used in practice, and shrink maintenance burden in the `/ai` workspace.

The target end state is:

- no `/intent` slash command
- no `/plan` slash command
- no dedicated Intent Test mode
- no dedicated planning-shell mode
- no frontend code that renders planning-shell-only interrupt cards
- no backend routes that exist only to support those removed entry points
- shared planning/intent internals preserved when they are still required by the
  main Agent and Mission flows

## Non-goals

- Do not remove mission planning itself.
- Do not remove structured intent parsing itself.
- Do not remove mission draft creation/editing itself.
- Do not remove route-planning tools.
- Do not remove Agent mode.
- Do not silently change safety semantics in mission creation or execution.
- Do not mix this cleanup with unrelated RAG or map work.

## Core cleanup principle

Treat this as two different problems:

1. **Remove the explicit entry points** `/intent` and `/plan`
2. **Preserve or relocate the shared internals** they happen to use

The main risk is deleting code that looks “planning-shell” or “intent-test”
related but is actually still shared by ordinary Agent or Mission behavior.

## Current dependency picture

The live code dependency graph is narrower than the document surface suggests.
That matters because this cleanup should preserve only code-based functionality
that still depends on the planning/intent internals, not legacy product
surfaces.

### Dedicated slash-surface code that exists only for removal targets

These paths are dedicated to `/intent` or `/plan` and are removable once their
shared dependencies are handled:

- frontend `/intent` command registration and dispatch
- frontend `/plan` command registration and dispatch
- frontend `sendIntentTestRequest`
- frontend `sendPlanningShellRequest`
- frontend `resumePlanningShellApproval`
- frontend clarification/approval cards and pending-interrupt UI state used only
  by the planning-shell flow
- backend `POST /api/ai/sessions/{session_id}/intent-test`
- backend `POST /api/ai/sessions/{session_id}/planning-shell/stream`
- backend `POST /api/ai/sessions/{session_id}/planning-shell/thread/{thread_id}/resume`
- `PlanningShellGraphRuntime`
- `planning_shell_graph.py`
- planning-shell-specific graph state/checkpointer wiring

### Shared internals that normal Agent/Mission code still depends on

These must stay unless they are replaced by another live code path:

- `IntentService` because `parse_rover_intent` still uses it
- `parse_rover_intent` because normal Agent/Mission flows expose it
- `resolve_spatial_target` because normal Agent/data-surface flows expose it
- `create_mission_from_waypoints` because normal Agent mode can create durable
  Missions directly from explicit routes
- `propose_mission_draft` because normal Agent mode can create/edit durable
  Missions through it
- route-planning tools
- mission-reference resolution
- mission draft normalization/storage logic
- execution tools and Mission lifecycle backend

### `request_clarification` dependency verdict

Current code shows `request_clarification` is **not** part of the normal Agent
tool set. It is tied to the planning-shell-only graph/interrupt path.

Therefore:

- do not keep `request_clarification` just because it sounds generically useful
- remove it with the planning-shell stack unless a new non-planning
  clarification feature is explicitly designed and implemented
- do not let docs alone justify preserving it

## Safe-to-remove categories

These are strong candidates for full removal, subject only to the Slice 1
`ToolRegistry` decouple and any explicitly approved replacement feature:

- `/intent` slash command registration in the frontend
- `/plan` slash command registration in the frontend
- dedicated frontend dispatch paths for those commands
- dedicated Intent Test endpoint
- dedicated planning-shell stream endpoint
- dedicated planning-shell resume endpoint
- planning-shell-only frontend cards and stream-event handling
- `request_clarification`
- `PlanningShellGraphRuntime`
- `planning_shell_graph.py`
- planning-shell-specific graph state/checkpointer wiring
- docs that describe `/intent` or `/plan` as supported entry points

## Must-keep categories unless separately replaced

These are not “slash-command features”; they are shared internals:

- `IntentService`
- `parse_rover_intent`
- `resolve_spatial_target`
- `propose_mission_draft`
- `create_mission_from_waypoints`
- route-planning tools
- mission-reference resolution
- mission draft normalization/storage logic
- execution tools and Mission lifecycle backend

Do not keep code in this cleanup merely because it is mentioned in docs or was
once part of the planner migration. Keep it only if another current code path
still depends on it.

## Critical hidden coupling to break first

Today normal AI routes obtain the `ToolRegistry` through
`request.app.state.planning_shell_runtime.tool_registry`.

That means:

- removing `/plan` routes is fine
- removing `PlanningShellGraphRuntime` app-state wiring is **not** fine until
  the registry is re-homed

This coupling must be removed early in the cleanup so later deletion is safe.

## Cleanup strategy

Perform the cleanup in thin, reversible slices. Do not remove everything in one
patch.

The slices below are ordered to minimize risk and keep the app runnable after
each step.

## Slice 0 — Freeze scope and define the keep/delete boundary

### Deliverable

A documented keep/delete inventory that the implementation follows.

### Work

- Confirm that `/intent` and `/plan` are being removed as product entry points.
- Confirm that shared planning/intent internals remain in scope unless proven
  unused.
- Confirm whether Agent mode should remain allowed to create/edit Missions
  directly through terminal planning tools.
- Confirm the code-based keep/delete boundary:
  - keep shared Agent/Mission internals still used outside the slash surfaces
  - remove planning-shell-only runtime/graph/clarification code unless a new
    replacement feature is explicitly approved

### Output

- this document
- roadmap entries pointing to the implementation slices

### Risk gate

Do not start code deletion before the “delete entry points, keep shared
internals” boundary is explicit.

## Slice 1 — Decouple `ToolRegistry` from planning-shell runtime

### Why first

This is the main hidden coupling. Until it is removed, deleting planning-shell
runtime code risks breaking normal AI routes.

### Current state

- app startup creates a shared `ToolRegistry`
- app startup also creates `PlanningShellGraphRuntime`
- normal AI routes now obtain the registry directly from `app.state.tool_registry`

### Target state

- app state owns `tool_registry` directly
- normal AI routes read `request.app.state.tool_registry`
- planning-shell code, if still present temporarily, reads the same shared
  registry from app state or receives it explicitly

### Work

- add `app.state.tool_registry`
- update `_tool_registry(request)` to read from that direct state
- update planning-shell runtime construction to consume the shared registry
  without being the owner of it
- verify normal Agent chat still works

### Status

Done on 2026-06-17.

The shared registry is now owned by app state and passed into the temporary
planning-shell runtime as a consumer only. This was the only hidden coupling
blocking later deletion of planning-shell runtime wiring.

### Verifiable

- normal `/api/ai/sessions/{id}/messages`
- normal `/api/ai/sessions/{id}/messages/stream`
- session-command endpoint still works

### Deletion not yet allowed

- do not delete planning-shell routes or graph code in this slice
- do not treat this slice alone as proof that planning-shell runtime/graph code
  is dead; later slices still need explicit call-site removal

## Slice 2 — Remove `/intent` entry point and dedicated intent-test surface

### Why second

`/intent` is more isolated than `/plan`. It is the lower-risk cleanup and is a
 good first deletion.

### What to remove

- `/intent` slash command from frontend command inventory
- frontend parsing/dispatch path for `/intent`
- dedicated intent-test endpoint
- intent-specific UI rendering paths and status text
- docs that describe Intent Test mode as an available mode

### What to keep

- `IntentService`
- `parse_rover_intent` tool
- provider routing support for parser sub-tools if still used by planning or
  Agent internals

### Work

- remove `/intent` from slash-command list and parser
- remove frontend fetch to `/intent-test`
- remove `POST /api/ai/sessions/{session_id}/intent-test`
- remove intent-only message metadata and UI rendering if no longer referenced
- update docs to describe intent parsing as an internal/shared capability rather
  than a user-facing mode

### Status

Done on 2026-06-17.

The dedicated `/intent` product surface is gone from the active UI and backend.
Shared parsing internals remain in place for mission-planning/tooling flows.

### Verifiable

- normal Agent chat still works
- prompts that lead Agent to parse intent internally still work when applicable
- no broken composer behavior when typing `/intent ...` or after removing it

### Risk note

Do not delete `IntentService` in this slice. It is still used through
`parse_rover_intent`.

## Slice 3 — Remove `request_clarification` unless a replacement is explicitly approved

### Why this needs its own slice

`request_clarification` is conceptually tied to planning-shell interrupt/resume,
and current code confirms it is planner-only rather than part of ordinary Agent
mode.

That means the safe default is deletion, not preservation.

### Removal rule

Remove `request_clarification` together with the planning-shell flow unless all
of the following are true:

- there is an explicit product requirement to preserve operator clarification
  after `/plan` removal
- a replacement contract is designed for normal Agent mode
- the replacement no longer depends on planning-shell `interrupt()/resume`
  semantics
- the replacement has its own verification plan

Absent those conditions, keeping `request_clarification` is just keeping dead
or misleading code.

### Work

- inspect all code uses of `request_clarification`
- remove it from tool definitions/contracts/tests if no replacement is approved
- remove clarification-card handling that exists only for this tool
- remove any docs that describe clarification-card behavior as supported
- if a replacement is approved instead, write that replacement design first and
  do not reuse the old planning-shell contract by implication

### Verifiable

- no live code path depends on `request_clarification`
- mission-planning prompts either:
  - create/edit a Mission directly, or
  - return a clear non-resumable limitation / need-more-information answer

## Slice 4 — Remove `/plan` entry point and planning-shell frontend

### Why after Slice 3

This is where the main user-visible planning-shell surface disappears. It
should happen only after clarifying whether any of its unique control flow is
kept elsewhere.

### What to remove

- `/plan` slash command from frontend command inventory
- planning-shell request dispatch from frontend
- planning-shell stream event handling
- planning-shell approval and clarification card rendering
- planning-shell pending-interrupt state in frontend if no longer used
- planning-shell-specific status messages

### What to keep

- Agent mode
- Mission planning tools
- Mission creation/editing backend
- route-planning tool implementations

### Work

- remove `/plan` from slash-command registry and parser
- remove `sendPlanningShellRequest`
- remove `resumePlanningShellApproval`
- remove planning-shell card rendering helpers
- simplify message rendering and stream state if those paths become unreachable
- update active docs that still present `/plan` as a current operator path

### Verifiable

- ordinary Agent chat still works
- slash menu still behaves correctly
- no broken references to pending planning interrupts remain in UI state

## Slice 5 — Remove planning-shell backend routes and imports

### What to remove

- `POST /api/ai/sessions/{session_id}/planning-shell/stream`
- `POST /api/ai/sessions/{session_id}/planning-shell/thread/{thread_id}/resume`

### Precondition

- no frontend path still calls them
- no documented or tested feature still relies on them

### Work

- delete the routes
- delete imports that exist only for those routes
- remove route-level helpers that become dead after route removal
- delete backend references that remain only to serve the removed `/plan` flow

### Verifiable

- no backend import/runtime errors
- normal AI routes still work

## Slice 6 — Remove planning-shell graph/runtime once the slash surfaces are gone

### Why this is late

This is still the most dangerous deletion slice, but repo-wide code review shows
the planning-shell runtime/graph stack is self-contained once the slash
surfaces and `ToolRegistry` coupling are removed. The gate here is code-based,
not sentimental.

### Removal gate

Delete `planning_shell_graph.py`, `PlanningShellGraphRuntime`, graph-state
pieces, and related app state only when all of the following are true:

- no active route imports them
- no helper imports them
- no app startup path constructs them
- no normal AI path reads data through them
- no live tests still assert planner-only contracts that are being removed
- no docs still treat them as active behavior

### Likely work

- remove runtime construction from app startup
- remove app-state storage for planning-shell runtime
- remove graph/checkpointer setup tied only to planning shell
- remove dead helper functions and state models
- remove planner-only tests and fixtures

### Keep-check

Before deletion, confirm whether any useful utilities in the file are consumed
by normal Agent code. If not, delete rather than relocate.

## Slice 7 — Dead-code pass on planning/intent leftovers

### Goal

After entry points and dedicated surfaces are gone, identify the next layer of
code that became unreachable.

### Likely candidates

- intent-test-only message metadata
- planning-shell-only event types
- planning-shell-only frontend state
- docs references to “intent-test mode” or “planning-shell mode”
- ADR/design notes whose status wording now becomes outdated

### Work

- run narrow `rg` inventory for:
  - `/intent`
  - `/plan`
  - `intent-test`
  - `planning-shell`
  - `rover_intent_test`
  - `requires_planning_shell`
  - `request_clarification`
  - `clarification_request`
  - `prepare_clarification`
  - `PlanningShellGraphRuntime`
  - `planning_shell_runtime`
- delete or rewrite remaining dead references

### Verifiable

- repo search no longer shows active product docs or live code paths advertising
  those entry points
- repo search no longer shows live code paths depending on planning-shell-only
  clarification/runtime names

## Documentation cleanup plan

The docs currently still advertise `/intent` and `/plan` as supported entry
points. Cleanup should update these in phases:

### Must update during removal

- `roadmap.md`
- `docs/glossary.md`
- `docs/cross-cutting/architecture.md`
- `docs/components/gcs/README.md`
- `docs/components/gcs/design.md`
- `docs/components/gcs/design/api-and-runtime.md`
- `docs/components/gcs/design/ai-cli.md`
- `docs/components/ai-agent/requirements.md`
- `docs/components/ai-agent/design/intent-parsing.md`
- `docs/components/ai-agent/design.md`

### Mandatory doc-update rule

Any document that still describes `/intent` or `/plan` as an available,
supported, or planned operator-facing path must be updated in the same removal
slice that makes that statement false.

This is a hard requirement, not optional follow-up cleanup.

That includes:

- product/design/requirements docs
- cross-cutting architecture/glossary docs
- roadmap entries
- CLI design docs
- README/status overviews
- implementation notes or migration notes if they still describe the commands as
  active

Do not leave stale `/intent` or `/plan` references behind on the theory that
they will be cleaned up in a later pass. If a slice removes or changes the
behavior, that slice must also update every affected doc it touches or
invalidates.

### Rewrite guidance

- reframe structured intent parsing as an internal/shared capability unless a
  new user-facing inspection surface replaces it
- remove wording that says `/plan` remains the explicit product entry point
- remove wording that the AI workspace “hosts” intent-test and planning-shell
  modes if those modes are gone

### ADR handling

Do not rewrite accepted ADRs to pretend history was different.

Instead:

- leave ADRs as historical decisions
- update current design/requirements docs to state that the explicit slash entry
  points were later removed
- only add a new ADR if the cleanup changes a standing architectural decision

## Test and verification plan

This cleanup needs targeted smoke verification after each slice.

### Backend verification

- create AI session
- send normal blocking message
- send normal streaming message
- run session commands:
  - `/context`
  - `/retrieval-surfaces`
  - `/tool-activity`
  - `/capabilities brief`

### Agent planning verification

Use a planning-style prompt in normal Agent mode, for example:

- “create a mission around the second plantation and return”
- “edit mission #26 to add an inspection stop”

Confirm one of the intended outcomes:

- direct Mission creation/editing still works, or
- Agent returns a clear limitation without calling removed planning-shell paths

Also verify:

- Agent mode can still call `parse_rover_intent` when useful
- Agent mode can still create a Mission through `create_mission_from_waypoints`
  or `propose_mission_draft`
- no normal Agent run can hit a removed clarification interrupt path

### Frontend verification

- slash menu no longer advertises `/intent` or `/plan`
- typing those commands does not trigger dead paths
- no broken pending state or card rendering remains

### Search-based dead-code verification

After each removal slice, run targeted searches for:

- `/intent`
- `/plan`
- `intent-test`
- `planning-shell`
- `rover_intent_test`
- `requires_planning_shell`
- `request_clarification`
- `clarification_request`
- `prepare_clarification`
- `PlanningShellGraphRuntime`
- `planning_shell_runtime`

Use the remaining hits to drive the next cleanup slice.

Any non-historical doc hit that still claims `/intent` or `/plan` are current
must be updated before the slice is considered complete.

## Risks

- Deleting planning-shell runtime ownership before re-homing `ToolRegistry`
  breaks normal AI routes.
- Deleting `IntentService` or `parse_rover_intent` breaks shared planning logic.
- Keeping `request_clarification` without a replacement requirement leaves dead
  or misleading planner-only code behind.
- Removing docs incompletely leaves the repo claiming support for features that
  no longer exist.
- Large-file deletion without phased verification can hide subtle import/runtime
  breakage.

## Recommended execution order

1. decouple `ToolRegistry` from planning-shell runtime
2. remove `/intent` entry point and endpoint
3. remove `request_clarification` unless a replacement is explicitly designed
4. remove `/plan` frontend entry point and planning-shell UI
5. remove planning-shell backend routes/imports
6. remove planning-shell runtime/graph/tests after the code gates are clear
7. perform dead-code and docs cleanup pass

## Final recommendation

Do the cleanup. But do it as a **surface-removal-first, shared-internals-last**
refactor. The repo is large enough now that deleting by name similarity
(`intent`, `planning_shell`) will very likely remove code that still matters.

The safe strategy is:

- remove the explicit product features first
- preserve only the shared tools and parser/planning logic that normal code
  still uses
- delete planner-only runtime/graph/clarification code once the code gates are
  clear

That gives the codebase a real size reduction without destabilizing the current
Agent and Mission stack.
