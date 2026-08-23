# ADR 0034 — Cross-Container Drop Targets Need Our Own Overlay Layer

**Status:** Accepted
**Date:** 2026-08-23
**Related:** [ADR 0033](./0033-workspace-chrome-density-and-widget-groups.md)
(Widget Groups), [ADR 0030](./0030-greenfield-operator-console-frontend.md)
(dockview shell),
[operator-console.md](../../components/gcs/design/operator-console.md)
(§Cross-boundary drag), roadmap UI8/UI9,
[code review 2026-08-23](../../reviews/code-review-2026-08-23-cross-container-dnd.md).

## Context

UI3 shipped cross-boundary drag by bridging `onWillDragPanel` →
`onUnhandledDragOverEvent` → `onDidDrop` between the outer dock and each Group's
inner dock, with a module-local payload (`widgets/crossBoundaryDnd.ts`). Unit
tests passed, but in the browser the operator could not drag a widget from the
main workspace into a Group, and could not put a widget back into a Group it had
just been dragged out of.

Reading `dockview-core@4.7` sources explains it, and the explanation is not
guessable from the public API:

- Dockview stores the in-flight panel drag in a **module-global singleton**
  (`LocalSelectionTransfer`, read via `getPanelData()`), tagged with the source
  dock's `viewId`.
- **Group / pane drop targets do handle foreign drags.** For a `viewId`
  mismatch, `DockviewGroupPanelModel.canDisplayOverlay` fires
  `onUnhandledDragOverEvent`, and `handleDropEvent`'s else-branch fires
  `onDidDrop` (`dockviewGroupPanelModel.js:726-783`). So the bridge works — for
  panes.
- **The root drop target hard-refuses them.** In
  `dockviewComponent.js:181-186`, when panel data exists with a different
  `viewId`, `canDisplayOverlay` returns `false` immediately and *never fires the
  unhandled event*. Its `center` zone is additionally gated on
  `gridview.length === 0` **and** a matching `viewId`.

Two operator-visible consequences follow, and they are exactly the reported
bugs: **a container edge cannot receive a cross-boundary drop**, and **an empty
dock cannot receive one at all** — which is every emptied Widget Group.

`LocalSelectionTransfer` is not exported from `dockview-core`'s entry point
(only `getPanelData`, `PanelTransfer`, `PaneTransfer` are), so the payload
cannot be cleared while hovering a foreign dock.

## Decision

**Render our own drop-target overlay for the two zones dockview refuses —
container edges and empty docks — and leave dockview's native pane targets
alone.**

- Zone resolution is a pure function of rectangle + pointer, unit-tested
  independently of the DOM.
- Precedence: the **innermost** dock under the cursor wins, and within a dock a
  **24px rim** beats the pane beneath it — the same `activationSize` the nested
  dock already advertises via `dndEdges`, so one rule covers native and custom
  targets.
- The layer reuses dockview's own `dv-drop-target-*` theme tokens, so a
  cross-boundary target is visually identical to a native one. Which *dock*
  lights up is what tells the operator the move crosses a container.
- The transfer itself is transactional: add to the destination first, remove
  from the source only on success.

## Rejected alternatives

- **Mutate the global transfer's `viewId` (or reach the unexported singleton) so
  dockview treats the drag as native.** Smallest diff, and wrong: dockview would
  then drive its internal `_onMove` with a `groupId` that does not exist in the
  destination dock. It also depends on private internals that a patch release
  can move.
- **Replace dockview's cross-boundary targets entirely with one custom layer
  owning all five zones.** More consistent in principle, but it re-implements
  working behavior (pane targets already bridge correctly) and would drift from
  dockview's own overlay geometry. Still the natural end state if the two
  systems ever look inconsistent in practice.
- **Modifier-key cycling between overlapping containers.** The defect is
  discoverability, not ambiguity resolution: with a visible highlight and the
  innermost-wins rule the target is determined, and the non-drag "Move to →"
  menu (roadmap UI9) is the recoverable path for anything the pointer cannot
  express.
- **Patching or forking dockview.** Disproportionate; the workaround is ~one
  module and does not touch serialization, the catalog, or the container.

## Consequences

- A cross-boundary drop path exists that dockview does not know about, so future
  dockview upgrades must be smoke-tested against edge and empty-Group drops
  specifically — the pane path may keep working while these break.
- jsdom cannot validate any of this (zero-size rects, no HTML5 drag lifecycle).
  Regression cover is the pure resolver's unit tests plus a handler-wiring test;
  proving the real gesture needs browser automation, which is **not** stood up.
  Recorded as a known gap in roadmap UI8 rather than papered over with a jsdom
  test that asserts against fabricated coordinates.
