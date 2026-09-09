# Settings page inventory — `frontend-vanilla/settings.html` + `frontend-vanilla/settings.js`

Pass A extraction (mechanical). Source: `frontend-vanilla/settings.html`
(663 lines), `frontend-vanilla/settings.js` (2,009 lines), styles in
`frontend-vanilla/style.css`. Target app: `frontend/` — **no settings widget,
store, route, or schema layer exists yet**; present widgets are
`AIChatWidget.tsx`, `MapWidgetPanel.tsx`, `ClockWidget`, `DriveControlsWidget`,
`NotesWidget`, `TelemetryWidget`, `VideoWidget`.

**This page is a tabbed settings workstation, not a re-mount.** A single
`?tab=` query param drives eight client-side panes (Connectivity, Video,
Appearance, Mission Lifecycle, AI Settings, Add LLM Provider, RAG, Config I/O);
`renderTabs()` shows/hides `.settings-pane` sections, `bindTabs()` rewrites the URL
via `history.replaceState` and reacts to `popstate`. Almost all DOM is **static
HTML**; the dynamic leaves are three rendered regions — the **LLM provider table**
(`renderProviderList`, sortable, per-row action buttons), the **model-routing
list** (`renderRoutingList` + `renderFallbackEditor`), the **RAG model select**
(`renderRagModelSelect`) — plus the AI **browser-voice option list**
(`populateAiVoiceOptions`). Events bind via `addEventListener` in `bind*()`
functions and two **delegated** click/change handlers on the provider/routing
containers (`data-llm-action`, `data-llm-sort`, `data-routing-*`,
`data-fallback-*`).

`planned?` / `implemented?` pre-filled. Pass B decisions filled below.

**Pre-fill key.** `planned?`: the new design doc names this whole page as a planned
rebuild — [operator-console.md §"Settings (VS Code-style)"](../design/operator-console.md)
(line 125): *"Replaces the tabbed `settings.html`. Layout: top search, left
Explorer-style category tree, main filterable parameter→value rows … Requires a
new settings schema/metadata layer … authored by extracting today's settings from
`settings.html`/config JSON. The standalone `mqtt-setup` page folds into the
Connectivity category."* `roadmap.md:151` lists *"Settings VS-Code rebuild + schema
layer"* as **Later (not yet sliced)**. So node/leaf rows read
**yes (Settings VS-Code rebuild, operator-console.md:125; roadmap.md:151)**;
Connectivity rows additionally carry the **mqtt-setup fold** note
(operator-console.md:135). The page deliberately keeps the **config JSON
unchanged** (operator-console.md:129) — so every backend endpoint below carries
forward; only the *presentation* changes (tabbed forms → schema-driven rows).
`implemented?`: searched `frontend/src/` for `settings`/`llm`/`routing`/
`mqtt-config`/`video-mode`/`ai-settings`/`mission-lifecycle`/`rag`/`theme` — **no
hits**; there is no settings widget in `frontend/src/widgets/`, no settings store
in `frontend/src/data/`, and no schema layer. So every row is **no**. (AI TTS
settings here are the persistence side of the `ai.md` TTS gap — also unbuilt.)

**Pass B node cascade rule:** node decision applies to all child leaves below it
unless a leaf row carries an override note.

## API surface (settings.js → backend)

All via `readJson(url, options)` (or raw `fetch` for audio/RAG). The config JSON is
unchanged by the rebuild (operator-console.md:129), so these endpoints stay:

| Endpoint | Method | Driven by |
|----------|--------|-----------|
| `/api/mqtt-config` | GET / POST | Connectivity load + save |
| `/api/snapshot` | GET | simulation backend, video mode, broker pill |
| `/api/simulation-config` | POST | Connectivity → simulation backend |
| `/api/video-mode` | POST | Video tab save |
| `/api/ai-settings` | GET / POST | AI Settings load + save |
| `/api/ai-tts/speech` | POST | Test Voice (Kokoro) |
| `/api/mission-lifecycle` | GET / POST | Mission Lifecycle load + save (incl. controller adapter) |
| `/api/llm-settings` | GET | providers + routing bootstrap |
| `/api/llm-providers` | POST | create provider / add example |
| `/api/llm-providers/{id}` | PUT / DELETE | edit, toggle-enable, delete |
| `/api/llm-providers/{id}/check` | POST | check configured provider |
| `/api/llm-providers/check-draft` | POST | check unsaved draft |
| `/api/model-routing` | PUT | save routing, set-default, RAG embeddings model |
| `/api/rag/status` | GET | RAG status (503 → Qdrant offline) |
| `/api/rag/ingest` | POST | start incremental/regenerate job |
| `/api/rag/ingest/{jobId}` | GET | poll job (2 s) |
| `/api/settings/export` | POST | gather selected sections for save/export |
| `/api/settings/load-from-path` | POST | load JSON from backend path |
| `/api/settings/save-to-path` | POST | save selected JSON to backend path |
| `/api/settings/apply` | POST | apply imported sections to runtime |

## 1. Decision table

### Page shell, tabs & layout

