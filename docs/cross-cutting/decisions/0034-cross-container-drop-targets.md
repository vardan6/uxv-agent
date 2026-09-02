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

**Render our own drop-target overlay for cross-container drops.** It owns the
zones dockview refuses (container edges and empty docks) and, after browser
evidence showed an ancestor native target stealing nested occupied centers, it
also routes occupied-center drops to the actual pane under the pointer.

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
- Wrappers register their API and resolve the innermost dock by coordinates.
  An occupied center retains the rendered group's active panel as its reference,
  so a multi-pane inner dock cannot silently receive the panel in the wrong group.

## Rejected alternatives

- **Mutate the global transfer's `viewId` (or reach the unexported singleton) so
  dockview treats the drag as native.** Smallest diff, and wrong: dockview would
  then drive its internal `_onMove` with a `groupId` that does not exist in the
  destination dock. It also depends on private internals that a patch release
  can move.
- **Initially leave occupied pane centers entirely native.** Browser smoke
  disproved that the native and custom layers coexist reliably when nested:
  the outer content target can cover the inner pane and exclude its wrapper
  from the event path. The custom bridge now owns only foreign-dock centers;
  ordinary same-Dockview moves remain native.
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
- jsdom cannot validate the real gesture (zero-size rects, no HTML5 drag
  lifecycle). Regression cover is the pure resolver plus handler-wiring tests;
  Chromium smoke is the authoritative gesture evidence. The current matrix is
  recorded in
  [the UI8 browser smoke report](../../reviews/ui8-browser-smoke-2026-08-23.md).
- The dock registry this decision introduced for hit-testing is now also the
  source of destinations for the non-drag "Move to →" menu, so it has two
  consumers: a dock that fails to register loses both its cross-boundary drops
  and its place in that menu.

## Implementation status — 2026-08-24

The edge and empty-dock layer, destination-first transaction, and nested
container refusal are implemented. Browser smoke passes cross-boundary root
edges in both orientations, inner edges in both orientations, empty Group,
Group-to-Group leaf transfer, Group-over-Group refusal, and popout reachability.

The refusal required one implementation refinement beyond the original
decision: declining a Group payload in the nested dock was insufficient because
the ancestor Dockview could steal the same gesture and restack the source Group.
Refusing nested docks are now marked in the DOM, and the ancestor
cross-boundary wrapper blocks a container drag by coordinate even when
Dockview's native drop surface obscures the underlying event target.

## Implementation refinement — 2026-08-27

Browser event tracing confirmed that the outer group's content drop surface can
become `event.target` across nested content, excluding the inner wrapper from
the event path. The wrappers now coordinate through a module-local DOM/API
registry. The ancestor capture handler selects the innermost registered dock by
pointer coordinates and routes an occupied center to the active panel of the
rendered group under that point. Chromium verified that an outer Notes panel
became a tab beside Clock in the same inner pane. UI8 is complete.

## Planned refinement — 2026-08-30 (not yet implemented)

An architecture review (`/improve-codebase-architecture`) found the "move a
widget across a dock boundary" concept spread across seven files with 12+
exported functions: `widgets/crossBoundaryDnd.ts`'s payload and drop-accept
predicates, `widgets/CrossBoundaryDropTarget.tsx`'s dock registry and pure
hit-testing (`resolveCrossBoundaryTarget`, `resolveOccupiedPanePanel`,
`hasNestedDockAt`), and `widgets/moveWidget.ts`'s independent remove-and-re-add
implementation for the non-drag **Move to** path. Understanding or changing one
cross-boundary move requires reading all of them.

**Decision (grilled, not yet built):** consolidate the dock registry, the pure
hit-testing functions, and the remove-and-re-add transaction (both the drag
path and the non-drag menu path collapse onto one internal primitive) into a
single instantiable controller, e.g. `createCrossBoundaryController()` with an
explicit `reset()` — matching the factory pattern `createWorkspaceStore()` /
`createGroupTemplateStore()` already use elsewhere in `shell/`. This also
retires a test hack: `crossBoundaryDnd.test.ts` currently resets module-global
state by calling `completeCrossBoundaryDrop({}, ...)` as a no-op because no
real reset exists.

