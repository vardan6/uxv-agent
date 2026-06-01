# Codex 5.5 Review — `feat/gps-master-coordinate-frame`

Date: 2026-06-01  
Scope: current branch vs `master` (`7b2ab6a` over `d413483`) plus uncommitted local edits in `gcs_server/` and repo docs.  
Review focus: bugs, gaps, implementation/docs mismatches, unimplemented promised behavior, and hardening opportunities.

---

## ⚠️ Verified Status — 2026-06-01 (Claude re-review against current working tree)

This review is **substantially stale**: most code-level findings were fixed in
uncommitted edits *after* the review (including its own "Second Round Update").
Statuses below were verified by reading the current working tree. Trust this
table over the findings text.

| Finding | Original sev | Current status | Note |
|---|---|---|---|
| Planner allow-list omits pattern/geofence tools | P0 | ✅ Fixed | Both present in `_PLANNER_TOOL_NAMES` (`planning_shell_graph.py:84`) and `_ALWAYS_ALLOWED` (`tool_registry.py:179-180`). Nit: `set_mission_geofence` listed twice in planner set |
| Existing Mission rows migrated to origin `0,0,0` | P0 | ❌ **OPEN** | Migration 009 still defaults `0.0` with no backfill; `get_origin_datum()` returns it as real `Origin` (`mission_store.py:118`); `_resolve_origin()` accepts any non-None (`mission_execution_service.py:~455`). **Highest-priority remaining item.** |
| `set_mission_geofence` doesn't bump `client_version` | P1 | ✅ Fixed | Now calls `bump_client_version` (`tool_registry.py:1145`) |
| MissionListPanel `innerHTML` XSS | P1 | ✅ Fixed | `escapeHtml()` applied to all interpolated values |
| GCS design docs describe revision/operation model | P1 | 🟡 Partial | Body updated to flat-Mission model; heading "Mission Revision List" still stale |
| Sidebar Execute uses legacy revision/export path | P1 | ❌ **OPEN** | `MapWidget.js:~402` still calls `executeMission(revision.id)`, not the BT session executor. Needs a design decision (ADR 0023). |
| `_overlay_geofence` raw `float()` crash | P2 | ✅ Fixed | Now uses tolerant `parse_geofence()` |
| MAVSDK clear ignores `mission_type` | P2 | ⚪ Unverified | Likely still open |
| Stale FENCE/RALLY stores on empty upload | P2 | ⚪ Unverified | Likely still open; needs scoped-vs-persistent decision |
| `generate_pattern_subtree` counts direct children only | P2 | ❌ Open (minor) | `tool_registry.py:1102` |
| `arm_execution` description "arm and start" | P3 | ✅ Fixed | Description updated |
| **New:** `export_mission` permissive `sole_session_draft` fallback | P1 | ❌ **OPEN** | `tool_registry.py:1229-1231` — route-hash miss can export an unrelated draft. Wrong default for rover motion. |
| **New:** route-planning docs describe local-only coord model | P2 | ❌ **OPEN** | `ai-agent/design/route-planning.md:58+` and `ai-agent/design.md` now conflict with ADR 0022 |

**Net remaining backlog (planned in `roadmap.md`):** origin `0,0,0` backfill/sentinel
(P0), export sole-draft fallback removal (P1), sidebar Execute → BT executor
decision (P1), AI-agent coordinate-frame doc sync (P2), plus minor cleanups
(pattern waypoint count, planner-set duplicate, MAVSDK typed clear, FENCE/RALLY
store scoping).

---

## Summary

Branch is directionally coherent, but not ready to land without fixes. The main correctness issues are around tool reachability, coordinate datum migration/backfill, stale Mission row versioning, and UI safety. The local geofence-display follow-up mostly matches the intended doc update, but it also exposes some stale design text and a few robustness gaps.

Verification performed:

- `rtk node --check static/map/MapWidget.js static/map/ui/BasemapPanel.js static/map/ui/MissionListPanel.js static/settings.js` passed.
- `rtk python3 -m compileall -q ai app.py runtime.py config.py` passed.
- No SITL/browser smoke was run.

## Findings

### P0 — Phase 4/5 AI tools are registered but unreachable from the planner loop

Evidence:

