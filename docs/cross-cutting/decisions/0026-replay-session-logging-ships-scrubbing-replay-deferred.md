# 0026. Telemetry Session Logging Ships Now; Scrubbing Replay And Synchronized Video Remain Deferred

Date: 2026-06-13
Status: Accepted
Supersedes: [0008](./0008-defer-replay-and-live-map-until-sim-next.md)

## Context

ADR 0008 (2026-05-20) deferred three features — mission replay, high-fidelity live-map sync, and synchronized video — until `rover-sim-next` replaces `3d-env`. The rationale was that all three depend on deterministic state snapshots and accurate physics timing that `3d-env` cannot provide cleanly.

Since then, a `ReplayStore` (`replay_store.py`), a `ReplayAnalyticsService`, and a replay API router (`routers/replay.py`) have shipped on `3d-env`. ADR 0014 (2026-05-26) also governs server-side session reference resolution for this system. ADR 0008's "Accepted + no partial implementation" status is therefore factually wrong.

The shipped system is not the feature ADR 0008 deferred. It is an **observability and analytics layer**: it logs per-session telemetry samples, control events, and runtime events to SQLite; it exposes session timelines, summaries, and comparison aggregates to the operator and to AI tools; it does not provide time-scrubbing playback of a recorded mission or synchronized video.

## Decision

**Split the original bundle into two tracks with different defer conditions:**

### Track A — Telemetry session logging and analytics (ships now, `3d-env`-era)

`ReplayStore` and its router are observability infrastructure. They record what happened during a session so operators and AI tools can query it. This does not require deterministic physics timing or `rover-sim-next`; logging works against any backend. It ships and is governed by ADR 0014.

### Track B — Scrubbing replay, high-fidelity live-map sync, synchronized video (still deferred)

Operator-facing time-scrubbing playback ("scrub back through a recorded mission with full state"), sub-second live-map position sync, and camera-aligned video review remain blocked on `rover-sim-next`. The failure modes ADR 0008 identified — drifting timestamps, lossy snapshots — apply to these three features specifically. No partial implementation of Track B lands in `3d-env`-era code.

## Consequences

- ADR 0008 is superseded; its deferral reasoning applied to Track B only and remains valid for it.
- The `ReplayStore` / analytics system is no longer in conflict with any ADR.
- Operator-experience docs flag Track B features as "planned, blocked on `rover-sim-next`" (unchanged from ADR 0008).
- When `rover-sim-next` is the runtime, open individual implementation ADRs for Track B features as they are picked up (unchanged follow-up from ADR 0008).

## Alternatives Considered

- **Roll back the replay store.** Rejected: it provides real observability value, is already in production use, and does not violate the spirit of ADR 0008's concern (which targeted scrubbing UI, not logging).
- **Amend ADR 0008 in place.** Rejected: the scope change is substantive enough to warrant a new record rather than editing the original rationale.

## Follow-Ups

- Session reference resolution rules: [ADR 0014](./0014-replay-session-resolution-server-side.md).
- Track B features listed in product follow-ups under `docs/components/gcs/design.md` remain blocked on `rover-sim-next` per [ADR 0006](./0006-rover-sim-next-is-next-simulator.md).
