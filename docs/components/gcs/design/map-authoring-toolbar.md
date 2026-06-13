# Map Authoring Toolbar

Status: All phases (1–5) shipped; operational constraints (Phase 4) implemented and accepted 2026-06-09.
Date: 2026-06-06 (updated 2026-06-09)

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
  requirement (`ai-agent/requirements.md:302`). Their schema and scope are defined
  in [ADR 0025](../../../cross-cutting/decisions/0025-operational-constraints-schema-and-scope.md);
  the Constraints toolbar controls are enabled as of Phase 4.
- Per-mission **geofence** (single inclusion polygon) and **corridor/survey
  pattern generation** have backend round-trips (`_handleDrawnPattern`,
  `_handleSetGeofence`). Phase 1 changed the UI around them, not the contracts.

## Two load-bearing decisions (made, not deferred)

The review left these as open questions #6 and #1–2. They reshape the
architecture, so they are decided here first.

### Decision A — no geometry-editing plugin; extend the existing custom sketch

**Decision: do not adopt Leaflet-Geoman (or similar). Use the project's existing
custom editing interactions; canonical draft geometry lives in `MapSketchSession`
(introduced in Phase 2).**

Why — three constraints make a plugin the wrong fit:

1. The widget is deliberately a no-build, no-framework ES-module surface
   (`map-widget.md` §Frontend Module Boundary). A heavy Leaflet plugin reverses
   that.
2. Geoman binds editing to **one** `L.map` and owns its layers. Authoring must
   span the scene VIEWs (`L.CRS.Simple`) **and** the separate `BasemapPanel`
   `L.map` (EPSG:3857). Canonical-geometry + per-view-adapter is incompatible
   with a plugin that wants to own the map and layer.
3. The project already maintains custom geometry editing — waypoint drag,
   insert-before/after, the `V` vertex-edit sub-mode, `A` add mode. Vertex
   editing for sketches reuses it, not a second paradigm.

Consequence: drag-vertex / midpoint-insert / snapping are genuinely later work
(Phase 3), not a free plugin feature.

### Decision B — cross-view sketch capture (shipped 2026-06-09)

All drawing tools work on every view, not Basemap-only. The original phased
deferral was removed once it became clear the conversion already existed.

**Current behaviour:**
- All scene views: draw tools are enabled whenever the focused mission provides a
  GPS origin datum (ADR 0022). `MapWidget._map.on('click')` converts CRS.Simple
  metres → WGS84 and calls `session.addVertex()`; `_refreshSceneSketch()` renders
  the draft as a dashed overlay on the scene map.
- Basemap view: unchanged — `BasemapPanel` remains the Leaflet adapter for WGS84
  maps with full vertex drag, snap, survey handle, and constraint rendering.
- If no focused mission (no origin): draw tools show "Focus a mission to enable
  GPS-based drawing on this view." — same gate that already guarded geofence.

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
   mission geometry. Shipped (pattern/survey/waypoint).
2. **Planning & safety constraints** — mission geofence (Phase 1), allowed corridor
   + blockage (ADR 0025, Phase 4).
3. **Scene content** — roads, buildings, terrain, obstacles. **Read-only** in this
   toolbar. Any future scene editing is a separately permissioned mode.

The toolbar never mixes builders with constraints in the same menu group.

## Phases (all shipped)

### Phase 0 — Restore

Browser-tested and confirmed existing flows: waypoint add, corridor pattern
create, survey area create, geofence save/removal. No regression found.

### Phase 1 — Interaction Shell

**State machine — one active tool**

- **Idle (collapsed):** a small bottom-anchored launcher, clear of the cursor/info
  bar, with a recognizable create/edit icon, `aria-label`, and tooltip. Shows an
  unsaved-draft dot when a suspended draft exists. Opens with pointer / `Enter` /
  `Space`. Remembers collapsed state.
- **Idle (expanded):** compact action bar of tool *choices only* — no numeric
  fields visible:
  `Waypoint · Route pattern ▾ · Geofence · Constraints · Collapse`
  `Route pattern ▾` → Corridor pattern, Survey area.
- **Active tool:** the bar becomes that tool's contextual editor. At most one tool
  active at a time. Example (corridor):
  ```
  [Corridor pattern]  Draw path: 3 vertices · ready to finish
  Spacing [5 m]  Passes [1]  Altitude [0 m]
  [Undo] [Generate corridor] [Cancel sketch] [Collapse]
  ```