- `ai/tool_registry.py` registers `generate_pattern_subtree` and `set_mission_geofence` as planning tools.
- `ai/planning_shell_graph.py:84` defines `_PLANNER_TOOL_NAMES`, but the allow-list only includes route/reference/propose tools. It omits `generate_pattern_subtree` and `set_mission_geofence`.
- `ai/agent_loop.py:503` filters bound tools by `allowed_names`, so omitted tools never reach the model.

Impact:

- The roadmap/doc claim that AI tools can author pattern generators and geofences is false for `/plan`.
- The tool descriptions exist, but the planner cannot call them, so Phase 4/5 AI authoring is only partially implemented.

Suggested fix:

- Add `generate_pattern_subtree` and `set_mission_geofence` to `_PLANNER_TOOL_NAMES`.
- Update the planner system prompt to mention when to call them.
- Add a regression test or direct tool-binding assertion that the planner loop exposes the expected tools.

### P0 — Existing Mission rows migrated to origin `0,0,0` will render/execute in the wrong coordinate frame

Evidence:

- Migration 009 adds `origin_lat`, `origin_lon`, `origin_alt` with default `0.0` (`ai/migrations.py:180`).
- `MissionStore.get_origin_datum()` always returns an `Origin`, even if the stored datum is `0,0,0` (`ai/mission_store.py:118`).
- `MissionExecutionService._resolve_origin()` accepts any non-`None` resolver result and therefore will not fall back to the scene origin (`ai/mission_execution_service.py:453`).

Impact:

- Missions created before migration 009 get a null-island datum unless explicitly rewritten.
- Overlay derivation, basemap display, client editing, export, and executor geofence checks can all use the wrong local/WGS84 conversion for those rows.
- This contradicts ADR 0022’s GPS-master frame goal and the docs’ claim that the server derives from the per-Mission origin without drift.

Suggested fix:

- Backfill existing `missions` origin columns from `load_scene_origin()` during migration 009, or treat `0,0,0` as “unseeded” and fall back to scene origin in the resolver.
- Prefer an explicit nullable datum or sentinel flag over silently using `0,0,0` as a real origin.
- Add a migration test for an existing mission row bridged to WGS84 waypoints.

### P1 — `set_mission_geofence` AI tool does not bump the flat Mission `client_version`

Evidence:

- REST geofence path appends a fenced revision then calls `mission_store.bump_client_version()` (`app.py:1813`).
- AI tool path resolves the mission and calls `service.set_operation_geofence()` but returns directly without bumping the flat Mission row (`ai/tool_registry.py:1151`).
- The planning bridge bumps client version for appended revisions in `store_draft` (`ai/planning_shell_graph.py:983`).

Impact:

- The same logical edit has different Mission-row version semantics depending on whether it came from the basemap or the AI tool.
- Flat mission consumers relying on `client_version`/`updated_at` may miss that the Mission changed.
- This is an implementation mismatch with the ADR 0021/0020-style “edit in place bumps version” behavior already used elsewhere.

Suggested fix:

- After successful `service.set_operation_geofence()`, call `store.bump_client_version(clean_id)` in `_set_mission_geofence()`.
- Return `mission_id` and any bump error consistently with the REST route.

### P1 — Mission list row rendering injects unescaped backend data into `innerHTML`

Evidence:

- `MissionListPanel.renderMissions()` assigns a full template string to `innerHTML` (`static/map/ui/MissionListPanel.js:142`).
- `missionRowMarkup()` interpolates `missionRow.name`, `missionRow.id`, and other row values into HTML/text/attribute positions without escaping (`static/map/ui/MissionListPanel.js:49`).
- Mission names come from user/LLM/operator-created mission content via `mapMissionsForList()` (`static/map/missionListLogic.js:22`).

Impact:

- A mission name containing HTML can execute script or break row markup on `/ai`.
- The AI planner can create Mission names, so this is not only a local operator-input concern.

Suggested fix:

- Escape all interpolated values in `missionRowMarkup()`, or build DOM nodes with `textContent`/`dataset` instead of HTML strings.
- Add a small pure test for a mission name like `<img src=x onerror=alert(1)>`.

### P1 — GCS design docs still describe the old revision/operation mission-list model

Evidence:

- `docs/components/gcs/design.md:148` says `MissionListPanel.js` is “Mission list grouped by operation”.
- `docs/components/gcs/design/map-widget.md:62` still defines “Mission Revision List” as revision rows grouped by `operation_id`.
- Current implementation is flat Mission rows keyed by Mission id, with revision/operation internal behind the row (`static/map/ui/MissionListPanel.js:1`, `static/map/MapWidget.js:109`).

Impact:

- Future agents will make wrong decisions about UI state and backend contracts if they read the canonical design docs.
- This directly conflicts with ADR 0021’s “one row = one Mission” implementation.

Suggested fix:

- Update the GCS map-widget doc from “Mission Revision List” to “Flat Mission List”.
- Replace operation-grouping rules with Mission id, Active revision resolution, Selected/Visible/Active semantics, and batch selection behavior.

### P1 — Sidebar Execute still uses the legacy revision cutover path, not the behavior-tree execution/session path

Evidence:

- `MapWidget._handleExecuteRequest()` resolves a mission to active revision and calls `executeMission(revisionId)` (`static/map/MapWidget.js:396`).
- `missionApi.executeMission()` posts to `/api/ai/mission-revisions/{revision_id}/execute` (`static/map/data/missionApi.js:123`).
- That endpoint calls `MissionExecutionService.execute_revision()`, which requires an exported `.plan` file and installs that revision, not `MissionExecutionSessions` / `MissionExecutor` (`app.py:2644`).
- The behavior-tree/session execution path is only exposed through AI tools and confirm endpoints (`ai/tool_registry.py:1425`, `app.py:2567`).

Impact:

- A tree mission with multiple nav leaves / conditions / loops can be shown as executable in the sidebar but the UI action does not run the server-side behavior-tree executor.
- Confirm/Autonomous mode semantics are inconsistent between chat-driven execution and the visible play button.
- Docs describe `MapWidget` as the live vehicle view during mission execution, but the button is still a legacy cutover action.

Suggested fix:

- Decide whether the sidebar Play button is legacy “upload linear plan” or lifecycle “run Mission”. If it is lifecycle, add mission-keyed REST endpoints that call the same execution-session path and respect `mission_lifecycle.execution_mode`.
- If legacy cutover remains intentionally separate, rename/label the button and docs so it does not imply behavior-tree execution.

### P2 — Local geofence overlay builder can 500 on malformed stored fence values

Evidence:

- `_overlay_geofence()` converts `float(v["lat"])` / `float(v["lon"])` inside list comprehensions without catching `TypeError`/`ValueError` (`ai/mission_execution_service.py:306`).
- The safety parser already has tolerant coercion/drop behavior in `mission_safety.parse_geofence()` (`ai/mission_safety.py:112`).

Impact:

- A corrupt or legacy stored `geofence` can make the overlay endpoint fail, even though malformed fence entries should be dropped/fail-closed.

Suggested fix:

- Reuse `parse_geofence()` in `_overlay_geofence()` and return `None` unless `fence.is_usable`.
- Preserve rally `alt` in overlay if needed by UI/tooltips.

### P2 — MAVSDK clear ignores `mission_type`

Evidence:

- `MavsdkMissionClient.clear_mission_items(self, *, mission_type=0)` always calls `clear_mission()` (`ai/controller_mission_adapter.py:557`).
- The shared client interface includes `mission_type` for main mission, FENCE, and RALLY stores.

Impact:

- The method signature implies typed clearing, but MAVSDK implementation clears only the main mission store.
- If future code tries to clear stale FENCE/RALLY stores through this seam, it will silently do the wrong thing.

Suggested fix:

- Either implement typed clear where MAVSDK supports it or explicitly reject non-zero `mission_type` with `ControllerMissionAdapterError`.

### P2 — Stored FENCE/RALLY upload leaves stale stores when a new fence has no rally points

Evidence:

- `MavlinkControllerMissionAdapter.upload_geofence()` skips mission types with empty item lists (`ai/controller_mission_adapter.py:811`).
- The comment says empty stores are left untouched.

Impact:

- If a previous run uploaded rally points and the current mission has none, old rally points may remain authoritative on the controller.
- That violates the intuitive “mission fence upload represents the current mission’s fence/rally state” contract.

Suggested fix:

