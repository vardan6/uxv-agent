# AI Chat page inventory — `frontend-vanilla/ai.html` + `frontend-vanilla/ai.js`

Pass A extraction (mechanical). Source: `frontend-vanilla/ai.html` (256 lines),
`frontend-vanilla/ai.js` (3,877 lines), styles in `frontend-vanilla/style.css`.
Target app: `frontend/` — the AI widget today is
`frontend/src/widgets/AIChatWidget.tsx` (+ `frontend/src/data/aiChat.ts`).

`planned?` / `implemented?` pre-filled. `target` and `decision` are intentionally
blank — they are filled in **Pass B (INV-B)**.

**Pre-fill key.** `planned?`: the new design doc
([operator-console.md](../design/operator-console.md)) lists AI Chat only as a
generic "thread + composer" widget (§ widget table, line 82); the polished
behaviors below are not individually specified there. The parity rebuild itself is
the plan — `roadmap.md` §"Legacy UI inventory & gap analysis" (INV-A/B/C, lines
97–150) and the gap list at lines 99–102. `requirements.md:282` references provider
selection / retry-stop / source controls as behaviors a later visual cleanup "must
not change". So `planned?` reads **yes (parity, roadmap INV-C)** for rebuild-track
items and **unsure** where the new design is silent. `implemented?`: searched
`frontend/src/` — only `AIChatWidget.tsx` exists; it has session `<select>`, New,
title/status line, message list (role + time + content), textarea, Stop, Send. Two
chat panels can each pin one session. Everything else is **no**.

## 1. Decision table

### Page shell & layout

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai` | node | panel | — | Page root `main.app-shell[data-page="ai"]`; CSS grid `ai-chat-shell`: sidebar / splitter / chat, then footer (status bar), then map area + resizer | unsure: greenfield is a dockview workspace, not a fixed multi-page page | partial: dockview panel, no fixed multi-region page | `workspace` | Drop | Dockview composes the same widgets; page-level grid is a layout artifact |
| `ai.intro` | leaf | panel | "AI Chat" + lede paragraphs | `initAi()` injects `.ai-intro-grid` into `[data-page-intro]` (skipped when `data-page="mission-console"`) | no | no | — | Drop | Marketing/intro copy; not surfaced in new app |
| `ai.layout-resizer` | leaf | separator | (drag handle) "Resize sessions panel" | Pointer + arrow/Home/End keys set `--ai-sidebar-width` 240–560px, persisted `localStorage[gcs-ai-sidebar-width]`; disabled under `(max-width:1100px)` | no | no | — | Drop | Dockview handles panel sizing |
| `ai.height-resizer` | leaf | separator | "Resize chat panels height" | Sets `--ai-shell-height` (min 420px), persisted `gcs-ai-chat-shell-height` | no | no | — | Drop | Dockview handles panel sizing |
| `ai.status-bar` | node | panel | — | `<div id="gcs-status-bar-container">`; ES module mounts `StatusBar` from `map/ui/StatusBar.js`; AI mission-action tool calls push toasts via `window.__gcsStatusBar` | unsure | partial: GCS status surface exists separately | `workspace` | Redesign | Route AI tool-call status messages to workspace-level toast/notification surface |
| `ai.map-area` | node | panel | — | `<section id="ai-map-area">` hosts `MapWidget` (from `map/index.js`); follows `ai:session-open` / `ai:session-refreshed` events to bind/refresh per session | yes (Map widget is planned) | yes (separate MapWidget panel exists) | `MapWidgetPanel.tsx` | Drop | Map is its own dockview panel; not a sub-section of AI chat; wiring handled via mc.map |
| `ai.map-height-resizer` | leaf | separator | "Resize map panel height" | Sets `#ai-map-area` height 320–1100px, persisted `gcs-ai-map-height` | no | no | — | Drop | Dockview handles panel sizing |

