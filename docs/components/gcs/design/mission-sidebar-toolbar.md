# Mission Sidebar Toolbar

This note defines the intended layout and behavior for the mission-sidebar
header and the control bar immediately above the Mission rows on `/ai`.

> Branch context: the committed baseline lives on `master`; this work happens on
> `feat/mission-sidebar-toolbar-redesign`, so behavioral experiments are allowed and
> reviewable after implementation. Each behavioral departure below is tagged
> **[behavioral]**; naming/contract decisions are tagged **[contract]**.

## Vocabulary (term-collision fix)

ADR 0021 §4 already binds **Active** to the *focused* Mission — the single-gesture
target (click a row or a map waypoint). An earlier draft of this note reused
"Active" for an *executing* Mission, which is a true collision. Resolved
**[contract]**:

| Term | Meaning | Source of truth |
|------|---------|-----------------|
| **Active** | the focused Mission (0 or 1); target of single-item gestures | ADR 0021 §4 (unchanged) |
| **Selected** | the batch set (0..N); checkbox / shift-click | ADR 0021 §4 (unchanged) |
| **Visible** | renders on the map (0..N); eye toggle | ADR 0021 §4 (unchanged) |
| **Running** / **Paused** | executor session state | matches existing `sessionStatus` (`running`/`paused`) in `missionRowUtilityActions` |
| **Executing** | the revision-status value that locks edit/eye | ADR 0021 §3; `activeRevisionStatus === 'executing'` |

Rationale for **Running**: the code already calls the live executor session
`running`/`paused` (`sessionStatus`), so this name needs no code or ADR churn —
only this note adopts it. Use **Running**, never "Active", for execution state in
all toolbar copy, labels, and comments.

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

Count text (center slot):

- `None selected` — zero selections, no focused mission
- `N selected` — one or more selected

The count text never shows a mission name; the context action slot already
identifies the targeted mission. Checkbox title/aria-label: `Select all` /
`Deselect all` (type-neutral — the checkbox operates across all missions).

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

### Bar ownership [contract]

The **context bar owns both** selection and visibility controls in every state;
the header bar stays pure collection chrome. Concretely:

Header bar:

- `New mission`
- sort
- filter
- import/export
- overflow `⋯`

Context bar:

- select all / clear selection (left slot)
- show all / hide all (right slot)
- batch delete if retained

### Keep discoverable at row or focused-item level

- `Edit`
- `Run` (legacy sidebar play/upload path per ADR 0023)
- `Pause`
- `Resume`
- `Stop`

### Resolved placement

Move `Edit` and `Run` out of the repeated row chrome and into the **context
bar**, targeting the single acting Mission. The acting target resolves
**focus-first [behavioral]**:

1. if a Mission is **Active** (focused), verbs target it;
2. else if **exactly one** Mission is Selected, verbs target that one;
3. else (no focus, zero or multiple selected) single-item verbs are hidden.

This honors ADR 0021 §4 (single-item gestures target Active/focus) and keeps
**Selected** purely a batch concept — selecting a checkbox does not silently
become the target of a single-item verb. Make the focused-row state visually
strong so the context-bar action target is unambiguous.

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

### One focused (Active) or one selected Mission

Show contextual actions:

- `Edit`
- `Run` or `Resume`
- `Pause` when Running
- `Stop` when Running or Paused
- `Hide` / `Show`

Targeting rule (focus-first, see "Resolved placement"):

- if a Mission is **Active** (focused), actions target it;
- else if **exactly one** Mission is Selected, actions target that one;
- if multiple Missions are Selected, switch to batch actions only.

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

Once the context bar owns focused-item actions, rows become lighter. Resolved
row structure **[behavioral]**:

- colour/status rail — **clickable; opens the colour picker** (keeps today's
  `mission-row-status` affordance). The rail also carries the status tint.
- checkbox
- title/meta
- eye toggle (never collapses)
- overflow menu `⋯` for secondary row actions (never collapses)

Default rows carry **zero inline verbs**. The one exception **[behavioral]**: a
**Running** or **Paused** row promotes **`Stop` ⏹ inline** (in the action slot
next to the eye), because Stop is the urgent action during execution and must
not sit one click deep in overflow. This is a deliberate safety carve-out.

Row overflow candidates:

- rename
- delete
- duplicate, if added later

Note: **colour is NOT an overflow entry** — recolouring stays on the leading
rail, so there is exactly one path to it (no duplication).

## Icon Budget & Collapse Priority [contract]

The sidebar is narrow and gains controls over time. To stop icon placement from
being a per-PR judgment call, each bar has a fixed budget and a deterministic
collapse order. When a bar exceeds its budget at the current width, items move
into the nearest overflow `⋯` in priority order (lowest priority collapses
first).

**Never-collapse (pinned):** `eye`, `New mission`, `Stop` (on a Running/Paused
row). These are always directly reachable.

**Row budget:** trailing slots = `eye` + `⋯` only (plus the inline `Stop`
carve-out). Everything else lives behind `⋯`.

**Context bar budget:** `select` · `count` · **at most 2 contextual verbs** ·
`visibility`. A third+ verb collapses into a context-bar `⋯`.

**Collapse order (first to go → last):**

```
import/export → sort → filter → duplicate → rename → colour → delete
```

(`colour` and `delete` rank last because they are common/destructive enough that
hiding them early hurts; `import/export` ranks first as the rarest.)

### Context bar density degradation [behavioral]

When width is tight, the context bar degrades in this order:

1. **drop the center count text first** (keep it announced via `aria-live` for
   screen readers) — it is the most expendable pixel;
2. then collapse contextual verbs into the context-bar `⋯`;
3. the `select` checkbox and the `visibility` control never collapse.

This prevents the context bar from re-creating the very crowding this redesign
removes.

## Accessibility

- the header bar and context bar should each expose a distinct accessible label
  if both use `role="toolbar"`
- icon-only controls require `aria-label` and tooltip text
- tri-state select-all must expose its mixed state correctly
- context-bar action target must be obvious in text when acting on one Mission,
  for example: `Editing actions for #37 New mission`

## Implementation Notes

Expected frontend touch points:

- `backend/static/map/ui/MissionListPanel.js`
  - split current batch-bar markup into a real context bar
  - add contextual single-target action rendering
  - optionally remove repeated row buttons
- `backend/static/map/MapWidget.js`
  - keep ownership of action handlers
  - resolve context-bar target **focus-first**: `Active` first, then the single
    `Selected` Mission when exactly one is selected (see "Resolved placement")
  - distinguish executor session state via `sessionStatus` (`running`/`paused`),
    labelled **Running**/**Paused** — never "Active"
  - preserve ADR 0021 state model: `Visible`, `Selected`, `Active`
- `backend/static/style.css`
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