- For each authoritative store (FENCE and RALLY), clear it when the current mission has no items, or document that rally points are persistent site configuration rather than Mission-scoped.

### P2 — `generate_pattern_subtree` waypoint count is wrong for nested/multi-node outputs

Evidence:

- `_generate_pattern_subtree()` computes `leaves = node.children or [node]` and sums direct children waypoint counts (`ai/tool_registry.py:1102`).
- This only works for the current shallow pattern shape and will report `0` for nested sequences/loops even though the behavior-tree model supports nesting.

Impact:

- The tool response can under-report generated waypoints as pattern generators become more tree-shaped.

Suggested fix:

- Reuse `flatten_navigable_segments()` from `mission_tree.py` or add a recursive waypoint counter.

### P3 — Tool description for `arm_execution` says “arm and start”, but implementation only arms and opens the confirm window

Evidence:

- Tool description at `ai/tool_registry.py:482` says “arm and start running”.
- Handler `_arm_execution()` calls `sessions.arm_confirm()` and returns; actual start happens on `/api/ai/execution/confirm` (`ai/tool_registry.py:1425`).

Impact:

- This can mislead the model and operators during Confirm mode. It is not a runtime bug because the implementation is safer than the description.

Suggested fix:

- Change description to “arm and request operator confirmation; starts only after banner [Play]”.

## Implementation Gaps vs Docs / Roadmap

- AI pattern authoring is not fully implemented until `generate_pattern_subtree` is reachable from the planner and prompted.
- AI geofence authoring is not fully implemented until `set_mission_geofence` is reachable and bumps Mission row version like REST.
- Flat Mission list docs are not updated consistently; docs still say revision rows grouped by operation.
- Behavior-tree execution is implemented for AI tools, but the visible MapWidget Play button remains a revision/export cutover path.
- Per-Mission coordinate frame exists, but migrated existing Missions are not safely seeded/backfilled.

## Enhancements Worth Doing Before Merge

- Add a small binding/unit test around planner tool visibility: `_PLANNER_TOOL_NAMES` should include all intended planning tools.
- Add a migration/backfill test for pre-existing Mission rows after migration 009.
- Add frontend escaping tests for `missionRowMarkup()`.
- Add a backend overlay test for stored geofence rendering and malformed geofence tolerance.
- Decide and document whether controller FENCE/RALLY stores are Mission-scoped or persistent site-scoped.

## Local Changes Review

The uncommitted geofence-display change mostly matches the doc update:

- Overlay payload now carries `origin`, WGS84 point fields, and optional `geofence`.
- `BasemapPanel` renders saved fence polygon/rally points separately from the in-progress sketch.
- ResizeObserver and CSS resize support are reasonable and passed `node --check`.

Local-change caveats:

- `_overlay_geofence()` should use tolerant parsing instead of raw `float()` comprehensions.
- The doc update is incomplete because nearby map-widget docs still describe the old revision-list model.
- The UI displays rally points but the API wrapper does not expose authoring rally points from the basemap; that is fine if intentionally deferred, but should be stated if rally authoring is expected.


## Second Round Update — 2026-06-01

Scope of this pass: current `feat/gps-master-coordinate-frame` branch vs `master` plus the newer uncommitted implementation edits after the first review. The branch commit set is still `7b2ab6a` over `d413483`; local changes now include `ai/tool_registry.py` export-route recovery work in addition to the stored-geofence basemap display and resizable map widget edits.

### Status Changes Since First Pass

