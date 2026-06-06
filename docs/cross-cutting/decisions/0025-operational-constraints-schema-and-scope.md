# 0025. Operational Constraints (Allowed Corridors & Blockages): Schema, Scope, And Lifecycle

Date: 2026-06-06
Status: Proposed

Builds on [ADR 0022](./0022-gps-master-coordinate-frame.md) (coordinate frame)
and the map-widget safety invariants — the client never invents backend
contracts and never mutates authoritative scene/mission state directly
([map-widget.md](../../components/gcs/design/map-widget.md) §Safety Invariants,
carried forward from [ADR 0021](./0021-mission-lifecycle.md)). Unblocks the
Phase 4 work in
[map-authoring-toolbar.md](../../components/gcs/design/map-authoring-toolbar.md).

## Context

`ai-agent/requirements.md:302` requires **allowed corridors** (must-stay-inside,
soft/hard) and **blockages** (must-stay-outside, soft/hard) as first-class
mission-planning data, with a map UI to create, view, edit, enable/disable, and
delete them. `gcs/requirements.md:186` also requires the scene to render
blockages and corridors at all times.

The 2026-06-06 map-authoring-toolbar review correctly refused to add a `Blockage`
draw button before the data model, persistence, planner consumption, rendering,
and edit lifecycle were defined together (its finding #4). No implementation
exists today: the referenced `config/operational_constraints.v1.json` is named in
prose only.

This created a stall: the genuinely shippable toolbar UX (collapse, one-active-
tool, naming) was blocked behind an undefined platform with six open product
questions. This ADR resolves the platform's *shape* with conservative defaults so
the toolbar UX can ship first and the constraints feature can be built later
against a settled contract — not so it must be built now.

These constraints are **distinct from the per-mission geofence**. The geofence is
a single inclusion polygon owned by a mission and pushed with it. Operational
constraints are scene/project-level planning data the planner reasons over across
missions. Do not conflate them or reuse the geofence storage path.

## Decision

Define operational constraints as a versioned, scene/project-scoped backend
contract. Implementation is deferred to Phase 4 of the authoring toolbar; this
ADR fixes the schema and answers the open product questions.

### Object model

Two object kinds sharing one envelope:

- **allowed_corridor** — planner must remain inside.
- **blockage** — planner must remain outside.

Common fields:

| Field | Meaning |
|---|---|
| `id` | stable server-assigned id |
| `kind` | `allowed_corridor` \| `blockage` |
| `name` | operator-visible label |
| `geometry` | polygon/circle (ground) or volume (aerial), in WGS84 truth |
| `coordinate_frame` | source frame the client supplied (server normalizes to WGS84) |
| `rule` | `hard` \| `soft` |
| `cost_multiplier` | optional, soft only |
| `enabled` | bool; disabling never deletes and must restyle the map immediately |
| `vehicle_profile_ids` | optional, nullable — null = applies to all profiles |
| `effective_from` / `effective_to` | optional time window (schema only; runtime enforcement deferred) |
| `created_by` / `created_at` / `updated_at` | provenance metadata |
| `version` | optimistic-concurrency token (per ADR 0020 pattern) |

### Scope, persistence, lifecycle

- **Scope: scene/project-scoped.** Constraints persist with the scene/project, not
  per mission, matching "render … at all times" (`gcs/requirements.md:186`).
  Optional `vehicle_profile_ids` narrows applicability without changing scope.
- **Persistence: a dedicated versioned store and API**, separate from mission
  revisions and from the geofence path. The client never writes browser-only
  annotations and never mutates the large terrain-scene JSON directly (map-widget safety invariants).
- **Lifecycle: full CRUD + enable/disable**, with optimistic concurrency
  (`version`). Deleting a constraint requires confirmation; disabling is the
  non-destructive path.

### Resolved open product questions

1. **Scope** → scene/project, with optional nullable vehicle-profile applicability.
2. **Activation windows / expiry** → `effective_from`/`effective_to` exist in the
   schema; the planner honoring them is future work, gated separately.
3. **Permission tier** → none now (single-operator); `created_by` leaves room to
   add a gate later with no migration.
4. **Geofence vs. constraints** → separate. Geofence stays single-inclusion,
   per-mission; multi-region inclusion/exclusion, if ever needed, is modeled as
   constraints, not by overloading the geofence.
5. **Editor plugin** → none; constraint geometry editing reuses the custom
   `MapSketchSession` (see authoring-toolbar Decision A).

## Consequences

- The authoring toolbar's `Constraints ▾` menu stays **disabled** until this ADR
  is accepted and Phase 4 lands. The toolbar's Phase 1 (collapse, one-active-tool,
  naming, transaction model) ships independently — that is the point of this ADR.
- A new backend surface is required at Phase 4: versioned store + CRUD endpoints +
  a render layer. Until then, "render constraints at all times" is satisfied
  vacuously (no constraints exist).
- Soft `cost_multiplier` and `effective_*` windows are carried in the schema
  before the planner consumes them, so adding enforcement later needs no schema
  migration.
- Marked **Proposed**, not Accepted, because it commits the project to a new
  backend contract; it is ready to accept once the operator confirms scope and
  the conservative defaults.

## Alternatives Considered

- **Mission-scoped constraints** — rejected: contradicts scene-level "render at
  all times" and would duplicate constraints across missions sharing a scene.
- **Reuse the geofence path** — rejected: geofence is a single per-mission
  inclusion polygon with different semantics, ownership, and safety meaning;
  overloading it would re-create the "Corridor"/"Clear" term collisions the
  authoring redesign is removing.
- **Ship a `Blockage` button against client-only storage now** — rejected by the
  map-widget safety invariants (no invented contracts; no client-side scene
  mutation) and by the review's finding #4.
- **Define nothing and let Phase 4 decide** — rejected: that is the stall this ADR
  exists to break; leaving scope open keeps the toolbar UX blocked.
