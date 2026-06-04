# 0021. Mission Lifecycle: Configurable Execution Modes, Flat Mission Model, And Chat-Driven Operations

Date: 2026-05-26
Status: Accepted

## Context

ADR 0002 made "AI cannot cause rover motion" a *structural* invariant. ADR 0012 made "approval is not execution" a non-negotiable map-widget invariant. Together they hard-coded a single safety stance for every build, every operator, every environment.

That stance is mandatory for real-rover use. It is friction in the 3D simulator where active development happens: two-step approval for every test mission slows iteration without adding meaningful safety. At the same time the product is gaining a persistent mission sidebar where missions can be created either manually or by AI chat and should be treated as the same kind of object after creation. A single shipped stance cannot serve both contexts.

This ADR replaces the structural framing with a configurable policy, defines the operator-facing Mission as a flat first-class entity, and specifies how AI chat drives the lifecycle.

## Decision

### 1. Three execution modes, build-time default, runtime configurable

| Mode | AI execute capability | Operator action | Use |
|---|---|---|---|
| **Strict** | `execute_mission` tool not bound to the model | Manual play button only | Real-rover default |
| **Confirm** | AI may call `arm_execution`; operator confirms via banner within N seconds (default 10 s, async) | Click `[Play]` on banner before expiry | Trusted-ops middle ground |
| **Autonomous** | AI may call `execute_mission` directly | Watch, can abort | Sim-development default |

Mode lives in **Settings → Mission Lifecycle**. Defaults: sim build → Autonomous; real-rover build → Strict. The build-time gate that enforces the real-rover default is an Open Question.

`cancel_execution` and `abort` are always bound regardless of mode. ADR 0020's `expected_controller_version` guards AI execution as a **narrow first-install gate** (implementation detail, 2026-06-01): the LLM never supplies the version (it cannot know it), so the executor captures the version observed at authorization and CAS-gates only its *first* controller install against it. The executor is the sole writer for the rest of the run, so subsequent nav-segment installs build on the version it wrote and do not re-assert. This still prevents a third party who mutated the controller between authorization and start from being silently overwritten — the safety property ADR 0020 intends.

### 2. Mission is a flat, first-class entity

- **One sidebar row = one Mission.** No parent/child, no draft/revision surfaced in the UI.
- **Fields:** `#index` (stable integer handle, never reused), `name` (editable, defaults to AI-derived summary or `"Untitled mission"`), `origin` (`manual` | `ai_chat`, mutable), `origin_chat_id` (FK or null), `created_at`, `created_by_user_id`. Internal `client_version` per ADR 0020 still tracks edit concurrency.
- **Manual and AI-chat creation produce structurally identical Missions.** CRUD applies equally to both.
- **Persistence scope:** per-user global store. The sidebar shows all of a user's Missions across chats. `origin_chat_id` is captured for future filter UI but not surfaced now.

### 3. Editing, regeneration, and AI tool surface

| Operation | Result |
|---|---|
| Manual: drag a waypoint on the map | Mutates the **Active** Mission in place. `client_version` bumps. |
| AI: `create_mission(prompt)` | New Mission row, `origin = ai_chat`. |
| AI: `clone_and_edit_mission(source_id, edits)` — **default for AI-driven changes to an existing Mission** | New Mission row seeded from source. Both rows preserved for side-by-side comparison. |
| AI: `edit_mission_in_place(mission_id, edits)` — only when the operator explicitly says "edit in place" | Mutates `mission_id`. `client_version` bumps. |
| AI: `arm_execution` / `execute_mission` / `cancel_execution` | Per § 1; first two mode-gated, last always available. |

AI-driven changes are non-destructive by default; only manual edits and explicit overrides mutate.

### 4. Three independent UI states: Visible, Selected, Active

| State | Cardinality | Controlled by | Purpose |
|---|---|---|---|
| **Visible** | 0..N | Eye icon per sidebar row | Renders on the map |
| **Selected** | 0..N | Sidebar checkbox / shift-click | Target set for batch operations |
| **Active** | 0 or 1 | Single click on a sidebar row OR a waypoint on the map | Target for single-mission gestures: drag, edit, play, chat pronouns |

**Smart bindings.** Clicking a sidebar row makes it Active and turns Visible on. A newly created mission becomes Active and Visible (but not Selected). Eye icon, checkbox, and click are otherwise independent.

**Invariant.** The Active Mission must be Visible. Hiding the Active Mission clears Active.

**Sidebar-row affordances.** A flat Mission row surfaces only operator-facing actions: click → Active (focus), eye → Visible, **edit** (per § 3, mutates in place), and **execute** (mode-gated per § 1). Execute/edit resolve to the Mission's active revision; an `executing` Mission locks both. Draft-lifecycle actions (approve / reject) are **not** on the flat row — per "draft/revision plumbing stays internal" (Consequences), they live on the draft-review surface, not the Mission list.