Node decision: **Redesign / `SettingsWidget.tsx`** (VS-Code-style; tree nav replaces tab strip and fixed page shell). Leaves cascade unless noted.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st` | node | panel | — | Page root `body[data-page="settings"]` → `main.app-shell` → page-intro + `.settings-tabs` + `.settings-stack`. `initSettings()` boots: initShell → renderTabs → bind* → load* (connectivity, video, mission-lifecycle, ai, llm, rag) → `clearProviderForm()` | yes (Settings VS-Code rebuild, operator-console.md:125) | no | SettingsWidget.tsx | Redesign | new app is a dockview workspace; settings become a VS-Code-style view with category tree |
| `st.intro` | leaf | panel | "Settings" + subtitle | `<section data-page-intro>`; `GCSCommon.initShell` injects title + subtitle | no | no | — | Drop | page-intro pattern is old-app nav |
| `st.tabs` | node | tablist | "Settings sections" | `section.settings-tabs`; 8 anchor "tabs" `[data-settings-tab-link][href="?tab=…"]` | yes (replaced by Explorer-style category tree, operator-console.md:127) | no | — | Drop | tree nav replaces tab strip |
| `st.tabs.connectivity` | leaf | tab(link) | "Connectivity" | `href=?tab=connectivity`; `.active`+`aria-current` when selected | yes (Settings rebuild; mqtt-setup folds here, operator-console.md:135) | no | — | Drop | |
| `st.tabs.video` | leaf | tab(link) | "Video" | `?tab=video` | yes (parity) | no | — | Drop | |
| `st.tabs.appearance` | leaf | tab(link) | "Appearance" | `?tab=appearance` | yes (parity) | no | — | Drop | |
| `st.tabs.mission-lifecycle` | leaf | tab(link) | "Mission Lifecycle" | `?tab=mission-lifecycle` | yes (parity) | no | — | Drop | |
| `st.tabs.ai-settings` | leaf | tab(link) | "AI Settings" | `?tab=ai-settings` | yes (parity; persistence side of ai.md TTS gap) | no | — | Drop | |
| `st.tabs.llm-provider` | leaf | tab(link) | "Add LLM Provider" | `?tab=llm-provider` | yes (parity) | no | — | Drop | |
| `st.tabs.rag` | leaf | tab(link) | "RAG" | `?tab=rag` | yes (parity; ADR 0028) | no | — | Drop | |
| `st.tabs.json` | leaf | tab(link) | "Config I/O" | `?tab=json` | yes (parity) | no | — | Drop | |
| `st.stack` | node | panel | — | `section.settings-stack` wrapping all 8 `.settings-pane` sections; `renderTabs()` toggles `pane.hidden` | yes (parity) | no | SettingsWidget.tsx | Rebuild | content areas become category panels in tree view |
| `st.behavior.tab-routing` | leaf | (behavior) | — | `bindTabs()`: link click → `history.replaceState('/settings?tab=…')` + `renderTabs`; `popstate` → re-render from `readSelectedTab()` | yes (tree navigation in rebuild) | no | SettingsWidget.tsx | Drop | tree nav replaces URL-tab routing; note: `readSelectedTab` whitelist omits `mission-lifecycle` (latent bug, not ported) |
| `st.behavior.theme-bootstrap` | leaf | (behavior) | — | Inline `<head>` script reads `gcs-theme-mode`/`-light`/`-dark` localStorage, resolves system pref, sets `data-theme*` on `<html>` before paint | no (browser-local theme persistence) | no | ThemeStore.ts | Rebuild | move to React theme store / app bootstrap |

### Tab: Connectivity (`st.conn`) — MQTT + simulation backend

Node decision: **Rebuild / `SettingsWidget.tsx` > Connectivity category**. Includes mqtt-setup fold (operator-console.md:135). All leaves cascade Rebuild unless noted.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.conn` | node | panel | "Broker / MQTT Connectivity" | `section#tab-connectivity` → `article.panel.panel-secondary`; `loadConnectivity()` GETs `/api/mqtt-config` + `/api/snapshot`, fills form | yes (mqtt-setup folds into Connectivity, operator-console.md:135) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.pill` | leaf | pill | "Loading" → broker state | `#setup-broker-pill`; `updateSetupBrokerPill()` ← `brokerBadgeState()` (connected/stale/partial/waiting/disconnected → ok/warn/danger) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.hint` | leaf | label | "Saved to <path>. After save, the GCS reconnects…" | `.hint` with `#settings-path` `<code>`; path from `config.settings_path` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.form` | node | panel | — | `form#mqtt-form.form-grid`; submit → `saveConnectivity()` (POST mqtt-config + simulation-config, then reload after 800 ms) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.broker-host` | leaf | input(text) | "Broker Host" ph `192.0.2.10` | `#broker-host` `required`; `mqtt.broker_host` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.broker-port` | leaf | input(number) | "Broker Port" | `#broker-port` `min=1` `required`; `mqtt.broker_port` (default 1883) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.topic-prefix` | leaf | input(text) | "Topic Prefix" ph `/projects/remote-rover` | `#topic-prefix`; `mqtt.topic_prefix` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.client-id` | leaf | input(text) | "Client ID" ph `gcs-web` | `#client-id-input`; `mqtt.client_id` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.control-topic` | leaf | input(text) | "Control Topic" ph `control/manual` | `#control-topic` `required`; `mqtt.control_topic` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.state-topic` | leaf | input(text) | "Telemetry Topic" ph `telemetry/state` | `#state-topic` `required`; `mqtt.state_topic` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.camera-topic` | leaf | input(text) | "Camera Topic" ph `camera-feed` | `#camera-topic` `required`; `mqtt.camera_topic` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.control-hz` | leaf | input(number) | "Control Rate (Hz)" | `#control-hz` `min=1` `required`; `mqtt.control_hz` (default 20) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.connected-threshold` | leaf | input(number) | "Rover Connected Threshold (s)" | `#rover-connected-threshold` `min=0`; `rover_availability.connected_threshold_seconds` (default 2, floored) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.unavailable-threshold` | leaf | input(number) | "Rover Unavailable Threshold (s)" | `#rover-unavailable-threshold` `min=1`; `unavailable_threshold_seconds` (default 60, ≥ connected) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.rollover-on-reconnect` | leaf | toggle | "Rollover On Rover Reconnect" | `#rover-rollover-on-reconnect` checkbox; `rover_availability.rollover_on_reconnect` (default true) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.sim-backend` | leaf | select | "Active Simulator Backend": 3d-env | `#simulation-backend-select`; `simulation.backend`; saved via `/api/simulation-config` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.save` | leaf | button(submit) | "Save Connectivity" | form submit → POST both configs, reconnect broker | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.reload` | leaf | button | "Reload" | `#reload-config.ghost`; `loadConnectivity()` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.conn.status` | leaf | label | "Loading shared MQTT settings." → target/saved msgs | `#setup-status.status-banner` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |

### Tab: Video (`st.video`)

Node decision: **Rebuild / `SettingsWidget.tsx` > Video category**. All leaves cascade Rebuild.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.video` | node | panel | "Pipeline / Video Settings" | `section#tab-video` → panel; `loadVideoSettings()` ← `/api/snapshot.video` | yes (Settings rebuild, operator-console.md:125) | no | SettingsWidget.tsx | Rebuild | |
| `st.video.pill` | leaf | pill | "Loading" → "ingest -> delivery" / "Disabled" | `#video-settings-pill`; `updateVideoPill()` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.video.ingest-mode` | leaf | select | "Ingest mode": mqtt_frames / rtp_udp / rtsp / whip / disabled | `#ingest-mode`; `video.ingest_mode` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.video.delivery-mode` | leaf | select | "Delivery mode": websocket_mjpeg / webrtc_direct / webrtc_sfu / disabled | `#delivery-mode`; `video.delivery_mode` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.video.enabled` | leaf | toggle | "Video enabled" | `#video-enabled` checkbox; `video.enabled` | yes (parity) | no | SettingsWidget.tsx | Rebuild | relates to STAB-4 runtime video-mode-state gap |
| `st.video.save` | leaf | button | "Save Video Settings" | `#save-video-settings`; `saveVideoSettings()` → POST `/api/video-mode` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.video.status` | leaf | label | "Loading current video mode." → delivery path | `#video-settings-status.status-banner` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |

### Tab: Appearance (`st.appear`) — browser-local theme

Node decision: **Rebuild / `SettingsWidget.tsx` > Appearance category**. Static label/note/status leaves → Drop.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.appear` | node | panel | "Theme / Appearance" | `section#tab-appearance` → panel; `bindAppearance()` wires three selects to `GCSCommon.set*Theme` (localStorage, no backend) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.appear.pill` | leaf | pill | "Local preference" | `#appearance-pill` static | no | no | — | Drop | static label; no dynamic value |
| `st.appear.mode` | leaf | select | "Theme mode": System / Light / Dark | `#theme-mode-select`; `GCSCommon.setThemeMode` | yes (parity) | no | SettingsWidget.tsx | Rebuild | wires to ThemeStore |
| `st.appear.light` | leaf | select | "Default light theme": VS Code Light / Quiet Light / Cool Light / Sandstone Light | `#light-theme-select`; `setLightTheme` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.appear.dark` | leaf | select | "Default dark theme": VS Code Dark / Graphite Dark / Midnight Dark / Deep Forest Dark | `#dark-theme-select`; `setDarkTheme` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.appear.note` | leaf | label | "Theme mode follows the browser and OS…" | `.settings-note` static | no | no | — | Drop | |
| `st.appear.status` | leaf | label | "Theme preferences are stored in this browser." | `#appearance-status.status-banner` | no | no | — | Drop | |

### Tab: Mission Lifecycle (`st.mission`) — ADR 0021 + controller adapter

