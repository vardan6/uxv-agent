# Operator Console — Frontend Design

How the greenfield widget workspace is built. Decisions and rationale live in
[ADR 0030](../../../cross-cutting/decisions/0030-greenfield-operator-console-frontend.md)
(stack) and
[ADR 0031](../../../cross-cutting/decisions/0031-headless-full-architecture-and-frontend-data-layer.md)
(headless architecture + data layer); operator-visible behavior lives in
[../requirements.md](../requirements.md) §Operator Console. This file owns the
implementation strategy and seams. It does not restate the decisions.

## Stack

- **Vite + TypeScript + React** application; builds to a static dir served by the
  Python app with SPA fallback. Dev = Vite dev server proxying `/api` + `/ws`.
- **dockview-react** for the layout shell. **shadcn/ui + Tailwind** for components.
- **TanStack Query** (Domain Stores) + **Zustand** (Runtime State) + **TanStack
  Router** + **Vitest/Playwright**.

## Data layer (single projection — ADR 0031 §3)

One module owns all backend access; widgets import from it and never fetch or open
sockets themselves.

- **Runtime State** → a single `/ws` connection feeding a Zustand store
  (`telemetry`, `broker`, `controller`, `video/<cameraId>`). One connection per
  client regardless of widget count.
- **Domain Stores** → TanStack Query hooks over REST (`/api/replay/*`, AI sessions,
  missions, constraints). Query keys are the cache; mounting/unmounting a widget
  only adds/removes subscribers to an existing key.
- **Uniform access:** widgets see both tiers through the same hook surface; they do
  not know telemetry is WS and missions are REST.
- **Shared request helpers:** `data/apiClient.ts` owns `apiFetch`, `fetchJson`, and
  `jsonHeaders`. `fetchJson` reads an error body exactly once — attempting `json()`
  then `text()` on the same response throws `Body is unusable` and masks the real
  error.

### Whole-map endpoints must merge on write

`PUT /api/model-routing` replaces the entire routing map server-side; there is no
partial-update endpoint and no concurrency token. Any panel editing one purpose
must therefore merge its patch onto routing re-read at save time
(`data/llmSettings.ts` — `saveModelRouting`), never PUT a mount-time snapshot, or
it silently discards purposes another panel changed. Same rule applies to any
future endpoint that replaces a whole document.

### Per-client WS subscription protocol (ADR 0031 §5)

Built (Slice 5). `ws_manager` (`gcs_server/ws.py`) holds per-client topic sets.
Client sends `{op:"subscribe"|"unsubscribe", topic}` (e.g. `video/<cameraId>`);
server pushes high-volume streams only via `broadcast_to_subscribers`. Cheap topics
(telemetry, broker, controller) stay broadcast. A reference-counted subscription
manager in the data layer subscribes on first mounted consumer and unsubscribes on
last unmount. Snapshot/pull remains unconditional.

## Widget model (ADR 0031 §4)

A widget = a React component bound to the data layer + a catalog entry. Added from
a **widget palette** ("Add Widget"). dockview hosts each widget as a panel; the
same component type may be instantiated multiple times.

### Hot-path rule (ADR 0030)

High-frequency streams bypass React render: video frame → `imgRef.current.src`;
OSD line → `el.textContent` via ref; map markers → Leaflet imperative API. The
existing vanilla `MapWidget` is hosted inside a dockview panel via `dockview-core`
mounting, not rewritten into React state.

### Window-aware popout rule (ADR 0031 / ADR 0030)

A popped-out group runs in the **main window's JS context** (shared stores work)
but renders into **another window's `document`**. Therefore widget code must never
assume the main window: scope `document`/`window` references to the panel's owner
document, attach key listeners to the panel root (not global `window`), and measure
geometry from the panel element. This is a lint-enforced coding rule.

Exception: **Drive control ownership is shell-owned, not widget-owned.** The
active, focused GCS browser window owns keyboard driving even if the Drive
Controls panel is not mounted. The Drive panel is a view/controller surface over
that shared state, not the owner of the keyboard listeners.

### Widget catalog and isolation

All top-level widgets are isolatable (dock/split/float/popout). Indivisible
sub-parts travel with their widget.

> **Normal groups vs edge groups.** dockview's **edge groups** (panels anchored to
> a workspace edge) **cannot** be maximized or converted into floating / popout
> windows — they are structural. Any widget that needs float/popout (video, drive)
> must live in a **normal docked group**. Edge groups are reserved for persistent
> peripheral surfaces (e.g. a Status Bar rail). "Dock to any edge" in requirements
> means normal edge-snapping, not placing a widget into an edge group. See
> [ADR 0030](../../../cross-cutting/decisions/0030-greenfield-operator-console-frontend.md).

