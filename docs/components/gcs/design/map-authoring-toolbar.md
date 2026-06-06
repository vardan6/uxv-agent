# Map Authoring Toolbar

Status: planned (design decisions resolved 2026-06-06; pending operator confirmation)
Date: 2026-06-06

This note is the canonical design for the bottom-of-canvas **map authoring
toolbar** on `/ai`. It supersedes the analysis in
[`docs/archive/2026-06-06-map-authoring-toolbar-review.md`](../../../archive/2026-06-06-map-authoring-toolbar-review.md),
which remains the input record. Where this note and the review disagree, this
note wins; where the review's findings are good (taxonomy, terminology,
one-active-tool, transaction model), they are adopted verbatim below.

Sibling design: [map-widget.md](./map-widget.md) (toolbar placement, VIEW model,
coordinate frames) and [mission-sidebar-toolbar.md](./mission-sidebar-toolbar.md)
(list chrome — a *different* toolbar; do not merge the two).

## What grounds this design

- The authoring toolbar **must** sit at the bottom of the map canvas and work
  across VIEWs, not only Basemap (`gcs/requirements.md:197`, `map-widget.md` §Map
  Authoring Toolbar). The sidebar is not an option — it owns list chrome only.
- Operational **corridors** (stay-inside) and **blockages** (stay-outside), with
  create/view/edit/enable-disable/delete as first-class planning data, are a real
  requirement (`ai-agent/requirements.md:302`) — but a *future* one. Their schema
  and scope are resolved in [ADR 0025](../../../cross-cutting/decisions/0025-operational-constraints-schema-and-scope.md);
  no toolbar work waits on them.
- Per-mission **geofence** (single inclusion polygon) and **corridor/survey
  pattern generation** already have backend round-trips today
  (`_handleDrawnPattern`, `_handleSetGeofence`). Phase 1 changes the UI around
  them, not the contracts.

## Two load-bearing decisions (made, not deferred)

The review left these as open questions #6 and #1–2. They reshape the
architecture, so they are decided here first.

### Decision A — no geometry-editing plugin; extend the existing custom sketch

**Decision: do not adopt Leaflet-Geoman (or similar). Build a renderer-independent
`MapSketchSession` over the project's existing custom editing interactions.**

Why — three constraints make a plugin the wrong fit:

1. The widget is deliberately a no-build, no-framework ES-module surface
   (`map-widget.md` §Frontend Module Boundary). A heavy Leaflet plugin reverses
   that.
2. Geoman binds editing to **one** `L.map` and owns its layers. Authoring must
   span the scene VIEWs (`L.CRS.Simple`) **and** the separate `BasemapPanel`
   `L.map` (EPSG:3857). Canonical-geometry + per-view-adapter (the model the
   cross-view requirement forces) is incompatible with a plugin that wants to own
   the map and layer.
3. The project already maintains custom geometry editing — waypoint drag,
   insert-before/after, the `V` vertex-edit sub-mode, `A` add mode. The muscle
   exists; vertex editing for sketches should reuse it, not introduce a second
   paradigm.

Consequence: finding #7's "minimum interaction set" is **re-scoped** (see below).
Because we build it ourselves, drag-vertex / midpoint-insert / snapping are
genuinely later work, not a free plugin feature.

### Decision B — cross-view is architected now, delivered in phases

Cross-view capability is required, but full scene-view sketch capture needs the
per-mission origin/georef conversion path (ADR 0022 gives the origin datum;
`map-widget.md` still marks scene sketching deferred).

**Decision:**
- Phase 1 introduces `MapSketchSession` holding **canonical** geometry, with the
  **Basemap adapter only** — preserving today's behavior, no regression.
- The scene-view adapter (Phase 2) is gated on a focused mission with a known
  origin datum.
- A draft is **preserved across VIEW switches** (cheap once geometry is
  canonical). If the target VIEW has no adapter yet, the draft is **suspended and
  shown read-only** with a "switch to Basemap to continue this sketch" notice —
  never silently discarded.

This honors "don't lose work" without requiring every adapter at once. The
review's AC "draft fully editable across any view mid-sketch" is downgraded to
"draft survives the switch; editing resumes where an adapter exists."

## Resolved terminology (adopted from the review)

