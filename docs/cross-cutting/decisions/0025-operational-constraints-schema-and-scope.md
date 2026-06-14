# 0025. Operational Constraints (Allowed Corridors & Blockages): Schema, Scope, And Lifecycle

Date: 2026-06-06
Status: Accepted 2026-06-09 (operator confirmed V1 semantics)

Builds on [ADR 0022](./0022-gps-master-coordinate-frame.md) (coordinate frame)
and the map-widget safety invariants — the client never invents backend contracts
and never mutates authoritative scene/mission state directly
([map-widget.md](../../components/gcs/design/map-widget.md) §Safety Invariants,
carried forward from [ADR 0021](./0021-mission-lifecycle.md)). Implements the
Phase 4 work in
[map-authoring-toolbar.md](../../components/gcs/design/map-authoring-toolbar.md).

## Context

`ai-agent/requirements.md:302` requires **allowed corridors** (must-stay-inside,
soft/hard) and **blockages** (must-stay-outside, soft/hard) as first-class
mission-planning data, with a map UI to create, view, edit, enable/disable, and
delete them. `gcs/requirements.md:186` requires the scene to render blockages
and corridors at all times.

These constraints are **distinct from the per-mission geofence**. The geofence is
a single inclusion polygon owned by a mission revision. Operational constraints
are deployment-wide planning data the planner reasons over across missions. Do
not conflate them or reuse the geofence storage path.

The previous ADR draft carried speculative fields (`scene/project-scoped` scope
identity, circles/volumes, `cost_multiplier`, `vehicle_profile_ids`,
`effective_from`/`effective_to`, `created_by`) before any corresponding system
existed. This ADR replaces that draft with a contract the current product can
explain and enforce.

## Decision

Operational constraints are backend-owned planning data, independent of Mission
revisions and Mission geofences.

The V1 implementation supports a deliberately small contract:

- two kinds: `allowed_corridor`, `blockage`
- WGS84 polygon geometry only
- two rules: `hard`, `soft`
- enabled/disabled lifecycle
- deployment-wide scope for the one active operating area
- backend CRUD with optimistic concurrency
- planner consumption and map rendering in the same delivery slice

## Meaning

### Hard constraints

- Enabled hard allowed corridors form one **union** of permitted area.
- If no hard allowed corridor exists, the operating area is not restricted by an
  allowed-corridor boundary.
- If one or more exist, every planned waypoint and route segment must remain
  inside their union.
- Enabled hard blockages are excluded from that permitted area.
- A route intersecting a hard blockage or leaving the hard allowed union is
  **rejected** by the planner.

### Soft constraints

- A soft allowed corridor expresses preference to remain inside.
- A soft blockage expresses preference to remain outside.
- Soft constraints affect planner cost but never make a route impossible.
- V1 uses one planner-configured penalty per soft kind. Per-object cost
  multipliers are deferred until a real tuning need exists.

The planner owns the exact cost algorithm. The API contract owns only the
operator-visible `soft` meaning.

### Runtime

This ADR defines **planning behavior, not live vehicle containment**.

The UI labels the feature `Planning constraints`. A `hard` planning rule must not
be presented as an active runtime safety guarantee until breach monitoring and
abort/replan policy are separately implemented and accepted.

## V1 Object

```json
{
  "id": "constraint-...",
  "kind": "allowed_corridor",
  "name": "North access lane",
  "polygon": [
    {"lat": 40.1701, "lon": 44.5001},
    {"lat": 40.1702, "lon": 44.5004},
    {"lat": 40.1699, "lon": 44.5005}
  ],
  "rule": "hard",
  "enabled": true,
  "version": 3,
  "created_at": "2026-06-06T18:00:00Z",
  "updated_at": "2026-06-06T18:10:00Z"
}
```

Required validation:

- stable server-assigned `id`
- non-empty operator-visible `name`
- at least three distinct WGS84 vertices
- finite latitude/longitude in valid ranges
- normalized closed polygon at the backend boundary
- rejection of degenerate and self-intersecting polygons
- `rule` is exactly `hard` or `soft`
- `enabled` is explicit

WGS84 is authoritative under ADR 0022. The API does not persist a
`coordinate_frame` field after normalization.

## Scope

V1 is deployment-wide because the product currently has one active operating
area and no stable `project_id` or `scene_id`.

The store must be isolated from:

- Mission revisions
- Mission geofence content
- generated `terrain_scene.v1.json`
- browser local storage

When multi-project or multi-site support becomes real, add a stable scope
identifier through a new migration and ADR update. Do not encode today's scene
filename or MQTT topic prefix as a fake project identity.

## Persistence And API

Dedicated backend repository using the existing SQLite persistence boundary.

Required operations:

- list all constraints, including disabled
- create
- update name, polygon, rule, or enabled state
- delete

Create returns version `1`. Update and delete require `expected_version`.
Stale writes return `409 Conflict`; the client refreshes and shows the conflict
instead of retrying blindly.

Deletion requires confirmation. Disable is the normal reversible action.

## Rendering And Editing

- Enabled and disabled objects remain visible on the map.
- Disabled objects are muted and explicitly marked `Disabled`.
- Hard/soft and allowed/blockage states are distinguishable without color alone.
- Failed saves preserve the draft and the last server version.
- Scene objects remain read-only.

The authoring toolbar exposes `Allowed corridor` and `Blockage` tools only
because the full vertical slice (list, render, create, edit, enable/disable,
delete, planner consumption, conflict handling) is complete.

## Deferred

The following need concrete use cases and their own semantics:

- circles, holes, multipolygons
- altitude bands or 3D volumes
- effective-from, expiry, and recurring schedules
- vehicle-profile applicability
- per-object soft cost multipliers
- authentication, roles, and creator identity
- runtime breach monitoring and abort/replan policy
- per-project or per-scene scope

Schema migration is cheaper than shipping fields whose meaning the product
cannot yet honor.

## Consequences

- The first implementation is smaller and fully testable.
- Multiple allowed corridors have deterministic union semantics.
- A hard rule has one clear planning meaning.
- The UI cannot imply runtime enforcement that does not exist.
- Temporary blockages are manually enabled/disabled until scheduling is designed.
- Future aerial support requires a deliberate altitude-reference decision rather
  than an unspecified `volume`.

## Alternatives Considered

- **Mission-scoped constraints** — rejected: shared operating-area policy would be
  duplicated and could diverge across Missions.
- **Reuse Mission geofence storage** — rejected: ownership, lifecycle, and planner
  meaning differ.
- **Store optional future fields now** — rejected: null fields do not avoid
  semantic migrations; they only freeze guesses.
- **Mutable JSON config store** — rejected for concurrent CRUD and auditability.
- **Runtime enforcement in the same ADR** — rejected until monitoring location,
  breach tolerance, stale-position behavior, and response policy are designed.
- **Accept the original ADR draft unchanged** — rejected: key safety semantics
  (`hard` meaning, union vs. intersection), scope identity, and geometry contract
  were undefined; speculative fields anticipated systems that do not exist.
