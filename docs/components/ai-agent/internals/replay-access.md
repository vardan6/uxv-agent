# AI Replay Session Access Plan

## Scope

This document covers how Remote Rover GCS should expose replay sessions to AI Chat and the read-only AI Agent.

This plan is intentionally limited to replay sessions.

Deferred for later:
- AI session to replay session attachment UX and persistence
- multi-source RAG/document retrieval
- command-capable agent workflows
- LangGraph orchestration or multi-step tool execution loops

## Problem Statement

The system already stores replay sessions with structured telemetry, control frames, runtime events, and media timing metadata. The replay page can load and inspect a session, but AI Chat and the current read-only agent do not have a robust way to query arbitrary replay sessions or compute analytics across them.

The current AI context path only exposes:
- live rover/runtime/settings context
- scene-map summaries and a few scene queries
- active replay summary
- recent telemetry from the active replay session

That is sufficient for live conversational context but not for questions such as:
- Which replay session was longest?
- What was the total path length of session X?
- What was the maximum distance from the starting point?
- Compare session A and session B.
- Show the runtime events near the end of a session.

## Current System Behavior

### Replay Storage

Replay data is stored in SQLite and already has a good core structure:
- `replay_sessions`
- `replay_telemetry`
- `replay_controls`
- `replay_runtime_events`
- `replay_media_refs`

This is the correct source of truth for AI access.

### Current AI Agent Behavior

The current "agent" is not a real iterative tool-calling agent yet.

What it does today:
1. Build one compact context snapshot before the LLM call.
2. Optionally include a few precomputed read-only facts based on the user message.
3. Serialize those facts into the prompt as `tool_calls`.
4. Send a single LLM request.
5. Store the response.

What it does not do today:
- no tool selection after the first model response
- no second LLM call after retrieving data
- no autonomous loop of think -> call tool -> think again
- no LangGraph orchestration
- no real structured tool invocation contract with the provider

So the current implementation is best described as:
- single-request prompt assembly
- with pre-LLM context injection
- and prompt-level pseudo-tools

That is useful as a bootstrap layer but it is not sufficient for scalable replay-session analytics.

## Design Goals

The replay-session AI access design should satisfy these requirements:
- AI can reference any replay session, not only the active one.
- AI can answer quantitative questions reliably.
- replay data is not dumped wholesale into every prompt.
- expensive computations are performed in backend code, not inferred by the LLM.
- the same backend analytics surface can serve both the replay UI and AI.
- the design can evolve from current pre-context injection into true tool-calling later.

## Recommended Architecture

Use a dedicated backend replay analytics layer and expose it as read-only query primitives.

### Core Principle

Do not make the LLM reason over raw full session timelines whenever a deterministic backend calculation is possible.

Instead:
- backend services fetch and compute replay facts
- AI receives compact summaries or tool results
- the LLM focuses on interpretation, explanation, and comparison

## Proposed Components

### 1. Replay Analytics Service

Introduce a service such as `ReplayAnalyticsService` responsible for replay-session retrieval and deterministic metrics.

Recommended responsibilities:
- fetch session summaries
- fetch timeline slices
- compute session metrics
- compare sessions
- search runtime events and controls
- provide downsampled path geometry for UI or AI summaries

Recommended methods:
- `list_sessions(limit, filters)`
- `get_session_summary(session_id)`
- `get_session_metrics(session_id)`
- `get_session_path(session_id, downsample=None)`
- `get_session_event_slice(session_id, start_ts=None, end_ts=None, limit=...)`
- `search_session_events(session_id, text=None, event_type=None, limit=...)`
- `compare_sessions(session_ids, metrics=None)`

### 2. Replay Session Tool Registry

Add a read-only replay-session tool surface for agent mode.

Candidate tools:
- `list_replay_sessions`
- `get_replay_session_summary`
- `get_replay_session_metrics`
- `get_replay_session_path`
- `search_replay_session_events`
- `compare_replay_sessions`

These tools should initially be backend-callable primitives even if the provider-facing agent loop is still a single-request bootstrap.

That preserves forward compatibility:
- phase 1: tools can be invoked by server-side request planning before the LLM call
- phase 2: the same tools can be surfaced to true model tool-calling

