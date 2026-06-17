# 0015. MCP Is An Adapter Layer, Not The First Implementation Of Agent Tools

Date: 2026-05-26
Status: Accepted

## Context

Model Context Protocol (MCP) is an attractive substrate for exposing rover and replay tools to external agents. The shortest path from "we want agent tools" to "agent tools exist" is to write them as MCP servers from day one.

That shortest path has a coupling cost: every internal caller of these tools — the GCS Agent mode, shared intent-parsing and mission-authoring flows, the LangGraph planning shell, server-side request planning — would either go through an MCP client transport for in-process calls, or duplicate the logic outside MCP. The first option adds latency and packaging weight to internal flows that already have direct Python access; the second creates two implementations of the same query.

## Decision

MCP is treated as an adapter layer, not the first implementation. The order of work is:

1. Build deterministic spatial / state / replay services as normal Python modules.
2. Expose them through a single in-process tool registry, used by Agent mode, shared intent-parsing and mission-authoring flows, and planning shell.
3. Later, surface a stable subset of read-only and planning tools through MCP for external agents.

## Consequences

- Internal callers use direct Python calls; latency and packaging stay small.
- The in-process tool registry is the single source of truth for tool definitions, permission classes, and async/sync behavior — MCP becomes a thin adapter on top.
- External agents get a stable MCP-shaped surface without GCS internals having to be reorganized around MCP semantics.
- Adding a new tool starts in Python, not in MCP schemas, which keeps the tool-authoring surface familiar.

## Alternatives Considered

- **Implement tools as MCP servers from the start.** Rejected for the coupling cost above.
- **Skip MCP entirely.** Rejected: MCP-ready exposure is a real product goal for external agents; it just is not the implementation entry point.

## Follow-Ups

- Companion design lives in [`docs/components/ai-agent/design.md`](../../components/ai-agent/design.md) § "MCP Direction" and § "Agent Tool Registry".