### 5. Chat reference resolution

Resolution order for chat-driven Mission references:

1. Explicit index — `#26`, `mission 26`
2. Exact name match
3. Fuzzy name match (AI asks for disambiguation if ambiguous)
4. Pronouns (`it`, `this`, `the mission`) → the most recent Mission with `origin_chat_id = current_chat`

### 6. Settings tab

`Settings → Mission Lifecycle` exposes:

- Execution mode (Strict / Confirm / Autonomous)
- Confirm timeout slider, 3–60 s, default 10 s (shown when mode = Confirm)
- Auto-overlay new missions (default on)
- Steal map focus when the active chat creates a mission (default on)
- Default name template for manual missions (default `"Untitled mission"`)

A settings-icon button on the map widget / mission sidebar deep-links to this tab.

## Consequences

- The structural "AI cannot cause motion" invariant from ADR 0002 becomes a configurable policy. **Shipping the default correctly per build target is now a load-bearing safety responsibility** (see Open Questions).
- ADR 0012 invariants 2, 3, 4 (no client-side mutation of executing missions, no silent overwrites, no inventing backend contracts) **survive** as cross-cutting rules. Only invariant 1 (Approval ≠ Execution) is modified: it remains true in Strict and softens in Confirm / Autonomous.
- The operator-facing concept is the Mission. Draft / revision plumbing stays internal.
- Comparison is native: regenerations and AI edits produce new rows by default; old and new stay overlayable.
- ADR 0019 (per-waypoint provenance) remains in force, orthogonal to Mission-level `origin`.
- ADR 0020 (optimistic concurrency) is used by the new tool surface — `edit_mission_in_place` bumps `client_version`; execute paths carry `expected_controller_version` (the legacy revision-execute endpoint via its client token, AI execution via the narrow first-install gate described in §1).
- Single source of truth for the lifecycle replaces content previously spread across ADRs 0002 and 0012 plus several `design.md` sections. Those `design.md` sections will follow as implementation lands; until then, the system runs effectively in Strict mode.

## Alternatives Considered

- **Keep ADR 0002 structural; add execute-after-approval as a per-request flag.** Rejected: sim ergonomics pushed back hard; the structural framing prevented iteration speed without adding sim safety.
- **Heuristic imperative-vs-interrogative classifier deciding whether AI may execute.** Rejected: fragile LLM judgment, prompt-injectable, hard to test. Mode + tool-binding is auditable. Parked as an Open Question in case the spirit returns.
- **Per-mission risk classification (low/med/high) gates execution.** Rejected: premature. One mode covers current needs with much less surface.
- **Delete ADRs 0002 and 0012 outright.** Rejected per [STYLE.md](../../STYLE.md) convention — supersede in place; numbers are never reused.
- **Renumber later ADRs to fill the gap.** Rejected — breaks references in commit messages, archived snapshots, and `design.md` links for no real gain.

## Open Questions (revisit before real-rover hardware lands)

- **Structural vs policy framing for hardware builds.** Should the real-rover build forbid Autonomous mode at build time, or just default it off?
- **Deployment-time mode gate.** Mechanism (compile flag, env var, signed config) that prevents a sim default from leaking into a hardware build.
- **Prompt-injection threat model per mode.** What an attacker controlling a tool output or document can cause in Confirm and Autonomous.
- **Audit trail.** Per-execution log of mode-at-time, triggering prompt, confirming gesture (if any).
- **Imperative-vs-interrogative classifier (revisited).** Whether it ever earns its complexity, or whether mode + tool-binding stays sufficient.
- **Sidebar filter UI.** "This chat / All / By name" — small UI add when the unfiltered view hurts.
- **Per-project / per-environment scoping.** `project_id` column with default when multi-project or sim-vs-real separation matters.
- **Delete semantics.** Soft delete, audit, undo. Keep simple now, revisit.

## Follow-Ups

- ADR 0002 → status updated to *Superseded by ADR 0021*; content preserved.
- ADR 0012 → status updated to *Superseded by ADR 0021*; content preserved (invariants 2–4 still in force per § Consequences above).
- ADR 0019 and ADR 0020 → unchanged; remain Accepted.
- Implementation of Confirm and Autonomous modes plus the flat-Mission UI is new work; `design.md` (ai-agent, gcs) will catch up incrementally as code lands.
- **2026-06-04 — `approved`/`awaiting_approval` status cleanup complete.** Both statuses removed from all Python frozensets, SQL guards, and JS sets. `approve_revision()`, `approve_revision_for_draft()`, `approve_draft()`, the REST `/approve` endpoint, and the graph approval-interrupt nodes (`request_planning_shell_approval`, `record_approval`) are deleted. New revisions initialize to `proposed`. The `approved_at` DB column is retained as a dead no-op.
