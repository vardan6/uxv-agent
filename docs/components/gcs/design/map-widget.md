# Map Widget

This document defines the durable design contract for the reusable mission map
widget used on `/ai` and later available to other GCS surfaces. ADR 0021 makes
the flat Mission row the durable operator-facing object; any revision/draft API
shape described below is compatibility-only unless stated otherwise.

## Purpose

The widget gives operators spatial review of Missions and safe direct
manipulation of non-executing missions without collapsing approval and
execution into one action.

## Safety Invariants

These rules are non-negotiable:

1. approval is not execution
2. the client never mutates an executing mission
3. the client never silently overwrites authoritative mission state
4. the widget never invents backend contracts that do not exist

Implications:

- approval, rejection, and execution remain separate user actions
- all geometry mutation goes through backend round-trips
- missing backend features are hidden or disabled explicitly

## Backend Contracts

### Mission Overlay Payload

The widget consumes mission overlays from the backend Mission surface.

The durable payload concepts are:

- `mission_id`
- Mission lifecycle status (`awaiting_approval`, `approved`, `rejected`,
  `executing`, ...)
- `status`
- `goal`
- `waypoint_count`
- overlay `bounds`
- route-line and waypoint features

The backend overlay builder remains the source of truth for exact field shape.
The current `/ai` widget is still bridged by temporary compat fields such as
`revision_id` and `draft_id`; new UI work should not make those fields more
central.

### Coordinate System

Mission overlay points are local scene metres `{x, y, z}`, not WGS84
lat/lon.

Design rule:

- scene-mode rendering uses `L.CRS.Simple`
- WGS84 export remains a server-side concern
- any future WGS84 basemap mode must be a distinct widget mode with explicit
  CRS metadata

### Mission List

Durable target: one row = one Mission, with the independent **Visible**,
**Selected**, and **Active** states from ADR 0021.

Design rules:

- clicking a row makes that Mission Active and Visible
- hiding the Active Mission clears Active
- executing missions remain force-visible
- AI clone-and-edit produces a second row rather than mutating the source row

Transitional note:

- the current widget still groups rows through a one-Mission-per-operation
  compatibility projection because the direct sidebar rewrite is Slice 4

### Approval, Rejection, And Execution

The widget uses existing backend transitions rather than inventing new ones.

Design rules:

- approval writes mission approval/export state but does not execute the rover
- execution is a separate explicit action with controller-version staleness
  checks
- rejection is a separate explicit action
- after any of these actions, the widget refreshes mission and overlay state

### Telemetry Source

The live vehicle layer uses existing GCS telemetry projection.

Design rule:

- the widget does not open an unrelated parallel telemetry model when `/ws`
  already provides the needed state

### Deferred Sources

These remain gated on real backend sources:

- mission revision push events
- geofence display and validation
- standalone export affordances
- home-point editing

## Frontend Module Boundary

The widget remains a small ES-module surface without a framework or build step.

Durable separation:

- one orchestrator widget
- layer modules for overlays and live vehicle state
- UI modules for mission list, selection, context actions, and help
- data modules for backend wrappers
- pure state/logic modules for edit state, mission grouping, and profile logic

Pure logic modules should remain DOM- and Leaflet-free so they stay easy to
test later.

## AI Chat Integration

The map is a secondary surface on `/ai`, below the main chat area.

Design rules:

- chat remains the primary interaction surface
- the widget supports container re-parenting and resize invalidation
- map state is driven by the active AI session

## Mission List Rules

Each Mission row carries:

- visibility control
- status indication
- vehicle/profile identity
- mission name or equivalent label
- origin indicator
- action affordances appropriate to the revision state

Behavior rules:

- visible overlays are capped softly to avoid clutter
- focus applies fit-to-bounds and dims non-focused visible missions
- numbered waypoint badges remain visible because color alone is insufficient
- the sidebar header exposes a settings affordance that deep-links to
  `Settings → Mission Lifecycle` (`/settings?tab=mission-lifecycle`) in a new
  browser tab, per [ADR 0021 §6](../../../cross-cutting/decisions/0021-mission-lifecycle.md)

## Map Rendering Rules

- awaiting-approval missions render dashed or visually weaker
- approved missions render solid and fully emphasized
- executing missions render as locked
- rejected or completed missions render dimmed
- fit-to-bounds uses the focused mission when one exists, else the visible-set
  union

## Accessibility And Keyboard Ownership

The widget shares a page with a keyboard-heavy chat composer.

Design rules:

- icon-only controls still require explicit accessible labels
- color never carries meaning by itself
- map keyboard shortcuts only fire when focus is inside the widget and not in a
  free-text input
- `Esc` closes menus/modals before clearing selection and exiting edit mode
- touch/mobile may degrade to read-only editing behavior, but the surface must
  remain usable

## Empty, Error, And Offline States

- when no mission overlay exists, the widget shows a no-mission state rather
  than a broken map
- overlay API failures surface as non-blocking retryable errors
- missing vehicle telemetry hides the live vehicle marker without blocking
  mission rendering
- missing vehicle-profile data falls back safely rather than blocking the UI

## Editing Model

### Core Rules

- editing is available only for non-executing missions
- gesture handlers short-circuit on locked missions
- client edits operate against backend-backed mission state with optimistic
  concurrency checks
- manual edits mutate the active Mission in place
- AI edits default to clone-and-edit, producing a new Mission row

### Gestures And Keyboard

The widget supports:

- waypoint selection and multi-selection
- waypoint dragging
- insert-before / insert-after behavior
- add-waypoint mode
- delete and focus shortcuts
- explicit help and context actions

The exact input affordances may evolve, but they must continue to respect the
locking and concurrency rules above.

### Hard Lock During Execution

While a mission is executing:

- edit, reject, and approve affordances are disabled
- drag/insert/delete gestures are blocked before state changes
- the mission remains visibly locked in both the list and map rendering

## Vehicle Profile Boundary

Vehicle profiles represent mission capability context, not per-waypoint editing
schema by themselves.

The widget may render profile identity and use it to drive map hints, but
vehicle capability fields and per-waypoint property editing remain separate
concerns.

## Deferred Beyond The Current Widget Contract

These stay outside the core widget contract until real backend/platform support
exists:

- replay-page migration details
- geofence display and validation
- WGS84 basemap mode
- edit-during-execution
- richer per-waypoint property schema editing
- floating/second-monitor window behavior beyond re-parenting support