### 3. Replay Context Selection Layer

The AI system needs a deterministic way to decide which replay sessions are in scope for a given request.

Recommended selection policy:
- explicit session ID in the user prompt wins
- else use replay sessions currently selected/attached from the replay UI if available
- else use current active replay session for live-context questions
- else ask for clarification when multiple sessions are plausible

This selection layer should be implemented in backend code, not left to model guessing.

## Session Metrics

The first analytics set should be deterministic and cheap.

Recommended baseline metrics:
- `duration_s`
- `telemetry_sample_count`
- `control_count`
- `runtime_event_count`
- `path_length_m`
- `net_displacement_m`
- `max_distance_from_start_m`
- `max_speed_m_s`
- `max_speed_km_h`
- `position_frame`
- `position_coverage_ratio`

Definitions must be explicit.

### Duration

Preferred definition:
- `max(valid observed timestamp) - min(valid observed timestamp)` across replay data for the session

Fallback order:
- telemetry timestamps
- control timestamps
- runtime event timestamps
- `ended_at - started_at`

Return the method used.

### Path Length

Preferred definition:
- sum of Euclidean distances between consecutive valid position samples in local coordinates

Requirements:
- ignore samples without valid position
- ignore non-finite values
- optionally ignore obvious duplicates or zero-delta spam
- later, add outlier rejection thresholds if needed

### Maximum Distance From Start

Preferred definition:
- compute the greatest Euclidean distance from the first valid position sample used as session origin

Return:
- `origin_sample_ts`
- `origin_source`
- `max_distance_from_start_m`
- optionally the timestamp of the max distance point

### Net Displacement

Definition:
- Euclidean distance from first valid position sample to last valid position sample used in metric computation

## Data Model Review

The current replay schema is mostly sound, but there is an important correctness issue.

### Problem: Missing Numeric Values Are Collapsed To `0.0`

Today extracted telemetry columns are written with `0.0` fallbacks when values are absent.

That is dangerous for analytics because it merges these distinct cases:
- real zero
- missing value
- malformed value
- unavailable position source

For replay analytics this should be corrected.

### Recommended Telemetry Storage Adjustment

Preserve nullability in extracted columns:
- `position_x`, `position_y`, `position_z`
- `gps_lat`, `gps_lon`, `gps_alt`
- `heading_deg`
- `speed_m_s`, `speed_km_h`

Add or derive validity semantics:
- `has_position`
- `has_gps`
- `position_frame`

Possible values for `position_frame`:
- `local_xy`
- `gps_wgs84`
- `unknown`

This allows deterministic analytics and avoids fabricating coordinates.

## Caching Strategy

Do not compute all metrics on every chat request if the session is large.

Recommended approach:
- compute on demand at first request
- cache common metrics in a dedicated table
- invalidate or recompute when the session is still active and new telemetry arrives

Suggested cache table:
- `replay_session_metrics`

Suggested columns:
- `session_id`
- `computed_at`
- `telemetry_sample_count`
- `position_sample_count`
- `duration_s`
- `path_length_m`
- `net_displacement_m`
- `max_distance_from_start_m`
- `max_speed_m_s`
- `metrics_json`

Keep the canonical formulas in code, not SQL-only logic.

## AI Integration Phases

### Phase 1: Better Single-Request Agent Bootstrap

Since the current agent path is a single LLM request, improve it by adding backend request planning before the prompt is assembled.

Flow:
1. Parse user intent for replay-session questions.
2. Resolve target replay session(s).
3. Execute the necessary replay analytics functions server-side.
4. Inject only the relevant structured results into the prompt.
5. Make one LLM request.

This keeps the current architecture intact while making replay answers much better.

### Phase 2: Real Read-Only Tool Calling

Upgrade agent mode to true tool calling.

Target flow:
1. send conversation + tool schema to model
2. model requests replay tool(s)
3. backend executes tools
4. backend sends tool results back to model
5. model produces final answer

This can be one or more tool rounds, but the tools introduced in phase 1 should be reused directly.

### Phase 3: Workflow Orchestration

