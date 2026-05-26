# 0012. Map Widget Safety Invariants: Approval ≠ Execution, No Client-Side Mutation Of Executing Missions, No Fake Backend Contracts

Date: 2026-05-26
Status: Accepted

## Context

The reusable mission map widget on `/ai` exposes operators to direct manipulation of mission revisions: drag, insert, delete, multi-select, approve, reject, execute. Without explicit rules, a "responsive UI" instinct tends to collapse these into single gestures, optimistically mutate executing missions, or fake state for backend features that do not exist yet (geofence, home-point editing, mission revision push).

Each of those shortcuts has a concrete failure mode in this product:

- Collapsing approval and execution removes the human-in-the-loop safety gate that the two-approval model ([ADR 0002](./0002-two-approval-model.md)) exists to enforce.
- Client-side mutation of an executing revision creates a window where the rendered geometry diverges from what the controller is actually flying.
- Inventing UI for missing backend contracts creates user-visible affordances that silently do nothing — operators learn to distrust the widget.

## Decision

Four non-negotiable safety invariants govern the widget:

1. **Approval is not execution.** Approval, rejection, and execution remain separate explicit operator actions.
2. **The client never mutates an executing mission.** Drag/insert/delete gestures short-circuit on locked revisions; edit/approve/reject affordances are disabled while executing.
3. **The client never silently overwrites authoritative mission state.** All geometry mutation goes through backend round-trips with optimistic concurrency checks; on failure, the widget refreshes against the backend rather than retrying the local edit.
4. **The widget never invents backend contracts that do not exist.** Missing backend features (geofence display, home-point editing, WGS84 basemap, mission revision push) are hidden or disabled explicitly until a real backend source exists.

## Consequences

- Some affordances (geofence, home-point edit, WGS84 basemap, push events) stay deferred even when they would be straightforward to fake client-side.
- Every editing gesture pays a backend round-trip; the widget cannot guarantee zero-latency edits and does not pretend to.
- Execution lock is enforced at the gesture handler level, not only at the render layer — visually-locked rendering alone is not sufficient.
- The widget's editing model is allowed to evolve (new gestures, richer property editing) only within these invariants.

## Alternatives Considered

- **Optimistic client-side edits with reconciliation.** Rejected: the cost of a visible divergence on an executing mission is much higher than the cost of a round-trip.
- **Combine approval and execute into one button.** Rejected: directly contradicts [ADR 0002](./0002-two-approval-model.md).
- **Stub-render geofence/home-edit using local state.** Rejected: trains operators to trust UI that has no backend effect.

## Follow-Ups

- Companion design lives in [`docs/components/gcs/internals/map-widget.md`](../../components/gcs/internals/map-widget.md) § "Safety Invariants" and § "Editing Model".
- Per-waypoint provenance enforcement is the subject of [ADR 0019](./0019-per-waypoint-provenance-state-machine.md).
- Optimistic concurrency on revision mutation is the subject of [ADR 0020](./0020-optimistic-mission-revision-concurrency.md).
