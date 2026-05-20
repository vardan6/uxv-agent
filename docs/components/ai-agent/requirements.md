# AI Agent — Requirements

What the AI agent must be from the operator's point of view. The product-level source of truth for agent behavior, safety boundaries, interaction style, route planning, mission execution, and the flight-controller handoff boundary.

Companion documents:

- [design.md](./design.md) — implementation strategy, runtime seams, file layout, migration plan.
- [internals/graph-spec.md](./internals/graph-spec.md) — diagrams and state-machine views.
- [../../current-state.md](../../current-state.md) — what ships today.

If documents disagree:

- this document wins for product intent and fixed requirements
- `design.md` wins for implementation details
- `internals/graph-spec.md` wins for diagrams only

Superseded framing:

- fixed hand-authored planning DAGs are transitional implementation, not the target architecture
- older archived redesign drafts are reference material, not active requirements

## Table of Contents

- [Vision](#vision)
- [Primary Product Requirement](#primary-product-requirement)
- [Who This Is For](#who-this-is-for)
- [Core Interaction Model](#core-interaction-model)
- [Universal Agent Runtime Requirement](#universal-agent-runtime-requirement)
- [Tooling Requirement](#tooling-requirement)
- [Context and Retrieval Requirement](#context-and-retrieval-requirement)
- [Capability Ladder](#capability-ladder)
- [Approval Model](#approval-model)
- [Mission Execution Requirement](#mission-execution-requirement)
- [Route Planning and Mission Export Requirement](#route-planning-and-mission-export-requirement)
- [What The Agent Must Never Do](#what-the-agent-must-never-do)
- [Memory Requirement](#memory-requirement)
- [Voice Requirement](#voice-requirement)
- [Task Requirement](#task-requirement)
- [Operator Experience](#operator-experience)
- [Success Criteria](#success-criteria)
- [Fixed Decisions](#fixed-decisions)
- [Open Product Questions](#open-product-questions)
- [Glossary](#glossary)

## Vision

The AI agent is the primary communication terminal between an operator and one or more robots. The operator should be able to type or speak a goal in plain language, watch the agent gather only the evidence it needs, see the agent explain what it is doing, approve or reject high-impact outcomes, and eventually supervise execution through the same terminal.

This is not a chatbot with extra buttons. It is an operator-facing agent system with observable reasoning, bounded tool use, explicit approval, and strong code-enforced safety boundaries.

## Primary Product Requirement

The product must converge on a modern, general-purpose, bounded agent loop that is:

- universal across chat, planning, future monitoring, future reporting, and future execution-adjacent workflows
- driven by tool descriptions, policy, and current context rather than by hand-authored task-specific node chains
- able to discover information gradually and lazily instead of front-loading large context or fixed retrieval branches
- extensible through project-specific tools without reshaping the core runtime each time a new capability is added

The model should decide how to proceed within a bounded runtime. The product requirement is not "build many bespoke flows." The product requirement is "build one strong agent runtime with clear safety seams."

## Who This Is For

| Audience | What they need from this document |
|---|---|
| Operators | What the agent can do, how it behaves, and where approval is required |
| Product reviewers | The fixed decisions and target user experience |
| Engineers | The non-negotiable constraints implementation must satisfy |
| Safety reviewers | The boundaries the system must enforce in code |
| Future contributors | The architectural intent before reading source |

## Core Interaction Model

The operator gives a prompt. The agent does not immediately emit a final answer unless the prompt is trivial. Instead it runs a visible bounded loop:

1. understand the request
2. decide what information is already available
3. decide whether more information is needed
4. call the minimum set of tools needed, one step at a time
5. reflect on the results
6. continue, answer, ask for clarification, propose an artifact, or stop

The operator should be able to observe:

- what the agent thinks it is trying to do
- which tool it called
- why that tool was called
- what the tool returned at a useful summary level
- why the run stopped

The operator must not be shown raw chain-of-thought. The product surfaces short plan summaries, tool activity, citations, approvals, and stop reasons instead.

## Universal Agent Runtime Requirement

The system must center on a shared agent runtime that can serve multiple roles without requiring separate bespoke reasoning engines.

Required properties:

- One bounded loop powers chat, grounded Q&A, mission drafting, future monitoring, future research, and future reporting roles.
- Specialist behavior is achieved by changing tool availability, policy, prompts, and stop conditions, not by duplicating the runtime.
- Durable graph/state-machine wrappers are allowed for human-in-the-loop pause/resume, approvals, and long-running orchestration, but those wrappers must remain shells around the shared agent core.
- Fixed node chains may exist temporarily for migration or safety scaffolding, but they are not the target product architecture.

Non-requirement:

- The product does not require the agent core to be LangGraph-specific, framework-specific, or tied to any one vendor abstraction. The important part is the architecture and behavior, not the brand name of the loop.

## Tooling Requirement

Project-specific capability must be expressed primarily as tools and deterministic backend services, not as hardcoded agent branches.

Required tool properties:

- Every tool has a clear contract: purpose, input schema, output schema, side effects, permission class, and operator-visible description.
- Tools are separate from the core loop implementation.
- Adding a new tool should usually not require changing the core agent runtime.
- Tools are the agent's way to inspect or affect the world. Free-form model text must not bypass tool contracts.
- Planning, analysis, retrieval, and future execution-adjacent capabilities must be attachable through the same registry/policy surface.
- Tool descriptions are production code. The first line encodes the trigger condition; the description also names sibling tools, payload shape, return shape, and failure modes so the model can pick the right tool without graph-level branching.

Required runtime behavior:

- The model can choose which tools to call based on the prompt and tool descriptions.
- Tool calls are gradual, not bulk preloaded by default.
- The agent should stop early when it already has enough evidence.
- If a tool is unavailable, denied by policy, or disabled by source controls, the agent should adapt visibly rather than failing silently.

## Context and Retrieval Requirement

The system must optimize for efficient token use by separating compact always-on context from larger on-demand retrieval surfaces.

Required context strategy:

- Every run starts with a compact live context snapshot only.
- Larger data surfaces stay out of the initial prompt unless clearly needed.
- The agent discovers additional information incrementally through tools or bounded retrieval surfaces.
- Retrieval must be lazy by default and trace-visible when used.
- The agent must prefer exact deterministic services for live state, geometry, and measurements over semantic recall or guessed answers.

Required operator controls:

- The operator can see which retrieval surfaces were used.
- Source controls can enable or disable bounded retrieval surfaces.
- Citations or source references are surfaced when larger retrieved data affects the answer.

Explicit direction:

- "Load everything first" is the wrong design.
- "Tool-driven progressive discovery" is the correct design.

## Capability Ladder

The same agent runtime should grow by capability tier without requiring a rewrite each time.

| Level | Name | Authority | Approval surface | Status |
|---|---|---|---|---|
| L0 | Chat | Answer from compact context only | None | current |
| L1 | Read-only Agent | Inspect live state, map, replay, settings, memory | None | current |
| L2 | Planning Agent | Parse intent, retrieve evidence, draft non-executing missions | Draft approval | current target |
| L3 | Command Staging Agent | Convert approved drafts into staged commands | Separate staging approval | future |
| L4 | Simulated Execution Agent | Run staged requests in simulator | Simulation approval | future |
| L5 | Supervised Live Execution Agent | Coordinate with autopilot under supervision | Live grant + e-stop primacy | future |
| L6 | Scoped Autonomous Task Agent | Operate inside pre-granted limits | Time/geofence/budget grant | future |
| L7 | Multi-Robot Operations Agent | Coordinate across robots | Fleet policy + grants | future |

The key requirement is not the exact names. The key requirement is that promotion from one capability level to the next should happen by extending tools, policy, state, and approvals, not by throwing away the core agent architecture.

## Approval Model

The product keeps a strict two-approval model.

1. Draft approval: the operator approves a proposed planning artifact.
2. Execution approval: the operator separately approves any future staged execution command path.

Required properties:

- Planning artifacts are always non-executing by default.
- Approving a draft must never imply execution approval.
- Clarification is a separate human-in-the-loop pause, not an approval.
- Emergency stop is a separate synchronous path that bypasses the agent loop entirely.
- Mission approval policy must be deterministic and backend-configurable, with defaults in Settings and active session-level overrides in the AI UI.
- Approval must refer to a real stored revision, never to transient stream output.
- The effective policy must be recorded on each mission operation so later review shows which rules were active at creation and approval time.

See [ADR 0002](../../cross-cutting/decisions/0002-two-approval-model.md).

## Mission Execution Requirement

Mission-affecting rover requests must not end at "the agent proposed a draft." The product must support a distinct backend-owned mission execution boundary culminating in a real flight-controller handoff.

### Lifecycle properties

- Mission-style rover requests remain draft-first for this phase. The agent does not directly initiate rover execution.
- A valid mission proposal must be persisted immediately as a real mission revision before it is shown for review.
- Spatial mission proposals must appear immediately on the map as operator-visible overlays rendered from the durable stored revision (not transient stream content).
- Mission revisions are append-only and lineage-aware. A new revision references its parent through explicit lineage metadata. When a child revision is created, the parent becomes non-actionable for future approval unless explicitly re-selected.
- Local supersession does not change rover behavior by itself. The currently executing mission remains in effect until a replacement revision is approved and cutover succeeds.

### Backend ownership

- Controller-affecting behavior — approval effects, controller cutover, verification, rollback, stale-state rebasing — must be owned by deterministic backend code rather than by the model loop.
- Mission-affecting operations require a heavier lifecycle than ordinary chat. The product must model that lifecycle explicitly instead of through ad hoc flags.
- General AI chat must not inherit the full mission execution lifecycle unless it actually produces a mission-affecting artifact.
- Canonical mission IDs, lineage, versioning, and reconciliation metadata are backend-assigned and deterministic. The model is not responsible for infrastructure fields.
- Stable step and waypoint IDs must exist in the canonical mission model so revisions can be reconciled across reordering and geometry changes.

### Approval and cutover

- Approval policy is deterministic and backend-owned. Defaults come from Settings; active overrides in the AI session UI are session-scoped.
- Mission approval implies controller cutover by default, subject to the deterministic controller update policy.
- Cutover must use optimistic concurrency with controller mission version checks. A stale approval cannot overwrite a newer verified controller mission state. When a stale approval is rejected, the system must offer or trigger rebasing of the requested change against the latest verified controller mission state.
- Controller upload success cannot rely on ACK alone. Post-upload read-back verification is required.
- If cutover verification fails, the system must automatically attempt to restore the last verified controller mission snapshot. The rollback source is the exact previously verified controller-ready snapshot, not a regenerated mission from an old draft. That rollback state belongs to the rover/controller execution layer, not to one AI chat session.
- AI rebasing must use the latest verified controller mission snapshot as its base artifact, normalized back into the canonical internal mission model.

### Operation correlation

- Every operator mission request has a stable top-level `operation_id` (or equivalent correlation key) linking graph progress, mission revisions, approvals, controller cutover attempts, verification, rollback, and rebasing.
- Clarification and automatic rebasing remain under the same top-level operation while creating new mission revision records beneath it.
- An operation remains open until controller success is verified, rollback completes, the request is cancelled, or the flow ends in terminal failure.
- Mission lifecycle events are emitted authoritatively from the execution layer; the graph continues to stream proposal and reasoning progress.

### Controller adapter scope (first slice)

- The first controller adapter may be narrow in scope, but it must include mission upload, read-back verification, controller-version awareness, and rollback. Stopping at exported `.plan` files would leave too many architecture decisions unvalidated.
- The controller is the authoritative execution source of truth for live mission updates. Local UI or AI state cannot override reported controller mission progress.
- The first adapter must verify the actual installed mission after any cutover attempt; the design must assume both full-replacement and partial-update flows exist in future controller adapters.

See [ADR 0009](../../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) for why mission execution lives under `ai-agent/` rather than as a peer component.

## Route Planning and Mission Export Requirement

A mission draft is incomplete unless it carries a drivable route and a serialisable artifact the flight controller can consume. The product must support both, behind a first-class vehicle abstraction so the ground-rover path is one of several vehicle kinds.

### Route quality

- "Drive around X" route requests must cover every road of the target group (including interior service roads), not just the perimeter.
- "Drive from A to B" must take the shortest legal path.
- Per-road `metadata.route_planning_cost` (preferred / default / avoid) must influence routing, so preferred service roads are chosen over rough access tracks when both connect the goal.
- The road graph must handle T-junctions and crossroads correctly; connectivity cannot be silently dropped where roads meet mid-segment.
- The road-graph endpoint-snap epsilon must be operator-tunable (Settings), so the graph stays connected as the scene evolves.
- Startup must include a sanity check on graph connectivity (single connected component expected) so connectivity bugs surface immediately rather than at dispatch time.

### Route as plan, not execution

- Planner-tier route tools must be read-only and never execute. Planning never bypasses the approval gate.
- "Calculate me a route" must be reachable without it being executed, so the operator can review the plan first.
- "Drive from current pose to X" must use the rover's current telemetry pose as the implicit start. Stale or absent pose must return a structured error rather than silently routing from the scene origin.
- The Approval Card must show both the structured draft and a map preview of the route overlaid on the scene.

### Dispatch mode

- The agent must infer `plan_only` vs `plan_and_execute` from prompt context. "Calculate me a route" stores the plan; "drive around the plantation" queues it for execution after approval.
- Both modes pass through the Approval Gate. Mode only governs whether the agent chains into upload/execute after approval.
- A `plan_only` draft must be promotable to `plan_and_execute` by a later message ("yes, follow it"), so review-then-execute is a natural conversation.

### Stop

- The UI must offer a hardwired Stop button that does not depend on the agent being responsive.
- A `stop_mission` tool must be agent-callable from a prompt ("stop now").
- Every stop (UI or prompt) must be written to the draft's lifecycle history.

### Vehicle abstraction

- A `VehicleProfile` concept is first-class. The product supports `ground`, `multirotor`, and `fixed_wing` kinds even though only ground is exercised end-to-end today.
- The active profile is a Settings selection. Single-active is assumed (one vehicle commanded at a time).
- The agent must only see planning tools that match the active vehicle profile. A quadcopter is never dispatched to drive on roads.
- The mission exporter must read `mav_vehicle_type`, altitude semantics, and yaw policy from the active profile, never hard-code them.
- A Settings tab must expose vehicle profile selection and per-profile physical parameters, so the same GCS can be reconfigured for a rover today and a multirotor or fixed-wing later without code changes.

### Waypoint contract

- The route planner emits waypoints with no opinion on yaw (`yaw_rad = None`); task-level steps (such as `inspect`) may override yaw at specific waypoints to face the inspection target.
- Altitude `z` is always carried on each waypoint and rendered correctly per vehicle: ground profile clamps `alt = 0`, aerial profiles use the waypoint `z` or a task/profile cruise altitude.
- `accept_radius_m` is per-waypoint, tighter on narrow service roads and looser on wide connectors. Defaults live in Settings.
- `hold_s` default lives in Settings.

### Export

- An approved draft must be serialised to a QGC `.plan` file on disk. The `.plan` is the hand-off boundary the flight controller (or QGroundControl) consumes.
- The exported `.plan` must declare the correct `vehicleType` for the active vehicle.
- The exporter's lat/lon projection uses the scene's declared `coordinate_system.georeference`. The current scene and georeference are placeholders; both are expected to be regenerated together when real-world data arrives, with no projection code change required at the handover.

### Tool result hygiene

- Planner-tool results returned to the agent must be a compact summary (waypoint count, total distance, leg breakdown, route hash) so the agent's context budget is preserved.
- The full waypoint list must be persisted on the Mission Draft and fetched on demand by the UI and by the exporter, so the wire contract between agent and tools stays inspectable.

### Schema longevity

- The Mission Draft schema must declare the full lifecycle enum (`draft / approved / exported / uploading / uploaded / executing / completed / failed / cancelled`) and `dispatch_mode` from day one, so adding upload/execute/stop later does not require migrating existing drafts.

### Committed follow-up

The following are committed product work, not optional scope; they are separated from the route-planning/export slice only to keep that slice shippable:

- Named **Mission Templates** for recurring patrols, vehicle-bound (a rover template cannot be dispatched to a quadcopter).
- A **Missions page** to author, browse, and dispatch templates.
- **AI-assisted edits** and **manual waypoint editing** on the same template (drag / add / delete), with last-write-wins audit (`updated_at` / `updated_by`).
- **Replay planned-vs-actual overlay** and a shared `MissionMapView` component used by Approval Card, Missions page, and Replay overlay.
- **Corridors** (must-stay-inside regions, soft/hard) and **blockages** (must-stay-outside regions, soft/hard) supported by the planner and the map UI. A map authoring UI must let operators create, view, edit, enable/disable, and delete these objects as first-class mission planning data.
- **Off-route tolerance and interrupt-and-ask channel** during execution.
- **Mission upload + execute + abort** flows (this slice's `.plan` file is the current hand-off boundary).

## What The Agent Must Never Do

These are code-enforced invariants, not prompt suggestions.

- The agent must never publish low-level MQTT movement commands directly.
- The agent must never bypass the controller lock.
- The agent must never treat a planning draft approval as execution approval.
- The agent must never start physical execution without an explicit operator grant designed for that authority level.
- The agent must never answer live state or geometry questions from stale memory when deterministic live services are available.
- The agent must never silently exceed its configured iteration or budget limits.
- The agent must never silently use disabled retrieval surfaces.
- The agent must never leak secrets into prompts, traces, memory, or UI.
- The agent must never leak one operator's protected memory into another operator's run without an explicit shared scope.
- The agent must never override, delay, or reinterpret an emergency stop.

## Memory Requirement

Memory remains layered, permissioned, and subordinate to live deterministic state.

The product must support these conceptual layers over time:

- working memory for the current run
- session memory for the current conversation
- episodic memory for past missions and outcomes
- semantic memory for project documents and uploaded references
- procedural memory for approved operator/team procedures
- world memory for robot-specific persistent observations
- operator memory for preferences and conventions

Rules across all layers:

- no silent retention
- no secrets in memory
- no cross-operator leakage without explicit shared scope
- no use of memory as a substitute for live state when freshness matters

## Voice Requirement

Voice is a future I/O channel for the same agent, not a separate agent.

Required properties:

- text and voice use the same core runtime
- voice does not grant extra authority
- high-risk approvals require explicit confirmation patterns tied to specific artifacts
- low-confidence speech must trigger clarification rather than guessing
- emergency stop by voice bypasses the loop and hits the dedicated backend stop path

## Task Requirement

The long-term product includes scheduled, watchful, and recurring tasks. These are not one-shot prompts. They are persistent agent-managed tasks with scope, budget, state, and audit history.

A task must eventually support:

- title and intent
- schedule or trigger
- scope and bounds
- budget
- approval/grant linkage
- outputs and reports
- pause/resume/cancel lifecycle
- traceability to the same agent runtime and tool system

## Operator Experience

From the operator's point of view, the product should feel like a single AI terminal with bounded visible intelligence.

### The `/ai` page

The `/ai` page is the operator's AI terminal for asking questions about the rover, the map, recorded sessions, and mission goals. It is read-only with respect to rover motion today: no AI path can directly move the rover.

Layout requirement:

- **Session list** (left) — past and current AI sessions
- **Conversation area** (center) — messages, tool calls, streaming output, clarification cards, approval cards
- **Composer** (bottom) — input box, mode selector, Sources popover, provider override, send/retry/stop

### Long-term UI direction

- The operator-facing default should converge to one Agent mode.
- Chat may remain temporarily as a lightweight provider-test and fallback path during migration.
- Planning should not require a separate "brain" or permanently distinct user-facing mode.

The operator should not have to care whether a prompt triggered plain chat, grounded read-only investigation, iterative planning, future monitoring, or future reporting.

What the operator should care about:

- what the agent is trying to do
- whether it used tools
- what evidence it found
- whether it needs clarification
- whether approval is required
- whether the run ended safely and clearly

### Session management

Sessions must be creatable, searchable, archivable, restorable, and purgeable. Each session has its own history, provider override, and source-control state. Sessions and messages persist locally.

### Provider behavior

- Chat must work on any reachable provider.
- Agent works best with explicit tool-calling support.
- Planning-heavy Agent behavior benefits most from reliable structured output and tool use.

### Acceptance view

A new operator should be able to, without reading source:

1. open `/ai`, create a session, and get a response
2. use Agent mode for grounded rover/map questions and see tool activity
3. inspect how a prompt is being parsed (via the intent path)
4. reach draft clarification/approval for mission requests
5. understand that these are parts of one evolving AI terminal, not separate permanent product silos

## Success Criteria

The product direction is correct when all of these are true:

- new capabilities are usually added by adding tools and policy, not by creating new fixed reasoning flows
- the agent can inspect larger data only when needed instead of paying the token cost on every run
- operators can understand why the agent answered, asked, refused, or drafted
- planning runs and grounded Q&A both use the same core runtime model
- draft approval remains explicit and separate from any future execution approval
- mission proposals appear on the map immediately and approval drives real controller cutover with verification and rollback
- adding a new vehicle profile (multirotor, fixed-wing) requires new files, not refactors of the planner, exporter, tool registry, or planning shell
- traces are sufficient to audit the run after the fact
- the system can evolve toward richer autonomous behavior without replacing the agent core again

## Fixed Decisions

- The target architecture is a universal bounded agent loop, not a growing library of hardcoded node DAGs.
- The long-term primary `/ai` experience is one Agent mode. Chat may exist temporarily as a simpler fallback/testing path during migration.
- Project-specific capabilities belong in tools, deterministic services, policy, memory, and approval layers around the core loop.
- Retrieval and discovery must be lazy by default.
- Compact always-on context is required; large front-loaded prompts are not the target design.
- Human approval remains mandatory for planning artifacts that matter and for every future step above the current authority level.
- Safety boundaries are enforced in code, not delegated to the model.
- Durable graph wrappers are allowed for pause/resume and orchestration, but the reasoning center of gravity belongs in the shared agent runtime.
- Mission execution and route planning live under `ai-agent/`, not as peer components. (See [ADR 0009](../../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md).)
- Mission Templates are vehicle-bound, not vehicle-abstract — the `.plan` format itself is vehicle-bound, and a vehicle-abstract intent grammar would push divergent MAVLink branches into a dispatch-time re-materialiser where bugs become "wrong mission uploaded."
- The route planner emits waypoints with no opinion on yaw; task-layer steps may override per-waypoint yaw. Altitude `z` is always carried; the exporter renders it per vehicle profile.
- The `.plan` file is the current flight-controller hand-off boundary. Upload/execute/stop tools land in committed follow-up work.

## Open Product Questions

- Should general operator messaging auto-route into planning behavior when the agent infers a planning request, or should planning stay an explicit mode/command at the product layer?
- How much of the agent's short plan summary should be surfaced without encouraging chain-of-thought leakage?
- Which future memory writes require lightweight confirmation versus full approval artifacts?
- When future execution levels arrive, which grants are per-run versus long-lived scoped grants?

## Glossary

| Term | Meaning |
|---|---|
| Agent runtime | The shared bounded reasoning loop that decides what to do next |
| Tool | A contract-bound callable capability exposed to the model |
| Policy engine | The code path that allows, denies, or escalates tool use |
| Draft approval | Operator approval of a non-executing planning artifact |
| Execution approval | A separate future approval to let staged commands affect the robot |
| Compact context | The small always-on live context sent at run start |
| Lazy retrieval | On-demand loading of larger information only when needed |
| Durable shell | A graph or workflow wrapper used for interrupt/resume and long-running orchestration around the core loop |
| Planning shell | The durable shell that today wraps mission planning; implemented in the `workbench_*` code namespace |
| Vehicle profile | A first-class profile binding planner kind, MAVLink vehicle type, altitude semantics, yaw policy, and physical parameters; the active profile is a Settings selection |
| Mission revision | An append-only, lineage-aware snapshot of a mission proposal; backend-owned, canonical ID assigned by the execution layer |
| Mission operation | The top-level lifecycle of a mission-affecting request, correlating graph progress, mission revisions, approvals, cutover, verification, rollback, and rebasing under one `operation_id` |
| Controller cutover | The act of replacing the controller's currently executing mission with an approved revision, governed by compare-and-swap version checks and post-upload verification |
| Dispatch mode | Per-draft mode (`plan_only` / `plan_and_execute`) inferred from prompt context; both modes pass through the Approval Gate |