If needed later, wrap the tool-calling path in LangGraph or an equivalent orchestration layer for:
- replay investigation workflows
- summarization over multiple sessions
- planning or operator-assist flows

This is not required to make replay-session Q&A work well.

## API Surface Recommendation

The replay UI and AI should share the same backend analytics endpoints or service methods.

Recommended additions:
- `GET /api/replay/sessions/{session_id}/summary`
- `GET /api/replay/sessions/{session_id}/metrics`
- `GET /api/replay/sessions/{session_id}/path`
- `GET /api/replay/sessions/{session_id}/events/search`
- `POST /api/replay/sessions/compare`

These may be exposed as HTTP endpoints, internal services, or both.

## Why This Is The Right Direction

This design is preferable because it:
- keeps replay SQLite as the source of truth
- avoids prompt bloat
- makes metric answers deterministic
- supports UI reuse and AI reuse with the same logic
- works immediately with the current single-request agent path
- does not block later migration to true tool-calling

## Recommended Immediate Next Steps

1. Introduce `ReplayAnalyticsService` over the existing replay store.
2. Fix telemetry extracted-column semantics so missing values stay nullable.
3. Implement baseline metrics: duration, path length, net displacement, max distance from start.
4. Add replay analytics endpoints.
5. Extend AI agent request planning so replay-session questions trigger backend analytics before the single LLM call.
6. Later, upgrade agent mode from precomputed pseudo-tools to true provider tool-calling.

## Non-Goals For This Phase

Not part of this replay-session phase:
- mission execution
- write-capable tools
- autonomous rover control
- document upload or general RAG
- recorded video playback analytics
- AI-session linkage persistence beyond what is needed for future planning

## Implemented In This Session

The following pieces are now implemented in the codebase.

### Replay Analytics Service

A shared backend service now exists:
- `gcs_server/replay_analytics.py`
- `gcs_server/replay_session_resolver.py`

Implemented methods:
- `list_sessions`
- `get_session_summary`
- `get_session_metrics`
- `get_session_path`
- `search_session_events`
- `compare_sessions`
- `resolve_sessions`
- `aggregate_sessions`
- `build_ai_replay_context`

### Replay Metrics

Implemented deterministic metrics:
- `duration_s`
- `duration_source`
- `telemetry_sample_count`
- `position_sample_count`
- `path_length_m`
- `net_displacement_m`
- `max_distance_from_start_m`
- `max_distance_sample_ts`
- `max_speed_m_s`
- `max_speed_km_h`
- `position_frame`
- `origin_source`
- `origin_sample_ts`
- `coverage.position_coverage_ratio`

Current definitions:
- duration uses telemetry timestamp bounds when telemetry exists
- path length uses consecutive valid local position samples
- max distance from start uses the first valid local position sample as origin
- sessions without telemetry fall back to session start/end timestamps

### Replay Storage Changes

Replay telemetry storage was extended to support analytics safely.

Added extracted replay telemetry columns:
- `has_position`
- `has_gps`
- `position_frame`

Added metrics cache table:
- `replay_session_metrics`

Behavioral change:
- new telemetry rows preserve extracted nullability in replay storage instead of forcing all missing values to `0.0`
- live normalized telemetry payloads still keep numeric fields for dashboard/replay UI compatibility

Backfill behavior:
- replay DB initialization now backfills `has_position`, `has_gps`, and `position_frame` for existing replay telemetry rows where possible by inspecting stored `payload_json`

### Replay HTTP Endpoints

The following endpoints are implemented:
- `GET /api/replay/sessions/{session_id}/summary`
- `GET /api/replay/sessions/{session_id}/metrics`
- `GET /api/replay/sessions/{session_id}/path`
- `GET /api/replay/sessions/{session_id}/events/search`
- `POST /api/replay/sessions/compare`
- `POST /api/replay/sessions/resolve`
- `POST /api/replay/sessions/aggregate`

`GET /api/replay/sessions` was also extended with:
- `started_at_from`
- `started_at_to`
- `order`

These are intended to be shared by replay UI and AI.

### AI Integration Implemented Now

The current AI path now has replay-aware request planning before the single LLM call.

