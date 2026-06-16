# Decisions

Current Architecture Decision Records. Numbering is monotonic and never reused,
so removed superseded identifiers intentionally leave gaps. Git history retains
older decisions. Template and conventions live in [../../STYLE.md](../../STYLE.md).

| # | Title |
|---|---|
| [0001](./0001-no-retained-current-state-topic.md) | No Retained MQTT Current-State Topic |
| [0003](./0003-rag-scope-vs-live-context.md) | RAG Scope: Documents And Memory, Not Live State |
| [0004](./0004-langgraph-checkpointer-choice.md) | LangGraph Planning Shell Checkpointer: MemorySaver For Now |
| [0005](./0005-keep-3d-env-as-current-simulator.md) | Keep `3d-env` As The Current Simulator Runtime |
| [0006](./0006-rover-sim-next-is-next-simulator.md) | `rover-sim-next` Is The Next Simulator Implementation |
| [0007](./0007-rag-later-not-now-for-live-state.md) | RAG Is Deferred; Live State Stays Structured Only |
| [0009](./0009-mission-execution-fold-under-ai-agent.md) | Mission Execution Lives Under `ai-agent`, Not As A Peer Component |
| [0013](./0013-intent-parser-provider-routing-order.md) | Intent-Parser Provider Routing Order |
| [0014](./0014-replay-session-resolution-server-side.md) | Replay Session Reference Resolution Happens Server-Side |
| [0015](./0015-mcp-as-adapter-not-first-implementation.md) | MCP Is An Adapter Layer, Not The First Implementation |
| [0016](./0016-terrain-scene-source-and-pipeline-discipline.md) | Terrain Scene Source-And-Pipeline Discipline |
| [0017](./0017-shadow-path-reverse-cull-and-simplepbr-optin.md) | Simulator Shadows: Reverse-Cull Path; `simplepbr` Opt-In |
| [0018](./0018-rover-physics-tuning-order.md) | Rover Physics Tuning Order |
| [0019](./0019-per-waypoint-provenance-state-machine.md) | Per-Waypoint Provenance State Machine |
| [0020](./0020-optimistic-mission-revision-concurrency.md) | Optimistic Mission Revision Concurrency |
| [0021](./0021-mission-lifecycle.md) | Mission Lifecycle: Configurable Execution Modes, Flat Mission Model, And Chat-Driven Operations |
| [0022](./0022-gps-master-coordinate-frame.md) | GPS-Master Coordinate Frame: WGS84 Is The Stored Truth, Local Metres Is Derived, Origin Per Mission |
| [0023](./0023-behavior-tree-missions-relocatable-executor.md) | Behavior-Tree Missions With A Relocatable Server-Side Executor; FC Upload Is The Navigation-Leaf Layer |
| [0024](./0024-mission-pause-stop-mechanism.md) | Mission Pause/Stop: Mode Switch Over MAV_CMD_DO_PAUSE_CONTINUE |
| [0025](./0025-operational-constraints-schema-and-scope.md) | Operational Constraints (Allowed Corridors & Blockages): Schema, Scope, And Lifecycle |
| [0026](./0026-replay-session-logging-ships-scrubbing-replay-deferred.md) | Telemetry Session Logging And Frame Scrubbing Ship Now; Deterministic Full-State Replay And Synchronized Video Remain Deferred |
| [0027](./0027-soft-constraint-route-scoring-for-pattern-planning.md) | Soft-Constraint Route Scoring For Operator-Drawn Pattern Planning |
| [0028](./0028-rag-project-docs-first-consumer-qdrant.md) | RAG Ships: `project_docs` Is The First Consumer, On A Qdrant Sidecar |