| Widget | Multi-instance | Notes |
|---|---|---|
| Map | design for many, ship one | self-contained: includes its own layer/object/visibility controls; per-instance view state |
| Video Feed | yes (one per camera) | OSD overlay is a bound sub-part; WS-subscription-gated; per-panel params carry the applied OSD preset id |
| Drive Controls | singleton | independent of Video; optional UI over shell-owned key capture tied to the active GCS window |
| Telemetry / Runtime | yes | pure read view |
| AI Chat (thread+composer) | yes, one per distinct session | composer bound to thread; ≤1 view per session |
| AI Session List | singleton | isolatable but low value |
| Replay Sessions | singleton | per-map track visibility is a Map toggle |
| Replay Playback Controls | singleton | |
| Status Bar | singleton | reuse `StatusBar.js` |

### Multi-instance and active-target

dockview supplies multiple panels of one component type and tracks the active
group. **Map controls live inside each Map widget**, so there is no "which map does
the panel control?" ambiguity — each map owns its layers/visibility. Where a future
cross-widget controller needs a target, it acts on the **active** map (active-group
pattern). Multi-map costs: pause/throttle rendering for hidden/off-screen maps. The
replay UI is the first realization of this pattern — per-map replay view state and
an active-target singleton transport are specified in
[ADR 0032](../../../cross-cutting/decisions/0032-per-map-replay-state-and-active-target-transport.md).

## Chrome density and stacking policy

Cost is charged **per dockview group, not per widget**: one tab bar serves a whole
stack. Twelve widgets spread across twelve solo groups pays the strip twelve times
for tabs that are never used as tabs. Three settings follow from that:

- Tab bar height is pinned via `--dv-tabs-and-actions-container-height: 22px` in
  the `.quiet-dockview` block (`frontend/src/index.css`), down from dockview's
  stock 35px.
- `singleTabMode="fullwidth"` on `DockviewReact`, so a solo panel's tab spans its
  group and reads as a title bar rather than a stub tab beside dead space.
- **Stacking policy for curated layouts:** widgets the operator *monitors
  continuously* get solo groups; widgets *consulted one at a time* share a stack.
  Mission = Map solo, AI Chat solo, and Telemetry + Replay Sessions + Notes
  stacked. Driving = Video solo, Drive Controls + Telemetry stacked.

### Palette-added widgets split, they do not stack

Curated seeds are hand-authored, but a palette add has no authored intent, and
defaulting to dockview's active group made every added widget a tab — so a
Widget Group could only ever show one widget at a time, defeating its purpose.
`palettePlacement` (`frontend/src/shell/panelPlacement.ts`) is the single
convention both docks use: split off the dock's active panel, `right` when the
dock is wider than tall and `below` otherwise. Splitting the short axis is what
drives panes under the Group's 360×240 minimum, which is why direction follows
the aspect ratio rather than being fixed.

Stacking stays reachable as a deliberate operator gesture — drag a panel onto a
tab strip. The earlier plan to hardcode curated palette pairings (Settings + LLM
Provider + Config I/O; the replay triad) is **dropped**: it guessed at intent the
operator can express in one drag, and it would have needed a second placement
rule alongside this one.

Rejected chrome alternatives and their reasoning are in
[ADR 0033](../../../cross-cutting/decisions/0033-workspace-chrome-density-and-widget-groups.md).

Changing the curated seeds does not migrate Workspaces the operator already
saved; they adopt the new grouping only via the existing "reset a curated
default" path.

## Widget Groups (nested docks)

A **Widget Group** is a panel whose content is *another* `DockviewReact` instance.
It is not dockview's `DockviewGroupPanel` — that is a **tab stack** (one panel
visible at a time), and in operator-facing copy those are called "tabs", never
"groups". In code the container is `NestedDockPanel` so the names cannot collide.

Nesting is what buys the behavior: the outer dock treats the Group as one opaque
panel, so docking, snapping, splitting, and resizing all work unchanged, and the
inner arrangement survives a move because the subtree never unmounts.

- **Depth 1.** A Widget Group cannot contain a Widget Group.
- **Inner layout is proportional, not absolute.** On move the Group keeps its
  relative splits and stretches to the new rectangle. Preserving absolute pixel
  sizes breaks as soon as a wide Group is docked into a narrow column.
- **Minimum size** via `setConstraints` (~360×240) so a populated Group cannot be
  squeezed into an unusable sliver.