| Use this | For | Never |
|---|---|---|
| **Corridor pattern** / **Route pattern** | generated mission waypoints from a drawn polyline | bare "Corridor" |
| **Allowed corridor** (stay-inside) | operational planning constraint | "Corridor" |
| **Blockage** / **Keep-out area** (stay-outside) | operational planning constraint | "blocker" |
| **Mission geofence** | per-mission inclusion safety boundary | "fence" alone in copy |
| **Cancel sketch** | discard unsaved draft | "Clear" |
| **Delete** | remove a persisted object (confirm for safety objects) | "Clear" |

The current code's twin `Clear` / `Clear fence` buttons are the canonical example
of the overload this fixes: one cancels a draft, one deletes persisted state.

## Object taxonomy (adopted from the review)

1. **Mission builders** — waypoint route, corridor pattern, survey area. Produce
   mission geometry. Shipped today (pattern/survey/waypoint).
2. **Planning & safety constraints** — mission geofence (today), allowed corridor
   + blockage (ADR 0025, future).
3. **Scene content** — roads, buildings, terrain, obstacles. **Read-only** in this
   toolbar. Any future scene editing is a separately permissioned mode.

The toolbar never mixes builders with constraints in the same menu group.

## Phase 1 — Interaction Shell (ship now)

This is the slice that delivers the felt UX win without the platform work. It
does **not** change any backend contract.

### State machine — one active tool

- **Idle (collapsed):** a small bottom-anchored launcher, clear of the cursor/info
  bar, with a recognizable create/edit icon, `aria-label`, and tooltip. Shows an
  unsaved-draft dot when a suspended draft exists. Opens with pointer / `Enter` /
  `Space`. Remembers collapsed state.
- **Idle (expanded):** compact action bar of tool *choices only* — no numeric
  fields visible:
  `Waypoint · Route pattern ▾ · Geofence · (Constraints ▾ — disabled, see ADR 0025) · Edit existing · Undo · Redo · Collapse`
  `Route pattern ▾` → Corridor pattern, Survey area.
- **Active tool:** the bar becomes that tool's contextual editor. At most one tool
  active at a time. Example (corridor):
  ```
  [Corridor pattern]  Draw path: 3 vertices · ready to finish
  Spacing [5 m]  Passes [1]  Altitude [0 m]
  [Undo] [Finish] [Cancel sketch] [Collapse]
  ```

### Transaction model (every tool, standardized)

`Choose tool → Draw/edit draft → Review properties → Finish/Save or Cancel`

- `Finish/Save` commits (pattern → generate mission; geofence → save to mission).
- `Cancel sketch` discards the in-progress draft only.
- `Delete` only ever removes a persisted object; safety objects confirm first.
- Failed save **preserves the draft** and reports via the global StatusBar;
  duplicate submission is disabled while saving.

### Corrected "minimum interaction set"

Because we build editing ourselves (Decision A), Phase 1 minimum is small and
honest:

- undo last vertex
- finish (double-click or explicit `Finish`)
- cancel (`Escape`)

Drag-vertex, midpoint/ghost-handle insert, delete-selected-vertex, and snapping
are **Phase 3**, reusing the existing waypoint vertex-edit code — explicitly *not*
"minimum."

### Labels, status, keyboard

- Visible labelled fields with units (`Spacing … m`, `Altitude … m`, `Passes`).
  Drop `sp` / `alt` / `×`. Tooltips supplement, never replace, labels.
- `Escape` cancels the current pointer op first; collapses only when no unsaved
  draft remains.
- Map shortcuts fire only when focus is in the widget and not in a text field
  (existing `map-widget.md` rule).
- Icon-only actions carry accessible names; targets are touch-sized on narrow
  screens (full bottom-sheet responsive pass is Phase 5).

### Phase 1 acceptance criteria (trimmed from the review's 12)

1. Idle state shows tool choices only — no irrelevant numeric fields.
2. At most one authoring tool is active.
3. Every active tool offers `Finish/Save`, `Cancel sketch`, and undo where
   geometry changed.
4. The toolbar collapses to an accessible launcher and reopens without losing
   draft state.
