# 0008. Defer Replay, Live-Map Sync, And Synchronized Video Until `rover-sim-next`

Date: 2026-05-20
Status: Accepted

## Context

Three operator-experience features have been sketched repeatedly:

1. **Mission replay** — scrubbing back through a recorded mission with full state.
2. **Live map / state sync at high fidelity** — sub-second-accurate rover position and orientation on the GCS map.
3. **Synchronized video** — camera stream aligned to telemetry timestamps for review and incident analysis.

All three depend on simulator capabilities that `3d-env` does not provide well: deterministic state snapshots, accurate physics timing, and a clean separation between sim time and wall time. Attempts to retrofit these onto `3d-env` produced fragile workarounds in earlier planning rounds.

## Decision

Replay, high-fidelity live-map sync, and synchronized video are deferred until `rover-sim-next` (see [0006](./0006-rover-sim-next-is-next-simulator.md)) is the runtime. They are not implemented against `3d-env`.

In the meantime, the AI agent and GCS provide best-effort live state via the structured providers from [0001](./0001-no-retained-current-state-topic.md), and the map widget shows current position without replay or fine-grained sync guarantees.

## Consequences

- Operator-experience requirements documents flag these features as "planned, blocked on `rover-sim-next`" rather than as in-progress work.
- No partial replay or sync implementation lands in `3d-env`-era code, which avoids creating cleanup debt at cutover.
- These features stay explicitly deferred in the active simulator and GCS design docs until a future simulator path makes them practical.
- Stakeholders asking about these features get a single answer with a clear unblock condition.

## Alternatives Considered

- **Build a degraded replay against `3d-env` now.** Rejected: the failure modes (drifting timestamps, lossy snapshots) would either ship to operators as a buggy feature or require a rewrite at cutover.
- **Treat each feature independently.** Rejected: all three share the same blocking dependency, so bundling them under one decision keeps the rationale visible and prevents the same conversation from happening three times.

## Follow-Ups

- When `rover-sim-next` is the runtime, open individual implementation ADRs (or designs) for each feature as it is picked up.