- **A Group shows several widgets at once.** The inner dock is a full
  `DockviewReact`, so split panes, edge snapping and resizing work inside a Group
  exactly as they do in the outer dock; see §Palette-added widgets split.
- **Tab stacks are still allowed inside a Group**, with the same 22px chrome.
- **An emptied Group persists.** Dragging out the last widget leaves a
  drop-here placeholder; the Group closes only when the operator closes it.
- **Singleton rules stay workspace-global.** `multiInstance: false` widgets
  (Drive Controls, Settings, the replay triad) are not duplicable by placing one
  inside a Group. This is not free: both palettes must count **recursively**
  across the outer layout and every Group's inner layout, since neither dock's
  `toJSON` sees the other's panels.
- **Edge groups are still excluded** — the normal-vs-edge-group restriction in
  the callout above applies to Widget Groups too. ("Group" alone means a Widget
  Group; dockview's own groups are "tab stacks" or "edge groups".)

### Catalog seam

`dockviewComponents` is derived from `WIDGET_CATALOG` (`widgets/catalog.tsx`), and
ADR 0031 §4 forbids hardcoded shell panels, so the Group must register as a
catalog entry to exist at all — but it is a container, not a widget. `WidgetCatalogEntry`
gains `isContainer: true`; **Add Widget** filters those out and a separate **Add
Group** action instantiates them. The container's component key is
**`workspace.group`**. Two derived maps in `widgets/catalog.tsx` carry the rule:
`WIDGET_ENTRIES` (non-container entries — what both palettes offer) and
`nestedDockviewComponents` (what a Group's inner dock can render). Depth 1 is
enforced by the inner dock simply not having a `workspace.group` component.
Anything else that must distinguish a container should test `isContainer` rather
than string-match the key.

### Serialization recurses in both directions

A Group's inner `toJSON` lives in that panel's `params.layout`, invisible to the
outer `grid.root` walk. Both directions need handling:

- **Write.** The inner dock's `onDidLayoutChange` calls
  `outerPanelApi.updateParameters({ layout })`, which mutates the outer layout and
  so triggers the outer `onDidLayoutChange` autosave (`Workspace.tsx`). Without
  that hop, an inner rearrangement fires no outer event and is lost on reload —
  the outer dock has no idea anything moved.
- **Read.** `prepareLayoutForRestore` (`shell/layoutRestore.ts`) prunes panels
  whose `contentComponent` is missing from the catalog; it recurses into each
  `params.layout` and merges the inner `droppedPanels` into the same restore
  banner. Inner layouts must be pruned against `nestedDockviewComponents`, not the
  outer map, or a nested `workspace.group` survives the prune and then fails to
  render.
- **An empty inner layout is preserved, not deleted** — that is how "an emptied
  Group persists" survives a round-trip. Restore pruning must not treat an empty
  Group as garbage.

Pruning is not free of side effects: it collapses single-child branches and nulls
an empty root, so it must not run on layouts that need no pruning at all — the
no-drops case is expected to reach `fromJSON` verbatim, which is what surfaces a
genuinely corrupt layout as "Could not restore".

### Compact mode flattens Groups

`compactWorkspacePanels` (`shell/compactWorkspace.ts`) ignores the grid and
flattens `layout.panels`, so the stacking policy above is a no-op on small
screens — but a Group is a panel too, and would otherwise surface as one opaque
entry hosting a nested dock inside a mobile stack. It therefore recurses: a Group
entry is replaced by its member widgets and never rendered itself, so Groups are
invisible on touch/small screens. Consistent with §Mobile constraint. Anything
derived from the compact list (e.g. `compactMapPanelIds`) sees Group members as
ordinary panels.

### Cross-boundary drag (decided, roadmap UI3)

Each dockview instance owns its DnD scope, so dragging a widget from the outer dock
*into* a Group, or between two Groups, needs explicit `showDndOverlay`/`onDidDrop`
wiring and a shared drag payload. Groups ship first populated by their header's
"add widget" control; whole Groups drag normally in the outer dock from the start.
The deferral was safe because the DnD work is purely additive — it touches drop
handlers only, not the container, header, catalog flag, constraints, or
serialization format.

**Prerequisite invariant verified 2026-08-23.** Every widget's view state must
live in its dockview panel `params` and be fully serializable (as §Workspaces
already requires), since a cross-boundary move is remove-and-re-add with `params`
carried over:

- **Video** — clean. State is `params` (`osdPresetId`) plus a re-subscribable
  websocket topic; nothing held in a closure survives that matters.
- **Drive Controls** — clean, and takes no `params` at all: its live state is a
  module-level Zustand store, unaffected by the widget's own mount/unmount.
- **AI Chat** — clean except one accepted gap: an in-flight streaming response's
  abort handle (`abortRef`) is a local ref, lost on unmount. Dragging an AI Chat
  widget across a boundary mid-stream silently drops the client's ability to
  cancel that stream and glitches the "typing" indicator until the next
  `sessionQuery` refetch reconciles it — the stream itself keeps running and its
  result still arrives server-side. Accepted as a rare, non-data-destructive edge
  case rather than gating a generic DnD system on mid-stream detection.

**Depth 1 guard.** Today it holds only because no palette offers a container; the
drop path is a second way in, so `onDidDrop` must reject an `isContainer` payload
over a Group's overlay. Rejection happens **at drop time** (a "not-allowed" cursor
via the guard), not by blocking pickup — the drag payload doesn't know its
destination until hover, and blocking pickup would also block the legitimate case
of dragging a Group around the outer dock.

### Closing a populated Group (decided, roadmap UI2c)

The header's `×` stays destructive: it calls `outerPanelApi.close()`, which
destroys member widgets and their `params`, gated by a confirm dialog ("Close
Group and N widgets?"). No eviction path — members are not moved back to the
outer dock. Rejected: evicting members back into the outer dock's grid slot,
because the app is about to grow a Group-templates feature (below) that makes
losing a Group's *arrangement* cheap to recover from (save it as a template
first), so eviction's main benefit — not losing widget composition — is
redundant with a feature already being built.

### Group templates (roadmap UI6/UI7)

A **Group template** is a named, reusable snapshot of a Group's composition —
member widget types and their inner layout/sizes — **not** their live content
(a saved Notes template starts empty each time it's applied; content is
instance state, not template state). Stored client-side only, in a new store
separate from `WorkspaceStore` (below): the two share the same
`SerializedDockview`-subtree serialize/apply code but are different lists,
since `WorkspaceStore` already owns the whole-workspace list's lifecycle
(active pointer, default-workspace reset) and grafting a second entry *kind*
into it would force every consumer to filter by tag.

- **Save.** Triggered from the Group header menu ("Save as template"),
  alongside the existing rename/add-widget/close actions. Requires a name;
  saving under a name that already exists shows a confirm dialog ("Template
  'X' already exists — overwrite?") and overwrites the existing entry in place
  on confirm, or cancels the save on decline. No silent overwrite, no
  auto-suffixed duplicates.
- **Apply.** Always creates a brand-new Group, appended to the current tab
  with the same default placement `Add Group` already uses today — never
  overwrites an existing Group. Surfaced alongside the existing Add
  Group/Add Widget palette.
- **Delete.** Requires a confirm dialog ("Delete template 'X'? This can't be
  undone").
- **Management surface (rename, browse).** Deferred past the first slice —
  save+apply from existing menus covers the primary loop; a dedicated
  templates list/editor is follow-up work once that loop is validated.
- **Whole-workspace templates are not a separate mechanism.** The
  "generalize to whole-tab, not just Groups" instinct is already satisfied by
  `WorkspaceStore` itself — a curated/duplicated Workspace *is* a whole-layout
  template (see §Workspaces, "Curated default Workspaces"). No second store is
  needed at that level; only the Group-scoped case is new.

### Popout and Groups (decided, roadmap UI4)

- **Popping out a whole Group is intentional, supported behavior.** Verified
  2026-08-23: `addPopoutGroup` reparents the group's live DOM element into the
  new window (`popoutContainer.appendChild(group.element)`) rather than
  mounting a fresh React tree, so a Group's nested `DockviewReact` instance
  keeps running unchanged after popout — no special-casing needed.
- **A widget popping out *from inside* a Group has no dedicated action, and
  none is being built.** The two-step path — drag the widget out via UI3,
  then use the existing popout action on the outer dock — already reaches
  the same result, so a bespoke "popout this nested panel" code path would
  duplicate UI3's remove-and-re-add logic for no new capability. This makes
  UI4 depend on UI3 shipping first for that direction, even though whole-Group
  popout itself has no such dependency.
- **Non-goal: cross-window drag.** Once a Group is popped out, dragging a
  widget between that window and the main window is out of scope — the same
  category of exotic that justified deferring in-window cross-boundary drag
  (UI3) until after UI2 shipped.

## Workspaces (layout profiles)

A **Workspace** is a named saved layout (dockview `toJSON`/`fromJSON`). Persistence
goes through a `WorkspaceStore` interface:

```
interface WorkspaceStore { list(); load(id); save(id, layoutJson); resetDefault(id); remove(id); }
```

Backed by `localStorage` keyed by an operator-profile id now; swappable to a
server/per-operator backend later with **zero** widget/layout code change. No auth
is built now (consistent with requirements §No Authentication Yet).

**Per-tab active workspace.** The named-workspace *library* is shared across a
browser origin (`localStorage`), but the *active-workspace pointer* is per tab
(`sessionStorage`), so each tab/window holds a different workspace and restores it
on refresh (incl. hard refresh). See roadmap workstream W1.

**Per-widget state travels with the Workspace.** A saved Workspace restores not only
panel positions but each widget's own view state — map view/zoom and active layer
toggles, a chat widget's pinned session, replay playback position, etc. Each widget
serializes its state into its dockview panel `params`, which `toJSON` captures and
`fromJSON` rehydrates; authoritative data still lives in the data layer, so `params`
holds only view state, never a private copy of backend state.

For **Video widgets**, this split is explicit:

- shared OSD preset definitions live in persisted settings/config, not in panel params
- each Video panel stores only the selected `osdPresetId` (and future per-panel video
  view state such as `cameraId`) in its dockview params
- editing a preset in Settings updates every Video widget that references that preset,
  because widgets re-read the shared preset catalog through the data layer rather than
  storing copied preset payloads

**Curated default Workspaces ship with the app.** Beyond free-form docking, the app
provides a small set of pre-built, well-placed layouts the operator can pick from
(e.g. "Driving" = video + drive controls + telemetry; "Mission" = map + AI chat +
replay) — the "choose a polished layout" path. These are seeded `WorkspaceStore`
entries the operator can load, modify, and re-save; mobile also selects from them.
Default Workspaces are recoverable: resetting a curated default replaces its saved
layout with the shipped seed for that workspace, while custom Workspaces are not
eligible for default reset.

## Settings (VS Code-style)

Replaces the tabbed `settings.html`. Layout: top **search**, left Explorer-style
**category tree**, main **filterable parameter→value rows**. The underlying config
JSON is **unchanged** — the UI is a view/editor over the same values.

Requires a new **settings schema/metadata layer**: per setting `{ key, type
(bool/enum/number/string), label, description, default, category }`, authored by
extracting today's settings from `settings.html`/config JSON. The schema powers
search, per-type input widgets, and tree grouping. The standalone `mqtt-setup` page
folds into the Connectivity category (it is currently duplicated as both a
standalone page and a settings tab); a lightweight first-run flow is retained only
if onboarding-gated (open question).

The operator-facing workspace exposes **one** top-level Settings widget in the
palette. Heavier settings clusters such as LLM provider management and Config I/O
can still use dedicated React components internally, but they are routed
sub-views inside `SettingsWidget`, not separate addable workspace widgets.

The OSD redesign adds one more split setting surface:

- a shared **OSD** settings category manages the saved preset catalog
- `SettingsWidget` performs CRUD over that shared catalog
- `VideoWidget` applies presets independently per panel

The first milestone uses a **structured preset schema**, not a free-form overlay
builder: a preset selects from a fixed catalog of built-in runtime lines, plus
ordering, corner placement, and small readability controls. This keeps the feature
compatible with the hot-path rule and avoids inventing a client-side template
language.

Implementation rule: `VideoWidget` must obtain presets through the same shared data
layer/query surface as any other widget. It must not depend on `SettingsWidget`
being mounted, and it must not receive preset data by React prop-drilling from the
shell. Live frame and OSD text updates stay imperative (`imgRef.current.src`,
`el.textContent`) per ADR 0030.

## Mobile constraint

Video, Drive Controls (touch d-pad), Telemetry, and AI Chat work responsively. Full
free-form dockview docking is a desktop interaction model and is **not** offered on
touch/small screens; mobile uses a simplified stacked/curated layout or a chosen
Workspace. Documented limitation, not a silent gap.

## Build / serve seam

Vite output dir served by FastAPI as static assets with an SPA `index.html`
fallback for client routes; `/api` and `/ws` remain the backend contract for all
clients (web, future CLI, mobile).

Concrete seam (Slice 1): the app is mounted under **`/app`** with a `base: "/app/"`
Vite build that emits to **`gcs_server/webapp/`** (gitignored). `app.py` static-mounts
`/app/assets` and falls back any other `/app/*` to `index.html`. Dev runs the Vite
server proxying `/api` + `/ws` to the Python app.
