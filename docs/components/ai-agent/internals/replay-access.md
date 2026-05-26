# Replay Session Access

## Scope

This document defines how AI surfaces access replay sessions for read-only
analysis.

It covers:

- replay session selection and reference resolution
- deterministic replay analytics and metric definitions
- replay-specific tool and API surface expectations

It does not cover mission execution, write-capable tools, or generic
document/RAG retrieval.

## Core Principle

Do not make the model infer replay facts from raw timelines when backend code
can compute them deterministically.

Replay access should follow this split:

- backend services resolve target sessions and compute metrics
- AI receives compact structured results
- the model handles interpretation, explanation, and comparison

## Replay Analytics Surface

Replay analytics should be exposed as backend query primitives that can be
used by both the replay UI and AI surfaces.

Recommended responsibilities:

- list replay sessions with filters and ordering
- fetch one session summary
- compute deterministic session metrics
- fetch timeline slices and event search results
- compare multiple sessions
- provide downsampled path geometry when needed

Recommended service methods:

- `list_sessions(limit, filters)`
- `get_session_summary(session_id)`
- `get_session_metrics(session_id)`
- `get_session_path(session_id, downsample=None)`
- `get_session_event_slice(session_id, start_ts=None, end_ts=None, limit=...)`
- `search_session_events(session_id, text=None, event_type=None, limit=...)`
- `compare_sessions(session_ids, metrics=None)`

Recommended AI-facing tool surface:

- `list_replay_sessions`
- `get_replay_session_summary`
- `get_replay_session_metrics`
- `get_replay_session_path`
- `search_replay_session_events`
- `compare_replay_sessions`

## Session Reference Resolution

Session reference resolution must happen in backend code before model
reasoning.

The model should not be the source of truth for:

- what `last` means
- what `yesterday` means
- which timezone defines a calendar day
- whether sorting uses `started_at` or `ended_at`

Selection priority:

1. explicit session ID in the user request
2. replay sessions explicitly attached or selected by the UI
3. the active replay session for live-context questions
4. clarification when multiple sessions are plausible

### Ordering Semantics

Canonical ordinal rule:

- default sort: `started_at DESC`

Examples:

- `last session` means the most recently started session
- `the one before last` means the second item in `started_at DESC`
- `third from last` means the third item in `started_at DESC`
- `first session` means the oldest item in `started_at ASC`

If product language later needs a different meaning, use explicit phrasing such
as `last completed session` rather than changing the default ordinal rule.

### Date Semantics

Date selectors must resolve against an explicit timezone and compare against
`started_at`.

Examples:

- `today's sessions` means sessions whose `started_at` falls inside the current
  local calendar day
- `yesterday's sessions` means sessions whose `started_at` falls inside the
  previous local calendar day

## Session Metrics Contract

The first replay analytics set should remain deterministic and cheap.

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

Definitions must be explicit and stable.

### Duration

Preferred definition:

- `max(valid observed timestamp) - min(valid observed timestamp)` across replay
  data for the session

Fallback order:

- telemetry timestamps
- control timestamps
- runtime event timestamps
- `ended_at - started_at`

The response should include the method used.

### Path Length

Preferred definition:

- sum of Euclidean distances between consecutive valid position samples in
  local coordinates

Requirements:

- ignore samples without valid position
- ignore non-finite values
- optionally ignore obvious duplicates or zero-delta spam

### Maximum Distance From Start

Preferred definition:

- greatest Euclidean distance from the first valid position sample used as the
  session origin

Return:

- `origin_sample_ts`
- `origin_source`
- `max_distance_from_start_m`
- optionally the timestamp of the max-distance point

### Net Displacement

Definition:

- Euclidean distance from the first valid position sample to the last valid
  position sample used in metric computation

## Replay Telemetry Storage Invariants

Replay analytics must preserve the difference between zero and missing data.

Do not collapse absent numeric values to `0.0` in analytics storage, because
that merges:

- real zero
- missing value
- malformed value
- unavailable position source

Recommended extracted telemetry semantics:

- preserve nullability for position, GPS, heading, and speed fields
- track `has_position`
- track `has_gps`
- track `position_frame`

`position_frame` values should distinguish at least:

- `local_xy`
- `gps_wgs84`
- `unknown`

## Caching Strategy

Replay metrics should be computed on demand, then cached when the session is
large or queried repeatedly.

Recommended cache behavior:

- compute metrics on first request
- store common metric results in a dedicated cache table
- invalidate or recompute while the session is still active and new telemetry
  arrives

Keep the canonical formulas in code, not in SQL-only logic.

## Integration Direction

The replay UI and AI should share the same backend analytics endpoints or
service methods.

Recommended additions:

- `GET /api/replay/sessions/{session_id}/summary`
- `GET /api/replay/sessions/{session_id}/metrics`
- `GET /api/replay/sessions/{session_id}/path`
- `GET /api/replay/sessions/{session_id}/events/search`
- `POST /api/replay/sessions/compare`

AI integration should reuse the same replay analytics surface whether the
calling path is:

- server-side request planning before a model call
- provider tool calling
- a later workflow-orchestration layer
