# 0009. Mission Execution Lives Under `ai-agent`, Not As A Peer Component

Date: 2026-05-20
Status: Accepted

## Context

Mission execution — turning an approved mission plan into commands the rover follows, monitoring progress, and handing off to a flight controller — was initially scoped as its own component in early planning. A `components/mission-execution/` folder was on the table during the documentation restructure (see `restructure-plan.md`).

When the surface area was inventoried, every piece of mission-execution behavior was either:

- already implemented inside the AI agent graph (`gcs_server/ai/`), or
- a contract the AI agent owns (flight-controller handoff, plan-to-command translation, in-flight replanning).

There is no mission-execution code or runtime that lives outside the agent.

## Decision

Mission execution is documented as part of the `ai-agent` component, not as a peer component. Its requirements fold into `components/ai-agent/requirements.md`, its design into `components/ai-agent/design.md`, and its implementation lives in `components/ai-agent/internals/mission-execution.md`.

The same applies to closely related concerns: route planning and mission export are also folded under `ai-agent` for the same reason — the agent is the implementing surface.

## Consequences

- The `components/` folder has three components — `ai-agent`, `gcs`, `simulator` — not four or five. This matches the actual code boundaries.
- An operator wanting to understand mission execution lands in `ai-agent/` and finds it adjacent to the agent graph, context layer, and tool contracts that produce it.
- If mission execution ever grows a runtime outside the agent (e.g., a separate execution service), this ADR is superseded by one that promotes it to a peer component.
- Documentation cross-links don't have to thread between two components for what is in practice one component's responsibility.

## Alternatives Considered

- **Make mission-execution a peer component.** Rejected: would create a component folder whose `internals/` is a thin shim into `gcs_server/ai/`, with no independent surface. The folder would be more navigation overhead than navigation aid.
- **Split mission-execution requirements out as a top-level doc.** Rejected: the requirements naturally read alongside the broader agent requirements (planning, approval, handoff form one operator-facing flow).

## Follow-Ups

- If a separate mission-execution runtime is ever introduced, open a superseding ADR and refactor `components/`.
