# AI Agent — Internals

Topic-level notes on how the agent is currently implemented. Regenerable from code; freely edited as the implementation moves.

| Doc | Topic |
|---|---|
| [graph-spec.md](./graph-spec.md) | LangGraph node/edge structure for the planning shell |
| [context-layer.md](./context-layer.md) | What context is assembled for each turn and how |
| [spatial-tools.md](./spatial-tools.md) | Geospatial tools available to the agent |
| [mission-execution.md](./mission-execution.md) | Mission execution implementation |
| [tool-contract.md](./tool-contract.md) | Standard contract every agent tool implements |
| [replay-access.md](./replay-access.md) | How the agent reads replay state |
| [planning-shell.md](./planning-shell.md) | The planning shell and its durable approval wrapper |
| [intent-parsing.md](./intent-parsing.md) | Intent classification and parsing pipeline |
| [route-planning.md](./route-planning.md) | Road graph, planner tools, QGC `.plan` export, and the manual validation checklist |
| [token-efficiency.md](./token-efficiency.md) | Token-usage audit + phased optimization plan (Phase 1 + Phase 2 #6 shipped; Phase 3 outstanding) |
