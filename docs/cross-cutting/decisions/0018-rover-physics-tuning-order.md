# 0018. Rover Physics Tuning Order: Suspension → Drift → Climb → Side-Slope

Date: 2026-05-26
Status: Accepted

## Context

Rover physics tuning in the simulator touches a coupled set of parameters: suspension settling, slip/drift balance, hill traction, and side-slope stability. Each of these affects the others, and the cheap instinct is to chase whatever currently looks wrong on the test route. The expensive part is that slip-balance changes invalidate climb and side-slope results: tuning in the wrong order means re-running previously-accepted passes.

The tuning method is evaluated against one fixed manual route with four checkpoints (straight bump, uphill climb, side-slope traverse, downhill turn) and a fixed set of acceptance behaviors. Without an explicit order, accepted-baseline behavior can silently regress as later passes invalidate earlier ones.

## Decision

Tuning work proceeds in this fixed order:

1. Suspension settling
2. Turn and drift balance
3. Hill traction and climb
4. Side-slope stability

Each pass is evaluated against the same fixed four-checkpoint route and the same acceptance rules before moving to the next pass. Slip-balance changes are not introduced after climb and side-slope passes have been accepted.

## Consequences

- Earlier accepted passes remain valid as later passes proceed.
- Regressions caused by reordering become visible at the acceptance step rather than at integration time.
- The fixed route plus acceptance rules form a reusable harness; new tuning sessions do not need to re-derive what "good" means.
- Visual-only geometry changes stay decoupled from physics conclusions unless explicitly promoted into the physics layer.

## Alternatives Considered

- **Tune whatever looks worst first.** Rejected for the coupling reason above.
- **Auto-score the fixed route.** Out of scope for this decision (and explicitly a non-goal of the tuning doc).

## Follow-Ups

- Companion design lives in [`docs/components/simulator/design.md`](../../components/simulator/design.md) § "Tuning Sequence" and § "Acceptance Behavior".
