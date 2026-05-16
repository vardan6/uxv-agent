# Remote Rover Documentation

This directory is the source of truth for Remote Rover documentation. Docs are organized by audience and purpose.

The repo is a remote robot operations stack with a Panda3D rover simulator (`3d-env/`), a FastAPI + browser Ground Control Station (`gcs_server/`), shared MQTT + config, and an AI workbench. The successor simulator (`rover-sim-next/`) is scaffolded but not yet runnable.

## Living Status

| Doc | Purpose |
|---|---|
| [current-state.md](./current-state.md) | What is implemented today, what is partial, what is missing |
| [implementation-roadmap.md](./implementation-roadmap.md) | Prioritized forward plan |

## Product (User Perspective)

What the project is, what users see, what the system must do.

| Doc | Purpose |
|---|---|
| [product/vision.md](./product/vision.md) | What Remote Rover is, current value, long-term AI-assisted target |
| [product/operator-experience.md](./product/operator-experience.md) | Dashboard, replay, settings, MQTT setup — what operators see and do |
| [product/ai-experience.md](./product/ai-experience.md) | The `/ai` page: Chat, Agent, Intent Test, Workbench modes |
| [product/simulator-requirements.md](./product/simulator-requirements.md) | Stable requirements baseline for simulator and replay/map/logging work |
| [product/ai-agent-requirements.md](./product/ai-agent-requirements.md) | Canonical AI agent product requirements, safety boundaries, capability ladder, fixed decisions |
| [product/route-planning-and-mission-export-prd.md](./product/route-planning-and-mission-export-prd.md) | PRD for route planning, mission generation, and QGC `.plan` export |

## Technical (Implementation)

How the system is built.

### Cross-cutting

| Doc | Purpose |
|---|---|
| [technical/architecture.md](./technical/architecture.md) | Components, data flows, MQTT contract, runtime boundaries |

### GCS Server

| Doc | Purpose |
|---|---|
| [technical/gcs/overview.md](./technical/gcs/overview.md) | What the GCS does today; main files |
| [technical/gcs/api-and-runtime.md](./technical/gcs/api-and-runtime.md) | HTTP/WebSocket routes, runtime model |
| [technical/gcs/intent-parsing.md](./technical/gcs/intent-parsing.md) | Rover intent fields and the `/intent` slash command (formerly Intent Test mode) |
| [technical/gcs/workbench-mode.md](./technical/gcs/workbench-mode.md) | Workbench graph stages, endpoints, interrupt types, troubleshooting |
| [technical/gcs/llm-capability-matrix.md](./technical/gcs/llm-capability-matrix.md) | Configured providers and tool-calling fit |
| [technical/gcs/regressions.md](./technical/gcs/regressions.md) | Behavioral regressions to avoid |

### Simulator

| Doc | Purpose |
|---|---|
| [technical/simulator/overview.md](./technical/simulator/overview.md) | 3D simulator purpose, features, controls |
| [technical/simulator/technical-details.md](./technical/simulator/technical-details.md) | Simulator runtime structure |
| [technical/simulator/terrain-scene.md](./technical/simulator/terrain-scene.md) | Source-of-truth terrain/object manifest |
| [technical/simulator/platform-plan.md](./technical/simulator/platform-plan.md) | Simulator transition plan |
| [technical/simulator/rover-sim-next-phase-1.md](./technical/simulator/rover-sim-next-phase-1.md) | Concrete first implementation checklist for the successor simulator |

### AI

| Doc | Purpose |
|---|---|
| [technical/ai/README.md](./technical/ai/README.md) | Current AI documentation index and canonical reading order |
| [technical/ai/ai-agent-functional-spec.md](./technical/ai/ai-agent-functional-spec.md) | Canonical AI agent technical spec: runtime, tools, policy, events, migration, rollback |
| [technical/ai/ai-agent-graph-spec.md](./technical/ai/ai-agent-graph-spec.md) | Canonical AI agent diagrams and state machines |
| [technical/ai/context-layer.md](./technical/ai/context-layer.md) | Compact live context layer, providers, integration |
| [technical/ai/spatial-tools.md](./technical/ai/spatial-tools.md) | Spatial query service and tool registry design |
| [technical/ai/replay-access.md](./technical/ai/replay-access.md) | How replay sessions are exposed to AI Chat and Agent |
| [technical/ai/tool-contract-standard.md](./technical/ai/tool-contract-standard.md) | Mandatory contract fields and rules for every tool in `tool_registry.py` |
| [technical/ai/route-planning-mission-export-validation.md](./technical/ai/route-planning-mission-export-validation.md) | Manual validation checklist for route planning, approval, and QGC `.plan` export |
| [other/rover-route-planning-and-mission-export.md](./other/rover-route-planning-and-mission-export.md) | Technical design: VehicleProfile, RoadGraphService, route planning tools, QGC exporter |

## Decisions (ADRs)

Non-obvious architectural choices and the reasoning behind them.

| ADR | Title |
|---|---|
| [0001](./decisions/0001-no-retained-current-state-topic.md) | No Retained MQTT Current-State Topic |
| [0002](./decisions/0002-two-approval-model.md) | Two-Approval Model: Workbench Approval ≠ Execution Approval |
| [0003](./decisions/0003-rag-scope-vs-live-context.md) | RAG Scope: Documents And Memory, Not Live State |
| [0004](./decisions/0004-langgraph-checkpointer-choice.md) | LangGraph Workbench Checkpointer: MemorySaver For Now |

## Operations

| Doc | Purpose |
|---|---|
| [operations/run-and-config.md](./operations/run-and-config.md) | How to run the simulator and GCS, where runtime config lives |

## Reference

| Doc | Purpose |
|---|---|
| [glossary.md](./glossary.md) | Shared vocabulary across the project |
| [STYLE.md](./STYLE.md) | Documentation style and conventions for future updates |

## Archive

Older planning, completed feature plans, code review session output, and superseded docs are kept under [archive/](./archive/) for historical traceability. They should not be treated as the current source of truth.

## Recommended Reading Order

For a general or product-focused audience:

1. [product/vision.md](./product/vision.md)
2. [current-state.md](./current-state.md)
3. [product/operator-experience.md](./product/operator-experience.md)
4. [product/ai-experience.md](./product/ai-experience.md)
5. [implementation-roadmap.md](./implementation-roadmap.md)

For technical readers:

1. [technical/architecture.md](./technical/architecture.md)
2. [technical/gcs/overview.md](./technical/gcs/overview.md)
3. [product/ai-agent-requirements.md](./product/ai-agent-requirements.md)
4. [technical/ai/ai-agent-functional-spec.md](./technical/ai/ai-agent-functional-spec.md)
5. [technical/ai/ai-agent-graph-spec.md](./technical/ai/ai-agent-graph-spec.md)
6. [technical/ai/context-layer.md](./technical/ai/context-layer.md)
7. [decisions/](./decisions/) — read all ADRs
8. [operations/run-and-config.md](./operations/run-and-config.md)
