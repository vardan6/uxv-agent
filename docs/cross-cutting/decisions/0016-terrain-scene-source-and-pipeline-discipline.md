# 0016. Terrain Scene Source-And-Pipeline Discipline: Do Not Hand-Edit `terrain_scene.v1.json`

Date: 2026-05-26
Status: Accepted

## Context

`config/terrain_scene.v1.json` is the authoritative runtime manifest for the `3d-env` simulator and the GCS map: terrain heightfield, road centerlines, pads, buildings, charging station, solar panels, rocks, trees, collision proxies, route-planning metadata. It is also generated from a compact seed file plus a generator script.

When something looks wrong — a floating charger leg, a broken collider, a road junction that does not snap — the shortest fix is to open `terrain_scene.v1.json` and patch the field directly. The cost of doing that repeatedly is that the file drifts from the source design: regeneration silently undoes the patch, multiple representations diverge, and the "source of truth" claim becomes a lie.

A future map-synchronization layer (BUS-style pipeline, broader map database) makes this worse: any layer that rebuilds derived map representations from a shared source will overwrite hand-patches without warning.

## Decision

`config/terrain_scene.v1.json` is treated as a generated runtime artifact. Fixes to terrain, charging-station geometry, roads, or colliders must follow the source-and-pipeline order:

1. Update the source that owns the scene design (currently the compact seed file plus the generator script).
2. Regenerate `config/terrain_scene.v1.json`.
3. Run the scene validator against the schema.
4. Run the simulator and validate driving from spawn, docking-area exit, road entry, object collision, and absence of floating or buried parts.
5. When a broader synchronization pipeline exists, run it so every derived map representation is rebuilt from the same source design.

Hand-editing the manifest directly is permitted only as an intentional debugging probe, and any such edit must be reconciled into the source before merging.

## Consequences

- Fixes survive regeneration and any future BUS-style sync pipeline without manual reconciliation.
- The source files (seed + generator) remain the single point of truth; derived artifacts can be deleted and rebuilt.
- Some quick fixes get more expensive in the short term; the cost is the price of keeping a regenerable pipeline regenerable.
- Once the expanded manifest is the only consumed source, the compact seed file can be removed or archived — the rule still applies to whatever owns the design.

## Alternatives Considered

- **Promote `terrain_scene.v1.json` to source-of-truth and drop the generator.** Rejected: loses the ability to rebuild derived map representations consistently when a sync layer arrives.
- **Allow targeted hand-edits with comments.** Rejected: comments do not survive JSON regeneration, and the convention erodes within a few sessions.

## Follow-Ups

- Companion design lives in [`docs/components/simulator/design.md`](../../components/simulator/design.md) § "Source And Pipeline Discipline" and § "Editing Rule".
