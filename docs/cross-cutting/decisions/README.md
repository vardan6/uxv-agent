# Decisions

Architecture Decision Records. Numbering is monotonic and never reused. Superseded ADRs change status to "Superseded by <link>" but are not deleted. Template and conventions live in [../../STYLE.md](../../STYLE.md).

| # | Title |
|---|---|
| [0001](./0001-no-retained-current-state-topic.md) | No Retained MQTT Current-State Topic |
| [0002](./0002-two-approval-model.md) | Two-Approval Model: Draft Approval ≠ Execution Approval |
| [0003](./0003-rag-scope-vs-live-context.md) | RAG Scope: Documents And Memory, Not Live State |
| [0004](./0004-langgraph-checkpointer-choice.md) | LangGraph Planning Shell Checkpointer: MemorySaver For Now |
| [0005](./0005-keep-3d-env-as-current-simulator.md) | Keep `3d-env` As The Current Simulator Runtime |
| [0006](./0006-rover-sim-next-is-next-simulator.md) | `rover-sim-next` Is The Next Simulator Implementation |
| [0007](./0007-rag-later-not-now-for-live-state.md) | RAG Is Deferred; Live State Stays Structured Only |
| [0008](./0008-defer-replay-and-live-map-until-sim-next.md) | Defer Replay, Live-Map Sync, And Synchronized Video Until `rover-sim-next` |
| [0009](./0009-mission-execution-fold-under-ai-agent.md) | Mission Execution Lives Under `ai-agent`, Not As A Peer Component |
| [0010](./0010-internals-tier-naming.md) | "Internals" Is The Name Of The Third Documentation Tier |
