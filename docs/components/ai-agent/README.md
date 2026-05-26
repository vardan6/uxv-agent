# AI Agent

The planning and execution agent that turns operator intent into rover missions: parses requests, builds and validates routes, drafts missions, surfaces them for approval, and hands off to the flight controller. Mission execution and route planning live here, not as peer components — see [ADR 0009](../../cross-cutting/decisions/0009-mission-execution-fold-under-ai-agent.md).

| Doc | Tier | Purpose |
|---|---|---|
| [requirements.md](./requirements.md) | Requirements | Product target: behavior, safety, capability ladder, approval, mission execution, route planning, vehicle profiles |
| [design.md](./design.md) | Design | Implementation strategy: runtime seams, mission execution boundary, route planning + vehicle profiles + export, phase plan, rollback. Topic-level internals (graph spec, intent parsing, planning shell, mission execution, context layer, replay access, route planning, spatial tools, token efficiency, tool contract) are folded in at the end of this file as of 2026-05-26. |
