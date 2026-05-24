# AI Spatial Tools And Agent Plan

Status date: 2026-05-09.

## Purpose

This document defines the next AI implementation slice for terrain/object reasoning and future agent workflows.

The decision is:
- keep the always-injected AI context compact
- move larger map, object, replay, and perception detail behind on-demand tools
- implement deterministic spatial query services before full mission execution
- make those query services agent-tool-ready from the beginning
- use RAG for semantic knowledge, documents, definitions, reports, and memory, not exact geometry

This is the bridge between the implemented AI current-context layer and later LangGraph mission agents.

## Core Architecture

The AI system should use three separate knowledge layers:

```text
Current state layer
  -> latest rover pose, heading, speed, freshness, controller, active mission
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
- rover telemetry freshness
- current rover pose and heading
- runtime/broker summary
- active controller summary
- active mission summary or no-active-mission state
- scene summary: bounds, object counts, object kinds, source path
- safe LLM/provider/routing summary

On-demand tools should provide larger detail:
- objects in front of the rover
- objects to the left or right
- nearest objects by kind
- objects within radius
- objects inside a sector
- objects along a proposed route
- terrain/road/pad details
- recent telemetry/control/runtime events
- replay summaries
- mission drafts and validation results

The `AIContextService` proves the pattern with query-triggered object details. Spatial query logic has been extracted into `SpatialQueryService` and agent tools are now exposed through `ToolRegistry`, which serves Agent mode, Rover Intent Test, and the LangGraph planning shell via the same definitions.

## Spatial Query Service

Add a dedicated backend service:

```text
gcs_server/ai/spatial_query_service.py
```

Initial responsibilities:
- load object geometry from `scene_map.py`
- read rover pose from the current rover state passed by the caller
- calculate distance, bearing, and relative bearing
- filter objects by distance, field of view, side, kind, and sector
- return compact structured hits suitable for LLM/tool output

Initial methods:

```text
get_scene_summary()
find_objects_in_front(max_distance_m, fov_deg, kinds=None)
find_objects_near(radius_m, kinds=None)
find_objects_by_kind(kind)
find_objects_to_left(max_distance_m, angle_width_deg, kinds=None)
find_objects_to_right(max_distance_m, angle_width_deg, kinds=None)
find_nearest_objects(limit, max_distance_m=None, kinds=None)
find_objects_in_sector(center_bearing_deg, fov_deg, max_distance_m, kinds=None)
resolve_target_description(scene, rover_state, target)
```

Authoritative signature — implemented in `gcs_server/ai/spatial_query_service.py`. The `target` argument is the structured target dict produced by the intent parser. It should combine structured intent fields with deterministic candidate filtering. For example:

```text
"tree on the right around 20-30 meters"
  -> target.kind = tree
  -> target.side = right
  -> target.min_distance_m = 20
  -> target.max_distance_m = 30
  -> rank candidates by distance and relative bearing
```

## Agent Tool Registry

Implemented:
- `gcs_server/ai/tool_registry.py` defines `ToolRegistry` with `ToolDefinition`/`ToolInvocationContext`.
- Permission classes: `read_only`, `analysis`, `planning`; `command_staging`/`execution` explicitly rejected.
- `build_langchain_tools(runtime, context_snapshot, timezone_name, permissions)` is called per-request.
- Tools close over the request's prebuilt context snapshot for async runtime facts, keeping LangChain tool invocation synchronous.
- Agent mode skips keyword-triggered spatial prompt enrichment and asks the model to call these tools instead.
- Runtime streaming emits `agent_tool_start` and `agent_tool_result` progress events before the final agent answer.
- Agent mode in `chat_service.py` was rewired through `ToolRegistry`; `ReadOnlyAgentToolset` removed from `agent_tools.py`.

The same registry serves:
- Agent mode (Chat page)
- Rover Intent Test
- LangGraph planning-shell workflows
- future MCP server adapters

Initial read-only tools:

```text
get_current_rover_state()
get_scene_summary()
query_objects_in_front(max_distance_m, fov_deg, kinds=None)
query_objects_near(radius_m, kinds=None)
query_objects_by_kind(kind)
query_objects_to_left(max_distance_m, angle_width_deg, kinds=None)
query_objects_to_right(max_distance_m, angle_width_deg, kinds=None)
get_recent_telemetry(seconds, limit)
get_replay_summary(session_id=None)
```

Implemented in `ToolRegistry` (via `SpatialQueryService`):
- `get_current_rover_state()`
- `get_scene_summary()`
- `query_objects_in_front(max_distance_m, fov_deg, kinds=None)`
- `query_objects_near(radius_m, kinds=None)`
- `query_objects_by_kind(kind)`
- `get_current_mission_state()`
- replay summary, recent telemetry, replay session resolution, metrics, paths, events, comparison, and aggregation

Planning-only tools:

```text
parse_rover_intent(prompt)
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

