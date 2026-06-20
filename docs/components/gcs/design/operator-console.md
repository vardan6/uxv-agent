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

### Per-client WS subscription protocol (ADR 0031 §5)

`ws_manager` (`gcs_server/ws.py`) is broadcast-only today. Add per-client
subscriptions: client sends `{op:"subscribe"|"unsubscribe", topic}` (e.g.
`video/<cameraId>`); server pushes high-volume streams only to subscribers. Cheap
topics (telemetry, broker, controller) stay broadcast. A reference-counted
subscription manager in the data layer subscribes on first mounted consumer and
unsubscribes on last unmount. Snapshot/pull remains unconditional.

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
| Video Feed | yes (one per camera) | OSD overlay is a bound sub-part; WS-subscription-gated |
| Drive Controls | singleton | independent of Video; owns key capture when focused |
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
pattern). Multi-map costs: pause/throttle rendering for hidden/off-screen maps.

## Workspaces (layout profiles)

A **Workspace** is a named saved layout (dockview `toJSON`/`fromJSON`). Persistence
goes through a `WorkspaceStore` interface:

```
interface WorkspaceStore { list(); load(id); save(id, layoutJson); remove(id); }
```

Backed by `localStorage` keyed by an operator-profile id now; swappable to a
server/per-operator backend later with **zero** widget/layout code change. No auth
is built now (consistent with requirements §No Authentication Yet).

**Per-widget state travels with the Workspace.** A saved Workspace restores not only
panel positions but each widget's own view state — map view/zoom and active layer
toggles, a chat widget's pinned session, replay playback position, etc. Each widget
serializes its state into its dockview panel `params`, which `toJSON` captures and
`fromJSON` rehydrates; authoritative data still lives in the data layer, so `params`
holds only view state, never a private copy of backend state.

**Curated default Workspaces ship with the app.** Beyond free-form docking, the app
provides a small set of pre-built, well-placed layouts the operator can pick from
(e.g. "Driving" = video + drive controls + telemetry; "Mission" = map + AI chat +
replay) — the "choose a polished layout" path. These are seeded `WorkspaceStore`
entries the operator can load, modify, and re-save; mobile also selects from them.

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
