# Mission Sidebar Toolbar

Status: planned
Date: 2026-06-06

This note defines the intended layout and behavior for the mission-sidebar
header and the control bar immediately above the Mission rows on `/ai`.

It exists because the current "None selected" bar is visually too close to a
Mission row, which makes the control strip read like content instead of chrome.
The redesign separates collection controls from item rows and reduces repeated
row actions on narrow sidebars.

## Problem

Current issues observed in the shipped sidebar:

- the batch/selection bar uses the same stripe-and-card geometry as a Mission
  row, so it looks like a broken or empty row instead of a toolbar
- the left grey stripe in the bar has no semantic meaning and reads as an
  artifact
- the select-all checkbox and the right-side show/hide button do not align
  cleanly with the row checkbox and eye columns below
- per-row action density is high for a narrow sidebar; edit and run compete with
  row scanning

## Design Decision

The sidebar gets **two distinct top bars**, not one mixed toolbar:

1. **Header bar** for list-level, persistent controls
2. **Context bar** for selection- and focus-sensitive actions

This follows the common split used by data/list surfaces:

- persistent toolbar for collection actions
- contextual action bar for selected items
- row-level actions only for fast, high-confidence affordances

## Layout

Top-to-bottom order:

1. `Missions` header bar
2. context/action bar
3. Mission rows

### Header Bar

Purpose: collection-level controls that are always available and do not depend
on the focused or selected Mission.

Contents:

- left: `Missions` title
- right: `+ New`, sort/filter entry point, overflow menu

Rules:

- do not place Mission-specific actions (`Edit`, `Run`, `Pause`, `Stop`) here
- keep the bar visually light; it is navigation chrome, not a row
- settings/import/export/sort belong in overflow unless they are used
  constantly

## Context Bar

Purpose: actions for the current selection and, when exactly one Mission is the
acting target, actions for that Mission.

### Visual Rules

- must not reuse the Mission-row left colour/status stripe
- must not look like a Mission card
- should use a flatter background and tighter border than rows
- should keep the same checkbox column and right action column alignment as the
  Mission rows below

### Structural Rules

- left slot: tri-state select-all checkbox
- center slot: status/count text
- middle actions slot: contextual actions
- right slot: visibility controls for the list or selection

Suggested text:

- `No missions selected`
- `1 mission selected`
- `N missions selected`

Prefer `No missions selected` over `None selected`; it reads as state text, not
as a placeholder row title.

## Alignment Contract

The context bar and Mission rows must share the same column geometry for the
checkbox and visibility slots.

Implementation rule:

- define shared CSS custom properties for sidebar columns, for example:
  - `--mission-list-select-col`
  - `--mission-list-visibility-col`
  - `--mission-list-leading-gap`
- consume the same values in both `.mission-list-row` and the context bar grid
- do **not** include a stripe column in the context bar grid

The context bar should align to the row checkbox and eye button, not mimic the
full row template.

## Action Placement

Mission actions split by scope:

### Keep in the header/context bars

- `New mission`
- sort
- filter
- import/export
- show all / hide all
- select all / clear selection
- batch delete if retained

### Keep discoverable at row or focused-item level

- `Edit`
- `Run` (legacy sidebar play/upload path per ADR 0023)
- `Pause`
- `Resume`
- `Stop`

### Preferred compromise

Move `Edit` and `Run` out of the repeated row chrome and into the **context
bar when exactly one Mission is the acting target**, but keep one clear path for
discoverability:

- either keep a single inline primary action on each row
- or make the focused-row state visually strong enough that the context-bar
  action target is obvious

Do **not** move all Mission actions into the persistent header bar. Those
actions are item-scoped, not list-scoped.

## Recommended Interaction Model

### No selection

Show:

- select-all checkbox
- text: `No missions selected`
- right-side: `Show all` / `Hide all`

Hide:

- Mission-specific verbs

### One selected or one focused Mission

Show contextual actions:

- `Edit`
- `Run` or `Resume`
- `Pause` when active
- `Stop` when active
- `Hide` / `Show`

Targeting rule:

- if there is exactly one selected Mission, actions target that Mission
- otherwise, if there is no selection and one Mission is Active, actions target
  the Active Mission
- if multiple Missions are selected, switch to batch actions only

This keeps the bar useful without forcing selection before every single-item
action.

### Multiple selected Missions

Show only batch-safe actions:

- `Show`
- `Hide`
- `Delete` only if bulk delete remains a supported flow
- `Clear selection`

Do not show `Edit` or `Run` in a multi-select state.

## Row Simplification

Once the context bar owns focused-item actions, rows should become lighter.

Preferred row structure:

- colour/status rail
- checkbox
- title/meta
- eye toggle
- overflow menu for secondary row actions

Good candidates for row overflow:

- rename
- delete
- colour
- duplicate, if added later

If a row keeps one inline primary action, cap it at **one**. The narrow sidebar
should not try to expose the whole Mission lifecycle inline on every row.

## Accessibility

- the header bar and context bar should each expose a distinct accessible label
  if both use `role="toolbar"`
- icon-only controls require `aria-label` and tooltip text
- tri-state select-all must expose its mixed state correctly
- context-bar action target must be obvious in text when acting on one Mission,
  for example: `Editing actions for #37 New mission`

## Implementation Notes

Expected frontend touch points:

- `gcs_server/static/map/ui/MissionListPanel.js`
  - split current batch-bar markup into a real context bar
  - add contextual single-target action rendering
  - optionally remove repeated row buttons
- `gcs_server/static/map/MapWidget.js`
  - keep ownership of action handlers
  - resolve context-bar target from `Selected` first, then `Active`
  - preserve ADR 0021 state model: `Visible`, `Selected`, `Active`
- `gcs_server/static/style.css`
  - replace the pseudo-row batch bar styles
  - introduce shared sidebar column variables
  - align checkbox and visibility columns between context bar and rows

## Non-Goals

- changing ADR 0021's three-state Mission model
- changing ADR 0023's meaning of the sidebar `Run` action
- inventing new backend contracts for toolbar actions
- turning the sidebar header into a global command bar for unrelated map tools

## External Pattern References

These informed the split between persistent collection controls and contextual
selection actions:

- PatternFly toolbar and bulk selection patterns
- Carbon data-table and batch-action patterns
- Fluent toolbar guidance
- WAI-ARIA toolbar pattern
