# ADR 0032 — Per-Map Replay State and Active-Target Transport

**Status:** Accepted
**Date:** 2026-06-22
**Related:** [ADR 0026](./0026-replay-session-logging-ships-scrubbing-replay-deferred.md)
(replay logging shipped; UI scrubbing was deferred — this un-defers the operator
UI), [ADR 0031](./0031-headless-full-architecture-and-frontend-data-layer.md)
(two-tier state, single data layer), [ADR 0030](./0030-greenfield-operator-console-frontend.md)
(widget shell), [ADR 0022](./0022-gps-master-coordinate-frame.md) (dual scene/WGS84
coordinates).

## Context

The replay backend is complete (`routers/replay.py`, `replay_analytics.py`,
`replay_store.py`) but no widget in the greenfield console (`frontend/`) consumes
it. We are building that UI: the legacy `MapWidget` renders the recorded track,
driven by new React widgets (`ReplaySessionsWidget`, `ReplayControlsWidget`, a
replay-bound `TelemetryWidget`, and later `ReplayRecordsWidget`).

Two requirements forced an architectural decision rather than a UI detail:

1. **The operator runs many maps at once, each showing its own thing.** Per-tab
   workspaces (separate dockview layouts per browser tab) plus multi-instance Map
   widgets mean two maps can coexist in one tab. The operator has stated they will
   need each map to render a *different* replay session, and later to render
   *multiple* replay sessions on a *single* map with per-session visibility and
   selection — mirroring the existing mission visibility/selection model.

2. **`operator-console.md` lists Replay Playback Controls as a singleton.** A single
   transport widget must therefore drive whichever map the operator is working in,
   without a transport-per-map proliferation.

A naïve single tab-global replay cursor (one loaded session, one frame index for
the whole tab) is simpler but cannot express "map A shows session X, map B shows
session Y," and has no growth path to multiple sessions per map. The cost of
discovering this later is a store reshape plus rewiring every replay widget.

## Decision

Replay state is split into three tiers, and per-view attributes are keyed by map.

- **Tier 1 — Session domain data is shared and single.** The session list and each
  session's intrinsic data (path geometry, timeline, counts) come from the backend
  via TanStack Query (ADR 0031 Domain Stores), cached by session id. There is one
  list; refresh / rollover / delete act on it globally.

- **Tier 2 — Rendering and functional attributes are per map.** A `replayStore`
  (Zustand) holds state keyed by **dockview panel id** (`props.api.id`):

  ```
  replayStore = {
    activeMapId,
    maps: {
      [mapId]: {
        sessions: { [sessionId]: { visible, color, selected, ... } },
        activeSessionId,
        cursor: { frameIndex, isPlaying, speed }
      }
    }
  }
  ```

  Per-map state **never copies session data** — it only carries attributes that
  reference sessions by id. `visible`, `selected`, `active`, and `color` are per
  map; future attributes are added here additively, never to the shared Tier-1
  object. This is deliberately the same shape as the mission visibility/selection
  model. The first implementation slice uses a single `sessions` entry per map;
  multiple visible sessions per map is then additive (more entries), not a reshape.

- **Tier 3 — The playback cursor is per map** and applies to that map's
  `activeSessionId`. Visible-but-not-active sessions render as static full tracks;
  the active session gets the moving marker.

- **The singleton transport targets the active map.** `ReplayControlsWidget` is the
  sole writer of `cursor` and acts on `replayStore.maps[activeMapId]`. `activeMapId`
  is set by dockview active-group change and by the sidebar loading a session into
  the active map (the active-target pattern anticipated in `operator-console.md`).
  Tracking the active map is new shell infrastructure in `Workspace.tsx`; replay is
  its first consumer. In compact layout (narrow viewports, no dockview focus
  concept — a scrollable card stack instead of dockable panes), `activeMapId` is
  set by `useCompactActiveMap`'s `IntersectionObserver` instead: whichever map
  card is most visible in the scrolled viewport wins (FE5, 2026-08-22).

- **The cursor stays off the React render hot path.** `MapWidgetPanel` subscribes to
  its own `replayStore` slice and pushes paths/frames into the legacy `MapWidget`
  via imperative methods (`loadReplayPath`/`setReplayFrame`/`clearReplay`), per the
  ADR 0030 Leaflet-imperative rule. `replayStore` is a sibling of `runtimeStore`,
  which stays WS-only (ADR 0031).

- **Per-tab isolation is free.** A module-level Zustand store is per JS context, so
  separate browser tabs get independent replay state automatically. Same-tab
  multi-map and multi-session are what this keyed model exists to serve.

- **Coordinate frame: scene-metres primary, GPS fallback.** Each path point carries
  `position` (scene metres) and/or `gps`. Rendering normalizes every point into the
  map's active CRS so a mixed-frame session is one continuous track: in scene view,
  prefer `position`, else convert `gps → scene` via the session georeference origin
  (ADR 0022); in basemap view, the mirror. A session with only GPS and no origin
  falls back to basemap rendering or an explicit empty state.

- **Live vs replay marker is a per-map toggle.** Each map's layer rail gains
  `Replay track` and `Live rover` toggles. `Live rover` auto-sets off when a replay
  is active on that map (avoiding a confusing double rover) but is operator
  overridable.

## Consequences

- One new piece of shell infrastructure: active-map tracking via dockview
  active-group events. Every future cross-widget "act on the active X" controller
  reuses it.
- The session list, deletes, and rollover stay globally coherent because they live
  in Tier 1; only view attributes diverge per map.
- Multiple-sessions-per-map and per-session selection/colour are additive on this
  model — no migration of the shared list.
- **Explicitly out of scope for the first slices** (not precluded): batch selection
  UI across sessions, per-session colour pickers, and synchronized multi-session
  scrubbing. The data model already admits them.