- Still open: planner-loop allow-list still omits `generate_pattern_subtree` and `set_mission_geofence` from `_PLANNER_TOOL_NAMES` (`ai/planning_shell_graph.py:84`), even though `ToolRegistry` now lists them in `_ALWAYS_ALLOWED_TOOL_NAMES` (`ai/tool_registry.py:179`). The plain chat/tool manifest may show them, but `/plan` filters through the separate planner allow-list at `ai/planning_shell_graph.py:1238` + `ai/agent_loop.py:503`, so the original P0 remains valid.
- Still open: migrated Mission origin datum still defaults to `0.0` and `MissionStore.get_origin_datum()` still returns that as a real `Origin` (`ai/migrations.py:216`, `ai/mission_store.py:118`). The P0 coordinate-frame migration risk remains valid.
- Still open: `set_mission_geofence` still returns `service.set_operation_geofence(...)` directly and does not bump the flat Mission row (`ai/tool_registry.py:1151`). The P1 client-version mismatch remains valid.
- Still open: `MissionListPanel` still builds row HTML through unescaped template strings and assigns `innerHTML` (`static/map/ui/MissionListPanel.js:49`, `static/map/ui/MissionListPanel.js:142`). The P1 XSS risk remains valid.
- Partially fixed: GCS map-widget docs were updated for WGS84 basemap and stored geofence display, but the old “Mission Revision List” / operation grouping section still remains (`docs/components/gcs/design/map-widget.md:62`). The docs mismatch is reduced, not closed.
- Still open: sidebar Execute still posts to the legacy revision execution endpoint (`static/map/MapWidget.js:402`, `static/map/data/missionApi.js:144`) rather than the behavior-tree/session execution path. The P1 execution-path mismatch remains valid.
- Still open: `_overlay_geofence()` still uses raw `float(...)` list comprehensions and raw `min_alt`/`max_alt` conversions without a tolerant parse wrapper (`ai/mission_execution_service.py:305`, `ai/mission_execution_service.py:318`). The P2 malformed-geofence overlay crash remains valid.
- Still open: MAVSDK typed clear and stale FENCE/RALLY-store behavior are unchanged (`ai/controller_mission_adapter.py:557`, `ai/controller_mission_adapter.py:811`).
- Still open: `generate_pattern_subtree` still counts only direct children (`ai/tool_registry.py:1102`).
- Still open: `arm_execution` description still says “arm and start running” while implementation only arms and waits for banner confirmation (`ai/tool_registry.py:477`, `ai/tool_registry.py:1499`).

### New Finding — P1: `export_mission` route-hash recovery can export the wrong draft

Evidence:

- The new `_resolve_export_draft()` correctly tries an exact draft id first, then matches a 12-char route hash against stored `route_artifacts` (`ai/tool_registry.py:1221`, `ai/tool_registry.py:1228`).
- If no route-artifact hash matches, it falls back to `sole_session_draft` whenever there is exactly one non-rejected draft in the session (`ai/tool_registry.py:1236`).
- “Exportable” is defined as `status != "rejected"` (`ai/tool_registry.py:1237`), which includes `draft`, `awaiting_approval`, `needs_clarification`, `validation_failed`, `approved`, `exported`, and `superseded` under the draft service’s status model (`ai/mission_draft_service.py:12`).

Impact:

- If the model passes a route hash from a route tool and the current session happens to have exactly one unrelated approved/exported draft, `export_mission` can export that unrelated draft instead of rejecting the bad id.
- If the sole draft is unapproved, the exporter rejects later, but the error no longer clearly says “this is a route_hash, not a draft_id”; it silently resolved to `sole_session_draft` first.
- For rover motion, a permissive fallback on an identifier mismatch is the wrong default. Exact id or exact route-artifact hash match should be required.

Suggested fix:

- Remove the `sole_session_draft` fallback, or make it opt-in only when the sole draft has a matching route artifact fingerprint.
- If a route hash does not match any `route_artifacts`, return the directed route-hash error with `available_drafts`.
- If a fallback is retained, restrict it to `approved`/`exported` and include a hard warning requiring explicit retry with the resolved draft id before writing a `.plan`.

### New Finding — P2: AI-agent route-planning docs still describe the old local-only coordinate model

Evidence:

- `docs/components/ai-agent/design/route-planning.md:62` says export performs local-to-geo projection from the terrain manifest georeference.
- `docs/components/ai-agent/design/route-planning.md:66` says planner output, revision storage, and map rendering all use local scene metres and “nothing upstream of the exporter deals in lat/lon.”
- `docs/components/ai-agent/design.md:669` repeats the old export-only local-to-geo projection statement.
- Current code and updated GCS map-widget docs now carry WGS84 truth through stored mission content and overlay payloads (`ai/mission_execution_service.py:185`, `docs/components/gcs/design/map-widget.md:50`).

Impact:

- The canonical AI-agent docs now conflict with ADR 0022 and the implemented storage/export path.
- Future changes to route tools or exporter code could accidentally reintroduce local-only storage because the route-planning design doc still says that is the intended contract.

Suggested fix:

- Update `docs/components/ai-agent/design/route-planning.md` and the matching section in `docs/components/ai-agent/design.md` to say WGS84 is stored truth, local metres are derived for scene rendering, and export reads WGS84 directly with local projection only as a legacy fallback.
- Mention per-Mission origin datum instead of only the terrain scene manifest georeference.

### New Local-Change Notes

- The stored-geofence basemap display implementation is useful but should reuse `parse_geofence()` before merge. The backend already has the tolerant, fail-closed parser; keeping a separate raw-float overlay parser creates a needless crash surface.
- The new vertical resize implementation is mechanically reasonable: `ResizeObserver` is disconnected on destroy, and `invalidateSize()` now forwards to `BasemapPanel`. No new functional issue found in that slice.
- The route-hash tool-description improvements are useful and directly address likely model misuse, but the permissive fallback undermines the safety of the fix.

### Second-Pass Verification

- Re-read local diffs and cited code paths.
- Rechecked the previous findings against current code.
- Syntax verification will be rerun after this document update.

---

## Follow-up Backlog (to fold into `roadmap.md`) — 2026-06-01

Derived from the verified-status table above. Sequenced by risk. "Plan only"
this session — no code changes made. Mirror these as roadmap slices once the
roadmap is updated.

### Slice A — P0: Per-Mission origin `0,0,0` safety (coordinate-frame correctness, ADR 0022)
- Treat stored origin `0,0,0` as **unseeded** rather than a real datum.
- Either backfill `missions.origin_lat/lon/alt` from `load_scene_origin()` in
  migration 009, or have `_resolve_origin()` fall back to the scene origin when
  the stored datum is the null-island sentinel.
- Prefer an explicit nullable datum / sentinel flag over silently using `0,0,0`.
- Touch points: `ai/migrations.py` (009), `ai/mission_store.py:get_origin_datum`,
  `ai/mission_execution_service.py:_resolve_origin`.
- Acceptance: a pre-009 mission bridges to WGS84 using the scene origin, not null island.

### Slice B — P1: Remove permissive `export_mission` `sole_session_draft` fallback
- On a route-hash miss, return the directed route-hash error with
  `available_drafts` instead of resolving to the only non-rejected draft.
- If any fallback is kept, restrict to `approved`/`exported` and require explicit
  retry with the resolved draft id before writing a `.plan`.
- Touch points: `ai/tool_registry.py:_resolve_export_draft` (~1221-1237).
- Acceptance: bad route-hash never silently exports an unrelated draft.

### Slice C — P1: Sidebar Execute path decision (execution-model unification, ADR 0023)
- Decide: is the sidebar Play button legacy "upload linear plan", or lifecycle
  "run Mission" via the behavior-tree session executor?
- If lifecycle: add mission-keyed REST endpoints calling the same execution-session
  path, respecting `mission_lifecycle.execution_mode`.
- If legacy stays separate: relabel button + docs so it doesn't imply BT execution.
- Touch points: `static/map/MapWidget.js:_handleExecuteRequest`,
  `static/map/data/missionApi.js`, `app.py` execute routes.
- Note: this likely warrants an ADR note/update rather than a silent code change.

### Slice D — P2: Sync AI-agent coordinate-frame docs with ADR 0022
- Update `docs/components/ai-agent/design/route-planning.md` and the matching
  section in `docs/components/ai-agent/design.md`: WGS84 is stored truth, local
  metres are derived for scene rendering, export reads WGS84 directly (local
  projection only as legacy fallback); reference per-Mission origin datum.

### Slice E — Minor cleanups (batch)
- De-duplicate `set_mission_geofence` in `_PLANNER_TOOL_NAMES`
  (`ai/planning_shell_graph.py`).
- Fix GCS map-widget doc heading "Mission Revision List" → "Flat Mission List".
- `generate_pattern_subtree` recursive waypoint count (reuse
  `flatten_navigable_segments()`), `ai/tool_registry.py:~1102`.
- MAVSDK typed clear: implement or reject non-zero `mission_type`
  (`ai/controller_mission_adapter.py:557`).
- Decide + document FENCE/RALLY store scoping (Mission-scoped vs persistent site
  config); clear stale stores on empty upload if Mission-scoped
  (`ai/controller_mission_adapter.py:811`).
