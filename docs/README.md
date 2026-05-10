# Remote Rover Documentation

This directory is the main documentation set for the `remote-rover` workspace.

It is organized for two audiences:
- non-technical readers who need to understand what the project does, what is already working, and what is planned next
- technical readers who need architecture, runtime contracts, operational notes, and subproject details

## Start Here

- [Project Overview](./project-overview.md): high-level explanation of the project, intended use, and current demo story
- [Current State](./current-state.md): what is implemented now, what is partially implemented, and the main current limitations
- [Architecture](./architecture.md): how the simulator, GCS, broker, and shared config fit together
- [Documentation Status Audit](./documentation-status.md): latest markdown review, implementation status reconciliation, and archive summary
- [Implementation Roadmap](./implementation-roadmap.md): recommended forward plan, grouped by priority
- [AI Current Context Layer](./ai-current-context-layer.md): implemented live rover/runtime/settings/LLM/map/replay context layer, spatial query service, tool registry, and read-only Agent tools
- [AI Spatial Tools And Agent Plan](./ai-spatial-agent-tools-plan.md): spatial query service, permissioned tool registry, intent parsing, mission-draft planning, and perception data shape design reference
- [AI Agent Workbench Detailed Plan](./ai-agent-workbench-detailed-plan.md): historical planning rationale for schema migrations, spatial services, tool registry, intent parsing, mission drafts, approval state, and first LangGraph checkpoint (Milestones A–F now complete)
- [Rover Intents And Intent Test](./gcs_server/intent-and-intent-test.md): what rover intents are, why the AI page has an `Intent Test` mode, how it differs from Chat/Agent/Workbench, and what safety boundary it provides
- [AI Agent, LLM Provider, LangGraph, And RAG Implementation Plan](./ai-agent-rag-implementation-plan.md): implemented AI Chat/session foundation plus planned RAG/source controls, web research/search, LangGraph mission workflow, and rover-agent use cases
- [Terrain Scene Manifest](./terrain-scene.md): source-of-truth terrain/object manifest, generator, validation, and runtime consumers
- [Simulation Platform Requirements](./simulation-platform-requironments.md): stable requirements baseline for the next simulator and replay/map/logging work
- [Simulation Platform Plan](./simulation-platform-plan.md): current implementation and remaining phases for the simulator transition
- [rover-sim-next Phase 1 Checklist](./rover-sim-next-phase-1-checklist.md): concrete first implementation checklist by file and module for the successor simulator
- [Run And Config Guide](./operations/run-and-config.md): how to run the simulator and GCS, and where runtime configuration lives

## Subproject Documents

- [3D Simulator Docs](./3d-env/README.md): simulator purpose, features, controls, telemetry publishing policy, and technical structure
- [GCS Server Docs](./gcs_server/README.md): Ground Control Station purpose, browser workflow, MQTT integration, and technical structure
- [GCS Intent Parsing Docs](./gcs_server/intent-and-intent-test.md): operator and engineering reference for structured rover intents and the `/ai` `Intent Test` mode
- [GCS Workbench Mode Docs](./gcs_server/workbench-mode.md): purpose, lifecycle, API flow, examples, and troubleshooting for the `/ai` Workbench mode
- [GCS LLM Capability Matrix](./gcs_server/llm-provider-agentic-capability-matrix.md): provider/model capability mapping and tool-calling fit for Agent mode
- [rover-sim-next Scaffold](../rover-sim-next/README.md): current successor-simulator scaffold and intended ROS 2 + Gazebo direction

## Existing Historical Documents

Older planning and phase documents are still kept in the repository for historical traceability, but they should not be treated as the main source of truth for the current system.

Historical references:
- `3d-env/phase1-3D-Simulator.md`
- `3d-env/initial-hl-design.md`
- `3d-env/mqtt-plan-canonical-2026-04-05_00-58-36.md`
- `docs/archive/root/PROJECT_REVIEW_AND_CURRENT_STATE.md`
- `docs/archive/root/remote_rover_architecture_and_implementation_plan.md`
- `docs/archive/root/REPO_STATUS_BEFORE_PUSH.md`

Archive index:
- [Archive README](./archive/README.md)

For presentation, onboarding, and current engineering status, use this `docs/` directory first.


  Active AI docs (as of 2026-05-11):
  - ai-agent-rag-implementation-plan.md — master plan
  - ai-agent-workbench-detailed-plan.md — milestones A–F historical planning (complete)
  - ai-agent-workbench-next-session-plan-2026-05-10.md — implementation guide (Phases 1–3 done; Phase 4 next)
  - ai-current-context-layer.md — context layer reference
  - ai-langgraph-agent-design-plan-2026-05-10.md — LangGraph design
  - ai-spatial-agent-tools-plan.md — spatial tools reference
  - ai-replay-session-access-plan.md — replay AI design + status
