# ADR 0030 — Greenfield Operator Console Frontend (Vite + TypeScript + React + dockview)

**Status:** Accepted
**Date:** 2026-06-21
**Supersedes (frontend only):** the hand-written vanilla ES-module + 150 KB
`style.css` browser frontend under `gcs_server/static/`. The Python backend is
**not** changed by this ADR (see [ADR 0031](./0031-headless-full-architecture-and-frontend-data-layer.md)).

## Context

The browser frontend is six hand-written vanilla-JS pages (`index.html`/`app.js`,
`ai.js` ~152 KB, `replay.js` ~57 KB, `settings.js` ~82 KB, `mqtt-setup`,
`mission-console`) plus ~150 KB of bespoke `style.css` theming, served as static
files with no build step. The operator wants a flexible, IDE-grade widget
workspace: move any widget anywhere, snap/dock to any edge, split, tab, float,
and **pop widgets out into separate OS windows** (e.g. a minimal video or drive
window draggable to another monitor), with saved/restored layouts. Building that
window-manager by hand on the existing vanilla stack is impractical.

Two paths were weighed:

- **Plan B (rejected for this goal):** keep vanilla, add `dockview-core` from CDN,
  componentize panels by hand. Lower effort, no build step, but no type safety, no
  component model, and the heavy pages (`ai.js`, `settings.js`) stay hand-managed.
- **Plan A (accepted):** a clean greenfield rewrite on a modern stack.

The operator explicitly chose "best of the best" for long-term functionality and
accepted the rewrite cost, mitigated by a frozen demo fork (below).

## Decision

Rebuild the frontend greenfield with:

- **Vite + TypeScript + React** — build tooling, type safety, component model.
- **dockview-react** — docking/grid/snap/split/tabs, **floating groups**,
  **popout windows** (separate OS window, draggable across monitors), and
  `toJSON`/`fromJSON` layout persistence. Chosen over golden-layout (unmaintained
  ~4 yr), flexlayout-react and rc-dock (low adoption). flexlayout-react is a real
  contender — it *does* support new-browser-window popout (`enablePopout`) and JSON
  serialization (`model.toJson()`) — so the choice is not "the only one that can
  popout." dockview wins on fit for the **requested IDE-style free-form floating
  group model**, the maturity of its React binding (its flagship target), active
  docs, and a vanilla `dockview-core` escape hatch that lets hot-path widgets (the
  existing `MapWidget`) mount without a React rewrite. dockview is MIT and actively
  maintained.

  **Edge-group caveat (dockview):** dockview distinguishes normal docked groups
  from **edge groups** (persistent panels anchored to a workspace edge). Per
  dockview's docs, edge groups *cannot* be maximized or converted into floating /
  popout windows. Widgets that must float or pop out (video, drive) live in normal
  docked groups; edge groups are reserved for persistent peripheral surfaces (e.g.
  a status rail). The "dock to any edge" language in requirements/design refers to
  normal edge-snapping, not edge groups.
- **shadcn/ui + Tailwind** — design language. The existing custom theme system and
  `style.css` are **deleted, not ported**.
- **TanStack Query** (server/domain state), **Zustand** (client/runtime state),
  **TanStack Router** (typed routing), **Vitest + Playwright** (tests; Playwright
  already vendored in `.venv`).
- **Serving:** Vite builds to a static dir served by the Python app with an SPA
  fallback; dev uses the Vite dev server proxying `/api` + `/ws` to Python.

### Migration is in-place big-bang, made safe by a frozen fork

Rather than a strangler that runs old and new in one repo, demo safety comes from
a **full filesystem fork** of the project (code + data + DBs + venv + config) kept
outside the repo (`../remote-rover-demo-backup/`) and demoed from `master`. The
fork physically isolates the data/schema, so the in-place rewrite is free to
change DBs and config here. Work lands on branch `feat/greenfield-webapp`.

### React is correct *despite* being weaker at high-frequency rendering

React re-renders + VDOM-diffs where Solid/Svelte write the DOM node directly, so
React is measurably slower for high-frequency updates (telemetry OSD, video
frames, live map markers). This is accepted because:

1. The weakness is confined to a few **hot paths that must bypass React anyway** —
   video frame → `imgRef.current.src`, OSD lines → `el.textContent` via refs, map
   markers → Leaflet's imperative API (the existing vanilla `MapWidget` already
   works this way and can be hosted inside a dockview panel untouched).
2. Switching to Solid/Svelte would sacrifice dockview-react maturity — the layout
   engine is the centerpiece, and React is its flagship binding.

Architectural rule (enforced in design): **high-frequency runtime streams bypass
React's render cycle via refs/imperative APIs; React owns only the layout shell
and low-frequency UI.**

## Consequences

- A Node/Vite build pipeline enters a project that previously shipped zero Node.
- Six pages migrate incrementally; the Mission Console is the flagship first
  milestone (see `roadmap.md`). Until a page is rebuilt it is demoed from the fork.
- The bespoke theme system is lost and rebuilt on shadcn/Tailwind tokens.
- Widget/layout decisions, data layer, and window-aware popout rules are specified
  in [`docs/components/gcs/design/operator-console.md`](../../components/gcs/design/operator-console.md).
- Mobile gets a constrained experience: full free-form docking is desktop-only
  (see ADR 0031 and GCS requirements §Operator Console).
