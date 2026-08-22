# ADR 0033 — Workspace Chrome Density and Widget Groups

**Status:** Accepted
**Date:** 2026-08-22
**Related:** [ADR 0030](./0030-greenfield-operator-console-frontend.md) (dockview
shell, hot-path rule), [ADR 0031](./0031-headless-full-architecture-and-frontend-data-layer.md)
(§4 widget catalog is the only source of shell panels),
[operator-console.md](../../components/gcs/design/operator-console.md)
(§Chrome density, §Widget Groups).

## Context

The console now carries ~12 catalog widgets. Two operator complaints, one
structural cause.

1. **Tab bars eat the workspace.** dockview's stock tab bar is 35px, and panels
   pay it per group whether or not the group holds more than one tab — a solo
   panel spends a full strip on a stub tab occupying ~15% of its width.

   > **Correction (2026-08-22, plan review).** This section originally read "the
   > curated layouts add each panel with `direction: "right"`, so nearly every
   > panel sits in its own group". That described the test helper
   > (`workspaceDefaultLayouts.test.tsx`), not the shipped defaults: the curated
   > layouts are serialized grids in `workspaceStore.ts` and already used some
   > stacking (mission and driving were two leaves each). The real cost driver is
   > solo curated leaves plus palette-added widgets against a 35px strip. The
   > decision below is unaffected.

2. **There is no way to move several widgets together.** The operator wants a
   rectangle holding several *simultaneously visible* widgets that docks and moves
   as one unit with its internal arrangement intact.

The second is not a styling question. dockview's grid re-tiles on every panel
move; there is no primitive for picking up a subtree of the grid and dropping it
elsewhere intact. Neither golden-layout, rc-dock, nor flexlayout-react offers one
either, so "switch libraries" does not solve it.

## Decision

**Chrome:** pin the tab bar to 22px, enable `singleTabMode="fullwidth"`, and
regroup the curated layouts so widgets consulted one at a time share a stack while
continuously-monitored widgets stay solo.

**Containers:** implement Widget Groups as **nested `DockviewReact` instances
hosted inside a panel**, depth 1, registered through the catalog behind an
`isContainer` flag.

**Sequencing:** three slices — chrome compaction, then the Group container, then
cross-boundary drag-and-drop.

## Rationale

Nesting is the only approach where the outer dock needs no modification: it sees
one opaque panel, so docking, snapping, splitting, resizing, and workspace
serialization keep working, and the inner layout survives a move for free because
the subtree never unmounts.

Splitting cross-boundary DnD into its own slice is safe rather than merely
cautious, because that work is **purely additive** — it touches drop handlers and
a drag payload, not the container, header, catalog flag, constraints, or
serialization format. Nothing built in the container slice is rewritten by it. It
is also the part whose ergonomics (how the outer dock should highlight a Group as
a drop target vs. the Group's own internal split indicators) can only be judged
against a running prototype.

## Alternatives rejected

**Vertical / side-mounted tab bars.** dockview has no tab-strip orientation
option. The only routes are a `writing-mode`/`rotate()` hack on
`.dv-tabs-container` — which breaks tab scrolling and, worse, drop-indicator
hit-testing, because dockview computes drop targets from unrotated bounding boxes
— or forking. Even if free, the economics are wrong here: a vertical strip costs
width *per column of groups*, and the curated layouts are column-heavy, so three
columns would spend ~300px of width to reclaim ~35px of height once. Vertical tabs
pay off only in layouts with few, tall groups. The axis was never the problem;
unused stacking was.

**Hidden header with a custom drag grip.** dockview's drag source *is* the tab
element, so hiding the header means reimplementing the drag source against
dockview internals. It also requires adding a title bar to the six widgets that
render no internal header of their own (Telemetry, Notes, Clock, Video, Drive
Controls, Map), which gives back most of the reclaimed height. High cost, small
net saving.

**Hover-reveal / auto-hide strip.** Saves the most, keeps DnD intact, but destroys
at-a-glance identification for the unlabeled widgets and collides with widgets
whose controls sit at the top edge (Map toolbar, Video OSD). Viable later as an
opt-in focus mode; wrong as a default.

**Icon-only tabs.** Saves width, not height, and twelve rover widgets do not have
twelve unambiguous glyphs.

**Global VS Code-style activity rail.** Largest visual win, largest rewrite, and
it severs widget identity from position in the dock — the wrong trade for a
layout-centric console.

**dockview floating / popout groups as the "move together" answer.** They move as
a unit and drag by their header, but they remain tab stacks: one widget visible at
a time. They do not satisfy the requirement.

## Consequences

- `WidgetCatalogEntry` gains `isContainer`; the Add Widget palette must filter it,
  and a distinct Add Group action instantiates it.
- Layout serialization becomes recursive **in both directions**. Restore must
  descend into each Group's inner layout in panel `params`, or a widget dropped
  from the catalog survives inside a Group and breaks restore. Save is the
  subtler half: the outer dock emits no event when an inner dock changes, so the
  Group must push its inner `toJSON` back into its own panel `params` to reach
  the autosave at all.
- Every workspace-global rule that used to be a single flat walk becomes a
  recursive one — singleton counting, compact flattening, restore pruning, and
  dropped-panel reporting. That is four traversals of one structure; they belong
  in one shared walker (roadmap UI2s) rather than four hand-rolled copies.
- Compact/mobile mode must flatten Groups into their member widgets; a nested dock
  inside a mobile stack is not a usable surface.
- The invariant that all widget view state lives in serializable panel `params`
  (already required by §Workspaces) becomes load-bearing: cross-boundary moves in
  the third slice are remove-and-re-add, and any widget holding state in a closure
  or module singleton will silently lose it.
- Operator-facing vocabulary changes: "group" now means a Widget Group; dockview
  tab stacks are called "tabs" in UI copy and docs.
