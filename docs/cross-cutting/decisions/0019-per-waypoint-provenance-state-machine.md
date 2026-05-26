# 0019. Per-Waypoint Provenance State Machine: `ai` / `user` / `ai+edited`

Date: 2026-05-26
Status: Accepted

## Context

Mission waypoints can originate from AI planning, from direct operator authoring, or from operator edits on top of AI output. The planning shell can be invoked again on an existing mission to refine or regenerate waypoints. Without a provenance model, regeneration silently overwrites operator edits — including edits made specifically to correct an AI mistake — which is exactly the failure mode the mission-lifecycle approval gate ([ADR 0021](./0021-mission-lifecycle.md), superseding the original two-approval model in [ADR 0002](./0002-two-approval-model.md)) exists to prevent.

The provenance signal must be carried through three surfaces consistently: the mission revision store (`mission_execution`), the planning shell's regeneration logic, and the map widget's editing UI.

## Decision

Every waypoint carries one of three provenance states:

- `ai` — created by planning output without manual edits
- `user` — created directly by the operator
- `ai+edited` — originally AI-created, then operator-modified

Transition rules:

- Any operator edit to an `ai` waypoint promotes it to `ai+edited`. There is no demotion.
- `ai` waypoints can be freely replaced by new AI output.
- `user` and `ai+edited` waypoints require explicit operator confirmation when replacement is proposed.

Enforcement points:

- The planning shell checks provenance before overwrite and routes through the clarification flow when `ai+edited` (or `user`) waypoints would be replaced.
- The mission-execution backend blocks regenerations that would overwrite `ai+edited` waypoints without explicit operator confirmation.
- The map widget surfaces provenance per waypoint and uses it to drive the editing/regeneration UX.

## Consequences

- AI regeneration never silently undoes an operator correction.
- The three-state model is simple enough to render in the widget and explain in approval cards.
- The clarification flow becomes the canonical place where "the AI wants to replace your edit" is resolved.
- Provenance is part of the mission revision payload, not a UI-only convention — it survives across reloads and across the agent/widget boundary.

## Alternatives Considered

- **Single "user-modified" flag.** Rejected: loses the distinction between operator-authored and operator-edited-AI waypoints, which matters for regeneration semantics.
- **No provenance, with operator re-approval gating regeneration.** Rejected: re-approval is too coarse; operators want to see which specific waypoints would change.

## Follow-Ups

- Backend state machine lives in [`docs/components/ai-agent/design.md`](../../components/ai-agent/design.md) § "Provenance State Machine".
- Regeneration guard lives in [`docs/components/ai-agent/design.md`](../../components/ai-agent/design.md) § "Provenance-Aware Regeneration Rule".
- UI contract lives in [`docs/components/gcs/design.md`](../../components/gcs/design.md) § "Provenance State Machine".