Commit labels are explicit and distinct per tool:
- Corridor sketch → `Generate corridor`
- Survey sketch → `Generate survey`
- Geofence sketch → `Save geofence`
- Constraint sketch → `Save constraint`
- Always paired with `Cancel sketch`. Never `Finish` alone for a backend action.

**Transaction model (every tool, standardized)**

`Choose tool → Draw/edit draft → Review properties → Save or Cancel`

- `Save` commits (pattern → generate mission; geofence → save to mission).
- `Cancel sketch` discards the in-progress draft only.
- `Delete` only ever removes a persisted object; safety objects confirm first.
- Failed save **preserves the draft** and reports via the global StatusBar;
  duplicate submission is disabled while saving.

**Phase 1 acceptance criteria**

1. Idle state shows tool choices only — no irrelevant numeric fields.
2. At most one authoring tool is active.
3. Every active tool offers a commit action, `Cancel sketch`, and undo where
   geometry changed.
4. The toolbar collapses to an accessible launcher and reopens without losing
   draft state.
5. Failed persistence leaves the draft recoverable and reports in the StatusBar.
6. `Cancel sketch` (draft) and `Delete` (persisted) are never the same control.
7. Switching VIEW preserves the draft; where no adapter exists it suspends
   read-only rather than discarding.
8. Existing corridor/survey/geofence/waypoint flows behave exactly as before the
   redesign.

### Phase 2 — Shared Sketch Session

Extracted sketch state from `BasemapPanel` into `MapSketchSession`; added the
Basemap adapter; draft preserved across VIEW changes; undo/redo of vertices.

### Phase 3 — Mission-Builder Polish

Corridor-width preview, oriented survey rectangle, generated-route preview before
commit, vertex drag/insert, snapping (custom, reusing waypoint edit code).

### Phase 4 — Operational Constraints

Implemented [ADR 0025](../../../cross-cutting/decisions/0025-operational-constraints-schema-and-scope.md):
backend CRUD + versioning, rendering layer, create/enable-disable/delete,
planner consumption (hard-constraint rejection via point-in-polygon).
`Constraints` toolbar button is enabled.

### Phase 5 — Responsive & A11y

Bottom-sheet on narrow screens, full keyboard contract, focus management, touch
+ screen-reader verification. `Escape` stops pointer capture first; collapses
only when no unsaved draft remains.

## Visual language (adopted from the review)

Never color alone. Mission route: solid + numbered. Corridor draft: dashed
centerline + translucent width preview. Survey draft: hatched area + sweep
preview. Hard blockage: red/orange cross-hatch; soft: amber dashed. Allowed
corridor: solid (hard) / dashed (soft) boundary. Geofence: shield + inclusion
iconography. Disabled constraint: muted + visible `Disabled` mark.

## Architecture boundary

- **`MapSketchSession`** (Leaflet/CRS-free) owns: active tool, canonical draft
  geometry, undo/redo stack, validation, selection, dirty/saving/error state.
- **View adapters** provide `screenPointToCanonical`, `canonicalToViewPoint`,
  overlay renderer, hit-test/snap candidates, capability metadata. Basemap uses
  WGS84 directly; scene views convert `L.CRS.Simple` metres through the focused
  mission's origin datum (ADR 0022). Backend stays the coordinate-normalization
  authority; the client carries the source frame and never guesses an origin.
- **`MapAuthoringToolbar`** handles presentation and tool transitions.
- **`BasemapPanel`** provides Basemap rendering and WGS84 pointer capture.
- **`MapWidget`** owns focus, command dispatch, refresh, and StatusBar reporting.

## Open product decisions — resolved

| # | Question (from review) | Decision |
|---|---|---|
| 1 | Pattern inserts into focused mission or new? | **New Mission** for now (matches `_handleDrawnPattern`); insertion deferred. |
| 2 | Geofence inclusion-only or +exclusion? | **Single inclusion polygon per mission** now; multi-region inclusion/exclusion moves to the constraints platform (ADR 0025). |
| 3 | Constraint scope (global/mission/vehicle)? | **Deployment-wide** for the one active operating area. See ADR 0025. |
| 4 | Temporary blockage activation/expiry? | **Not in V1 schema.** Deferred until concrete scheduling use case exists. See ADR 0025. |
| 5 | Constraint editing needs higher permission? | **No separate tier now** (single-operator). ADR 0025. |
| 6 | Geoman dependency acceptable? | **No** — Decision A above. |

## Non-goals

- Editing scene content (roads/buildings/terrain) through this toolbar.
- Changing mission/geofence/pattern backend contracts.
- Merging this toolbar with the sidebar context bar (different surface, different
  scope — see mission-sidebar-toolbar.md).
