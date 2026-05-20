# Remote Rover Documentation

This directory is the source of truth for Remote Rover documentation. Docs are organized by audience and purpose.

The repo is a remote robot operations stack with a Panda3D rover simulator (`3d-env/`), a FastAPI + browser Ground Control Station (`gcs_server/`), shared MQTT + config, and an evolving AI agent terminal. The successor simulator (`rover-sim-next/`) is scaffolded but not yet runnable.

## Living Status

| Doc | Purpose |
|---|---|
| [current-state.md](./current-state.md) | What is implemented today, what is partial, what is missing |
| [implementation-roadmap.md](./implementation-roadmap.md) | Prioritized forward plan |

## Product (User Perspective)

What the project is, what users see, what the system must do.

| Doc | Purpose |
|---|---|
| [product/vision.md](./cross-cutting/vision.md) | What Remote Rover is, current value, long-term AI-assisted target |
| [components/gcs/requirements.md](./components/gcs/requirements.md) | Dashboard, replay, settings, MQTT setup — what operators see and do |
| [components/ai-agent/requirements.md](./components/ai-agent/requirements.md) | Canonical AI agent requirements: behavior, safety, capability ladder, approval, mission execution, route planning, vehicle profiles |
| [product/simulator-requirements.md](./product/simulator-requirements.md) | Stable requirements baseline for simulator and replay/map/logging work |
| [product/rover-physics-tuning-prd.md](./product/rover-physics-tuning-prd.md) | PRD for realistic, operator-stable rover dynamics tuning in the simulator |

## Technical (Implementation)

How the system is built.

### Cross-cutting

| Doc | Purpose |
|---|---|
| [technical/architecture.md](./cross-cutting/architecture.md) | Components, data flows, MQTT contract, runtime boundaries |

### GCS Server

| Doc | Purpose |
|---|---|
| [components/gcs/README.md](./components/gcs/README.md) | GCS component index |
| [components/gcs/requirements.md](./components/gcs/requirements.md) | Operator workflow: pages, controls, safety invariants, acceptance criteria |
| [components/gcs/design.md](./components/gcs/design.md) | Runtime model, browser workflow, MQTT, AI chat, settings, current limitations |
| [components/gcs/internals/api-and-runtime.md](./components/gcs/internals/api-and-runtime.md) | HTTP/WebSocket routes, runtime model, intent parsing behavior |
| [components/ai-agent/internals/intent-parsing.md](./components/ai-agent/internals/intent-parsing.md) | Rover intent fields and the `/intent` slash command |
| [components/ai-agent/internals/workbench-mode.md](./components/ai-agent/internals/workbench-mode.md) | Planning shell stages, endpoints, interrupt types, troubleshooting (code namespace: `workbench_*`) |
| [components/gcs/internals/llm-capability-matrix.md](./components/gcs/internals/llm-capability-matrix.md) | Configured providers and tool-calling fit |
| [components/gcs/internals/regressions.md](./components/gcs/internals/regressions.md) | Behavioral regressions to avoid |

### Simulator

| Doc | Purpose |
|---|---|
| [technical/simulator/overview.md](./technical/simulator/overview.md) | 3D simulator purpose, features, controls |
| [technical/simulator/technical-details.md](./technical/simulator/technical-details.md) | Simulator runtime structure |
| [technical/simulator/terrain-scene.md](./technical/simulator/terrain-scene.md) | Source-of-truth terrain/object manifest |
| [technical/simulator/platform-plan.md](./technical/simulator/platform-plan.md) | Simulator transition plan |
| [technical/simulator/rover-sim-next-phase-1.md](./technical/simulator/rover-sim-next-phase-1.md) | Concrete first implementation checklist for the successor simulator |
| [technical/simulator/rover-physics-tuning.md](./technical/simulator/rover-physics-tuning.md) | Manual route, acceptance behavior, and tuning order for rover dynamics work |

### AI

