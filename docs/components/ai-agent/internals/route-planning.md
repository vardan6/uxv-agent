# Route Planning — Internals

Implementation notes for the road-graph + route-planner-tool + QGC `.plan` exporter slice. The product target and design rationale live in [../requirements.md](../requirements.md) (§ "Route Planning and Mission Export Requirement") and [../design.md](../design.md) (§ "Route Planning, Vehicle Profiles, and Mission Export"). This file is the implementation reference and the validation checklist.

## Implementation status (2026-05-16)

Implemented and ready for manual validation:

- `VehicleProfile` presets and active ground profile
- `RoadGraphService` graph build from terrain scene roads with explicit `metadata.group`
- `plan_route_around_group` and `plan_route_between` planner tools
- planner-loop route artifact preservation in stored mission drafts
- approval-card compact route summary
- approval-time QGC `.plan` export for route-bearing drafts
- `export_mission` side-effect metadata (`writes_file`) and approved/exported draft gating
- durable planner-loop trace IDs through the shared JSONL trace store

Committed follow-up work (not optional, separated only to keep this slice shippable):

- Mission template library and manual waypoint editing
- shared `MissionMapView`
- corridor/blockage creation, viewing, editing, enabling/disabling, and deletion UI
- planned-vs-actual replay overlay
- MAVLink upload, execution, stop/abort, and mission monitoring

## Algorithm reference

### Graph build

Source: `config/terrain_scene.v1.json`. Currently 16 road segments forming an explicit network. Each road carries `centerline=[start,end]`, `geometry.width`, `metadata.drivable=true`, `metadata.route_planning_cost`, and (schema bump) `metadata.group`.

Build order:

1. **Endpoint snap.** Configurable epsilon (Settings: `road_graph_epsilon_m`, default ~0.5 m). The authored scene does not guarantee endpoint coordinates coincide exactly at junctions. Snap each endpoint to a canonical node within epsilon.
2. **T-junction / crossroad split.** For each road, find points where another road's endpoint (or another road's segment) lies within epsilon of its interior. Split the road at those points into sub-edges sharing a node. Segment-intersection pass during graph build; O(n²) over ~16 edges is trivial.
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
- Local→geo projection: flat-earth approximation off `coordinate_system.georeference.origin_lat / origin_lon`, accurate to ~10 m over the scene's ~300 m extent

Output path: `data/missions/<draft_id>.plan`. Recorded on the draft. The `.plan` file is the current hand-off boundary to the flight controller; MAVSDK `import_qgroundcontrol_mission` → `upload_mission` over UDP 14550 is the documented next slice and lives outside this PR.

**Coordinate caveat.** The current scene and its `coordinate_system.georeference` are development placeholders. When real rover hardware and real-world scene data arrive, both the map and its georeference are expected to be regenerated together. The projection code consumes the new origin without changes.

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

## Per-waypoint defaults

- `accept_radius_m` is set per-waypoint by the route planner as `min(road_width / 2, default_accept_radius_m)`. `None` means "use Settings default" (allowed when road width is unknown).
- `hold_s` defaults to `0.0` from Settings. Route planner does not set per-waypoint values in this slice.
- `yaw_rad` is always `None` at the route-planner layer (a navigation path has no opinion on heading). Task-layer steps (e.g., `inspect`) may override yaw. Exporter renders `None → NaN` for vehicles where that means "keep current heading" (rover, copter); profiles where yaw cannot be honored (fixed-wing) strip the value.
- Altitude `z` is always carried. Exporter rendering depends on the active profile (ground → clamp to 0, aerial → use `z` or task/profile cruise altitude).

## Mission Draft schema additions

- `step.waypoints: list[Waypoint] | None` — populated when the step is materialised by a route tool.
- `step.route_summary: RouteSummary | None` — the compact result the agent saw.
- `draft.lifecycle: Literal["draft", "approved", "exported", "uploading", "uploaded", "executing", "completed", "failed", "cancelled"]` — declared in full now. Reachable in this slice: `draft / approved / exported / failed / cancelled`.
- `draft.lifecycle_history: list[{state, ts, actor}]` — append-only audit trail.
- `draft.dispatch_mode: Literal["plan_only", "plan_and_execute"]` — inferred by the agent from prompt context.

## Manual validation checklist

Automated tests are intentionally deferred for this prototype phase. Validate end-to-end by running the following from a clean dev environment.

1. Start the GCS normally.
2. Open `/ai` and run `/plan drive around the second solar plantation and come back`.
3. Confirm the planning-shell stream starts with `planner_loop_enabled: true`.
4. Confirm the approval card appears and shows a Route row with waypoint count and distance.
5. Approve the draft.
6. Confirm the final assistant metadata includes `planner_agent_trace_id`.
7. Confirm the stored draft contains `route_artifacts` with waypoints and route hash.
8. Confirm `data/missions/<draft_id>.plan` exists after approval.
9. Open the `.plan` JSON and confirm QGC `Plan` shape with rover `vehicleType`, waypoint items, and trailing RTL item.
10. (Optional) Open the `.plan` in QGroundControl; waypoints render at the right location.
11. (Optional) Load into ArduRover SITL per [../../../cross-cutting/research/flight-controllers/simulation.md](../../../cross-cutting/research/flight-controllers/simulation.md) and confirm AUTO mode runs.

Expected result: route-bearing planning-shell drafts can be planned, reviewed, approved, exported to a `.plan` file, and traced without any rover command dispatch.

> **Note (post-Phase-6).** Earlier validation steps that toggled `ai_use_planner_loop` to exercise a deterministic-DAG fallback path are obsolete — that path was removed when the planner-loop became default. The planner-loop path is the only path; the toggle is gone.