Implemented behavior:
- if the user message looks like a replay-session question, backend replay analytics are executed before the LLM call
- results are injected into AI context as structured replay-session context
- agent mode exposes that replay context inside the existing prompt-level pseudo-tool mechanism

This means replay analytics are available now to the current single-request AI flow without waiting for true provider tool-calling.

### Verification Performed

Completed during implementation:
- Python compile check for changed backend files
- temporary SQLite replay smoke test

Smoke test verified:
- duration metric
- path length metric
- replay AI context generation for an explicit session-id question

## Current Limitations After This Session

The implementation is useful but not yet complete for natural operator-style session references.

### What Works Now

- explicit replay session id references such as `session-abc123...`
- active-session replay questions
- ordinal selectors:
  - `last session`
  - `the one before last`
  - `previous session`
  - `third from last`
  - `first session`
  - `second session`
- slice selectors:
  - `last 5 sessions`
  - `all sessions`
- date selectors:
  - `today's sessions`
  - `yesterday's sessions`
  - `sessions on 2026-05-09`
  - `sessions from May 8`
  - `sessions between May 8 and May 9`
- deterministic path/duration/distance/event calculations
- deterministic multi-session aggregation over resolved session sets

### What Does Not Work Yet

Not implemented yet:
- clarification flow when a natural-language selector maps ambiguously to more than one intended interpretation
- browser/operator timezone propagation into AI requests; current default is backend local timezone unless a timezone is passed explicitly
- metric-ranked selectors such as `longest session` or `furthest session`
- arbitrary natural-language duration filters such as `sessions longer than 10 minutes`
- full provider tool-calling agent integration

The current replay question detector still gates whether replay context is prepared for AI, but session resolution itself is now a dedicated backend component.

## Implemented Resolver Shape

The replay session selector/parser now exists as a dedicated backend component.

Current supported selectors:
- explicit id: `session-...`
- relative order:
  - `last session`
  - `previous session`
  - `second session`
  - `third from last`
- relative slices:
  - `last N sessions`
  - `all sessions`
- date-based:
  - `today's sessions`
  - `yesterday's sessions`
  - `sessions from May 8`
  - `sessions between May 8 and May 9`

Current output shape:

```json
{
  "selector_type": "relative_order|date_range|explicit_id|metric_rank",
  "resolved_session_ids": ["session-..."],
  "resolution_basis": {
    "timezone": "operator-local-or-configured",
    "sort_order": "started_at_desc"
  },
  "ambiguous": false,
  "needs_clarification": false
}
```

### Important Design Rule

Session reference resolution should happen in backend code before LLM reasoning.

Do not rely on the model alone to infer:
- what `last` means
- what `yesterday` means
- which timezone defines a calendar day
- whether sorting should use `started_at` or `ended_at`

These need explicit deterministic rules.

### Implemented Ordering Semantics

The resolver currently uses one canonical ordering rule for ordinal references:
- default sort: `started_at DESC`

Examples:
- `last session` -> most recently started session
- `the one before last` -> second item in `started_at DESC`
- `third from last` -> third item in `started_at DESC`
- `first session` -> oldest item in `started_at ASC`

If a different meaning is desired later, add explicit wording such as:
- `last completed session`
- `last ended session`

### Implemented Date Semantics

For date selectors:
- resolve using a defined timezone
- current implementation defaults to backend local timezone unless a timezone is passed explicitly
- store and compare against `started_at`

Examples:
- `yesterday's sessions` -> sessions with `started_at` inside the previous local calendar day
- `today's sessions` -> sessions with `started_at` inside the current local calendar day

## Handoff Summary

If work continues in a later session, the next logical implementation slice is:

1. propagate browser/operator timezone into replay AI requests and replay query APIs
2. add metric-ranked and filtered selectors such as `longest session` and `sessions longer than 10 minutes`
3. upgrade the current pseudo-tool AI flow to true provider tool-calling using the same resolver and analytics methods
4. optionally expose replay session candidate lists to the UI for explicit operator confirmation

The main missing piece for full agentic usage is no longer session resolution itself. It is true tool-calling integration plus stronger selector coverage and clarification behavior.
