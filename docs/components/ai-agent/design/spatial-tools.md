# AI Spatial Tools

## Purpose

This document defines the spatial-tool architecture for terrain/object
reasoning and future agent workflows.

The decision is:
- keep the always-injected AI context compact
- move larger map, object, replay, and perception detail behind on-demand tools
- implement deterministic spatial query services before full mission execution
- make those query services agent-tool-ready from the beginning
- use RAG for semantic knowledge, documents, definitions, reports, and memory, not exact geometry

This is the bridge between compact always-on AI context and later mission agents.

## Core Architecture

The AI system should use three separate knowledge layers:

```text
Current state layer
  -> latest vehicle pose, heading, speed, freshness, controller, active mission
  -> exact structured data from GCS runtime and telemetry

Spatial world model
  -> static terrain/map objects and later dynamic detected objects
  -> exact geometric queries from a structured map/perception store

RAG knowledge layer
  -> project docs, manuals, definitions, mission history, reports, operator notes
  -> semantic retrieval with citations
```

The LLM or agent should interpret the operator request and choose tools. The backend should calculate distances, bearings, sectors, route intersections, and object candidates.

## Always-On Context Versus On-Demand Tools

Always-on AI context should stay small and high-signal:
- vehicle telemetry freshness
- current vehicle pose and heading
- runtime/broker summary
- active controller summary
- active mission summary or no-active-mission state
- scene summary: bounds, object counts, object kinds, source path
- safe LLM/provider/routing summary

On-demand tools should provide larger detail:
- objects in front of the vehicle
- objects to the left or right
- nearest objects by kind
- objects within radius
- objects inside a sector
- objects along a proposed route
- terrain/road/pad details
- recent telemetry/control/runtime events
- replay summaries
- mission drafts and validation results

## Spatial Query Service

Spatial query behavior should live in a dedicated deterministic service with
these responsibilities:
- load object geometry from `scene_map.py`
- read vehicle pose from the current vehicle state passed by the caller
- calculate distance, bearing, and relative bearing
- filter objects by distance, field of view, side, kind, and sector
- return compact structured hits suitable for LLM/tool output

Representative methods:

```text
get_scene_summary()
find_objects_in_front(max_distance_m, fov_deg, kinds=None)
find_objects_near(radius_m, kinds=None)
find_objects_by_kind(kind)
find_objects_to_left(max_distance_m, angle_width_deg, kinds=None)
find_objects_to_right(max_distance_m, angle_width_deg, kinds=None)
find_nearest_objects(limit, max_distance_m=None, kinds=None)
find_objects_in_sector(center_bearing_deg, fov_deg, max_distance_m, kinds=None)
resolve_target_description(scene, vehicle_state, target)
```

The `target` argument is the structured target dict produced by the intent
parser. It should combine structured intent fields with deterministic
candidate filtering. For example:

```text
"tree on the right around 20-30 meters"
  -> target.kind = tree
  -> target.side = right
  -> target.min_distance_m = 20
  -> target.max_distance_m = 30
  -> rank candidates by distance and relative bearing
```

## Agent Tool Registry

The same registry serves:
- Agent mode (Chat page)
- shared vehicle-intent parsing
- shared mission-authoring workflows
- future MCP server adapters

Initial read-only tools:

```text
get_current_vehicle_state()
get_scene_summary()
query_map_objects(mode, kinds=None, kind=None, position=None, heading_deg=None,
                  max_distance_m=None, fov_deg=20, angle_width_deg=90, radius_m=50, limit=5)
  # mode: front | near | by_kind | left | right | nearest
  # replaces query_objects_in_front, query_objects_near, query_objects_by_kind,
  #           query_objects_to_left, query_objects_to_right, query_nearest_objects
resolve_spatial_target(target)
get_recent_telemetry(seconds, limit)
get_replay_summary(session_id=None)
```

Planning-only tools:

```text
parse_vehicle_intent(prompt)
resolve_spatial_target(intent)
draft_mission(goal, target_candidates, constraints)
validate_mission_draft(plan)
```

Do not add execution tools in the first pass.

## Tool Permission Classes

Every tool should declare a permission class:

```text
read_only
analysis
planning
command_staging
execution
```

Rules:
- `read_only` tools can run automatically and should be logged.
- `analysis` tools can run automatically but may be more expensive or verbose.
- `planning` tools can create drafts only.
- `command_staging` tools require explicit operator approval before anything is staged.
- `execution` tools require explicit approval plus controller and safety checks.

The initial safe surface includes only `read_only`, `analysis`, and `planning`.

### Async/Sync Boundary For Spatial Tools

`SpatialQueryService` should stay synchronous and deterministic. It should accept already-resolved inputs such as vehicle pose, heading, scene payload, and query parameters, then return geometry results without touching async runtime state.

Callers are responsible for resolving async state before invoking spatial tools:
- API/context callers should `await get_current_vehicle_state()` or use an already-built context snapshot.
- LangChain tools must remain synchronous. They should close over the request's preloaded vehicle/context snapshot rather than calling `asyncio.run()` inside the tool loop.

This keeps spatial queries testable without an event loop and avoids nested-event-loop failures inside FastAPI/uvicorn.

## Future Perception Data Model

When lidar/camera/object detection is added, do not feed raw point clouds or long frame descriptions directly into normal chat context.

The perception subsystem should produce structured detected objects or tracks:

```json
{
  "track_id": "dyn_0012",
  "class_label": "rock",
  "confidence": 0.87,
  "pose": {
    "frame_id": "map",
    "x": 18.2,
    "y": -4.5,
    "z": 0.3
  },
  "relative_to_vehicle": {
    "distance_m": 14.8,
    "bearing_deg": 12.5,
    "zone": "front"
  },
  "geometry": {
    "type": "bbox_3d",
    "size_m": [1.2, 0.8, 0.6]
  },
  "source": {
    "sensors": ["lidar", "camera"],
    "timestamp": 1778270000.0
  },
  "status": "active"
}
```

Later storage can split the world model into:

```text
static_map_objects
dynamic_object_tracks
sensor_observations
missions
mission_events
```

For current simulator scale, JSON plus SQLite metadata is enough. For larger
real sites, use a spatial database such as PostGIS or SpatiaLite.

## MCP Direction

MCP should be treated as an adapter layer, not the first internal implementation.

First build normal Python services and a tool registry. Later, expose stable read-only and planning tools through MCP for external agents:

```text
query_map_objects
resolve_spatial_target
get_current_vehicle_state
get_scene_summary
get_recent_telemetry
retrieve_project_docs
draft_mission
validate_mission_draft
```

This avoids coupling the core GCS logic to one agent transport while still keeping the project MCP-ready.