5. Failed persistence leaves the draft recoverable and reports in the StatusBar.
6. `Cancel sketch` (draft) and `Delete` (persisted) are never the same control.
7. Switching VIEW preserves the draft; where no adapter exists it suspends
   read-only rather than discarding.
8. Existing corridor/survey/geofence/waypoint flows behave exactly as before the
   redesign (verified in-browser per Phase 0).

The remaining review ACs (constraint CRUD, hard/soft styling, scene-mutation
guards, cross-view coordinate round-trips) attach to Phases 2 and 4 below.

## Phases 2–5 (designed now, built later)

- **Phase 0 — restore current flows.** Before redrawing any DOM, browser-test and
  fix corridor / survey / geofence / waypoint flows; capture network + console.
  Static reading does not prove the reported post-`487f850` regression. *(This is
  a prerequisite for Phase 1, not parallel to it.)*
- **Phase 2 — shared sketch session.** Extract sketch state out of `BasemapPanel`
  into `MapSketchSession`; add the scene-view adapter; preserve drafts across VIEW
  changes; add undo/redo of vertices.
- **Phase 3 — mission-builder polish.** Corridor-width preview, oriented survey
  rectangle, generated-route preview before commit, vertex drag/insert, snapping
  (all custom, reusing waypoint edit code).
- **Phase 4 — operational constraints.** Implement [ADR 0025](../../../cross-cutting/decisions/0025-operational-constraints-schema-and-scope.md):
  backend CRUD + versioning, rendering layer, create/edit/enable-disable/delete,
  planner consumption. Only after this does the `Constraints ▾` menu enable.
- **Phase 5 — responsive & a11y pass.** Bottom-sheet on narrow screens, full
  keyboard contract, focus management, touch + screen-reader verification.

## Visual language (Phase 3+/4, adopted from the review)

Never color alone. Mission route: solid + numbered. Corridor draft: dashed
centerline + translucent width preview. Survey draft: hatched area + sweep
preview. Hard blockage: red/orange cross-hatch; soft: amber dashed. Allowed
corridor: solid (hard) / dashed (soft) boundary. Geofence: shield + inclusion
iconography. Disabled constraint: muted + visible `Disabled` mark.

## Architecture boundary (Phase 2)

- **`MapSketchSession`** (Leaflet/CRS-free) owns: active tool, canonical draft
  geometry, undo/redo stack, validation, selection, dirty/saving/error state.
- **View adapters** provide `screenPointToCanonical`, `canonicalToViewPoint`,
  overlay renderer, hit-test/snap candidates, capability metadata. Basemap uses
  WGS84 directly; scene views convert `L.CRS.Simple` metres through the focused
  mission's origin datum (ADR 0022). Backend stays the coordinate-normalization
  authority; the client carries the source frame and never guesses an origin.
- The toolbar invokes typed domain commands (`createCorridorPattern`,
  `setMissionGeofence`, `createBlockage`, …) instead of delegating to
  `BasemapPanel` methods — removing today's `MapAuthoringToolbar → BasemapPanel`
  coupling.

## Open product decisions — resolved

| # | Question (from review) | Decision |
|---|---|---|
| 1 | Pattern inserts into focused mission or new? | **New Mission** for now (matches `_handleDrawnPattern`); insertion deferred. |
| 2 | Geofence inclusion-only or +exclusion? | **Single inclusion polygon per mission** now; multi-region inclusion/exclusion moves to the constraints platform (ADR 0025). |
| 3 | Constraint scope (global/mission/vehicle)? | **Scene/project-scoped**, optional nullable vehicle-profile applicability. See ADR 0025. |
| 4 | Temporary blockage activation/expiry? | **Schema carries optional `effective_from`/`effective_to`; runtime enforcement deferred.** ADR 0025. |
| 5 | Constraint editing needs higher permission? | **No separate tier now** (single-operator); `created_by` metadata leaves room to add one later. ADR 0025. |
| 6 | Geoman dependency acceptable? | **No** — Decision A above. |

## Non-goals

- Editing scene content (roads/buildings/terrain) through this toolbar.
- Changing mission/geofence/pattern backend contracts in Phase 1.
- Merging this toolbar with the sidebar context bar (different surface, different
  scope — see mission-sidebar-toolbar.md).
- Building the constraints platform before ADR 0025 is accepted.
