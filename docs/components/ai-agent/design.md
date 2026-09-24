# AI Agent — Design

**How** the AI agent is built — interfaces, file layout, runtime boundaries, the mission-execution lifecycle, route planning, mission export, the vehicle-profile abstraction, the phase plan, and rollback. Implementation-flexible companion to [requirements.md](./requirements.md). The requirements doc wins on product intent and fixed decisions; this doc wins on implementation specifics; [design.md](./design.md) wins on diagrams only.

The planner loop is the planning core. `mission_execution` owns canonical
revision storage, overlay/state APIs, durable controller mission snapshots,
compare-and-swap version checks, mutation/execute APIs, and controller adapters.
ADR 0021 defines execution modes; ADR 0023 defines controller transport and the
relocatable behavior-tree executor.

## Table of Contents

- [Scope and Audience](#scope-and-audience)
- [Architecture Overview](#architecture-overview)
- [Mission Execution Boundary](#mission-execution-boundary)
- [AgentLoopRuntime](#agentloopruntime)
- [Tool and Permission Model](#tool-and-permission-model)
- [Policy Engine](#policy-engine)
- [Context and Data Strategy](#context-and-data-strategy)
- [Agent Mission-Authoring Integration](#agent-mission-authoring-integration)
- [Route Planning, Vehicle Profiles, and Mission Export](#route-planning-vehicle-profiles-and-mission-export)
- [Memory Subsystem](#memory-subsystem)
- [Specialist Agents and Handoffs](#specialist-agents-and-handoffs)
- [Reflection and Critique Loop](#reflection-and-critique-loop)
- [Task Subsystem](#task-subsystem)
- [Mission Supervision Subsystem](#mission-supervision-subsystem)
- [World Model and Observations](#world-model-and-observations)
- [Voice Subsystem](#voice-subsystem)
- [Provider Abstraction and Onboard Fallback](#provider-abstraction-and-onboard-fallback)
- [Budgeting and Governance](#budgeting-and-governance)
- [Safety Layers Beyond Code Invariants](#safety-layers-beyond-code-invariants)
- [Event Model](#event-model)
- [Observability, Replay, and Evaluation](#observability-replay-and-evaluation)
- [Migration Plan](#migration-plan)
- [Per-Phase Rollback](#per-phase-rollback)
- [Pre-Execution Readiness Checklist](#pre-execution-readiness-checklist)
- [Component Catalog](#component-catalog)
- [File Impact Map](#file-impact-map)
- [Provider Compatibility](#provider-compatibility)
- [Open Engineering Questions](#open-engineering-questions)

## Scope and Audience

This is the engineering reference for implementing the AI agent. Readers:

- engineers writing code in `backend/ai/`
- reviewers approving phase rollouts
- on-call engineers debugging traces

Non-readers (for them, see [requirements.md](./requirements.md)):

- operators
- product reviewers debating fixed decisions

## Architecture Overview

```text
Operator Terminal (text today, voice later)
  │
  ▼
AIChatService
  │
  ▼
AgentLoopRuntime  ────►  ContextManifest
  │                       compact context + manifest
  │
  ├──► ToolRegistry        permissioned tools, tier + scopes + side effects;
  │                       filtered by active VehicleProfile.planner_kind
  ├──► PolicyEngine        grants, freshness, side effects, budget, lifecycle gates
  ├──► MemoryStore         working / session / episodic / semantic /
  │                       procedural / world / operator (layered)
  ├──► AgentTraceStore     JSONL traces per run
  ├──► ProviderRegistry    role-based model routing
  └──► Specialists         planner, critic, researcher, monitor, reporter, executor
  │
  ▼
LangGraph workflow shell (durable HITL only)
  │
  ▼
mission_execution  ────►  canonical revisions, mission operation state machine,
                          policy, controller snapshot store, controller adapter,
                          verification, rollback, rebasing
  │
  ▼
Flight controller / autopilot (own physical authority; e-stop primacy)
```

Three boundaries are load-bearing:

- **The agent loop owns reasoning.** Picking tools, asking for clarification, drafting mission proposals, summarizing.
- **`ToolRegistry` + `PolicyEngine` own capability enforcement.** Permissions and grants are checked in code, not in prompts.
- **`mission_execution` and backend services own physical authority.** Canonical mission state, approval effects, controller lock, mission handoff, verification, rollback, low-level motion, autopilot handoff, and emergency stop do not belong to the model loop.

## Mission Execution Boundary

`mission_execution` is the deep backend module that owns mission-affecting state and controller-facing behavior. Reference: [ADR 0009](../../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) for why it lives under `ai-agent/` rather than as a peer component.

### Responsibilities

Belongs to `mission_execution`:

- receive semantic mission proposal packages from the graph/runtime
- canonicalize mission revisions and assign deterministic IDs/lineage
- persist revisions immediately, before map render or approval UI
- emit authoritative mission lifecycle events
- evaluate mission policy and approval requirements
- own the mission operation state machine for mission-affecting requests
- manage controller mission versioning and compare-and-swap checks
- coordinate controller upload, read-back verification, rollback, and stale-state rebasing

Does **not** belong:

- general reasoning loop behavior
- ordinary AI chat response generation
- non-mission tool orchestration

### Deep modules to build or strengthen

- mission proposal intake and canonicalization
- mission revision store and lineage manager
- mission policy and approval evaluator
- mission operation lifecycle manager
- controller mission snapshot store
- controller adapter and verification layer
- rollback and rebase coordinator
- UI policy/session mode projection layer

### Deterministic ownership

The LLM is not trusted for anything that can be computed or derived analytically. Backend code owns:

- canonical mission IDs
- step and waypoint IDs (stable across reordering and geometry changes)
- lineage metadata (`parent_draft_id` or equivalent)
- validation rules
- policy evaluation
- operation state transitions
- controller version checks
- controller reconciliation
- cutover success/failure decisions

The graph/runtime hands off **semantic mission proposal packages** containing semantic mission content, route geometry or route artifacts, operator review context, and revision lineage metadata. It does **not** create authoritative mission lifecycle records directly.

### Mission operation lifecycle

Every operator mission request opens a first-class operation. The state machine represents planning, review, cutover, verification, rollback, rebasing, failure, and cancellation explicitly rather than through scattered flags.

- Each operation has a stable top-level `operation_id` linking graph progress, mission revisions, approvals, controller cutover attempts, verification, rollback, and rebasing.
- Clarification and automatic rebasing remain under the same top-level operation while creating new mission revision records beneath it.
- The operation remains open until controller success is verified, rollback completes, the request is cancelled, or the flow ends in terminal failure.
- Mission-operation mode is triggered by receipt of a valid normalized mission proposal artifact, **not** by prompt text alone.

### Controller truth and concurrency

- The flight controller is the authoritative execution source of truth for live mission updates. Local UI or AI state cannot override reported controller mission progress.
- Cutover uses optimistic concurrency with controller mission version checks. Stale approvals are rejected with structured reasons.
- When an approval is stale, the system rebases the requested change against the latest verified controller mission snapshot. AI rebasing uses the verified snapshot (not session-local draft history), normalized back into the canonical internal mission model.

### Verification and rollback

- Controller upload success cannot rely on ACK alone. Post-upload read-back verification is required.
- If cutover verification fails, the system automatically attempts to restore the last verified controller mission snapshot. The rollback source is the exact previously verified controller-ready snapshot, not a regenerated mission from an old draft.
- The rollback snapshot belongs to vehicle/controller execution state, not to a single AI chat session.
- Default behavior on cutover failure preserves the currently executing verified mission unless the state has become unsafe or ambiguous enough to require escalation.

### Controller update policy

The controller update policy is deterministic and decides whether a change can be partially applied or requires full mission replacement based on mission delta shape, controller capability, and verification semantics.

- The first implementation assumes both full-replacement and partial-update flows may exist in future adapters; it must verify the actual installed mission after any cutover attempt.
- Preferred operator experience is uninterrupted live update when safe, falling back to pause-update-resume when controller constraints require it.

### Approval policy

- Deterministic and backend-owned. Defaults live in Settings; active overrides in the AI session UI are session-scoped.
- The effective policy is recorded on each operation so later review shows which rules were active at creation and approval time.
- Approval refers to a real stored revision, never to transient stream output.
- Mission approval implies immediate controller cutover by default, subject to the deterministic controller update policy.

### Architecture boundary

- Keep the system as a clean monolith for now. Do not force a microservice split in this slice.
- Create a clear in-process subsystem seam for `mission_execution` so later extraction to a separate service is possible without redesigning the logic.

### Current implementation snapshot

- `mission_execution` exists in `backend/ai/mission_execution_service.py`.
- Canonical mission revisions, current mission state, and overlay APIs are implemented.
- Durable controller mission snapshot state and execution-attempt persistence are implemented.
- Optimistic controller-version compare-and-swap checks are implemented.
- The local execution adapter verifies against persisted controller snapshot state; alongside it, external `ControllerMissionAdapter` backends (pymavlink + MAVSDK) now do real upload-readback verification with controller-version CAS (ADR 0023 Phases 1–2).
- The behavior-tree executor (`ai/mission_executor.py` + `ai/mission_leaf_driver.py`) flattens nav segments to `.plan` and installs them through the adapter; the first install of a run is CAS-gated against the version observed at authorization (ADR 0020/0021).
- Stale-rejection rebase: the revision-execute path already creates a rebased revision on version mismatch; an exercised SITL/real-FC smoke loop is the remaining gap (deferred under the no-tests rule until a target exists).

## AgentLoopRuntime

The shared bounded ReAct runtime. The initial module (`backend/ai/agent_loop.py`) is extracted from Agent chat and is now called by `AIChatService` and the planning shell.

### Loop pseudocode

```python
# Implementation lives in backend/ai/agent_loop.py
async def run_loop(state, config: AgentLoopConfig) -> AgentLoopResult:
    rt = _runtime(config)
    iterations = 0
    artifact = None
    steps: list[AgentLoopStep] = []

    bound_model = _bind_role_tools(rt, state, config)
    messages = _seed_messages(rt, state, config)        # system + manifest + user

    while iterations < config.max_iterations:
        iterations += 1
        _emit("agent_iteration_start", iteration=iterations)

        # 1) plan / decide
        response = await bound_model.ainvoke(messages, budget=rt.budget)
        messages.append(response)

        calls = response.tool_calls or []
        if not calls:
            return _finalize(content=response.content,
                             stop_reason="final_answer",
                             steps=steps, iterations=iterations)

        observations = []
        guardrail_results = []
        policy_decisions = []

        for call in calls:
            # 2) guard
            decision = rt.policy_engine.evaluate(call, rt.context)
            policy_decisions.append(decision)
            if decision.action == "deny":
                return _finalize(stop_reason=decision.stop_reason,
                                 steps=steps, iterations=iterations)
            if decision.action == "escalate":
                return _finalize(stop_reason="requires_execution_approval",
                                 handoff={"reason": decision.reason},
                                 steps=steps, iterations=iterations)

            # 3) terminal / exit tools
            if call.name == config.terminal_action:
                artifact = call.args
                observations.append(_tool_obs(call, {"accepted": True}))
                messages.append(_tool_message(call, {"status": "accepted"}))
                continue
            # 4) act
            result = rt.tool_registry.invoke(
                call.name, args=call.args,
                runtime=rt.app_runtime,
                context_snapshot=_build_tool_context(state),
            )

            # 5) observe result
            observations.append(_tool_obs(call, result))
            messages.append(_tool_message(call, result))

        steps.append(AgentLoopStep(
            iteration=iterations,
            model_message_id=response.id,
            tool_calls=[_summarize_call(c) for c in calls],
            observations=observations,
            guardrail_results=guardrail_results,
            policy_decisions=policy_decisions,
            plan_summary=_extract_plan_summary(response),
        ))

        # 6) reflect / check
        if _repeated_tool_failure(steps, config.max_repeated_tool_failures):
            return _finalize(stop_reason="repeated_tool_failure",
                             steps=steps, iterations=iterations)
        if artifact is not None:
            return _finalize(artifact=artifact,
                             stop_reason="artifact_proposed",
                             steps=steps, iterations=iterations)

    # 7) iteration cap
    return _finalize(stop_reason="iteration_limit",
                     steps=steps, iterations=iterations)
```

### Important properties

- **Single role provider per loop.** Specialist tools may internally call their own providers (e.g., `parse_vehicle_intent` keeps its own structured-output provider).
- **Tool calls are sequential in v1.** Determinism over throughput for mission-authoring and safety-gated flows. `allow_parallel_tool_calls` is a future config knob.
- **Terminal actions are tools, not free-form output.** `propose_mission_draft` is the planning exit signal; its args schema is the mission draft schema. Strictly stronger than parsing free-form JSON.
- **No execution tools bound to the model.** `_bind_role_tools` reads from `ToolRegistry` with `permissions ⊆ DEFAULT_PERMISSIONS`.
- **High baseline input-token usage is expected in Agent mode.** The fixed
  overhead from system safety instructions, tool catalog/binding, and compact
  context injection is intentional. ADR 0029 governs token reduction: lazy
  loading is appropriate for rarely needed data and counterproductive for
  usually needed data. Removing usually needed vehicle, scene, or mission state,
  or pruning schemas per intent, requires the golden-question evaluation gate.
  Every optimization must preserve safety guardrails, tool reliability, and
  operator-facing answer quality.
- **Narrow greeting fast-path is allowed.** A trivial small-talk bypass may skip tool-loop/context injection for short greeting-only prompts in Agent mode, but it must remain strict and must not trigger for vehicle-state, map-object, mission, telemetry, or replay intent.

### Runtime interfaces

```python
@dataclass(slots=True)
class AgentLoopConfig:
    run_mode: str                              # chat | agent | planning_shell | specialist | voice | monitor
    role: str                                  # assistant | planner | critic | researcher | monitor | reporter
    terminal_action: str                       # final_answer | propose_mission_draft | critique_complete | report_complete
    max_iterations: int = 6
    max_repeated_tool_failures: int = 2
    permissions: frozenset[str] = DEFAULT_PERMISSIONS
    source_controls: dict[str, bool] | None = None
    grant_ids: list[str] | None = None
    task_id: str | None = None
    allow_parallel_tool_calls: bool = False
    trace_level: str = "standard"              # minimal | standard | verbose
    budget: Budget | None = None

@dataclass(slots=True)
class AgentLoopStep:
    iteration: int
    model_message_id: str
    tool_calls: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    guardrail_results: list[dict[str, Any]]
    policy_decisions: list[dict[str, Any]]
    plan_summary: str | None = None
    stop_signal: str | None = None

@dataclass(slots=True)
class AgentLoopResult:
    content: str
    artifact: dict[str, Any] | None
    steps: list[AgentLoopStep]
    tool_calls: list[dict[str, Any]]
    stop_reason: str
    iterations: int
    handoff: dict[str, Any] | None
    task_update: dict[str, Any] | None
    response_metadata: dict[str, Any]
    usage_metadata: dict[str, Any]
    trace_id: str
```

### Stop reasons

Exactly one stop reason per run. Agent chat stores `agent_stop_reason`, `agent_iterations`, and `agent_trace_id` on assistant message metadata. `AgentTraceStore` writes loop-level JSONL events. Read-only trace inspection is available through `GET /api/ai/traces` and `GET /api/ai/traces/{trace_id}`.

| Stop reason | Meaning |
|---|---|
| `final_answer` | Model produced text with no tool calls |
| `artifact_proposed` | Terminal artifact returned (generic) |
| `draft_proposed` | Planning shell produced a mission draft |
| `critique_complete` | Critic specialist finished review |
| `report_complete` | Reporter specialist finished a report |
| `requires_clarification` | Reserved stop reason for a future dedicated clarification contract; not used by the current product surface |
| `requires_planning_shell` | Historical stop reason from the removed `/plan` path; no longer used by the current product surface |
| `requires_command_staging` | Task needs staging; not available in current mode |
| `requires_execution_approval` | Execution authority needed but not granted |
| `handoff_requested` | Loop requested a typed specialist / workflow handoff |
| `iteration_limit` | `max_iterations` reached |
| `tool_unavailable` | Required tool not registered or not allowed |
| `tool_calling_unsupported` | Provider does not support tool calling — fall back |
| `repeated_tool_failure` | Same tool failed N times in a row |
| `guardrail_blocked` | Input / tool / output guardrail blocked the run |
| `policy_denied` | Policy engine denied a tool / action |
| `budget_exceeded` | Token / cost / latency / iteration budget exhausted |
| `provider_error` | Provider failed unrecoverably |
| `cancelled` | Operator or system cancelled (e-stop or session abort) |

## Tool and Permission Model

Tool declaration:

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    permission: str                  # tier name; legacy
    tier: int                        # numeric tier
    required_scopes: frozenset[str]  # e.g. {"controller_lock", "geofence:zone_A"}
    side_effects: frozenset[str]     # e.g. {"publishes_mqtt", "writes_world_memory"}
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    is_terminal: bool = False        # terminal-action exit signal (e.g. propose_mission_draft)
```

`side_effects` is informational but powers replay safety: tools flagged `publishes_mqtt` cannot run during shadow / replay sessions.

### Tier ladder

Tier 0–2 active today; tier ≥ 3 defined but with zero registered tools.

| Tier | Name | Allows | Approval surface |
|---|---|---|---|
| 0 | `read_only` | Inspect state, telemetry, replay summaries, settings metadata | None |
| 1 | `analysis` | Computed analytics over read-only data | None |
| 2 | `planning` | Mission draft proposal, intent parsing, target resolution, clarification, route planning, mission export | Draft approval per draft |
| 3 | `command_staging` | Propose specific commands for execution review | Separate staging approval |
| 4 | `execution_simulated` | Execute commands in simulator only | Draft + staging approval; never hardware |
| 5 | `execution_live` | Execute commands on the real vehicle | Draft + staging + per-mission live grant; e-stop primacy |
| 6 | `autonomous_scoped_execution` | Operate without per-command approval inside a grant | Pre-grant with TTL; auto-revocation on policy violation |

Tier numbers are monotone: a tool at tier *n* requires every guard from tier *n − 1* to also hold.

### Operator grants

```python
@dataclass
class OperatorGrant:
    grant_id: str
    operator_id: str
    granted_to: str            # "session:xyz" | "task:abc" | "global"
    tier: int
    scopes: frozenset[str]
    budget: dict[str, Any]
    expires_at: float
    revoked_at: float | None
    grant_origin: str          # "ui" | "voice" | "api"
```

### Tool access rule

All must hold:

- tool is registered
- tool tier is allowed by run mode
- permission is enabled
- operator grant covers tier and scope (for tier ≥ 2)
- source controls allow the data surface
- policy engine allows the call
- budget allows the call
- stale-data checks pass when freshness matters
- replay mode does not block side effects
- active `VehicleProfile.planner_kind` matches the tool's vehicle binding (where applicable)

## Policy Engine

Seam: `(tool, args, current_grants, world_context) → (allow | deny | require_escalation)`.

Layers (each independent):

- **Input guardrails** — unsafe requests, prompt injection, out-of-scope robot requests, ambiguous motion, low STT confidence.
- **Tool guardrails** — permission tier, grant scope, source controls, freshness, side effects, budget, rate limits, vehicle-profile binding.
- **Output guardrails** — no false execution claims, no secret leakage, no ungrounded live-state claims, clear uncertainty when data is stale.
- **Workflow guardrails** — mission drafting creates a reviewable Mission revision but is non-executing; plan serialisation happens during proposal creation, while staging and execution require separate approvals.
- **Execution guardrails** — future commands validate geofence, controller lock, telemetry freshness, obstacle policy, mission state, operator grant.

Phase-3 footprint: thin wrapper around the current permission filter. Same behavior, but the seam exists so future tiers do not require rewriting the loop. Traces emit `agent_policy_decision` events; blocked calls stop with `policy_denied`.

## Context and Data Strategy

```text
Always in context (compact summaries, not full payloads):
  current vehicle summary        usually needed -> stays always-on
  current scene summary        usually needed -> stays always-on
  current mission summary      usually needed -> stays always-on
  current run mode and permissions
  available data surfaces (manifest)
  safety boundaries

Loaded through tools (rarely needed per turn -> lazy):
  runtime / broker / sim / map config  (get_runtime_context)
  detailed map objects
  replay paths and metrics
  session / message history
  settings sections
  sensor / perception details
  memory records
  uploaded documents / RAG chunks
  task history
```

The always-on set is deliberately the surfaces **most operator turns depend on**.
`runtime` config moved to tool-loaded under ADR 0029 because it is rarely the
answer; lazy-loading a usually-needed surface would add a round-trip to the
majority of turns (lazy loading wins only for rarely-needed data). Vehicle and
scene are injected **once** (the compact block), not duplicated as synthetic
turn-0 tool calls — see ADR 0029.

Rules:

- Exact live state from deterministic state tools.
- Spatial geometry from map / spatial services, not semantic RAG.
- Large surfaces discoverable before loading.
- Every large tool result bounded by filters (`limit`, `time_range`, `session_id`, `section`, `query`, `radius`, `kind`).
- Retrieved sources cited via source IDs or `loaded_data_refs`.
- Prompt-injected retrieved documents are untrusted data.

Detail: [design.md](./design.md).

## Agent Mission-Authoring Integration

The shared runtime remains the reasoning center. Mission-authoring prompts now
flow through the normal Agent runtime and hand semantic mission proposal
packages to `mission_execution`, which owns authoritative draft/revision state,
approval effects, and controller-facing behavior.

```text
START
  └─► capture_request
      └─► retrieve_initial_context        compact snapshot + manifest only
          └─► planner_loop_node           AgentLoopRuntime, role=planner
              └─► critic_loop_node?       optional (Phase 7); role=critic
                  └─► validate_draft      deterministic, unchanged; backstop for empty waypoints
                      └─► hand off to mission_execution (proposal package)
                          └─► request mission approval through mission_execution
                              └─► record_approval | record_rejection
                                  └─► finalize_response
```

Disappearing nodes (collapsed into tools during the planner migration):

| Former planning-shell node | Now |
|---|---|
| `classify_request_scope` | Implicit in first planner tool choice |
| `retrieve_replay_context` | `lazy_load_replay` tool |
| `retrieve_application_memory` | `lazy_load_ai_memory` tool |
| `retrieve_settings_context` | `lazy_load_settings` tool |
| `retrieve_sensor_context` | `lazy_load_sensor` tool |
| `parse_intent` | `parse_vehicle_intent` tool |
| `resolve_target` | `resolve_spatial_target` tool |
| `generate_mission_draft` | `propose_mission_draft` terminal tool |
Agent mission-authoring loop config:

```python
AgentLoopConfig(
    run_mode="agent",
    role="planner",
    terminal_action="propose_mission_draft",
    max_iterations=8,
    permissions=frozenset({"read_only", "analysis", "planning"}),
    allow_parallel_tool_calls=False,
)
```

Historical state additions from the removed planning-shell wrapper:

```python
class PlanningShellGraphState(TypedDict, total=False):
    # ... existing fields unchanged ...
    planner_agent_iterations: int
    planner_agent_stop_reason: str
    thought_trace: Annotated[list, add]    # planned: user-safe summaries only
```

Detail: [design.md](./design.md), [design.md](./design.md), [design.md](./design.md).

## Route Planning, Vehicle Profiles, and Mission Export

A mission draft is incomplete unless it carries a drivable route and an exporter that serialises it into a flight-controller-ready artifact. This subsystem slots into the shared Agent mission-authoring flow as tools (no new graph nodes), behind a first-class vehicle abstraction.

Detail: [design.md](./design.md), [design.md](./design.md).

### Design principle

Keep the graph topology vehicle- and task-agnostic. Every new capability ships as a tool with a rich description, and the agent decides when to invoke it. Hard-coded graph nodes are a coupling tax paid only when something cannot be expressed as a tool. This shape — minimal graph, maximal tools, policy-gated execution — is also what enables A/B-ing the underlying agent (current vs. future runtimes) without touching tool code or graph wiring.

### `VehicleProfile` (`backend/ai/vehicle_profile.py`)

First-class profile concept. Populated for all currently-anticipated kinds (`ground_vehicle`, `multirotor`, `fixed_wing`) even though only `ground_vehicle` is exercised end-to-end. Goal: when multirotor or fixed-wing is wired up later, no refactor of the planner / exporter / tool-registry / shared mission-authoring flow is required — only new planner-tool files and a scene swap.

```python
@dataclass
class VehicleProfile:
    id: str                           # "rover_default", "quad_x500", ...
    kind: Literal["ground", "multirotor", "fixed_wing"]
    mav_vehicle_type: int             # 10=rover, 2=multirotor, 1=fixed-wing
    planner_kind: Literal["road_graph", "aerial_survey", "airspace_corridor"]
    default_cruise_alt_m: float       # 0 for ground
    supports_yaw_at_waypoint: bool    # rover skid-steer: False; ackermann/copter: True; fixed-wing: False
    max_speed_mps: float
    # extensible physical params (size, turn radius, payload mass, ...)
```

Active profile is a Settings selection. Single-active assumed (one vehicle commanded at a time). Consumed by:

- `ToolRegistry` — gates which planning tools register. `planner_kind="road_graph"` ⇒ register `plan_route_*`. `planner_kind="aerial_survey"` ⇒ register `plan_aerial_*` (stubbed `NotImplementedError` adapter). The model never sees a tool that doesn't fit the active vehicle.
- `MissionExportService` — reads `mav_vehicle_type`, altitude semantics (`default_cruise_alt_m`, `kind=="ground"` ⇒ clamp `alt=0`), and `supports_yaw_at_waypoint` (strip explicit yaws when False).
- Planning-shell logic — branches on `planner_kind` only inside tools, never at graph topology.

**Selection contract.** The selection persists as `vehicle_profile.active_profile_id` in the GCS settings file, read and written through `GET`/`POST /api/vehicle-profile/active` (`backend/routers/ai.py`). The two directions are deliberately asymmetric: the read path is tolerant — an absent or unrecognised id logs and resolves to `rover_default`, so a settings file naming a profile this build no longer ships cannot break planning or export — while the write path rejects an unknown id with `400` rather than persisting one. `ROVER_DEFAULT` is the fallback, not a hardcoded active profile.

**No operator control exists for this yet.** The contract above is server-side
only: the sole in-repository client is the `GET` in
`map/sources/authored/vehicleProfileApi.js`, and nothing calls `POST`, so the
selector described under §Settings layout is intent, not shipped behavior —
changing the active profile today means editing the settings file or calling the
API directly. Deliberately deferred, not overlooked; the gap is tracked as
finding 5 of
[the 2026-09-24 review](../../reviews/code-review-2026-09-24-projects-cleanup-vs-master.md).

Consumers never read settings themselves. `ToolRegistry`, `MissionExportService`, and `MissionExecutionService` each take an injected `profile_resolver` callable (`backend/runtime.py`, `backend/app.py` wire the settings-backed one); it is called per operation, so a selection change takes effect without a restart, and tests inject a fake instead of a config. This is the same injection seam the RAG modules use to keep their dependency direction one-way.

Vehicle binding is stamped at authoring time: `create_proposal` and `create_client_revision` write the resolved profile id into the revision's `mission.vehicle_profile_id`, and `execute_revision` refuses a mismatch with status `vehicle_profile_mismatch` before any export or controller install (see §Mission authoring and start target). A revision that predates the stamp carries no id and stays dispatchable under the active profile.

### `RoadGraphService` (`backend/ai/road_graph_service.py`)

- On startup, loads `scene/scenes/terrain_scene.v1.json` (already loaded by `scene/scene_map.py`).
- Builds an undirected weighted graph: nodes = road endpoints, edges = road segments. Edge weight = euclidean length × cost multiplier from `metadata.route_planning_cost` (`preferred=1.0`, default `1.5`, `avoid` removed from graph).
- Two non-naive construction steps:
  - **Endpoint snap** with a configurable epsilon (Settings: `road_graph_epsilon_m`, default ~0.5 m). The authored scene is not guaranteed to share endpoint coords exactly.
  - **T-junction / crossroad split** — for each road, find points where another road's endpoint or segment lies within epsilon of its interior; split into sub-edges sharing a node. Segment-intersection pass during graph build; O(n²) over ~16 edges is trivial.
- Each edge carries a `group` tag read from `metadata.group` on the road (schema bump). No id-prefix parsing — fragile to renames.
- Public interface:
  - `nearest_node(x, y) → node_id`
  - `shortest_path(start_node, goal_node) → [node_ids]` — Dijkstra (`heapq`, no extra deps)
  - `cover_group(group: str, entry_node) → [node_ids]` — Eulerian circuit if the tagged subgraph is connected and even-degree; otherwise a Chinese-postman variant pairing odd-degree nodes and duplicating shortest paths before computing the Euler circuit. Minimum-retrace tour over ≤ ~20 sub-edges per group.
  - `route_to_then_around_then_back(start_xy, group)` — composes `shortest_path(start → entry)` + `cover_group(group, entry)` + `shortest_path(entry → start)`. `entry` is the tagged-subgraph node with shortest graph distance from `start`.
- Sanity check on startup: log node count, edge count, connected-component count. Single component expected.

### Planner-tier tools

Registered when `planner_kind == "road_graph"`:

- `plan_route_around_group(group_id)` — wraps `route_to_then_around_then_back`.
- `plan_route_between(start_target, goal_target)` (also `plan_route_to(goal_target, start_target=None)`) — resolves targets via `SpatialQueryService.resolve_spatial_target`, snaps to graph, runs Dijkstra. `start_target=None` uses current vehicle pose from live telemetry; stale or absent pose (older than `pose_max_age_s`, default 5.0) returns a structured `pose_unavailable` error.
- `stop_mission(reason)` — registered now as a stub so the tool is always discoverable. `PolicyEngine` does **not** gate it on draft state; aborting a non-existent mission is a no-op.

Tool descriptions are production code. The first line states the trigger condition; the description also names sibling tools, payload shape, return shape, and failure modes.

### Waypoint contract

```python
Waypoint = {
    # Stored truth — WGS84 (ADR 0022); exporter reads these directly
    "lat": float, "lon": float, "alt": float,
    # Scene render — local metres derived from WGS84 + Mission origin datum on overlay load
    "x": float, "y": float, "z": float,
    "yaw_rad": float | None,         # None ⇒ NaN in .plan (vehicle keeps current heading)
    "accept_radius_m": float | None, # None ⇒ exporter falls back to settings default
    "hold_s": float | None,          # None ⇒ exporter falls back to settings default
    "source_edge_id": str,           # provenance for UI / traceability
}
```

- `yaw_rad` is `None` at the route-planner layer (a navigation path has no opinion on heading). Task-layer steps (e.g., `inspect`) may override yaw to point at the inspection target. Exporter renders `None → NaN` for vehicles where that means "keep current" (rover, copter); per-vehicle profile may strip explicit yaws on fixed-wing where they cannot be honored.
- `accept_radius_m` set per-waypoint by the route planner as `min(road_width / 2, default_accept_radius_m)`; `None` means "use Settings default."
- `hold_s` defaults to `0.0` from Settings; route planner does not set per-waypoint values in this slice.
- Altitude `z` is always carried; exporter rendering depends on the active profile (ground → clamp to 0, aerial → use z or task-supplied cruise altitude, or profile-default cruise altitude).

### Tool result hygiene

Planner-tool results returned to the agent are a compact summary:

```python
{
  "waypoint_count": int,
  "total_distance_m": float,
  "estimated_duration_s": float,
  "legs": [{"from": str, "to": str, "edge_ids": list[str], "distance_m": float}],
  "route_hash": str,
  "draft_step_id": str,
}
```

The full waypoint list is persisted with the proposed Mission revision, fetched by the UI for map rendering, and serialised to a QGC plan as part of proposal creation. The wire contract between agent and tools stays small and inspectable.

### Mission Draft schema extensions

- `step.waypoints: list[Waypoint] | None` — populated when the step is materialised by a route tool.
- `step.route_summary: RouteSummary | None` — the compact result the agent saw.
- `draft.lifecycle: Literal["draft", "approved", "exported", "uploading", "uploaded", "executing", "completed", "failed", "cancelled"]` — declared in full now; only `draft / approved / exported / failed / cancelled` are reachable in the current slice.
- `draft.lifecycle_history: list[{state, ts, actor}]` — append-only audit trail.
- `draft.dispatch_mode: Literal["plan_only", "plan_and_execute"]` — inferred by the agent from prompt context. Operator Approval Gate is required regardless of mode; mode only governs whether the agent chains into upload/execute after approval.

### Planning-shell graph wiring

No new nodes. Existing topology unchanged:

```text
parse_intent → resolve_target (LLM + tools) → generate_draft → validate → approval interrupt → (on approve) post-approval tool calls
```

- `validate` is extended to reject any `navigate` step whose target is a region/group but whose `waypoints` field is empty — backstop against the agent skipping a planner-tool call.
- All new capability is delivered as tools the agent selects; the Policy Engine is the single safety gate.

### Mission export

Output: QGC `.plan` JSON conforming to the documented format:

- `fileType="Plan"`, `version=1`
- `mission.firmwareType=3` (ArduPilot), `mission.vehicleType` from active profile, `plannedHomePosition` from current vehicle pose
- One `SimpleItem` per waypoint with `command=16` (`MAV_CMD_NAV_WAYPOINT`), `frame=3` (`GLOBAL_RELATIVE_ALT`), `params=[hold_s, accept_radius_m, 0, yaw_rad_or_NaN, lat, lon, alt]`
- Trailing `command=20` (`NAV_RETURN_TO_LAUNCH`) appended for `route_to_then_around_then_back` outputs
- Empty `geoFence` and `rallyPoints` blocks (schema-required)
- Coordinates: the exporter reads each waypoint's **stored WGS84 `lat/lon/alt` directly** ([ADR 0022](../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md) — WGS84 is the stored truth, local metres are derived). The legacy local→geo flat-earth projection (off the per-Mission origin datum, falling back to the Terrain Scene Manifest `coordinate_system.georeference`) survives only as a fallback for legacy waypoints lacking stored WGS84; accurate to ~10 m over the scene's ~300 m extent.
- Output path: `data/missions/<draft_id>.plan`. Recorded on the draft.

Hand-off boundary: the `.plan` file. No upload code in this slice; that lands when the controller-adapter slice ships.

### Settings layout

New sub-project Settings surface, two tabs:

- **Constants** — `default_accept_radius_m` (default 2.0), `default_hold_s` (default 0.0), `road_graph_epsilon_m` (default 0.5), exporter output directory, `pose_max_age_s` (default 5.0), `cross_track_tolerance_m` (declared, not used in this slice).
- **Vehicle profile** — active profile selector (not built yet; see §Selection contract) plus per-profile physical / behavioural fields. Ships with `ground_vehicle`, `multirotor`, `fixed_wing` presets; only `ground_vehicle` is exercised.

### Dispatch mode

Dispatch mode is inferred by the agent from prompt context and stored on the draft.

- *"calculate me a route around the second plantation"* → `plan_only`. Draft reaches `exported`; route renders on the map; agent reports the file path.
- *"drive around the second plantation and come back"* → `plan_and_execute`. The proposal persists a reviewable revision and QGC plan, then still passes through the operator approval interrupt before controller handoff and execution. On `plan_only` it stops after creating the proposal.
- *"plan it first, show me on the map; if it looks good I'll tell you to go"* → `plan_only`, then a later user message ("yes, follow it") flips that draft's mode to `plan_and_execute` and re-enters the approval flow for the upload step.

Tool descriptions must teach the agent this distinction so dispatch-mode inference is reproducible.

### Stop / abort path

Two independent channels. Safety requires stopping the vehicle never depends on the agent being responsive:

1. **UI Stop button** — hardwired, always present, bypasses the agent entirely. Calls a server-side `abort_mission()` handler directly which issues the appropriate FC command (rover: `MAV_CMD_DO_SET_MODE → HOLD`, or `DISARM` if HOLD unsafe; per-vehicle profile may override). Primary safety control.
2. **Agent-callable `stop_mission` tool** — convenience for prompt-driven stop ("stop now", "abort"). Wraps the same server-side handler. Policy engine treats it as always-available regardless of draft state.

Both channels write a `cancelled` (operator stop) or `failed` (FC error during stop) entry to the active draft's `lifecycle_history`. Stop is not gated by approval — that is the whole point.

### Mission authoring and start target (committed follow-up)

The `start_target` is not always "current vehicle pose." Two distinct dispatch modes:

- **Mode A — Live dispatch.** `start_target = None` ⇒ tool reads current pose at dispatch time. Pose must be fresh. Normal draft → approve → execute.
- **Mode B — Pre-authored revisions.** `start_target` is explicit at authoring time (coordinate, named scene object, or sentinel `"vehicle_pose_at_execution"` for deferred resolution). The operator authors the route directly on the `/ai` map — either by creating a new mission from scratch (`➕ New mission`) or by editing an AI-proposed revision. Manual edits and AI proposals are different provenance sources on the same revision data model.

Revisions are vehicle-bound. Every revision stores a required `vehicle_profile_id`. Dispatch refuses if the active vehicle profile does not match. Rationale: the `.plan` format is vehicle-bound; `NAV_WAYPOINT` parameter interpretation differs by stack, fixed-wing/PX4-multirotor require explicit `NAV_TAKEOFF` while rovers do not, and some commands exist only on specific firmware variants. A vehicle-abstract intent grammar would re-materialise through divergent rules at dispatch time — exactly where a bug becomes "wrong mission uploaded."

Concurrent edits use **optimistic concurrency** via `client_version`. Each mutation request carries `expected_version`; the backend rejects stale writes with `409 Conflict`. Editing a locked revision (status `approved`, `executing`, or `completed`) forks a new client-authored revision with provenance inheritance rather than mutating in place. There is no last-write-wins fallback — conflicts are surfaced to the operator.

### Operational constraints (committed follow-up)

Unified region model:

- **Corridor** (3D polytope for aerial, 2D polygon for ground): a region the vehicle should stay inside.
  - `hard` corridor → planner refuses to emit waypoints outside it; runtime aborts on exit.
  - `soft` corridor → high cost to leaving it but emit-able if no feasible alternative.
- **Blockage** (3D/2D region): a region the vehicle should stay outside.
  - `hard` blockage → planner refuses to enter; runtime aborts on entry.
  - `soft` blockage → high cost to entry; permitted only if no feasible alternative.

This subsumes `metadata.route_planning_cost = "avoid"` (an avoid road is equivalent to a soft blockage covering that segment). Every edge cost = base length × Σ(active soft-cost multipliers); `hard` rules pre-filtered out of the search graph. Required tools include `list_corridors()` and `list_blockages()`. Authoring UI must support create/view/edit/enable-disable/delete on the map.

Storage: `config/operational_constraints.v1.json` (or alongside the scene). Schema shared across vehicle kinds; dimensionality (2D vs 3D) is a field per region.

### Off-route handling (committed follow-up)

During execution, the vehicle may deviate (GPS drift, obstacle avoidance, terrain). Configurable tolerance (`cross_track_tolerance_m`, `off_route_max_age_s`):

- Within tolerance → continue silently.
- Beyond tolerance → execution interrupts itself; agent receives a structured `off_route` event with deviation + likely cause. Agent either resolves it autonomously (replan from current pose) or escalates ("vehicle is 8 m off route near `road_plant_b_loop_2`; replan / abort / continue?").

The same interrupt mechanism used for approval — generalised into a runtime exception channel rather than a one-shot gate. Other preventing events (low battery, sensor fault, blocked sensor) reuse the channel.

### UI split (committed follow-up)

Two pages, one shared `MapWidget` component:

- **AI Agent (`/ai`) — authoring + review.** The map widget on this page is the primary mission authoring surface: operators create missions from scratch (`➕ New mission`), review and edit AI-proposed revisions, and manage the mission list. Chat panel and map panel are co-present — the agent proposes, the operator refines on the same screen.
- **Replay (`/replay`)** — gains a planned-vs-actual overlay: when replaying a session whose mission came from a known revision, fetch that route and render it as a second layer alongside the actual telemetry path. Read-only; diff metrics (`max_cross_track_error`, `missed_waypoints`) in a side panel.
- **Shared `MapWidget` component** — takes N route layers + 1 optional telemetry layer + optional edit handles. Used by the Approval Card and the `/ai` mission editor. The Approval Card renders the structured draft and map preview with route + active corridors/blockages overlaid; footer verbs are **Approve draft (does not execute) / Reject / Execute mission**.

The `/ai` map is the authoring surface — there is no separate Missions page. Co-locating authoring with the agent removes a context switch: the operator reviews the AI's explanation and the spatial route in the same view, and edits are immediately visible to both the agent and the operator. Replay and `/ai` have incompatible interaction models (read-only history vs. live edit), so they remain separate pages sharing the map component.

### Critical files (route planning slice)

- **New**: `backend/ai/road_graph_service.py`, `backend/ai/mission_export_service.py`, `backend/ai/vehicle_profile.py`.
- **Modify**: `backend/ai/tool_registry.py` (register `plan_route_around_group`, `plan_route_between`, `propose_mission_draft`, `stop_mission`; gate by active `VehicleProfile.planner_kind`); `backend/ai/mission_execution_service.py` (own proposal/revision storage and plan-export state); `backend/ai/mission_draft_service.py` (deterministic `validate_draft_payload` helper); `scene/scene_map.py` (expose centerlines).
- **Reuse**: `SpatialQueryService.resolve_spatial_target`, `MissionExecutionService` for proposal storage and approval flow, existing `PolicyEngine` for tier gating, and deterministic draft validation.
- **Possibly bump**: `scene/scenes/terrain_scene.v1.json` + `scene/schema/terrain_scene.schema.json` to add `metadata.group` per road and confirm `coordinate_system.georeference` presence.

## Memory Subsystem

| Layer | Backing store | Access tools | Retention |
|---|---|---|---|
| Working | In-process state (loop step messages) | implicit | discarded at loop exit |
| Session | `ai_sessions` + summaries | bounded tool / load | existing session lifecycle |
| Episodic | `ai_sessions` + `mission_drafts` + new `mission_runs` | `recall_episode`, `search_episodes`, `summarize_session` | operator-controlled archive / purge |
| Semantic | Vector store over docs, manuals, reports | `search_knowledge` (RAG) with citations | indexed sources; reindex on change |
| Procedural | New `procedures` table | `list_procedures`, `recall_procedure`, `propose_procedure` (operator-confirmed write) | operator-curated |
| World | New `world_objects` and `world_observations` tables | `query_world_object`, `recall_last_seen`, `predict_object_position` | confidence decays with time; eviction below threshold |
| Operator | New `operator_profile` table | `recall_operator_preference`, `update_operator_memory` (policy-gated) | operator can view, edit, purge |

Current footprint: working + session active. Other layers ship as empty tables + tool stubs that return "memory layer not yet populated." See [ADR 0003](../../cross-cutting/decisions/0003-rag-scope-vs-live-context.md) for scope and [ADR 0028](../../cross-cutting/decisions/0028-rag-project-docs-first-consumer-qdrant.md) for the `project_docs` RAG implementation (supersedes ADR 0007's timing). `project_docs` citations surface as clickable links in the chat retrieval panel; each link opens `GET /docs/{path}` which renders the source markdown file in-browser.

## Specialist Agents and Handoffs

Each specialist is an `AgentLoopRuntime` invocation with a different system prompt, tool subset, exit condition, and provider role. Shared code path.

| Role | Job | Tools / tier | First phase |
|---|---|---|---|
| `planner` | Decompose request → mission draft / handoff | 0–2 | implemented |
| `parser` | Structured intent parsing | 0 | existing (wrapped as tool) |
| `critic` | Review planner output for safety, ambiguity | 0 (read-only) | Phase 7 (optional) |
| `researcher` | RAG / web / project-doc research with citations | 0–1 | later |
| `reporter` | Post-mission summaries; episodic memory updates | 0; writes episodic | Phase 7 |
| `monitor` | Watch active missions; escalate anomalies | 0; writes monitor events | Phase 12 |
| `executor` | Stage commands during mission execution | 3 | Phase 10 |
| `voice_adapter` | STT / TTS, barge-in, confidence | n/a | Phase 8 |

Handoff contract — typed artifacts only, never raw prompts:

```text
Planner    → Critic:        MissionDraft + ToolTrace
Critic     → Planner:       Critique{accepted, concerns, suggested_revisions, confidence, policy_flags}
Planner    → Researcher:    ResearchRequest{question, scope, source_controls}
Researcher → Planner:       ResearchResult{summary, citations, loaded_refs}
Planner    → Mission approval boundary: MissionDraftRequest{prompt, context_refs, source_controls}
Stager     → Executor:      StagedCommand{command_id, expected_outcome, grant_id}
Monitor    → Planner:       ReplanRequest{mission_id, reason, observations}
Reporter   → Memory:        EpisodeRecord{task_id, outcome, summary, citations}
```

Every artifact is JSON-schema validated, stored, and trace-tagged.

## Reflection and Critique Loop

After `propose_mission_draft` exits the planner loop, before `validate_draft` runs, optional `critic_pass`:

```json
{
  "accepted": true,
  "concerns": ["string"],
  "suggested_revisions": ["string"],
  "confidence": 0.0,
  "policy_flags": ["string"]
}
```

- `accepted = true`: proceed to `validate_draft`.
- `accepted = false` + revisions remaining (`MAX_PLANNER_REVISIONS = 1`): feed critique back into the planner loop with one bounded retry.
- After retry: proceed to `validate_draft` regardless of critic verdict.

**Critic can soften (warn the operator). Critic cannot harden (cannot bypass `validate_draft`).** Asymmetry is deliberate.

Current footprint: behind `ai_enable_critic = false`. Ships in Phase 7.

## Task Subsystem

```python
class Task:
    task_id: str
    parent_task_id: str | None
    operator_id: str
    title: str
    description: str
    status: str                  # see lifecycle below
    schedule: dict               # {kind: "cron" | "event" | "one_shot", expr: "..."}
    scope: dict                  # geofence, time window, robot_ids
    budget: dict                 # max_runs, max_tokens, max_duration_s
    grant_id: str | None
    expected_artifacts: list[str]
    created_at: float
    updated_at: float
```

Lifecycle:

```text
requested
  -> understood            (parse_vehicle_intent succeeded)
  -> clarified             (any required clarification answered)
  -> planned               (mission draft generated + validated)
  -> draft_approved        (draft approval; tier ≤ 2)
  -> staged                (tier 3)
  -> execution_approved    (tier ≥ 4)
  -> running               (executor active; monitor watching)
  -> paused | blocked | completed | failed | cancelled
  -> reported              (reporter wrote episode record)
```

Invariants:

- A task in `running` requires both `draft_approved` and `execution_approved`.
- `paused`, `blocked`, `failed`, `cancelled` reachable from `running` at any time without further approval.
- `reported` is reachable from any terminal state.
- Planner never writes state directly. It calls `propose_task_transition(task_id, target_state)`; the task service validates and either applies or rejects with a structured reason.

Scheduler tick: every 60 s. Inspects `active` + `scheduled` tasks. When a task fires, injects a synthetic prompt into a fresh `AgentLoopRuntime` invocation with `run_mode = "scheduled_task"`.

Current footprint: table + tools scaffolded; only `recall_active_tasks` wired. v1 tasks transition only through `requested → ... → draft_approved → reported`.

## Mission Supervision Subsystem

Monitor specialist: one LangGraph instance per active mission. Event-driven.

Subscribes to: telemetry deltas, perception events, mission-state transitions, controller-lock changes, battery state, operator manual overrides.

Applies declarative policies. Examples:

```yaml
- name: stale_telemetry_pause
  trigger: telemetry.age_s > 5
  action: signal_executor("pause")
  severity: warning

- name: geofence_breach_halt
  trigger: vehicle.position not in active_task.scope.geofence
  action: signal_emergency_stop
  severity: critical

- name: unexpected_obstacle_replan
  trigger: perception.detected_object.confidence > 0.7 and on_planned_path
  action: signal_planner("replan_around_object")
  severity: warning
```

Monitor never publishes commands. Escalates via `monitor_event` artifacts. E-stop is a synchronous bypass not gated by the monitor.

## World Model and Observations

World memory layer holds: static map objects; dynamic detected objects with timestamps + confidence + kind + geometry + velocity; last-seen positions; terrain updates.

Observation contract:

```python
@dataclass
class Observation:
    observation_id: str
    timestamp: float
    source_sensor: str                # "camera_front" | "lidar_top" | "imu" | "mic_array"
    modality: str                     # "frame" | "lidar_scan" | "imu_sample" | "audio_clip" | "telemetry"
    confidence: float
    payload_ref: str                  # opaque media-store reference; never inline bytes
    derived_facts: list[dict]
```

Vision-capable models can be passed `payload_ref` as multimodal content; non-vision models get `derived_facts` only.

## Voice Subsystem

Voice is an I/O channel over the same runtime. No separate brain.

Input rules:

- STT produces text + confidence + n-best + audio reference.
- Below threshold (e.g., 0.7): return a normal assistant clarification request
  echoing the n-best candidates.
- Barge-in cancels TTS immediately; new utterance becomes active prompt.
- Voice input stored with `input_modality = "voice"`, `stt_confidence`, alternatives, trace ID.

Output rules:

- Assistant text streams to UI and TTS in parallel.
- Spoken output shorter than written output.
- Approval requests, errors, safety events use distinct voice profile / earcon.
- TTS cancelable per chunk.

Privilege rules:

- Voice does not elevate permissions.
- Voice approval uses fixed grammar tied to draft ID.
- Misrecognized approvals fail closed.
- E-stop by voice goes to synchronous backend e-stop path, not through the planner.

## Provider Abstraction and Onboard Fallback

Evolution: replace per-purpose providers with roles.

| Role | Capability requirements | v1 default mapping |
|---|---|---|
| `assistant` | General chat, optional tools | Today's `general_chat` |
| `planner` | Strong tool calling, ≥ 32k context, reliable structured output | Today's `mission_planner` |
| `parser` | Strict structured output | Today's `vehicle_intent` |
| `critic` | Structured output reliability | Same as planner in v1 |
| `researcher` | Long context and citation quality | Future |
| `vision` | Multimodal frame input | Future; can be `None` |
| `reporter` | Long-form summarization | Today's `general_chat` |
| `monitor` | Fast, low-latency, structured output | Future; small local model preferred |
| `embedding` | Embeddings | Today's `embeddings` |

Each role: independent provider + fallback chain + budget.

Compatibility rules:

- Providers without tool calling: Agent mode falls back to non-tool chat where safe.
- Planning-shell planner mode requires a tool-capable provider.
- Provider settings show capability badges (tool calling, structured output, context size, multimodal, latency class, onboard availability).
- Provider fallbacks are role-specific, not global.
- Onboard fallback is operator-visible and capability-limited.

Onboard fallback: local models register as providers alongside cloud. For `monitor` and `parser`, onboard is *preferred*. Cloud is fallback.

## Budgeting and Governance

```python
@dataclass
class Budget:
    max_tokens_per_run: int
    max_tokens_per_period: int
    max_cost_usd_per_period: float
    max_latency_ms_per_run: int
    max_iterations: int
    period_seconds: int
```

Budgets compose: effective budget is the most restrictive across (operator, session, task, grant).

Enforcement:

- Each iteration checks remaining tokens / cost / latency before invoking the next model call.
- Budget exhaustion → `stop_reason = "budget_exceeded"`, structured error, never silent truncation.
- Operator can grant a one-shot budget override per request.
- Before expensive operations (large RAG, long-horizon task scheduling), planner produces a budget projection and surfaces it if it crosses a threshold.

## Safety Layers Beyond Code Invariants

Code invariants are layer one. More layers unlock with capability tiers.

1. **Code invariants** — `ToolRegistry` permission filter, `execution_allowed = false` forced, `DISABLED_PERMISSIONS` not registered.
2. **Policy engine** — declarative `(tool, args, grants, world) → allow|deny|escalate`.
3. **Input filtering** — adversarial prompt detection on operator input; prompt-injection detection in retrieved documents.
4. **Output filtering** — leaked secret patterns, commands disguised as analysis, unsolicited tier-elevation requests.
5. **Rate limiting / anomaly detection** — repeated planner failures, unusually rapid drafting, unusual tool-sequence patterns trigger a session pause and operator notification.
6. **Sim-first execution** — every tier-≥-4 command runs in simulator first when available; operator sees projected vs. simulated diff before live.
7. **Emergency stop primacy** — synchronous code path that bypasses every layer above. Tested on every release.

## Event Model

Event ownership splits cleanly:

- **Graph/runtime events** — reasoning progress, tool calls, clarification pauses, proposal progress.
- **Mission execution events** — revision stored, superseded, awaiting review, approved, cutover started, verification succeeded, rollback started, rollback succeeded/failed, stale approval rejected, rebasing started.

Every mission-affecting request carries a top-level `operation_id` linking both streams.

Preserved events:

- `agent_tool_start`, `agent_tool_result`
- `mission_draft_created`, `mission_draft_validation`, `mission_draft_approval_required`, `mission_draft_decision`
- `graph_interrupt`, `graph_node_result`, `graph_retrieval_result`

New loop-level events:

```json
{"type":"graph_run_start","run_id":"...","thread_id":"...","session_id":"...","trace_id":"...","ts":1.7e9}
{"type":"agent_run_start","run_id":"...","trace_id":"...","run_mode":"planning_shell","role":"planner","max_iterations":8,"ts":1.7e9}
{"type":"agent_iteration_start","run_id":"...","iteration":1,"ts":1.7e9}
{"type":"agent_plan_update","run_id":"...","iteration":1,"summary":"Resolving target then proposing draft.","ts":1.7e9}
{"type":"agent_guardrail_result","run_id":"...","policy":"read_only_permissions","decision":"allow","ts":1.7e9}
{"type":"agent_tool_start","tool_call":{"id":"...","name":"resolve_spatial_target","args":{},"iteration":1},"ts":1.7e9}
{"type":"agent_tool_result","tool_call":{"id":"...","name":"resolve_spatial_target","result":{},"iteration":1,"latency_ms":12},"ts":1.7e9}
{"type":"agent_repeated_tool_failure","tool_call":{"id":"...","name":"resolve_spatial_target","args":{},"iteration":2},"failure_count":2,"ts":1.7e9}
{"type":"agent_iteration_end","run_id":"...","iteration":1,"tool_call_count":1,"ts":1.7e9}
{"type":"agent_handoff_proposed","run_id":"...","target":"planning_shell","reason":"motion_task_requires_draft_approval","ts":1.7e9}
{"type":"agent_run_end","run_id":"...","stop_reason":"draft_proposed","iterations":4,"ts":1.7e9}
{"type":"graph_run_end","run_id":"...","thread_id":"...","draft_id":"...","approval_status":"approved","ts":1.7e9}
```

Rules:

- `agent_plan_update.summary` is a user-safe summary, **not** raw chain-of-thought. Free-text model content is stripped.
- New events are primarily for debugging, audit, and the eval harness. UI surface for them is incremental.

## Agent Chat UI — Observable Reasoning Flow

The agent activity disclosure in the chat UI must present run trace and tool usage as one unified vertical flow, not two separate flat sections. This is the agreed design from 2026-06-18.

### Unified flow structure

```
Agent run
  │
  ├─ Iteration 1
  │    └─ [tool card] search_project_docs · 372 ms · available, status…
  │         (expand: args JSON + result JSON)
  │
  ├─ Iteration 2
  │    └─ (no tools)
  │
  └─ Done · final_answer
```

Each node is a `<div>` in a vertical flex stack connected by a CSS `border-left` line on the container — no canvas, no library.

### Node types

| Node | Source event | CSS class |
|---|---|---|
| Agent run | `agent_run_start` | `ai-flow-node-start` |
| Iteration N | `agent_iteration_start` | `ai-flow-node-iteration` |
| Tool card | `agent_tool_progress` entry with `call.iteration === N` | `ai-flow-tool-card` |
| Done | `agent_run_end` | `ai-flow-node-end` |

### Invariants

- Per-tool `<details>` expand/collapse is preserved for args JSON and result JSON.
- Streaming is preserved: nodes are appended to the DOM as events arrive; no batch-render on completion.
- Tool cards are nested inside their iteration node using `call.iteration` as the join key.
- The "Context used" section (synthetic `prompt_context_tool_calls`) disappears once ADR 0029 lands, because that preamble is a removed duplicate of the compact context block — not because all preloaded context is gone. The compact vehicle/mission/scene block still reaches the model; if a disclosure is wanted, render the compact block as a single preamble node before Iteration 1 rather than as fabricated tool cards. Until ADR 0029 lands, the synthetic preamble is rendered as that preamble node.

### Implementation boundary

`renderAgentFlow(message)` in `frontend-vanilla/ai.js` replaces both `renderAgentTraceChips` and `renderAgentToolRows`. `renderAgentActivityDisclosure` calls `renderAgentFlow` in place of the two separate sections. Data sources — `agentTraceEvents`, `agentToolCalls`, `distinctAgentIterations` — are unchanged.

## Observability, Replay, and Evaluation

Every run has: `run_id`, `trace_id`, session ID, provider / model, role, run mode, permissions, source controls, grants, loop iterations, stop reason, tool calls (latency + result summary), guardrail / policy decisions, loaded source refs and citations, handoff decisions, approval / resume events, task / mission IDs.

Trace storage:

```text
backend/ai/agent_traces.py
data/agent_traces/YYYY-MM-DD/{trace_id}.jsonl
```

Each event:

```json
{"ts": 1.7e9, "trace_id": "...", "run_id": "...", "event_type": "tool_invocation",
 "tool": "...", "args_hash": "...", "result_summary": "...", "tier": 2,
 "policy_decision": "allow"}
```

OpenTelemetry exporter is a later phase. Start with JSONL.

Replay: given a `trace_id` and the world snapshot referenced by that run, the run can be re-executed offline against a different model, a tightened policy, or an updated tool catalog. Tier ≥ 3 tools mocked by their `side_effects` declaration. Replay never publishes commands. Detail: [design.md](./design.md).

Evaluation: current project policy says **do not spend implementation effort on tests unless explicitly requested**. The eval harness is optional during platform phases but **becomes mandatory before any tier-3+ feature ships.**

## Migration Plan

Near-term migration order:

1. keep the universal agent/runtime as the planning core ✅
2. promote the planner-loop to default and retire the superseded deterministic-DAG middle ✅
3. introduce `mission_execution` as the authoritative mission lifecycle owner ✅ (in-process, local adapter)
4. switch the planning shell from direct draft ownership to proposal handoff ownership ✅
5. add immediate overlay payloads from stored revisions ✅
6. use controller adapters with upload, verification, rollback, and mission-version checks

Phases are sequenced by what they unlock. Any phase can move based on product priority.

| Phase | What ships | Boundary |
|---|---|---|
| **1** | Extract `AgentLoopRuntime` from `chat_service.py`. **Done.** | Platform |
| **2** | Structured trace + stop reasons; loop start / end / iteration events; repeated-tool-failure detection; provider-tool-calling fallback. **Done.** | Platform |
| **3** | `PolicyEngine` seam; data-access manifest in loop input; extend `ToolDefinition` with `tier` / `required_scopes` / `side_effects`. **Done.** | Platform |
| **4** | Bounded lazy tools: settings, AI session listing / search / message, available-data-surface discovery, sensor / perception metadata stubs. | Platform |
| **5** | Introduce the shared planner-loop mission-authoring path with an initial migration flag. **Done.** | Platform |
| **6** | Default-on planner loop; remove the superseded deterministic-DAG nodes. **Done.** | Platform |
| **7** | Critic (7a) + Reporter (7b) + memory foundations (session summaries, mission / report memory, operator preference memory). | Platform |
| **8** | Voice terminal: STT / TTS adapters, voice transcript metadata, barge-in, fixed-grammar approvals + e-stop. | Platform |
| **9** | Task management: `TaskStore`, lifecycle state machine, scheduler tick, Tasks UI. | Platform |
| **10** | Command staging (tier 3). **Prereq: separate ADR / design review.** | Capability |
| **11** | Simulated execution (tier 4); projected vs. simulated diff. | Capability |
| **12** | Supervised live execution + monitoring (tier 5). **Prereq: full safety review.** | Capability |
| **13** | Onboard / hybrid mode. | Platform (cross-cutting) |
| **14** | Autonomous scoped tasks (tier 6) inside geofenced + time-windowed grants. | Capability |
| **15** | Multi-robot coordination (tier 7). | Capability |

**Platform vs. capability boundary.** The platform must be substantially complete before any capability phase begins. Phase 3 (policy engine) is a prerequisite for every capability phase. The safety architecture must be fully audited before Phase 12.

### Implementation order recommendation

1. Phases 1–6 are done.
2. Land the first real controller adapter path (mission_execution real-controller slice).
3. Phase 7+ specialists and memory layers.
4. Then voice, tasks.

**Do not start with command staging, voice, or multi-agent sprawl** until the controller-adapter slice and Phase 7+ foundations are in place.

## Per-Phase Rollback

| Phase | Rollback mechanism | Time to revert |
|---|---|---|
| 1 | Old chat loop behind temporary flag for one release | seconds |
| 2 | Disable new loop events; keep tool events | seconds |
| 3 | Fall back to existing `ToolRegistry` permission filter | minutes |
| 4 | Disable new tools from registry | seconds |
| 5 | Git revert of the historical planner-loop introduction | one deploy cycle |
| 6 | Git revert + redeploy; superseded code preserved on a tag | one deploy cycle |
| 7 | Disable specialist; read-through-only memory flags | per layer |
| 8 | Disable voice transport; text unchanged | seconds |
| 9 | Disable scheduler tick; tasks stored but inactive | seconds |
| 10 | Disable tier-3 tools and staging UI | seconds |
| 11 | Disable tier-4 tools | seconds |
| 12 | Hardware-side revoke + software flag; both required | hardware-side revoke immediate |
| 13 | Disable onboard registry; cloud-only | seconds |
| 14 | Revoke all tier-6 grants; auto-revocation policy | immediate |
| 15 | Per-fleet grant revocation | per fleet |

## Pre-Execution Readiness Checklist

Before tier-3+ capabilities are enabled, **all** of these invariants must hold:

- the agent loop is isolated behind a stable runtime boundary;
- the planner path preserves draft behavior;
- stop reasons and trace IDs are stored for every run;
- tool permissions are enforced outside prompts;
- a policy-engine seam exists;
- source controls and a data manifest exist;
- command staging has a separate ADR or specification;
- execution approval is explicitly separate from draft approval;
- the E-stop path is designed outside the planner loop;
- replay and shadow modes block side-effecting tools;
- voice approvals fail closed;
- operator grants have TTL and revocation;
- the evaluation harness passes seven consecutive days on the planner path.
- [ ] Policy engine ≥ 90% coverage on declared policies.
- [ ] Replay produces structurally-equivalent runs for ≥ 95% of sampled production traces.
- [ ] E-stop latency ≤ 200 ms across UI, voice, API, hardware.
- [ ] Onboard fallback meets latency budgets for `parser` and `monitor`.
- [ ] At least two independent reviewers signed off on tier-≥-3 tool catalog and policy set.
- [ ] Runbook exists for: budget overruns, policy denials, monitor escalations, voice failures, model provider outages.

## Component Catalog

| Component | Responsibility | State |
|---|---|---|
| `AgentLoopRuntime` | Shared bounded ReAct loop | implemented; serves Agent chat + planning shell |
| `AIChatService` | Chat / session integration and persistence | implemented |
| `ToolRegistry` | Tool registration and permission filtering | implemented; extended with tier / scopes / side_effects |
| `PolicyEngine` | Permission / grant / policy decision before tool execution | thin wrapper, implemented |
| `AIContextService` | Compact current context and manifest | implemented |
| `Planning flow` | Shared Agent runtime plus mission-authoring tools | implemented |
| `validate_draft_payload` | Deterministic mission-draft validation helper | implemented in `mission_draft_service.py` |
| `MissionExecutionService` | Authoritative mission revision / operation / controller-handoff state | implemented; real-controller adapter slice next |
| `ProviderRegistry` | Role / purpose model routing | implemented; evolves to roles |
| `AgentTraceStore` | JSONL trace persistence | implemented for Agent chat |
| `MemoryStore` | Layered memory | scaffolded; populated Phase 7 |
| `TaskStore` | Long-horizon task lifecycle | scaffolded; wired Phase 9 |
| `RoadGraphService` | Road graph build + queries | implemented |
| `MissionExportService` | Approved draft → QGC `.plan` | implemented |
| `VehicleProfileService` | Active vehicle profile selection + capability gating | implemented |
| `VoiceAdapter` | STT / TTS, barge-in, voice confirmations | Phase 8 |
| `CommandStagingService` | Convert approved drafts → staged commands | Phase 10 (separate spec) |
| `AutopilotHandoffService` | Submit approved work to backend | Phase 12 (separate spec) |
| `MonitorSpecialist` | Watch active missions and escalate | Phase 12 |
| `ReporterSpecialist` | Reports and memory summaries | Phase 7 |

## File Impact Map

### Platform phases 1–6 (done)

```text
backend/ai/agent_loop.py              shared runtime
backend/ai/policy_engine.py           policy / guardrail seam
backend/ai/agent_traces.py            JSONL trace writer
backend/ai/chat_service.py            calls runtime
backend/ai/tool_registry.py           extended definitions; bounded tools
backend/ai/planning_shell_graph.py    planner-loop node; deterministic-DAG middle removed
backend/ai/graph_state.py             planner_agent_iterations / planner_agent_stop_reason
backend/ai/provider_registry.py       purpose routing evolving toward roles
backend/ai/context_service.py         compact context and manifest
backend/ai/mission_execution_service.py   mission_execution subsystem
frontend-vanilla/ai.js                  loop progress + approval surfaces
frontend-vanilla/style.css              UI states
backend/app.py                        settings flag plumbing
```

### Route-planning / export slice (planned)

```text
backend/ai/road_graph_service.py      RoadGraphService
backend/ai/mission_export_service.py  QGC .plan serializer
backend/ai/vehicle_profile.py         VehicleProfile + active selection
backend/ai/tool_registry.py           plan_route_*, propose_mission_draft, stop_mission tools
backend/ai/mission_execution_service.py proposal/revision storage, approval state, export result
backend/ai/mission_draft_service.py   validate_draft_payload helper
scene/scene_map.py                       expose centerlines + metadata.group
scene/scenes/terrain_scene.v1.json       schema bump: metadata.group per road
```

### Scaffolded; implemented later

```text
backend/ai/migrations.py              tables: procedures, world_objects,
                                         world_observations, operator_grants,
                                         operator_profile, tasks, mission_runs,
                                         agent_traces
backend/ai/memory/                    stub services per layer
backend/ai/specialists/               critic stub, reporter stub
backend/ai/observations.py            Observation schema, payload_ref handling
backend/ai/task_store.py              TaskStore CRUD
```

### Future-phase additions

```text
backend/ai/agent_memory.py            Phase 7
backend/ai/specialists/critic.py      Phase 7a
backend/ai/specialists/reporter.py    Phase 7b
backend/ai/specialists/researcher.py  RAG phase
backend/ai/specialists/monitor.py     Phase 12
backend/ai/specialists/executor.py    Phase 10–11
backend/ai/voice/stt.py               Phase 8
backend/ai/voice/tts.py               Phase 8
backend/ai/mission_monitor.py         Phase 12
backend/ai/staging_service.py         Phase 10
backend/ai/autopilot_handoff.py       Phase 12
backend/ai/onboard_provider.py        Phase 13
backend/ai/mission_template_service.py committed follow-up
backend/ai/operational_constraints.py  committed follow-up (corridors / blockages)
```

These file names are guidance, not mandatory. **Central invariant: after Phase 3, `agent_loop.py`'s public runtime contract should be stable.** New capability should primarily add tools, policies, specialists, and graph shells. Changes to the loop after that point should be treated as platform changes, not incidental feature work.

## Provider Compatibility

Agent-chat handles tool-calling-unsupported providers through `AgentLoopRuntime.prepare_tool_runtime`, with compatibility wrappers in `chat_service.py` around `_prepare_agent_tool_runtime` and `_is_tool_calling_unsupported_error`. The agent loop uses the same guard: if `bind_tools` raises an unsupported error, the run stops with `tool_calling_unsupported`.

Phase 6 onward (deterministic-DAG removed): providers without tool calling cannot be assigned to the `planner` role. Provider settings UI shows a capability badge.

Detail: [design.md](../gcs/design.md) *(currently in gcs internals; will migrate during step 6)*.

## Open Engineering Questions

Paired so reviewers can decide together. Product-level questions live in [requirements.md](./requirements.md).

| # | Question | Recommendation |
|---|---|---|
| 1 | Default loop iteration cap: 6 or 8? | Chat at 6; planner-style Agent turns at 8. |
| 2 | `propose_mission_draft` mid-loop or only final? | Final only. Simpler invariant: once proposed, loop exits. |
| 3 | Allow planner to retry `parse_vehicle_intent` after new observations? | One retry, gated by `_intent_retries` counter. |
| 4 | Keep planning as a separate runtime? | No; current product path uses shared `AgentLoopRuntime`. |
| 5 | Streaming: include free-text content in `agent_plan_update`? | Strip free-text; only summary + tool-call summaries. |
| 6 | Sub-tool provider routing (`parse_vehicle_intent`)? | Keep its own structured-output provider; independent of planner. |
| 7 | Critic provider — same as planner or different family? | Same in single-provider deployments; different family once available. |
| 8 | Procedural memory writes — draft approval or inline? | Inline tier-2 operator confirmation. |
| 9 | Voice approval phrasing — free-form or fixed grammar? | Fixed grammar for approvals + e-stop; free-form elsewhere. |
| 10 | Target hardware for onboard fallback? | GCS host first; vehicle compute is a later phase. |
| 11 | Policy engine substrate — custom DSL or OPA / Cedar? | Minimal custom DSL in v1; re-evaluate when policy count > ~30. |
| 12 | Episodic memory — summaries replace raw or coexist? | Augment, do not replace. |
| 13 | Replay determinism — seed providers or compare structurally? | Seed where supported; compare structurally otherwise. |
| 14 | Multi-operator memory scope default? | Per-operator private; team scope is explicit grant kind. |
| 15 | Onboard fallback failure for tier ≥ 3? | Refuse by default; operator can override with confirmation prompt. |
| 16 | E-stop latency target? | ≤ 200 ms across UI, voice, API, hardware. |

## Topic-Level Design Files

Detailed per-topic design content lives in sibling files under [`design/`](./design/). This is topic-level organization within the design tier (same stability rules as this file), not a separate tier.

- [`design/context-layer.md`](./design/context-layer.md) — Context Layer
- [`design/graph-spec.md`](./design/graph-spec.md) — Graph Spec
- [`design/intent-parsing.md`](./design/intent-parsing.md) — Intent Parsing
- [`design/mission-execution.md`](./design/mission-execution.md) — Mission Execution
- [`design/replay-access.md`](./design/replay-access.md) — Replay Access
- [`design/route-planning.md`](./design/route-planning.md) — Route Planning
- [`design/spatial-tools.md`](./design/spatial-tools.md) — Spatial Tools
- [`design/token-efficiency.md`](./design/token-efficiency.md) — Token Efficiency
- [`design/tool-contract.md`](./design/tool-contract.md) — Tool Contract
