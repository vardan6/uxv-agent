# 0011. Mission Coordinate Frame Split: Local Metres Internally, WGS84 Only At Export

Date: 2026-05-26
Status: Superseded by [ADR 0022](./0022-gps-master-coordinate-frame.md)

## Context

The mission stack handles coordinates in several places: the route planner, mission-draft storage, the AI agent's tool results, the map widget's rendering surface, and the QGC `.plan` exporter. Each of these could in principle work in either local scene metres or WGS84 lat/lon. The terrain scene manifest carries both representations (`coordinate_system.georeference` defines an artificial origin), so the choice has to be deliberate.

Two failure modes motivated an explicit rule:

1. Mixing units across layers — e.g. storing waypoints in lat/lon but rendering against `L.CRS.Simple` — creates silent geometry bugs that only surface at export time.
2. Treating the current development georeference as authoritative bakes a placeholder anchor into every consumer. The georeference is expected to be regenerated together with the scene when real hardware/site data arrive.

## Decision

All mission overlay coordinates inside the system use **local scene metres** (`{x, y, z}`) with `L.CRS.Simple` as the coordinate reference system. This applies to planner output, revision storage, map widget rendering, AI tool results, and any intermediate transformation.

Conversion to WGS84 lat/lon happens **only at export time** in `MissionExportService`, via a flat-earth approximation off `coordinate_system.georeference.origin_lat / origin_lon`. Nothing upstream of the exporter deals in lat/lon.

## Consequences

- Internal geometry, distance, and bearing calculations stay in one frame; no unit-mismatch bugs between layers.
- Replacing the development georeference is a single-point change: the projection code consumes the new origin without callers needing to be updated.
- Any future WGS84 basemap mode must be a distinct widget mode with explicit CRS metadata — it does not retroactively change the internal frame.
- `.plan` export remains the canonical boundary at which lat/lon enters the world.

## Alternatives Considered

- **Store WGS84 throughout.** Rejected: forces every consumer to depend on a placeholder georeference, and adds projection cost to every render and query.
- **Store both and pick per call site.** Rejected: doubles the surface area for unit-mismatch bugs.

## Follow-Ups

- See [`docs/components/ai-agent/design.md`](../../components/ai-agent/design.md) § "Coordinate frame split" for the algorithmic detail.
- See [`docs/components/gcs/design.md`](../../components/gcs/design.md) § "Coordinate System" for the rendering rule.