The next implementation should only include `read_only`, `analysis`, and `planning`.

## Agent Implementation Timing

It is reasonable to start agent implementation now if "agent" means:
- structured tool definitions
- tool invocation logging
- Rover Intent Test mode
- mission draft generation
- explicit approval state

It is too early to start autonomous rover execution.

Completed sequence (Milestones A–F + LangGraph Phases 1–3):

1. ✅ Extracted spatial query logic from `AIContextService` into `SpatialQueryService`.
2. ✅ Added tests for front/near/kind/left/right/sector queries, including heading wraparound.
3. ✅ Replaced the direct toolset with a `ToolRegistry` with explicit permission classes.
4. ✅ `AIContextService` uses the registry/service for on-demand details.
5. ✅ Rover Intent Test mode with structured output.
6. ✅ Session mode → provider-routing purpose mapping.
7. ✅ Target resolution using spatial tools.
8. ✅ Mission draft storage, approval, and reject status.
9. ✅ LangGraph planning shell: planner-loop tool selection → deterministic validation → approval or clarification interrupt.
10. Bounded non-RAG source controls are implemented; later milestone is true RAG/document/web retrieval.

### Async/Sync Boundary For Spatial Tools

`SpatialQueryService` should stay synchronous and deterministic. It should accept already-resolved inputs such as rover pose, heading, scene payload, and query parameters, then return geometry results without touching async runtime state.

Callers are responsible for resolving async state before invoking spatial tools:
- API/context callers should `await get_current_rover_state()` or use an already-built context snapshot.
- LangChain tools must remain synchronous. They should close over the request's preloaded rover/context snapshot rather than calling `asyncio.run()` inside the tool loop.

This keeps spatial queries testable without an event loop and avoids nested-event-loop failures inside FastAPI/uvicorn.

### Agent Progress Streaming

The current chat streaming transport is newline-delimited JSON (`application/x-ndjson`). Agent mode uses the same transport unless the API is intentionally changed to SSE.

Recommended event protocol:
- `{"type":"agent_tool_start","tool_call":{"id":"...","name":"...","args":{},"iteration":1}}`
- `{"type":"agent_tool_result","tool_call":{"id":"...","name":"...","args":{},"result":{},"iteration":1,"latency_ms":12}}`
- `{"type":"assistant_delta","delta":"..."}` for final answer text
- `{"type":"assistant_message","message":{...}}` after the assistant message is stored

The UI should render tool-call progress above or near the final answer so operators can see what the agent inspected while waiting.

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
  "relative_to_rover": {
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

For the current simulator scale, JSON plus SQLite metadata is enough. For large real sites, use a spatial database such as PostGIS or SpatiaLite.

## MCP Direction

MCP should be treated as an adapter layer, not the first internal implementation.

First build normal Python services and a tool registry. Later, expose stable read-only and planning tools through MCP for external agents:

```text
query_objects_in_front
query_objects_near
get_current_rover_state
get_scene_summary
get_recent_telemetry
retrieve_project_docs
draft_mission
validate_mission_draft
```

This avoids coupling the core GCS logic to one agent transport while still keeping the project MCP-ready.
