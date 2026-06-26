# Legacy UI Inventory & Gap Analysis

Method and rollup for inventorying every widget of the **old** GCS UI and deciding
what carries forward into the **new** greenfield operator console.

- **Source (what we inventory):** `gcs_server/static/` — the original multi-page
  vanilla-JS app (full source, committed, served at `/`, `/ai`, `/mission-console`,
  `/replay`, `/settings`, `/mqtt-setup`). This is the authoritative baseline.
- **Target (what we fill in):** `frontend/` — the greenfield React/TS widget
  workspace. See [../design/operator-console.md](../design/operator-console.md),
  [ADR 0030](../../../cross-cutting/decisions/0030-greenfield-operator-console-frontend.md),
  [ADR 0031](../../../cross-cutting/decisions/0031-headless-full-architecture-and-frontend-data-layer.md).
- **Not a source:** `gcs_server/webapp/` (the `/app` "Operator Console" bundle) — a
  newer modernization attempt with no source in-repo (minified only). Ignored for
  inventory; if it turns out to have polished behavior `static/` lacks, capture that
  one item ad hoc.

Why this exists: the greenfield was built from zero, so many polished behaviors from
the old app simply don't exist yet. This inventory makes the gap explicit and
decidable, widget by widget, instead of discovering omissions by accident.

## Unit & naming

Every **node and leaf** of the UI tree is a row — not only leaves. Node rows give a
higher-level mapping that simplifies lookup and cascades decisions. The row `id`
**is** its dotted path, so hierarchy is readable from the name:

```
ai
ai.composer
ai.composer.input            (leaf)
ai.composer.actions.run-mode (node)
ai.composer.actions.run-mode.agent (leaf)
```

A `kind` column marks `node` vs `leaf`. Mapping is **top-down** (page → region →
component → leaf). **Node decisions cascade** to their leaves unless a leaf overrides
— so a whole component can be `Drop`/`Rebuild` in one call instead of per-button.

## Schema (per page)

Each page file has two parts.

### 1. Decision table (scannable)

Column order — Target sits after the status columns, right before Decision:

```
id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes
```

- `type` — button / input / textarea / select / toggle / icon / label / pill / panel / dialog / listbox …
- `text` — visible label / placeholder / pill text.
- `behavior / data` — what it does on interact (action, state change, shortcut) and
  which API/WS field or endpoint drives it.
- `planned?` — **yes** (with link to where) / **no** / **unsure: <detail>**.
  Pre-filled by searching `roadmap.md`, `operator-console.md`, and the ADRs.
- `implemented?` — **yes** / **partial: <what's missing>** / **no**.
  Pre-filled by searching `frontend/src/`.
- `target` — where it lands in the `frontend/` catalog (filled during Pass B).
- `decision` — one of the vocabulary below.
- `notes` — rationale / open questions.

### 2. Style appendix (lossless, keyed by `id`)

Full fidelity on the dimensions that cost the most time — **colors, spacing,
positions** — recorded by the layer that owns each property, with the source line:

- **Node rows carry layout:** display (flex/grid), direction, gap/spacing, padding,
  margin, alignment, position, size/min/max, overflow, responsive rules.
- **Leaf rows carry appearance:** color (fg/bg/border), typography (size/weight/
  line-height), radius, icon, box (size/padding), states (hover/active/disabled/focus).
- **Every row** ends with `@ style.css:<line>` (and class) as a lossless backstop.

A button's spacing lives once on its parent flex container, not copied onto every
sibling. This is "full fidelity, no duplication."

## Decision vocabulary

| Decision | Meaning |
|----------|---------|
| **Rebuild** | Reimplement this widget in React in the new app. Default for missing things. |
| **Embed** | Host the existing vanilla code as-is inside a panel, no rewrite (e.g. MapWidget). |
| **Redesign** | Bring the capability forward but change its shape/UX — not a 1:1 copy. |
| **Keep** | Already adequate in the new app; leave it. |
| **Drop** | Intentionally exclude — not relevant to the new app. |
| **Defer** | Will rebuild, but later — not this round. |

Per-row progress (not-started / in-progress / done) is tracked in the rollup below,
not in the per-page tables.

## Workflow

- **Pass A — Extraction (mechanical).** Parse each `static/` page's DOM-building code
  and `style.css`; emit the node+leaf rows + style appendix. Derived from source, so
  coverage is complete by construction. `planned?` / `implemented?` pre-filled.
- **Pass B — Mapping & decision (review).** Page by page, fill `target` and
  `decision`; node decisions cascade. Pure judgment, no transcription.

Constraint: all reads from the working tree — **no branch switching** (the greenfield
`frontend/` is uncommitted; `static/` is identical on `master` and this branch).

## Rollup — per-page status

One file per source page. Status reflects Pass A (extracted) and Pass B (decided).

| Page | File | Pass A | Pass B | Notes |
|------|------|--------|--------|-------|
| AI chat | `ai.md` | ✓ | ✓ | Flagged most incomplete in new app; ~50 node/leaf rows + style appendix |
| Mission console | `mission-console.md` | ✓ | ✓ | Composite re-mount: AI chat shell (=`ai.md`) + Map (`map.md`) + unique replay-sessions sidebar; ~24 rows. Key gap: replay selection is inert (no map/playback wiring) |
| Map (sub-panels) | `map.md` | ✓ | ✓ | ~80 node/leaf rows across MapWidget + 14 UI panels + layers. **Already Embedded** in new app (`MapWidgetPanel.tsx` imports `static/map/index.js`); gap is wiring (sessionId/statusBar/list-side), not re-code |
| Replay | `replay.md` | ✓ | ✓ | Standalone replay workstation (own Leaflet map, scene/geo, transport); ~60 rows. Sidebar → Rebuild/`ReplaySessionsWidget.tsx`; Map → Redesign/`MapWidgetPanel.tsx`; Transport → Rebuild/`ReplayControlsWidget.tsx`; Telemetry → Redesign/`TelemetryWidget.tsx`; Records → Defer |
| Settings | `settings.md` | ✓ | ✓ | 8 tabs; ~110 node/leaf rows. Shell/tabs → Redesign/`SettingsWidget.tsx` (VS-Code-style tree). Conn/Video/Appear/Mission/AI/RAG → Rebuild/`SettingsWidget.tsx`. LLM provider+routing → Redesign/`LLMProviderWidget.tsx` as a routed Settings sub-view. Config I/O → Redesign/`ConfigIOWidget.tsx` as a routed Settings sub-view. mqtt-setup folds into Connectivity |
| Dashboard / index | `dashboard.md` | ✓ | ✓ | Original single-screen 3-panel operator view (Video+OSD / Controls+Connection d-pad / Telemetry stat sheet); ~40 rows + shared `common.js` header/nav/intro shell (inventoried once here). Panels map to built widgets (`VideoWidget`/`DriveControlsWidget`/`TelemetryWidget`); key gaps = video **OSD overlay** (absent in VideoWidget) + **connection-indicator** broker/rover pills (no panel in new app). No map module on this page |
| MQTT setup | `mqtt-setup.md` | ✓ | ✓ | 1 panel, 9 form fields (8 text/number + 1 select), broker pill, status banner; folds into Settings → Connectivity per operator-console.md:134–137. Decision: Drop standalone page |