### Sessions sidebar

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.sidebar` | node | panel | "Sessions" / "Chats" | `aside.panel.ai-sidebar`; grid head / search / list | yes (parity, roadmap INV) | no | `AIChatWidget.tsx` | Rebuild | Replace the `<select>` with a full sidebar panel |
| `ai.sidebar.head.kicker` | leaf | label | "Sessions" | static | no | no | `AIChatWidget.tsx` | Rebuild | Cascades from sidebar node |
| `ai.sidebar.head.title` | leaf | label | "Chats" | static `<h2>` | no | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.show-active` | leaf | button | "Active" | `setArchiveFilter(false)` → reload `GET /api/ai/sessions`; `aria-pressed` toggled | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.show-archived` | leaf | button | "Archived" | `setArchiveFilter(true)` → `GET /api/ai/sessions?include_archived=true&limit=500` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.new-session` | leaf | button | "+" | `createSession()` → `POST /api/ai/sessions` (title, mode, provider_id, source_controls), then `openSession` | yes (parity) | yes ("New" button) | `AIChatWidget.tsx` | Rebuild | Existing button only; needs to pass mode/provider_id/source_controls on create |
| `ai.sidebar.search` | leaf | input(search) | placeholder "Search sessions" | client-side filter over `title`+`last_message`; re-renders list on input | yes (parity, req.md:282) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list` | node | panel | — | `renderSessionList()` builds rows; empty → "No [archived ]sessions found." | yes (parity) | partial: `<select>` only | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row` | node | panel | (session title) | `div.ai-session-row[tabindex=0]`; single-click (220ms debounced) → `openSession`; Enter/Space opens; dblclick → inline rename | yes (parity) | partial: `<option>` | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row.title` | leaf | label | session title or "New chat" | truncated; `font-weight:650` | yes (parity) | partial | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row.title-input` | leaf | input(text) | (edit title) | Shown when `editingSessionId` matches; Enter/blur → `saveSessionTitle` `PATCH /api/ai/sessions/{id}`; Esc cancels | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row.count` | leaf | pill | message count | `session.message_count` | unsure | no | `AIChatWidget.tsx` | Rebuild | Include in sidebar row; low implementation cost |
| `ai.sidebar.list.row.archive` | leaf | button | "📥" / "↺" | `toggleSessionArchive` → `DELETE …` (archive) or `POST …/restore` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row.delete` | leaf | button | "✕" | `deleteSession` → `window.confirm` then `DELETE …/purge` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.sidebar.list.row.meta` | leaf | label | "{time} · N msg[· mission …]" | `formatAiTime(updated_at)` + mission_state | unsure | no | `AIChatWidget.tsx` | Rebuild | Include; useful at-a-glance context |
| `ai.sidebar.list.row.preview` | leaf | label | last message / mission preview | `missionPreview \|\| last_message \|\| "No messages yet"` | yes (parity, req.md:282) | no | `AIChatWidget.tsx` | Rebuild | |

### Chat panel header

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.chat` | node | panel | "General Chat" | `section.panel.ai-chat-panel`; head / provider-strip / message-list / composer | yes | partial | `AIChatWidget.tsx` | Keep | Chat panel exists; rebuild missing sub-parts |
| `ai.chat.head.kicker` | leaf | label | "General Chat" | static | no | no | — | Drop | Static decorative label; no functional value |
| `ai.chat.head.title` | leaf | label | session title `#ai-session-title` | `renderMessages` sets to active title | yes | yes (title line) | `AIChatWidget.tsx` | Keep | |
| `ai.chat.head.provider-select` | leaf | select | provider list | `renderProviderSelect`: "Routing default: …" + enabled chat providers; change → `updateSessionProvider` `PATCH …{provider_id}` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.head.rename` | leaf | button(icon) | pencil — "Rename chat" | `renameSession` → `window.prompt` then `PATCH …{title}` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.head.archive` | leaf | button(icon) | archive/restore — "Archive chat" | `archiveSession` → `toggleSessionArchive`; icon swaps archive↔restore by `archived_at` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.head.copy` | leaf | button(icon) | copy — "Copy chat as markdown (Shift-click for diagnostics)" | `buildChatMarkdown` → clipboard; Shift/Alt includes diagnostics + open activity | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |

### Provider strip (status pills)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.chat.provider-pill` | leaf | pill | "Provider: {label}[· Tools: …]" | `renderProviderSelect`; appends tools-support label in agent mode | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.status-pill` | leaf | pill | "Idle" / status | `setAiStatus(text, level)` sets text + `pill ok\|warn\|danger` | yes (parity) | partial: "ready/streaming" text line | `AIChatWidget.tsx` | Rebuild | Upgrade to a toned pill (ok/warn/danger) matching style appendix |

### Message list & message

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.chat.messages` | node | panel | (aria-live polite) | `renderMessages` rebuilds full list each frame; coalesced via rAF during streaming; scroll-pinned to bottom | yes | yes (list w/ optimistic stream) | `AIChatWidget.tsx` | Keep | |
| `ai.chat.messages.empty` | leaf | label | "Type a message to start…" etc. | varies by active/archived/empty | unsure | yes (equivalent empty states) | `AIChatWidget.tsx` | Keep | |
| `ai.chat.messages.message` | node | panel | — | `article.ai-message-{role}`; meta / body / foot; user right-aligned, assistant left | yes | yes (basic bubble) | `AIChatWidget.tsx` | Keep | Basic bubble exists; rebuild missing sub-parts |
| `ai.chat.messages.message.mode-chip` | leaf | pill | "Chat"/"Agent" | `runModeLabel(messageRunMode)` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.messages.message.speak` | leaf | button(icon) | play/pause — "Read this response aloud" | `toggleAiSpeech` → Kokoro service `POST /api/ai-tts/speech` or browser SpeechSynthesis | yes (parity, TTS) | no | `AIChatWidget.tsx` | Rebuild | Depends on st.ai TTS settings |
| `ai.chat.messages.message.stop-speech` | leaf | button(icon) | stop — "Stop reading" | `stopAiSpeech` | yes (parity, TTS) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.messages.message.copy-md` | leaf | button(icon) | copy — "Copy markdown" | `buildMessageMarkdown` → clipboard; Shift/Alt = diagnostics | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.messages.message.resend` | leaf | button | "Resend" | user messages only; `resendMessage` re-streams content | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.messages.message.time` | leaf | label | timestamp | `formatAiTime(created_at)` | unsure | yes | `AIChatWidget.tsx` | Keep | |
| `ai.chat.messages.message.body` | leaf | panel | rendered markdown | `renderMarkdown` (marked + DOMPurify + hljs); code blocks get header + Copy btn | yes (parity) | partial: plain text only (`whitespace-pre-wrap`) | `AIChatWidget.tsx` | Rebuild | Add markdown rendering (marked + DOMPurify + hljs) + code block copy button |
| `ai.chat.messages.message.foot` | leaf | label | provider · model · ms · tokens | `messageStats` (↑in ↓out tok, tok/s, finish) + `renderContextStatus` (chat mode) | unsure | no | `AIChatWidget.tsx` | Defer | Token/latency stats are nice-to-have; add after core parity is complete |
| `ai.chat.messages.message.context-status` | node | panel | "Context {pct}%" + meter | token window meter; live budget chars; sources/trimmed counts | unsure | no | `AIChatWidget.tsx` | Defer | Token window visualization; complex, defer after foot |