Node decision: **Rebuild / `SettingsWidget.tsx` > Mission Lifecycle category**. Static hint/note leaves → Drop. All functional leaves cascade Rebuild.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.mission` | node | panel | "Execution / Mission Lifecycle" | `section#tab-mission-lifecycle` → panel; `loadMissionLifecycle()` ← `/api/mission-lifecycle` (settings + build_default + controller_adapter) | yes (parity; ADR 0021) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.pill` | leaf | pill | "Loading" → mode label | `#mission-lifecycle-pill`; `updateMissionLifecyclePill()` (strict/confirm/autonomous → ''/ok/warn) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.hint` | leaf | label | "Controls how AI-authored missions move from draft to execution… See ADR 0021." | `.hint` static | no | no | — | Drop | |
| `st.mission.execution-mode` | leaf | select | "Execution mode": strict / confirm / autonomous (with descriptions) | `#mission-execution-mode`; `execution_mode` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.confirm-timeout` | leaf | input(range) | "Confirm timeout (seconds)" 3–60 | `#mission-confirm-timeout`; live label `#mission-confirm-timeout-value` "N s" | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.auto-overlay` | leaf | toggle | "Auto-overlay new missions on the map" | `#mission-auto-overlay`; `auto_overlay_new_missions` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.steal-focus` | leaf | toggle | "Steal map focus when a new mission is created" | `#mission-steal-focus`; `steal_map_focus` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.name-template` | leaf | input(text) | "Default mission name template" ph `Untitled mission` | `#mission-name-template`; `default_name_template` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.hw-kicker` | leaf | label | "Hardware Link" | `.section-kicker` static divider | no | no | — | Drop | |
| `st.mission.fc-adapter-type` | leaf | select | "FC adapter type": json_file / file_sink / mavlink / mavsdk | `#fc-adapter-type`; `updateFcAdapterFields()` reveals url/timeout rows; `controller_adapter.type` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.fc-mavlink-url` | leaf | input(text) | "MAVLink connection URL" ph `udp:127.0.0.1:14550` | `#fc-mavlink-url` (row `#fc-mavlink-url-row` hidden unless mavlink) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.fc-mavsdk-url` | leaf | input(text) | "MAVSDK connection URL" ph `udp://127.0.0.1:14540` | `#fc-mavsdk-url` (row hidden unless mavsdk) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.fc-heartbeat-timeout` | leaf | input(number) | "Heartbeat timeout (s)" 1–60 | `#fc-heartbeat-timeout` (in `#fc-timeout-rows`, shown for mavlink/mavsdk); default 5 | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.fc-request-timeout` | leaf | input(number) | "Request timeout (s)" 1–60 | `#fc-request-timeout`; default 5 | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.save` | leaf | button | "Save Mission Lifecycle" | `#save-mission-lifecycle`; POST `/api/mission-lifecycle` (lifecycle + adapter) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.mission.build-default-note` | leaf | label | "…Build default mode: <mode>." | `.settings-note` w/ `#mission-build-default`; from `result.build_default_mode` | no | no | — | Drop | |
| `st.mission.status` | leaf | label | "Loading mission lifecycle settings." | `#mission-lifecycle-status.status-banner` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |

### Tab: AI Settings (`st.ai`) — response audio / TTS

Node decision: **Rebuild / `SettingsWidget.tsx` > AI Settings category**. Static note → Drop. All functional leaves cascade Rebuild.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.ai` | node | panel | "Voice / AI Response Audio" | `section#tab-ai-settings` → panel; `loadAiSettings()` ← `/api/ai-settings.tts` | yes (persistence side of ai.md TTS gap, operator-console.md:125) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.pill` | leaf | pill | "Loading" → "Voice: Kokoro/Browser" / "Voice disabled" | `#ai-settings-pill`; set in `fillAiSettings`/toggle | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.tts-enabled` | leaf | toggle | "Show text-to-speech controls for assistant responses" | `#ai-tts-enabled`; `tts.enabled` | yes (parity; pairs with ai.md TTS controls) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.auto-read` | leaf | toggle | "Automatically read new assistant responses" | `#ai-tts-auto-read`; `tts.auto_read` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.engine` | leaf | select | "Speech Engine": Kokoro local service / Browser fallback voice | `#ai-tts-engine`; `tts.engine` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.service-url` | leaf | input(url) | "Kokoro Service URL" `http://127.0.0.1:9101` | `#ai-tts-service-url`; `tts.service_url` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.service-voice` | leaf | input(text) | "Kokoro Voice" `af_sky` | `#ai-tts-service-voice`; `tts.voice` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.service-speed` | leaf | input(range) | "Kokoro Speed" 0.5–2 | `#ai-tts-service-speed`; `tts.speed` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.browser-fallback` | leaf | toggle | "Use browser voice if the local TTS service fails" | `#ai-tts-browser-fallback`; `tts.browser_fallback` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.browser-voice` | leaf | select(dynamic) | "Browser Voice" | `#ai-tts-voice`; `populateAiVoiceOptions()` from `speechSynthesis.getVoices()` (option list rebuilt on `voiceschanged`) | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.browser-rate` | leaf | input(range) | "Browser Rate" 0.5–2 | `#ai-tts-rate`; `tts.rate` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.browser-pitch` | leaf | input(range) | "Browser Pitch" 0–2 | `#ai-tts-pitch`; `tts.pitch` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.save` | leaf | button | "Save AI Settings" | `#save-ai-settings`; POST `/api/ai-settings` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.test-voice` | leaf | button | "Test Voice" | `#test-ai-voice.ghost`; `testAiVoice()` — Kokoro path saves then POST `/api/ai-tts/speech` → plays blob; browser path uses `SpeechSynthesisUtterance` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.ai.note` | leaf | label | "Kokoro local service should run on port 9101…" | `.settings-note` static | no | no | — | Drop | |
| `st.ai.status` | leaf | label | "Loading AI settings." | `#ai-settings-status.status-banner` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |

### Tab: Add LLM Provider (`st.llm`) — 3 panels: editor, registry, routing

Node decision: **Redesign / `LLMProviderWidget.tsx`**. LLM editor + registry + routing are too interactive for a flat schema row; they become a dedicated Settings sub-view rather than a separate palette widget. All `st.llm.*` leaves cascade Redesign unless noted. Static notes → Drop.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.llm` | node | panel | — | `section#tab-llm-provider`; three `.panel.llm-settings-panel` (Provider editor, Configured LLMs registry, Routing); `loadLlmSettings()` ← `/api/llm-settings` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| **Editor** `st.llm.form` | node | panel | "Add or edit / Provider Settings" | `article.panel` #1; `form#llm-provider-form.form-grid` submit → `saveProvider()` (POST new / PUT existing) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.mode-pill` | leaf | pill | "New provider" / "Editing selected provider" | `#llm-form-mode-pill`; set in `fillProviderForm` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.template-select` | leaf | select | "Provider template" (13 options: openrouter…openai_compatible) | `#llm-provider-template`; one of `LLM_TEMPLATES` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.apply-template` | leaf | button | "Apply Template" | `#llm-apply-template.ghost`; `applyProviderTemplate()` fills form from template | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.id` | leaf | input(hidden) | — | `#llm-provider-id`; tracks `editingProviderId` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.display-name` | leaf | input(text) | "Display Name" | `#llm-display-name` `required` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.provider-type` | leaf | select | "Provider Type" (13 options) | `#llm-provider-type` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.auth-mode` | leaf | select | "Auth Mode": Environment variable / Store API key / No auth | `#llm-auth-mode`; `updateProviderAuthFields()` swaps secret-ref label/placeholder & toggles value row | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.secret-ref` | leaf | input(text) | "Secret / Env Var" (label varies) ph `OPENROUTER_API_KEY` | `#llm-secret-ref` (`#llm-secret-ref-label`); disabled for `none` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.secret-value` | leaf | input(password) | "API Key Value" ph `Paste API key` | `#llm-secret-value` (row `#llm-secret-value-row`, shown only for stored_secret) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.base-url` | leaf | input(url) | "Base URL" ph `https://openrouter.ai/api/v1` | `#llm-base-url` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.model-id` | leaf | input(text) | "Model ID" ph `anthropic/claude-sonnet` | `#llm-model-id` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.context-window` | leaf | input(number) | "Context Window" ph `e.g. 131072` | `#llm-context-window` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.capabilities` | leaf | input(text) | "Capabilities" ph `chat, reasoning` | `#llm-capabilities`; comma-split list | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.enabled` | leaf | toggle | "Enabled" | `#llm-enabled` checkbox | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.save` | leaf | button(submit) | "Save Provider" | POST/PUT `/api/llm-providers[/{id}]` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.check-draft` | leaf | button | "Check Draft" | `#llm-check-draft.ghost`; POST `/api/llm-providers/check-draft` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.new` | leaf | button | "New Provider" | `#llm-new-provider.ghost`; `clearProviderForm()` (openrouter template) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.cancel` | leaf | button | "Cancel Edit" | `#llm-cancel-edit.ghost`; `clearProviderForm()` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.form.status` | leaf | label | "LLM providers are stored in the active GCS settings file." | `#llm-provider-status.status-banner` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| **Registry** `st.llm.registry` | node | panel | "Registry / Configured LLMs" | `article.panel` #2; `#llm-provider-list` (dynamic table) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.pill` | leaf | pill | "Loading" → "N enabled" | `#llm-registry-pill`; `renderProviderList()` enabled count | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.note` | leaf | label | "Check verifies auth, base URL, and the provider model endpoint…" | `.settings-note` static | no | no | — | Drop | |
| `st.llm.registry.add-examples` | leaf | button | "Add Missing Example Providers" | `#llm-add-example-providers.ghost`; `addMissingExampleProviders()` POSTs each missing template (disabled) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.list` | node | table(dynamic) | — | `#llm-provider-list`; empty → "No LLM providers configured yet."; else `.llm-provider-table`. Delegated click → `handleProviderListClick` (sort + actions) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.sort-header` | leaf | button×7 | Name / Type / Model / Auth / Capabilities / Enabled / Status (▲▼) | `[data-llm-sort]`; `renderProviderSortHeader`; toggles `llmProviderSort` key/dir, re-renders | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row` | node | row(dynamic) | per provider | `tr.llm-provider-row[data-provider-id]`; cells name/type/model/auth/caps + control cells | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.caps` | leaf | pill×N | capability chips | `.llm-chip` per capability (or "none") | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.toggle` | leaf | button(icon) | enable/disable power glyph | `[data-llm-action=toggle]`; PUT `/api/llm-providers/{id}` flips `enabled` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.check` | leaf | button(icon) | status glyph (ok/pending/danger) | `[data-llm-action=check]`; POST `/api/llm-providers/{id}/check`; title shows last message | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.set-default` | leaf | button(icon) | star — default for General Chat | `[data-llm-action=set-default]`; `setDefaultProvider()` PUTs `/api/model-routing` general_chat.primary; disabled if disabled & not default | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.edit` | leaf | button(icon) | "✎" Edit | `[data-llm-action=edit]`; `fillProviderForm` + scroll/focus editor | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.registry.row.delete` | leaf | button(icon) | "🗑" Delete | `[data-llm-action=delete].llm-action-danger`; `window.confirm` → DELETE `/api/llm-providers/{id}` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| **Routing** `st.llm.routing` | node | panel | "Routing / Model Routing Rules" | `article.panel` #3; "Primary + fallback" pill; `#llm-routing-list` (dynamic) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.note` | leaf | label | "Each task type gets a primary provider and ordered fallbacks…" | `.settings-note` static | no | no | — | Drop | |
| `st.llm.routing.list` | node | panel(dynamic) | 6 rows | `#llm-routing-list`; `renderRoutingList()` one row per `ROUTING_LABELS` (general_chat, rover_intent_parser, mission_planner, reporter, embeddings, vision_object_description); delegated click+change → `handleRoutingClick`/`handleRoutingChange` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.row.primary` | leaf | select | primary provider | `[data-routing-field=primary]`; `providerOptions()` (disabled if unavailable) | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.row.fallback-chips` | leaf | pill×N | "1. Provider…" / "No fallbacks" | `.llm-fallback-chips`; ordered fallback list | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.row.edit-fallbacks` | leaf | button | "Edit fallbacks" ↔ "Close editor" | `[data-routing-action]`; toggles `editingFallbackPurpose` → renders `renderFallbackEditor` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.fallback-editor` | node | panel(dynamic) | — | `.llm-fallback-editor`; per-fallback row select + Up/Down/Remove + Add row | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.fallback.up` | leaf | button | "Up" | `[data-fallback-action=up]`; swap order | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.fallback.down` | leaf | button | "Down" | `[data-fallback-action=down]`; swap order | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.fallback.remove` | leaf | button | "Remove" | `[data-fallback-action=remove]`; splice | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.fallback.add` | leaf | button | "Add fallback" | `[data-fallback-action=add]` + `[data-fallback-field=add]` select | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.save` | leaf | button | "Save Routing" | `#save-model-routing`; `saveRouting()` PUT `/api/model-routing` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.reload` | leaf | button | "Reload Routing" | `#reload-model-routing.ghost`; `loadLlmSettings()` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |
| `st.llm.routing.status` | leaf | label | "Routing rules load after providers are available." | `#llm-routing-status.status-banner` | yes (parity) | no | LLMProviderWidget.tsx | Redesign | |

