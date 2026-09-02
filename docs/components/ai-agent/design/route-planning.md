# Route Planning — Internals

Design reference for the road-graph + route-planner-tool + QGC `.plan` exporter slice. The product target and design rationale live in [../requirements.md](../requirements.md) (§ "Route Planning and Mission Export Requirement") and [../design.md](../design.md) (§ "Route Planning, Vehicle Profiles, and Mission Export").

## Algorithm reference

### Graph build

Source: `config/terrain_scene.v1.json`. Each road carries `centerline=[start,end]`, `geometry.width`, `metadata.drivable=true`, `metadata.route_planning_cost`, and `metadata.group`.

Build order:

1. **Endpoint snap.** Configurable epsilon (Settings: `road_graph_epsilon_m`, default ~0.5 m). The authored scene does not guarantee endpoint coordinates coincide exactly at junctions. Snap each endpoint to a canonical node within epsilon.
2. **T-junction / crossroad split.** For each road, find points where another road's endpoint (or another road's segment) lies within epsilon of its interior. Split the road at those points into sub-edges sharing a node. Segment-intersection pass during graph build; O(n²) over a small edge count is trivial.
3. **Edge weighting.** `length × cost_multiplier`. `cost_multiplier`: `preferred=1.0`, default `1.5`, `avoid=∞` (removed from the graph entirely).
4. **Group tagging.** Read `metadata.group` directly. No id-prefix parsing — fragile to renames and breaks for ad-hoc IDs. Current groups: `plant_a`, `plant_b`, `connector`, `building`, `start_hub`.

### Public interface

```python
class RoadGraphService:
    def nearest_node(self, x: float, y: float) -> NodeId: ...
    def shortest_path(self, a: NodeId, b: NodeId) -> list[NodeId]:
        """Dijkstra via heapq. No extra deps."""
    def cover_group(self, group: str, entry: NodeId) -> list[NodeId]:
        """Node-ordered tour visiting every group-tagged edge at least once.

        If the tagged subgraph is connected and all nodes have even degree,
        returns the Eulerian circuit. Otherwise pairs odd-degree nodes and
        duplicates shortest paths between each pair before computing the
        Euler circuit (Chinese-postman variant). For ≤ ~20 sub-edges per
        group, this is fast and gives a minimum-retrace tour.
        """
    def route_to_then_around_then_back(
        self, start_xy: tuple[float, float], group: str
    ) -> list[Waypoint]:
        """Composes:
           shortest_path(start → entry)
         + cover_group(group, entry)
         + shortest_path(entry → start)

        `entry` is the tagged-subgraph node with shortest graph distance
        from `start`.
        """
```

### Startup sanity check

Log node count, edge count, connected-component count. Single component expected for the current scene. A non-`1` component count surfaces graph-build bugs immediately rather than at dispatch time.

## Mission export reference

Output format: QGC `.plan` JSON. Reference: [../../../cross-cutting/research/flight-controllers/mission-formats.md](../../../cross-cutting/research/flight-controllers/mission-formats.md).

- `fileType="Plan"`, `version=1`
- `mission.firmwareType=3` (ArduPilot)
- `mission.vehicleType` from active `VehicleProfile.mav_vehicle_type` (10=rover, 2=multirotor, 1=fixed-wing)
- `plannedHomePosition` from current vehicle pose
- One `SimpleItem` per waypoint with `command=16` (`MAV_CMD_NAV_WAYPOINT`), `frame=3` (`GLOBAL_RELATIVE_ALT`), `params=[hold_s, accept_radius_m, 0, yaw_rad_or_NaN, lat, lon, alt]`
- Trailing `command=20` (`NAV_RETURN_TO_LAUNCH`) for `route_to_then_around_then_back` outputs
- Empty `geoFence` and `rallyPoints` blocks (schema requires the keys)
- Coordinates: the exporter reads each waypoint's **stored WGS84 `lat/lon/alt` directly** ([ADR 0022](../../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md)). The legacy local→geo flat-earth projection (off the per-Mission origin datum, falling back to `coordinate_system.georeference.origin_lat / origin_lon`) survives only as a fallback for legacy waypoints that carry `x/y/z` but no stored WGS84; accurate to ~10 m over the scene's ~300 m extent