### Agent activity disclosure (agent mode)

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.chat.messages.message.activity` | node | dialog/details | "Agent activity"/"Thinking now" | `renderAgentActivityDisclosure`; open-state persisted per message id; streams `agent_run/iteration/tool` events | yes (parity, agent) | no | `AIChatWidget.tsx` | Rebuild | Agent events are ignored in new app; this is a major gap for agent mode |
| `ai.chat.…activity.flow` | node | panel | flow nodes | `renderAgentFlow`: run-start, context-used, iteration(s), done, fallback nodes | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | Cascades from activity |
| `ai.chat.…activity.tool-card` | leaf | details | tool name · args · result · ms | `renderAgentFlowToolCard`; expandable args/result JSON | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.…activity.context-step` | leaf | details | "Context" injected result | `prompt_context_tool_calls` rows | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.chat.messages.message.intent-panel` | node | panel | "Rover intent" | `renderIntentPanel`: type/summary/confidence/target/candidates/missing | unsure | no | `AIChatWidget.tsx` | Defer | Intent display is unsure in plan; defer until intent system is validated |
| `ai.chat.messages.message.retrieval-panel` | node | panel | "Retrieval surfaces" + "Sources" citations | `renderRetrievalPanel`; citation links → `/docs/{path}#{slug}` | yes (parity, RAG) | no | `AIChatWidget.tsx` | Rebuild | RAG citations are a parity gap; link with ADR 0028 |
| `ai.chat.thinking` | leaf | icon | (animated rings) | `.ai-thinking` pending spinner in disclosure summary | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | Thinking animation for in-flight agent activity |