### Tab: RAG (`st.rag`) — project docs embeddings (ADR 0028)

Node decision: **Rebuild / `SettingsWidget.tsx` > RAG category**. Static notes → Drop. All functional leaves cascade Rebuild.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.rag` | node | panel | "Knowledge / Project Docs Embeddings" | `section#tab-rag` → panel; `loadRagSettings()` ← `/api/rag/status` (503 → "Qdrant not running") | yes (parity; ADR 0028) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.pill` | leaf | pill | "Loading" → Up to date / Stale / Not indexed / Model changed / Offline | `#rag-status-pill`; `RAG_STALENESS_META[staleness]` → ok/warn/danger | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.note` | leaf | label | "Project documentation is embedded into a Qdrant collection… (ADR 0028)" | `.settings-note` static | no | no | — | Drop | |
| `st.rag.model-warning` | leaf | label | staleness warning (hidden when fresh) | `#rag-model-warning.status-banner`; from `RAG_STALENESS_META[].warn` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.model-select` | leaf | select(dynamic) | "Routed model" | `#rag-model-select`; `renderRagModelSelect()` lists embedding-capable providers; change → PUT `/api/model-routing` embeddings.primary then reload | yes (parity) | no | SettingsWidget.tsx | Rebuild | RAG keeps its own model picker here; defers to routing editor for other task types |
| `st.rag.collection` | leaf | label | "Collection" → name | `#rag-collection` ← `status.collection` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.point-count` | leaf | label | "Indexed chunks" → N | `#rag-point-count` ← `status.point_count` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.last-ingest` | leaf | label | "Last updated" → timestamp | `#rag-last-ingest` ← `formatTimestamp(status.last_ingest_at)` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.update-index` | leaf | button | "Update Index" | `#rag-embed-incremental`; `triggerRagIngest('incremental')` POST `/api/rag/ingest`; disabled when missing/model_mismatch | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.rebuild-index` | leaf | button | "Rebuild Index" | `#rag-embed-regenerate.ghost`; `triggerRagIngest('regenerate')` w/ confirm | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.refresh` | leaf | button | "↻ Refresh" | `#rag-refresh-status.ghost`; `loadRagSettings()` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.status` | leaf | label | "Loading RAG status." → collection/chunks | `#rag-status-message.status-banner` | yes (parity) | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.last-incremental` | leaf | label | "Last Update Index: …" | `#rag-last-incremental-result.settings-note` (hidden until run; persisted to localStorage) | no | no | SettingsWidget.tsx | Rebuild | localStorage persistence carries forward |
| `st.rag.last-regenerate` | leaf | label | "Last Rebuild Index: …" | `#rag-last-regenerate-result.settings-note` (localStorage) | no | no | SettingsWidget.tsx | Rebuild | |
| `st.rag.behavior.poll` | leaf | (behavior) | — | `pollRagJob()` polls `/api/rag/ingest/{jobId}` every 2 s until complete/error; reports upserted/skipped/deleted/tokens | yes (parity) | no | SettingsWidget.tsx | Rebuild | |