**Rejected: folding everything in.** Two things stay out of the controller
*permanently*, not as a staging step toward a later full merge:
- `widgets/groupActions.ts`'s registry — it answers "what can this Group do"
  (add-widget/save-template/close), a different question with a different
  lifecycle (bound to the Group's mount, not to one gesture) than transfer
  state. `MoveToTab.tsx` already treats it as optional, consulted only when
  the panel is a container.
- The outer/inner dock `onReady` wiring (`Workspace.tsx`, `NestedDockPanel.tsx`)
  that binds `onWillDragPanel`/`onUnhandledDragOverEvent`/`onDidDrop`. The
  outer dock and the inner dock are its two real adapters into the controller —
  exactly why that seam should stay open rather than collapse. Folding it in
  would pull `DockviewReadyEvent`/React lifecycle timing into what should be a
  framework-agnostic module, and would cost the controller its DOM-free
  testability.

Scope is landing in one PR (no staged extraction). The exact method names on
the controller's interface and its final file location are open — left to
implementation time.

## Implementation refinement — 2026-08-30 (implemented)

Landed as `widgets/crossBoundaryController.ts`, exporting `createCrossBoundaryController()`
plus one shared `crossBoundaryController` singleton instance that every dock in
the app coordinates through. `widgets/crossBoundaryDnd.ts` and `widgets/moveWidget.ts`
are deleted; their exports became controller methods (`registerDock`,
`moveDestinations`, `innermostRegisteredDock`, `hasNestedDockAt`, `beginDrag`,
`canAcceptDrag`, `shouldBlockDrag`, `isContainerDrag`, `dragTitle`, `acceptDrag`,
`rejectContainerDrop`, `completeDrop`, `panelSnapshot`, `moveToDock`,
`moveToNewGroup`, `reset`). `completeDrop` and `moveToDock`/`moveToNewGroup` now
share one internal `transfer()` primitive for the add-to-destination-first,
remove-from-source-on-success rule. `resolveCrossBoundaryTarget`,
`resolveOccupiedPanePanel`, and `singlePanelLayout` stay plain pure exports
alongside the factory, callable without an instance. `CrossBoundaryDropTarget.tsx`
keeps the React overlay and `moveLabel`/`selectionStyle`, importing the
controller instead of owning a module-local registry. `groupActions.ts` and the
`Workspace.tsx`/`NestedDockPanel.tsx` `onReady` wiring were left untouched, as
decided above. `reset()` replaces the `completeCrossBoundaryDrop({}, ...)`
no-op-drop test hack; `createCrossBoundaryController()` gives unit tests an
isolated instance instead of sharing the production singleton.

## Planned refinement — 2026-08-31 (not yet implemented)

**Amends, does not reverse, the "Rejected: folding everything in" clause
above.** That clause rejected pulling the dock `onReady` wiring *into the
controller*, on two grounds: it would drag `DockviewReadyEvent`/React lifecycle
timing into a framework-agnostic module, and it would cost the controller its
DOM-free testability. Both grounds still hold and are honoured here. What it
did not intend to protect is the wiring existing **twice**: the outer dock
(`shell/useWorkspaceController.ts`) and the inner Group dock
(`widgets/NestedDockPanel.tsx`) each hand-bind the same four dockview events,
and they have already drifted — the outer one guards
`onUnhandledDragOverEvent` with `hasNestedDockAt` and binds no `onWillDrop`,
the inner one binds `onWillDrop` and omits the guard. They last had to change
together in `ddca3c6`.

**Decision:** the seam stays open with **two adapters and one implementation**.
A new module `widgets/crossBoundaryDockWiring.ts` exports

```
wireCrossBoundaryDock(api, { acceptsContainers }, controller = crossBoundaryController)
```

which both `onReady` bodies call. It is deliberately *not* a controller method
and *not* placed in `crossBoundaryController.ts`: keeping it in its own module
leaves the controller's file, interface, and DOM-free test surface exactly as
the 2026-08-30 refinement left them, and makes the dockview-lifecycle
dependency visible in the import graph rather than buried in the deep module.
The `controller` parameter is injectable for the same reason
`createCrossBoundaryController()` exists — a wiring test gets an isolated
instance instead of the production singleton.

Two behaviour rules the unified helper must encode, both non-obvious:

- **`onWillDrop` is gated on `!acceptsContainers`, never bound
  unconditionally.** `rejectContainerDrop` calls `preventDefault()` for *any*
  container payload. Binding it on the outer dock would refuse dragging a
  Widget Group into the main workspace, which is a legal and shipped move.
  This gate is the one asymmetry that must survive the merge.
- **The `hasNestedDockAt` deferral applies to both docks.** On an inner Group
  dock it is provably a no-op, because Groups never nest (ADR 0033), so no
  registered dock is ever contained by one — asserted today by
  `crossBoundaryController.test.ts` (`hasNestedDockAt(innerApi, …) === false`).
  Applying it unconditionally is therefore behaviour-preserving and removes the
  asymmetry rather than parameterising it.

The helper returns `void` rather than a disposer, matching the current
lifetime: dockview calls `onReady` once per dock and the subscriptions die with
the dock's api. Nothing unwires today, so returning a disposable would add an
interface with no caller.

**Not in scope, and why:** relocating `reachableDestinations` out of
`widgets/MoveToTab.tsx` (architecture-review candidate #6) is a pure file move
of an already-deep, already-unit-tested function, and unifying
`shell/layoutRestore.ts`'s rewriting traversal with `walkLayoutPanels`
(candidate #5's second half) is blocked on the visitor having no rewrite mode.
Both stay parked.

### Verification obligation

Per §Consequences, jsdom cannot exercise the real gesture, so unit tests are
necessary but not sufficient here. This refinement rewires the exact path whose
last regression was invisible to a green unit suite. Chromium smoke must
re-confirm, at minimum: main → Group, Group → main, Group → Group leaf
transfer, **Group → main workspace (the `onWillDrop` gate)**, and Group over
Group refusal.