| Doc | Purpose |
|---|---|
| [components/ai-agent/README.md](./components/ai-agent/README.md) | AI agent component index |
| [components/ai-agent/requirements.md](./components/ai-agent/requirements.md) | Requirements tier: product target |
| [components/ai-agent/design.md](./components/ai-agent/design.md) | Design tier: runtime, mission execution, route planning + export, phase plan, rollback |
| [components/ai-agent/internals/graph-spec.md](./components/ai-agent/internals/graph-spec.md) | LangGraph diagrams and state machines |
| [components/ai-agent/internals/context-layer.md](./components/ai-agent/internals/context-layer.md) | Compact live context layer, providers, integration |
| [components/ai-agent/internals/spatial-tools.md](./components/ai-agent/internals/spatial-tools.md) | Spatial query service and tool registry design |
| [components/ai-agent/internals/replay-access.md](./components/ai-agent/internals/replay-access.md) | How replay sessions are exposed to AI Chat and Agent |
| [components/ai-agent/internals/mission-execution.md](./components/ai-agent/internals/mission-execution.md) | Current `mission_execution` implementation: data model, APIs, execution transition, and remaining gaps |
| [components/ai-agent/internals/route-planning.md](./components/ai-agent/internals/route-planning.md) | Road graph, planner tools, QGC `.plan` exporter, manual validation checklist |
| [components/ai-agent/internals/tool-contract.md](./components/ai-agent/internals/tool-contract.md) | Mandatory contract fields and rules for every tool in `tool_registry.py` |
| [components/ai-agent/internals/token-efficiency.md](./components/ai-agent/internals/token-efficiency.md) | Token-usage audit and phased optimization plan |

## Decisions (ADRs)

Non-obvious architectural choices and the reasoning behind them.

| ADR | Title |
|---|---|
| [0001](./cross-cutting/decisions/0001-no-retained-current-state-topic.md) | No Retained MQTT Current-State Topic |
| [0002](./cross-cutting/decisions/0002-two-approval-model.md) | Two-Approval Model: Draft Approval ≠ Execution Approval |
| [0003](./cross-cutting/decisions/0003-rag-scope-vs-live-context.md) | RAG Scope: Documents And Memory, Not Live State |
| [0004](./cross-cutting/decisions/0004-langgraph-checkpointer-choice.md) | LangGraph Planning Shell Checkpointer: MemorySaver For Now |
| [0005](./cross-cutting/decisions/0005-keep-3d-env-as-current-simulator.md) | Keep `3d-env` As The Current Simulator Runtime |
| [0006](./cross-cutting/decisions/0006-rover-sim-next-is-next-simulator.md) | `rover-sim-next` Is The Next Simulator Implementation |
| [0007](./cross-cutting/decisions/0007-rag-later-not-now-for-live-state.md) | RAG Is Deferred; Live State Stays Structured Only |
| [0008](./cross-cutting/decisions/0008-defer-replay-and-live-map-until-sim-next.md) | Defer Replay, Live-Map Sync, And Synchronized Video Until `rover-sim-next` |
| [0009](./cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md) | Mission Execution Lives Under `ai-agent`, Not As A Peer Component |
| [0010](./cross-cutting/decisions/0010-internals-tier-naming.md) | "Internals" Is The Name Of The Third Documentation Tier |

## Operations

| Doc | Purpose |
|---|---|
| [operations/run-and-config.md](./cross-cutting/operations/run-and-config.md) | How to run the simulator and GCS, where runtime config lives |

## Reference

| Doc | Purpose |
|---|---|
| [glossary.md](./glossary.md) | Shared vocabulary across the project |
| [STYLE.md](./STYLE.md) | Documentation style and conventions for future updates |

## Archive

Older planning, completed feature plans, code review session output, and superseded docs are kept under [archive/](./archive/) for historical traceability. They should not be treated as the current source of truth.

## Recommended Reading Order

For a general or product-focused audience:

1. [product/vision.md](./cross-cutting/vision.md)
2. [current-state.md](./current-state.md)
3. [components/gcs/requirements.md](./components/gcs/requirements.md)
4. [components/ai-agent/requirements.md](./components/ai-agent/requirements.md)
5. [implementation-roadmap.md](./implementation-roadmap.md)

For technical readers:

1. [cross-cutting/architecture.md](./cross-cutting/architecture.md)
2. [components/gcs/design.md](./components/gcs/design.md)
3. [components/ai-agent/requirements.md](./components/ai-agent/requirements.md)
4. [components/ai-agent/design.md](./components/ai-agent/design.md)
5. [components/ai-agent/internals/graph-spec.md](./components/ai-agent/internals/graph-spec.md)
6. [components/ai-agent/internals/context-layer.md](./components/ai-agent/internals/context-layer.md)
7. [cross-cutting/decisions/](./cross-cutting/decisions/) — read all ADRs
8. [cross-cutting/operations/run-and-config.md](./cross-cutting/operations/run-and-config.md)