### Tab: Config I/O (`st.json`) — JSON import/export

Node decision: **Redesign / `ConfigIOWidget.tsx`**. Import/export console is too interactive for flat schema rows; it becomes a dedicated Settings sub-view rather than a separate palette widget. All leaves cascade Redesign unless noted.

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.json` | node | panel | "Config I/O / JSON Import & Export" | `section#tab-json` → panel → `section.settings-source-block`; export + import columns + source fields | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.header` | node | panel | "Config source options" + copy | `.settings-source-header`; static note + `.settings-source-copy` | no | no | — | Drop | static wrapper |
| `st.json.export` | node | panel | "Export sections" | `section.json-scope-column` #1; 7 `.json-export-toggle` checkboxes (on/off pill) + policy notes + actions | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.export.toggle` | leaf | toggle×7 | MQTT / Simulation / Video / Appearance / AI Settings / LLM Providers / Model Routing Rules (each w/ desc + on/off pill) | `.json-export-toggle[value=…]`; `selectedExportSections()`; `setScopePills` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.export.save-local` | leaf | button | "Export Selected JSON" | `#save-local-file`; `saveJsonToLocalFile()` → `/api/settings/export` then browser download | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.export.save-backend` | leaf | button | "Save to Backend Path" | `#save-backend-path.ghost`; `saveJsonToBackendPath()` POST `/api/settings/save-to-path` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.export.select-all` | leaf | button | "Select All" | `#select-all-export-sections.ghost`; check all export toggles | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.import` | node | panel | "Import and apply sections" | `section.json-scope-column` #2; 7 `.json-import-toggle` (safe/off pill) + policy + actions | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.import.toggle` | leaf | toggle×7 | MQTT / Simulation / Video / Appearance / AI Settings / LLM Providers / Model Routing Rules (each w/ desc + safe/off pill) | `.json-import-toggle[value=…]`; `selectedImportSections()` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.import.load-preview` | leaf | button | "Load JSON and Preview" | `#load-backend-path`; `loadJsonFromBackendPath()` POST `/api/settings/load-from-path` → `previewJsonSettings` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.import.apply` | leaf | button | "Apply Checked Sections" | `#apply-json-settings.ghost`; `applyPendingJsonSettings()` POST `/api/settings/apply` then reloads all tabs | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.import.select-all` | leaf | button | "Select All" | `#select-all-import-sections.ghost` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.backend-path` | leaf | input(text) | "Backend JSON Path (inside ../config)" ph `common.local.json` | `#backend-config-path` (`.settings-source-field`) | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.local-file` | leaf | input(file) | "Load from Local JSON" accept json | `#local-config-file`; change → `loadJsonFromLocalFile()` (parses + previews) | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.preview` | leaf | label | preview payload (hidden until loaded) | `#json-preview.status-banner.json-preview`; `updateJsonPreview()` lists apply/missing + JSON | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |
| `st.json.status` | leaf | label | "Loading backend config path details." | `#json-settings-status.status-banner` | yes (parity) | no | ConfigIOWidget.tsx | Redesign | |

### Cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `st.behavior.readjson` | leaf | (behavior) | — | `readJson(url, opts)` wraps `fetch` + JSON, throws `data.detail` on non-2xx; the single backend call helper | yes (becomes data-layer fetch in rebuild) | no | settings data hooks | Rebuild | becomes TanStack Query hooks per category |
| `st.behavior.json-preview` | leaf | (behavior) | — | `pendingJsonImport` holds loaded settings; `updateJsonPreview()` recomputes found/missing vs checked sections; toggles re-preview | yes (parity) | no | ConfigIOWidget.tsx | Rebuild | |
| `st.behavior.scope-pills` | leaf | (behavior) | — | `setScopePills()` flips each scope item's pill to on/safe/off as its toggle changes | yes (parity) | no | ConfigIOWidget.tsx | Rebuild | |
| `st.behavior.escape-html` | leaf | (behavior) | — | `escapeHtml()` used on all interpolated values in `innerHTML` templates (provider table, routing, voice options) | n/a | n/a | — | Drop | React escapes by default |
| `st.behavior.delegated-events` | leaf | (behavior) | — | Two delegated handlers on dynamic containers: `#llm-provider-list` click (`data-llm-sort`/`data-llm-action`), `#llm-routing-list` click+change (`data-routing-*`/`data-fallback-*`) | yes (parity; React handlers in rebuild) | no | — | Drop | React event handling replaces delegated vanilla handlers |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is authoritative. Node rows carry
layout; leaf rows carry appearance. Settings styling reuses the shared `.panel` /
`.panel-head` / `.pill` / `.status-banner` / `.section-kicker` / `.form-grid` /
`button` vocabulary plus a settings-/LLM-/json-/rag-specific block.

