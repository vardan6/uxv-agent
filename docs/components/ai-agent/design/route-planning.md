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

Output path: `data/missions/<draft_id>.plan`. Recorded on the draft. The `.plan` file is the current hand-off boundary to the flight controller; MAVSDK `import_qgroundcontrol_mission` → `upload_mission` over UDP 14550 is the documented next slice and lives outside this PR.

**Coordinate frame (GPS-master, [ADR 0022](../../../cross-cutting/decisions/0022-gps-master-coordinate-frame.md), supersedes ADR 0011).** WGS84 `lat/lon/alt` is the **stored, authoritative** coordinate for every waypoint (planner output, draft/revision storage, AI tool results). Local scene metres (`{x, y, z}`, `L.CRS.Simple`) are a **derived, displayed** view, not the master record — the map widget computes them on overlay load by converting WGS84 through the Mission's origin. Each Mission carries its **own origin datum** `{origin_lat, origin_lon, origin_alt}`: seeded from the terrain scene's georeference in the simulator, sourced from the rover's GPS/home position on real hardware. Both representations are derivable from `WGS84 + origin`; neither is persisted twice (that was the unit-drift bug ADR 0011 guarded against). `MissionExportService` reads the stored WGS84 directly rather than projecting at the boundary.

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

The full waypoint list is persisted on the Mission Draft step and fetched by the UI for map rendering and by `export_mission` for serialisation. The wire contract between agent and tools stays small and inspectable.

### `route_hash` is not a `draft_id`

`route_hash` is a content fingerprint of the waypoints (`sha1` of the rounded x,y list, 12 hex chars — `_route_hash` in `tool_registry.py`). It is **not** a persisted handle and must never be passed to `export_mission`. The pipeline has a required middle step:

```
plan_route_* ──(waypoints)──▶ propose_mission_draft ──(draft_id)──▶ export_mission(draft_id)
   route_hash                  creates+persists draft        after approval
```

`plan_route_*` only computes a route; it persists nothing. Only `propose_mission_draft` creates a draft and returns the prefixed `draft_id` (`ai-draft-…`, `draft-draw-…`, `draft-fence-…`) that `export_mission` resolves via `MissionDraftService.get_draft`. Skipping `propose_mission_draft` and handing the bare `route_hash` to `export_mission` was a real planner failure mode (the export 404'd because no draft existed).

**Guardrail + auto-bridge** (`_resolve_export_draft` in `tool_registry.py`). When `export_mission` gets an id that isn't a stored draft:
- If it looks like a bare `route_hash` (12 hex, no `draft` substring), it tries to **auto-bridge** to an existing session draft by matching the hash against a draft's `route_artifacts`, and tags the result `resolved_via` / `resolved_draft_id`. It never fabricates a draft, so the ADR 0021 approval gate stays intact.
- Otherwise it returns a directed error naming `propose_mission_draft` as the next tool plus `available_drafts` (the session's real draft ids + statuses), so the planner self-corrects instead of dead-ending.

## Per-waypoint defaults

- `accept_radius_m` is set per-waypoint by the route planner as `min(road_width / 2, default_accept_radius_m)`. `None` means "use Settings default" (allowed when road width is unknown).
- `hold_s` defaults to `0.0` from Settings. Route planner does not set per-waypoint values in this slice.
- `yaw_rad` is always `None` at the route-planner layer (a navigation path has no opinion on heading). Task-layer steps (e.g., `inspect`) may override yaw. Exporter renders `None → NaN` for vehicles where that means "keep current heading" (rover, copter); profiles where yaw cannot be honored (fixed-wing) strip the value.
- Altitude `z` is always carried. Exporter rendering depends on the active profile (ground → clamp to 0, aerial → use `z` or task/profile cruise altitude).

## Mission Draft schema additions

- `step.waypoints: list[Waypoint] | None` — populated when the step is materialised by a route tool.
- `step.route_summary: RouteSummary | None` — the compact result the agent saw.
- `draft.lifecycle: Literal["draft", "approved", "exported", "uploading", "uploaded", "executing", "completed", "failed", "cancelled"]` — declared in full; reachable today: `draft / approved / exported / failed / cancelled`.
- `draft.lifecycle_history: list[{state, ts, actor}]` — append-only audit trail.
- `draft.dispatch_mode: Literal["plan_only", "plan_and_execute"]` — inferred by the agent from prompt context.