Output path: `data/missions/<draft_id>.plan`. Recorded on the draft. The `.plan` is compiled per navigable segment by the behavior-tree leaf driver (`ai/mission_leaf_driver.py`) and installed on the flight controller through a `ControllerMissionAdapter` — pymavlink or MAVSDK (`MissionRaw`), selected by the `controller_mission_adapter` setting (ADR 0023 Phases 1–3). The earlier "MAVSDK upload is outside this PR" note is superseded: that upload-readback path now exists with controller-version CAS.

**Coordinate frame (GPS-master, [ADR 0022](../../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md)).** WGS84 `lat/lon/alt` is the **stored, authoritative** coordinate for every waypoint (planner output, draft/revision storage, AI tool results). Local scene metres (`{x, y, z}`, `L.CRS.Simple`) are a **derived, displayed** view, not the master record — the map widget computes them on overlay load by converting WGS84 through the Mission's origin. Each Mission carries its **own origin datum** `{origin_lat, origin_lon, origin_alt}`: seeded from the terrain scene's georeference in the simulator, sourced from the rover's GPS/home position on real hardware. Both representations are derivable from `WGS84 + origin`; neither is persisted twice, preventing cross-layer unit drift. `MissionExportService` reads the stored WGS84 directly rather than projecting at the boundary.

**Coordinate caveat.** The WGS84 ⇄ local-metres conversion is a flat-earth approximation, sub-metre-accurate over a rover's working area; large-area / multi-site accuracy is an Open Question (ADR 0022). For simulator Missions the seeded origin still comes from the scene `coordinate_system.georeference`; when real-world scene data arrives the georeference is regenerated and the conversion code consumes the new origin without changes.

## Tool result shape

Planner-tool results returned to the agent are a **compact summary** — not the raw waypoint list — so the agent's context budget is preserved:

```python
{
  "waypoint_count": int,
  "total_distance_m": float,
  "estimated_duration_s": float,
  "legs": [{"from": str, "to": str, "edge_ids": list[str], "distance_m": float}],
  "route_hash": str,
  "draft_step_id": str,
}
```

The full waypoint list is persisted with the proposed Mission revision, fetched by the UI for map rendering, and serialised to a QGC plan as part of proposal creation. The wire contract between agent and tools stays small and inspectable.

### `route_hash` is not a `draft_id`

`route_hash` is a content fingerprint of the waypoints (`sha1` of the rounded x,y list, 12 hex chars — `_route_hash` in `tool_registry.py`). It is **not** a persisted handle or Mission identity. The pipeline has one terminal planning step:

```
plan_route_* ──(waypoints)──▶ propose_mission_draft
   route_hash                  creates a Mission revision and serialises its plan
```

`plan_route_*` only computes a route; it persists nothing. `propose_mission_draft` is the terminal planning action: it creates the Mission revision and flat Mission row, returns their durable identifiers, and serialises the plan. A bare `route_hash` cannot substitute for either identifier.

## Per-waypoint defaults

- `accept_radius_m` is set per-waypoint by the route planner as `min(road_width / 2, default_accept_radius_m)`. `None` means "use Settings default" (allowed when road width is unknown).
- `hold_s` defaults to `0.0` from Settings. Route planner does not set per-waypoint values in this slice.
- `yaw_rad` is always `None` at the route-planner layer (a navigation path has no opinion on heading). Task-layer steps (e.g., `inspect`) may override yaw. Exporter renders `None → NaN` for vehicles where that means "keep current heading" (rover, copter); profiles where yaw cannot be honored (fixed-wing) strip the value.
- Altitude `z` is always carried on persisted waypoints. Tool inputs may omit `z`; when they do, the tool layer samples terrain ground elevation from the current scene heightmap and persists that value as the waypoint's local `z` before the WGS84 truth-flip. Exporter rendering still depends on the active profile (ground → clamp to 0, aerial → use `z` or task/profile cruise altitude).

## Mission Draft schema additions

- `step.waypoints: list[Waypoint] | None` — populated when the step is materialised by a route tool.
- `step.route_summary: RouteSummary | None` — the compact result the agent saw.
- `draft.lifecycle: Literal["draft", "approved", "exported", "uploading", "uploaded", "executing", "completed", "failed", "cancelled"]` — declared in full; reachable today: `draft / approved / exported / failed / cancelled`.
- `draft.lifecycle_history: list[{state, ts, actor}]` — append-only audit trail.
- `draft.dispatch_mode: Literal["plan_only", "plan_and_execute"]` — inferred by the agent from prompt context.