### Layout (nodes)

- `st` — `main.app-shell` page container `@ style.css:289`; `.app-shell.has-page-intro` header offset `@ style.css:312`.
- `st.tabs` — `.settings-tabs` horizontal wrap of tab links; `@ style.css:2283`. Base `.settings-tab` link chip `@ style.css:370`; hover `@ style.css:608`; `.settings-tab.active` accent state `@ style.css:2314`.
- `st.stack` — `.settings-stack` vertical stack of panes `@ style.css:451`; `.settings-pane` `@ style.css:2364`.
- `st.{conn,video,appear,mission,ai,rag,json}` panes — `.settings-grid` (1-col / responsive) `@ style.css:452`; compact variant `.settings-grid-compact` `@ style.css:508`. `article.panel` base `@ style.css:296`; `.panel-secondary` has **no dedicated rule** (inherits `.panel`); `.panel-head` `@ style.css:541`.
- `st.conn.form` / `st.llm.form` — `.form-grid` two-column field grid `@ style.css:2677`; `.form-actions` button row `@ style.css:2684`; `.form-actions-inline` `@ style.css:2692`.
- `st.llm` — `.llm-settings-panel` `@ style.css:2376`; template row `.llm-template-row` `@ style.css:2380`.
- `st.llm.registry.list` — `.llm-provider-list` `@ style.css:2394`; `.llm-provider-table` `@ style.css:2414`; sort header button `.llm-sort-button` `@ style.css:2443`.
- `st.llm.routing.list` — `.llm-routing-list` `@ style.css:2395`; `.llm-routing-row` grid `@ style.css:2381`; `.llm-fallback-editor` `@ style.css:2382`; `.llm-fallback-chips` `@ style.css:2468`; `.llm-cell-control` `@ style.css:2475`; `.llm-actions` `@ style.css:2492`; `.llm-provider-meta` `@ style.css:2467`.
- `st.rag` — `.rag-status-grid` `dl` `@ style.css:3828`; `.rag-status-row` `@ style.css:3834`; select row `.rag-status-row-select` `@ style.css:3855` (dd `@3859`, select `@3863`).
- `st.json` — `.json-scope-grid` two-column `@ style.css:2610`; `.json-scope-column` `@ style.css:2617`; `.json-scope-list` `@ style.css:2623`; `.json-scope-item` `@ style.css:2629`; `.json-policy-list` `@ style.css:2651`; `.json-scope-actions` `@ style.css:2657`; `.json-source-fields` `@ style.css:2665`. `.settings-source-block`/`-header`/`-copy`/`-fields`/`-field` have **no dedicated rules** (inherit `.settings-note`/`label`/`.form-grid`).

### Appearance (leaves)

- Pills — base `.pill` `@ style.css:553`; tones `.pill.ok` `@562`, `.pill.warn` `@567`, `.pill.danger` `@572` (used by broker/video/mission/llm/registry/rag pills).
- Status banners — `.status-banner` `@ style.css:709`; hints `.hint` `@710`; notes `.settings-note` `@711`; section kicker `.section-kicker` `@334`.
- Buttons — base `button` + `.ghost` ghost variant `@ style.css:599` (Reload, Test Voice, template apply, new/cancel/check, save-backend, select-all, etc.).
- Checkbox rows — `.checkbox-row` inline label+input `@ style.css:2271` (video enabled, mission overlays, AI toggles, llm enabled).
- `st.llm.registry.row.*` action icons — `.llm-action-icon` `@ style.css:2499`; danger `.llm-action-icon.llm-action-danger` `@2521`; status icon badges `.llm-icon-badge` `@2525`, `.llm-icon-status-ok` `@2562`, `-pending` `@2567`, `-danger` `@2572` (SVG glyphs hard-coded in `renderProviderIcon`, settings.js:821).
- `st.llm.*.chip` — `.llm-chip` capability/fallback chip `@ style.css:2482`.
- `st.json.preview` — `.json-preview` monospace banner `@ style.css:2669` (extends `.status-banner`).
- `st.json.*.toggle` pills — `.json-scope-item .pill` "on"/"safe"/"off" reuse base `.pill`; item layout `@ style.css:2629`.

### Theme tokens (resolve in `style.css` `:root`/`[data-theme]`)

`--accent`, `--accent-soft`, `--line`, `--muted`, `--text`, `--panel`,
`--panel-strong`, `--bg-base`. Theme palettes are switched via `data-theme`
(8 themes: 4 light, 4 dark) bootstrapped by the inline `<head>` script
(`st.behavior.theme-bootstrap`) and toggled by the Appearance tab. The LLM provider
status SVG glyphs and star/power icons are **drawn in `settings.js`**
(`renderProviderIcon` @821), not CSS.
