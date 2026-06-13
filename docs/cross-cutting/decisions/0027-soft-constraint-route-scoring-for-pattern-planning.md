# 0027. Soft-Constraint Route Scoring For Operator-Drawn Pattern Planning

Date: 2026-06-13
Status: Proposed

Builds on [ADR 0025](./0025-operational-constraints-schema-and-scope.md)
(operational constraints semantics) and the current operator-drawn pattern flow
in `gcs_server/ai/mission_execution_service.py:create_drawn_pattern_mission`.

## Context

ADR 0025 already defines the operator-visible meaning of `soft` constraints:
they affect planner cost but never make a route impossible. The shipped code
only enforces the `hard` half of that contract. `create_drawn_pattern_mission`
generates one corridor or survey route and either accepts it or rejects it
against hard constraints; no cost model exists, so soft corridors and soft
blockages are currently ignored.

The next implementation slice needs an explicit contract for:

- which candidate routes the draw-pattern planner may compare
- how soft penalties are computed from those routes
- how hard rejection and soft preference interact
- what metadata the UI and tests can rely on

Without that contract, any scoring code would be guesswork.

## Decision

V1 soft-cost planning applies to **operator-drawn survey patterns first** and
to **corridor patterns only as scored metadata**.

- Hard constraints stay unchanged: any candidate violating a hard allowed
  corridor or hard blockage is rejected before soft scoring.
- Survey generation may evaluate multiple valid candidates and must choose the
  lowest-cost one.
- Corridor generation remains geometry-preserving in V1: the operator-drawn path
  is the route. It is still scored against soft constraints and may report its
  penalty breakdown, but it is not laterally rerouted in this ADR.
- Soft penalties are additive and length-based so tuning is stable and local:
  longer travel through undesirable space costs more than shorter travel.

This scopes the first delivery to a finite candidate set that the current code
can generate without inventing speculative path-offset machinery for arbitrary
polylines.

## Candidate Generation

### Survey

For one drawn survey rectangle, the planner evaluates these candidates:

1. heading `0` over the rectangle's local bounding box
2. heading `90` over the same rectangle
3. heading `180` only as the reverse traversal of candidate 1
4. heading `270` only as the reverse traversal of candidate 2

The geometry pairs are therefore two unique sweep layouts:

- east-west lines stepping north-south
- north-south lines stepping east-west

Reverse traversals are included only as tie-break variants for operator feel and
future vehicle-entry heuristics. They do not change the soft penalty because
the path geometry is identical.

### Corridor

Corridor V1 has exactly one geometric candidate: the operator's drawn polyline
densified by the existing `corridor_pattern` logic. The planner computes its
soft-cost breakdown but does not synthesize left/right offset alternatives.

If operators later need automatic corridor biasing around soft blockages, that
requires a separate ADR because arbitrary polyline offsetting, corner handling,
and self-intersection repair are new path-planning semantics rather than a
small extension.

## Cost Model

The planner scores each surviving candidate with:

`total_cost = base_length_m + soft_penalty`

Where:

- `base_length_m` is the total route length in metres
- `soft_penalty` is the sum of all enabled soft-constraint penalties below

### Soft blockage penalty

For every enabled soft blockage polygon:

- measure the total route-segment length that lies inside the polygon
- add `inside_length_m * soft_blockage_penalty_per_m`

### Soft allowed-corridor penalty

For the union of all enabled soft allowed corridors:

- if no enabled soft allowed corridor exists, add `0`
- otherwise measure the total route-segment length outside that union
- add `outside_length_m * soft_corridor_penalty_per_m`

This keeps the semantics parallel to ADR 0025:

- soft blockage means "prefer to stay outside"
- soft allowed corridor means "prefer to stay inside"

### Overlap

Penalties are additive across distinct soft constraints. A route segment inside
two soft blockages incurs both penalties. This is intentional: overlapping soft
objects express stronger operator preference in that area.

Hard constraints are never converted into a large soft penalty. They remain
binary rejection.

## Tie-Break Order

Candidates are ordered by:

1. lowest `total_cost`
2. lowest `soft_penalty`
3. lowest `base_length_m`
4. existing generator order

This keeps route choice deterministic when two candidates are effectively equal.

## Runtime Surface

The draw-pattern planner should return scoring metadata alongside the chosen
revision so tests and the UI can explain why one survey layout won:

```json
{
  "soft_cost": {
    "chosen_heading_deg": 90,
    "base_length_m": 120.0,
    "soft_penalty": 35.0,
    "total_cost": 155.0,
    "breakdown": {
      "soft_blockage_m": 5.0,
      "soft_corridor_outside_m": 3.0
    },
    "candidate_count": 4
  }
}
```

V1 requires this metadata only on the backend response and in tests. No new map
chrome or panel text is required in the same slice.

## Settings

V1 uses two planner-configured constants:

- `soft_blockage_penalty_per_m`
- `soft_corridor_penalty_per_m`

They may initially live as module-level defaults inside the planner code. A
user-editable settings surface is deferred until there is real tuning pressure.

The penalties should be chosen so that:

- a short excursion through a soft area can still win when it saves meaningful
  distance
- a long path through an undesirable area predictably loses to a modest detour

## Non-Goals

This ADR does not add:

- lateral corridor offset generation
- curved detours or polygon clipping around blockages
- runtime containment or breach monitoring
- per-object soft multipliers
- soft-cost consumption by the road-graph route tools

Those are separate work items with different geometry and UX implications.

## Consequences

- ADR 0025's `soft` meaning becomes implementable without widening the public
  CRUD schema.
- Survey authoring gains a real preference mechanism with deterministic tests.
- Corridor authoring remains stable and predictable instead of shipping an
  under-specified auto-offset feature.
- The next code slice can be small: score finite survey candidates, choose one,
  and expose the scoring metadata.

## Alternatives Considered

- **Treat soft constraints as warnings only.** Rejected: it would leave ADR 0025
  unimplemented and give the planner no preference behavior.
- **Convert hard constraints into very large penalties.** Rejected: a hard rule
  must remain impossible to violate, not merely expensive.
- **Add arbitrary corridor offset candidates now.** Rejected: corner joins,
  self-intersection repair, and operator expectations are not defined yet.
- **Apply soft scoring to all route planners in one step.** Rejected: the
  road-graph tools and draw-pattern generators have different candidate spaces;
  coupling them would make the first delivery larger and less testable.