### Composer

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.composer` | node | form | — | `form#ai-message-form.ai-composer`; submit → `sendMessage` | yes | yes | `AIChatWidget.tsx` | Keep | |
| `ai.composer.input` | leaf | textarea | placeholder "Ask anything" (varies by mode/archived) | autosize ≤220px; Enter sends, Shift+Enter newline; `/` opens slash menu | yes | yes (basic textarea, no autosize/slash) | `AIChatWidget.tsx` | Rebuild | Add autosize, slash-menu trigger, archived placeholder |
| `ai.composer.slash-menu` | node | listbox | slash commands | `renderSlashMenu`; ↑↓ navigate, Tab/Enter apply, Esc close | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.slash-menu.item` | leaf | option | command + description | 5 commands (see Session commands) | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.actions` | node | panel | — | run-mode / sources / status / inline-actions, wrap | yes | partial | `AIChatWidget.tsx` | Keep | Scaffold exists; rebuild missing children |
| `ai.composer.run-mode.chat` | leaf | button | "Chat" | `updateSessionRunMode('chat')` `PATCH …{mode:general_chat}` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.run-mode.agent` | leaf | button | "Agent" | `updateSessionRunMode('agent')` `PATCH …{mode:agent}`; default active; warns if provider lacks tools | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.sources-toggle` | leaf | button | "Sources" + count "N/M" + caret | opens popover; Alt+S shortcut; disabled w/o session | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.sources-popover` | node | dialog | "Source Controls" | `role=dialog`; closes on outside-click / Esc | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.sources-popover.count` | leaf | pill | "N/M enabled" | from `normalizeSourceControls` | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.sources-popover.item` | leaf | toggle(checkbox) | 7 sources (project_docs, mission_history, replay_reports, ai_chat_history, settings_config, sensor_context, web_research) | `updateSessionSourceControl(key, checked)` `PATCH …{source_controls}`; gates optional agent tools | yes (parity, RAG) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.status` | leaf | label | "Create or open a session to begin." | `#ai-status` banner mirrors status-pill text | yes (parity) | partial: "pinned/created" hint | `AIChatWidget.tsx` | Rebuild | Upgrade to full status text matching legacy |
| `ai.composer.retry` | leaf | button | "Retry response" | `retryResponse` → `POST …/retry/stream`; disabled while sending/archived | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.composer.stop` | leaf | button | "Stop" | aborts in-flight stream via AbortController | yes (parity) | yes | `AIChatWidget.tsx` | Keep | |
| `ai.composer.send` | leaf | button(submit) | "Send" | `sendMessage` → `POST /api/ai/sessions/{id}/messages/stream` ({content, run_mode}); creates session if none; JSON-lines stream | yes | yes | `AIChatWidget.tsx` | Keep | |

### Session commands (slash) & cross-cutting behaviors

| id | kind | type | text | behavior / data | planned? | implemented? | target | decision | notes |
|----|------|------|------|-----------------|----------|--------------|--------|----------|-------|
| `ai.cmd.capabilities-brief` | leaf | command | "/capabilities brief" | `POST …/commands {command}` else local fallback; lists surfaces + tools (brief) | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | Slash menu command; cascades from slash-menu node |
| `ai.cmd.capabilities-full` | leaf | command | "/capabilities full" | surfaces + full tool catalog | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.cmd.retrieval-surfaces` | leaf | command | "/retrieval-surfaces" | enabled surfaces + availability | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.cmd.tool-activity` | leaf | command | "/tool-activity" | latest recorded agent tool activity | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | |
| `ai.cmd.context` | leaf | command | "/context" | latest context snapshot (providers, retrieval, loaded blocks) | yes (parity) | no | `AIChatWidget.tsx` | Rebuild | Local `formatContextMarkdown` |
| `ai.behavior.multi-session-streaming` | node | (behavior) | — | `_sessionLive` Map keeps per-session streams alive on switch; concurrent independent streams | unsure | partial: per-panel pinned session, single stream | `AIChatWidget.tsx` | Defer | Complex multi-stream map; current per-panel pinning is sufficient for now |
| `ai.behavior.inflight-resume` | node | (behavior) | — | `localStorage[gcs-ai-inflight-stream]` + `GET …/stream-status`; reconnect with `?resume=1` on reload | no | no | `AIChatWidget.tsx` | Defer | Reconnect on reload; nice-to-have, not critical for parity |
| `ai.behavior.auto-read-tts` | leaf | (behavior) | — | auto-speak assistant message when `ai_settings.tts.auto_read`; `GET /api/ai-settings` | yes (parity, TTS) | no | `AIChatWidget.tsx` | Rebuild | Triggered by st.ai.auto-read setting; requires TTS settings rebuild |
| `ai.behavior.timezone-header` | leaf | (behavior) | — | every fetch adds `X-Operator-Timezone` header | no | no | `data/aiChat.ts` | Rebuild | Add tz header to all GCS fetch calls in the data layer |

## 2. Style appendix (lossless backstop)

Values keyed by `id`; `@ style.css:<line>` is the authoritative source. Node rows
carry layout; leaf rows carry appearance. Spacing lives once on the parent.

### Layout (nodes)

- `ai.chat-shell` — CSS grid `minmax(240px,var(--ai-sidebar-width)) 6px minmax(0,1fr)` / rows `minmax(420px,var(--ai-shell-height)) 10px`; areas `sidebar splitter chat` + `footer`; `row-gap:4px`. Tokens: `--ai-sidebar-width:340px`, `--ai-shell-height:680px`, `--ai-card-radius:14px`, `--ai-card-padding-y:13px`, `--ai-card-padding-x:14px`, `--ai-card-shadow`/`-hover`. `@ style.css:2700`
- `ai.sidebar` — grid rows `auto auto minmax(0,1fr)`; `gap:12px`; `padding:12px 6px 12px 12px`; `border:1px color-mix(--line 64%)`; `border-radius:18px`; `background:color-mix(--panel 88%,--panel-strong)`; `box-shadow:var(--ai-card-shadow)`. `@ style.css:2734`
- `ai.layout-resizer` — `grid-area:splitter`; `width:6px`; `border-radius:5px`; gradient handle; hover/focus accent. `@ style.css:2748`
- `ai.height-resizer` — horizontal splitter `grid-area:footer`-row, `height:10px`. `@ style.css:2770`
- `ai.chat-head / sidebar-head / composer-actions / provider-strip` — shared flex row, `align-items:center`, `justify-content:space-between`. `@ style.css:2819`
- `ai.chat-actions` — flex; `gap:8px`; `width:min(760px,100%)`; `margin-left:auto`. `@ style.css:3036`
- `ai.sidebar.list` — scroll column. `@ style.css:2894`
- `ai.sidebar.list.row` — grid; `gap:4px`; `padding:10px`; `border:1px color-mix(--line 52%)`; `border-radius:10px`; `background:color-mix(--panel-strong 54%)`; hover/active raise accent border+bg; focus `outline:2px accent`. `@ style.css:2905`
- `ai.chat.messages` — `.ai-message-list` scroll column. `@ style.css:3237`
- `ai.chat.messages.message` — `width:min(100%,860px)`; grid `gap:8px`; `padding:13px 14px` (card tokens); `border-radius:14px`; card shadow; hover raises shadow+accent border. user: `justify-self:end`, `width:min(92%,860px)`, `background:color-mix(--accent-soft 64%,--panel-strong)`. assistant: `justify-self:start`. `@ style.css:3258`
- `ai.composer` — grid `gap:12px`; `padding-top:14px`; `border-top:1px color-mix(--line 72%)`; `z-index:8`. `@ style.css:5950`
- `ai.composer.actions` — flex-wrap; `gap:12px`; `justify-content:flex-start`. `@ style.css:6041`
- `ai.composer.slash-menu` — absolute above input; `bottom:calc(100% + 12px)`; grid `gap:8px`; `max-height:min(360px,46vh)`; `padding:10px`; `border-radius:16px`; `box-shadow:0 22px 48px rgba(0,0,0,.28)`; `backdrop-filter:blur(14px)`. `@ style.css:5981`
- `ai.composer.run-mode` — inline-flex; `gap:4px`; `padding:3px`; `border-radius:9px`; segmented bg. `@ style.css:6048`
- `ai.composer.sources-popover` — absolute panel; head + note + list. `@ style.css:3153`
- `ai.map-area` — `@ style.css:4299`; mobile override `@ style.css:5611`.

### Appearance (leaves)

- `*.pill` — `padding:6px 10px`; `border-radius:999px`; `background:var(--button-secondary-bg)`; `color:var(--muted)`; `font-size:.85rem`. Variants `.ok`→accent-strong/ok-bg, `.warn`→warn/warn-bg, `.danger`→danger/danger-bg. `@ style.css:553`
- `ai.chat.head.{rename,archive,copy}` — `.ai-chat-icon-btn` 36×36; `border-radius:8px`; icon 18px; CSS `::after` tooltip from `data-tooltip`. `@ style.css:3055`
- `ai.sidebar.list.row.title` — ellipsis; `font-weight:650`; `font-size:.98rem`. `@ style.css:2950`
- `ai.sidebar.list.row.count` — `min-width:28px`; `padding:2px 6px`; `border-radius:999px`; `font-size:.7rem`. `@ style.css:2961`
- `ai.sidebar.list.row.{archive,delete}` — `.ai-session-action` 24×20; `border-radius:6px`; `font-size:.78rem`. `@ style.css:2979`
- `ai.sidebar.list.row.title-input` — `min-height:34px`; `padding:6px 8px`; `font-weight:700`. `@ style.css:2991`
- `ai.chat.messages.message.mode-chip` — inline-flex; `padding:2px 7px`; accent border; `border-radius:999px`; `background:color-mix(--accent-soft 45%)`. `@ style.css:3292`
- `ai.chat.messages.message.{speak,copy-md,resend}` — ghost icon buttons; `.ai-message-speak-icon` 24×24 viewBox; tooltip `::after`; `.active` accent. `@ style.css:3314`
- `ai.composer.input` — `min-height:96px`; `max-height:220px`; `resize:vertical`; `padding:12px 14px`; `line-height:1.42`; `border:1px var(--line)`; `border-radius:14px`; `background:var(--panel-strong)`. `@ style.css:5965`
- `ai.composer.slash-menu.item` — grid `minmax(140px,180px) minmax(0,1fr)`; `padding:11px 12px`; `border-radius:12px`; hover/active accent + `translateY(-1px)`. command: mono `.83rem` 600; description: `--muted .8rem`. `@ style.css:6003`
- `ai.composer.run-mode.{chat,agent}` — `min-height:30px`; `padding-inline:12px`; `border-radius:6px`; `.active`→accent border + `var(--button-active-gradient)`. `@ style.css:6057`
- `ai.composer.sources-toggle` — `min-height:32px`; `padding:4px 10px`; `.has-enabled` count accent. `@ style.css:3123`
- `ai.composer.status` — `flex:1 1 200px`; `font-size:.82rem`; `color:var(--muted)`. `@ style.css:6076`
- `ai.composer.{retry,stop,send}` — `.inline-actions` buttons `min-height:34px`; submit `padding-inline:18px`. `@ style.css:6087`
- `ai.chat.messages.message.context-status` — label/value `.ai-context-status`; meter `.ai-context-status-meter-fill` width = pct. `@ style.css:5746`
- `ai.chat.thinking` — `.ai-thinking-core` + 3 `.ai-thinking-rings>span` animated; reduced-motion override `@ style.css:5943`. `@ style.css:5791`
- code blocks — `.code-block-wrapper` header `.code-block-lang` + `.code-copy-btn` ("Copy"→"Copied!"). `@ style.css:5664`
- agent flow — `.ai-flow-node` connectors via `::before`; start/end vs error dot color; `.ai-activity-step` details. `@ style.css:3887`, `3484`
- retrieval/citation — `.ai-retrieval-row`, `.ai-citation-link` accent link. `@ style.css:3704`, `3817`
- intent — `.ai-intent-row` label/value, `.ai-intent-warn`. `@ style.css:4005`

### Theme tokens (referenced above, defined at `:root`/`[data-theme]`)

`--accent`, `--accent-soft`, `--accent-strong`, `--line`, `--muted`, `--text`,
`--panel`, `--panel-strong`, `--bg`/`--bg-base`, `--warn`/`--warn-bg`,
`--danger`/`--danger-bg`, `--ok-bg`, `--button-secondary-bg`,
`--button-active-gradient`. Resolve in `style.css` `:root` block when porting exact
colors.
