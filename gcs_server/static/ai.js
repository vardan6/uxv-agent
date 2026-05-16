const aiState = {
  sessions: [],
  providers: [],
  routing: {},
  activeSession: null,
  editingSessionId: '',
  showArchived: false,
  runMode: 'chat',
  messageListPinnedToBottom: true,
  slashMenuItems: [],
  slashMenuIndex: 0,
  activeSpeechMessageId: '',
  activeSpeechUtterance: null,
  activeSpeechAudio: null,
  activeSpeechAudioUrl: '',
  activeSpeechAbortController: null,
  activeSpeechPaused: false,
  aiSettings: {
    tts: {
      enabled: true,
      engine: 'kokoro_service',
      auto_read: false,
      service_url: 'http://127.0.0.1:9101',
      voice: 'af_sky',
      format: 'wav',
      speed: 1,
      browser_fallback: true,
      voice_name: '',
      rate: 1,
      pitch: 1,
    },
  },
  messageActivityOpen: {},
};

const AI_SOURCE_CONTROL_META = {
  project_docs: {
    label: 'Project docs',
    description: 'Planned RAG source for internal docs and design notes.',
  },
  mission_history: {
    label: 'Mission history',
    description: 'Use stored mission drafts and approval records.',
  },
  replay_reports: {
    label: 'Replay reports',
    description: 'Allow replay summaries and analytics tools.',
  },
  ai_chat_history: {
    label: 'AI chat history',
    description: 'Bounded retrieval from saved AI sessions and messages.',
  },
  settings_config: {
    label: 'Settings/config',
    description: 'Use compact settings context and safe section lookups.',
  },
  sensor_context: {
    label: 'Sensor context',
    description: 'Use metadata-only camera/video freshness and runtime sensor status.',
  },
  web_research: {
    label: 'Web research',
    description: 'Planned external research source. Not active yet.',
  },
};

const AI_ALWAYS_ALLOWED_TOOL_NAMES = new Set([
  'list_data_surfaces',
  'get_current_rover_state',
  'get_scene_summary',
  'query_objects_in_front',
  'query_objects_near',
  'query_objects_by_kind',
  'query_objects_to_left',
  'query_objects_to_right',
  'query_nearest_objects',
  'resolve_spatial_target',
  'get_current_mission_state',
]);

const AI_OPTIONAL_TOOL_NAMES_BY_SOURCE = {
  replay_reports: new Set([
    'get_current_replay_summary',
    'get_recent_telemetry',
    'list_replay_sessions',
    'resolve_replay_sessions',
    'get_replay_session_summary',
    'get_replay_session_metrics',
    'get_replay_session_path',
    'search_replay_session_events',
    'compare_replay_sessions',
    'aggregate_replay_sessions',
  ]),
  ai_chat_history: new Set([
    'list_ai_sessions',
    'search_ai_messages',
    'get_ai_session_messages',
  ]),
  settings_config: new Set([
    'get_settings_summary',
    'get_settings_section',
    'get_llm_provider_summary',
  ]),
  sensor_context: new Set([
    'get_sensor_status',
  ]),
};

const AI_AGENT_TOOL_DEFINITIONS = [
  {
    name: 'list_data_surfaces',
    permission: 'read_only',
    description: 'List every bounded data surface available to this session, show which source controls currently enable them, and identify the exact tools that can load each surface. Call this first when you need to discover where replay history, AI chat history, settings/config, or sensor metadata can be retrieved from.',
  },
  {
    name: 'get_current_rover_state',
    permission: 'read_only',
    description: 'Get the current rover telemetry snapshot captured for this request, including pose, heading, freshness, battery, speed, and camera state. If live telemetry is stale or unavailable, inspect last_known_replay_state for the latest recorded rover values and source session.',
  },
  {
    name: 'get_scene_summary',
    permission: 'read_only',
    description: 'Get the current terrain scene summary, including bounds, road count, object count, object kinds, spawn point, and site name. Use this before object queries when the operator asks what exists on the map or in the loaded scene.',
  },
  {
    name: 'query_objects_in_front',
    permission: 'read_only',
    description: 'Find map objects in front of the rover within max_distance_m and fov_deg. Use this for prompts about what is ahead, in front, straight ahead, on the route ahead, or visible in a forward cone. Optional kinds filters the returned object kinds. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg.',
  },
  {
    name: 'query_objects_near',
    permission: 'read_only',
    description: 'Find map objects near the rover within radius_m. Use this for prompts about nearby, around the rover, close objects, or surroundings. If the operator provides hypothetical map coordinates, pass them as position or coordinates.',
  },
  {
    name: 'query_objects_by_kind',
    permission: 'read_only',
    description: 'Find all map objects whose kind exactly matches the given kind string. Use this when the operator names an object type such as tree, rock, road, building, or waypoint.',
  },
  {
    name: 'query_objects_to_left',
    permission: 'read_only',
    description: 'Find map objects to the rover\'s left. Use this for prompts about left side, port side, left flank, or objects off the left of the rover. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg.',
  },
  {
    name: 'query_objects_to_right',
    permission: 'read_only',
    description: 'Find map objects to the rover\'s right. Use this for prompts about right side, starboard side, right flank, or objects off the right of the rover. If the operator provides hypothetical map coordinates, pass them as position or coordinates and optionally heading_deg.',
  },
  {
    name: 'query_nearest_objects',
    permission: 'read_only',
    description: 'Find nearest map objects to the rover. Use this when the operator asks what is closest or nearest, optionally constrained by max_distance_m or kinds. If the operator provides hypothetical map coordinates, pass them as position or coordinates.',
  },
  {
    name: 'resolve_spatial_target',
    permission: 'planning',
    description: 'Resolve a structured spatial target description against the current map and rover pose. Use this to turn a described target such as a rock on the left or the nearest tree into concrete candidate objects. Target objects may also include position or coordinates and optionally heading_deg.',
  },
  {
    name: 'get_current_mission_state',
    permission: 'read_only',
    description: 'Get the current mission state. This is read-only.',
  },
  {
    name: 'get_current_replay_summary',
    permission: 'read_only',
    description: 'Get the active replay session summary.',
  },
  {
    name: 'get_recent_telemetry',
    permission: 'read_only',
    description: 'Get recent telemetry samples from the active replay session.',
  },
  {
    name: 'list_replay_sessions',
    permission: 'analysis',
    description: 'List replay sessions with started_at, ended_at, telemetry_count, control_count, and runtime_event_count. Use this to enumerate sessions, fetch latest/first sessions, or gather candidates before comparing or ranking by metrics.',
  },
  {
    name: 'resolve_replay_sessions',
    permission: 'analysis',
    description: 'Resolve a natural-language replay session selector such as all sessions, latest 5 sessions, first session, or a date-based selector into explicit session_ids.',
  },
  {
    name: 'get_replay_session_summary',
    permission: 'read_only',
    description: 'Get a replay session summary by session_id.',
  },
  {
    name: 'get_replay_session_metrics',
    permission: 'analysis',
    description: 'Get computed replay analytics metrics for a session_id, including duration_s, path_length_m, net_displacement_m, and max_distance_from_start_m.',
  },
  {
    name: 'get_replay_session_path',
    permission: 'analysis',
    description: 'Get downsampled replay path points for a session_id.',
  },
  {
    name: 'search_replay_session_events',
    permission: 'analysis',
    description: 'Search runtime events within a replay session.',
  },
  {
    name: 'compare_replay_sessions',
    permission: 'analysis',
    description: 'Compare multiple replay sessions by explicit session_ids. Returns per-session summaries and metrics so you can rank, sort, and answer longest/furthest questions. Travel distance means path_length_m. Furthest from home/start means max_distance_from_start_m.',
  },
  {
    name: 'aggregate_replay_sessions',
    permission: 'analysis',
    description: 'Aggregate replay analytics across resolved selector results or explicit session_ids. Use this for totals, averages, built-in longest/latest/furthest summaries, and ranked top-N session lists. Travel distance means path_length_m. Furthest from home/start means max_distance_from_start_m.',
  },
  {
    name: 'list_ai_sessions',
    permission: 'analysis',
    description: 'List saved AI chat sessions with bounded metadata, message counts, archival state, and latest-message previews. Call this before `get_ai_session_messages` when you need a specific session_id, or before `search_ai_messages` when the operator refers to earlier chats without naming the session.',
  },
  {
    name: 'search_ai_messages',
    permission: 'analysis',
    description: 'Search saved AI messages by text across the current session or across saved sessions and return bounded match snippets with session/message references. Use this when the operator asks about earlier answers, prior discussions, or something that was said before and you need to locate the right session or message window.',
  },
  {
    name: 'get_ai_session_messages',
    permission: 'read_only',
    description: 'Load a bounded window of saved AI messages from one session. If session_id is omitted, use the current AI session. Call this after `list_ai_sessions` or `search_ai_messages` when you need the surrounding conversation, not just a preview or search snippet.',
  },
  {
    name: 'get_settings_summary',
    permission: 'read_only',
    description: 'Get the safe compact settings summary available to AI flows, including which top-level sections exist, key non-secret configuration summaries, and the settings path. Call this first before requesting one section with `get_settings_section` or checking provider/routing state with `get_llm_provider_summary`.',
  },
  {
    name: 'get_settings_section',
    permission: 'read_only',
    description: 'Get one safe settings section by name. Supported sections are `mqtt`, `key_bindings`, `video`, `gcs`, `simulation`, `map`, `ai_settings`, and `settings_path`. Call `get_settings_summary` first if you need section discovery or a compact overview. This tool never exposes secrets.',
  },
  {
    name: 'get_llm_provider_summary',
    permission: 'read_only',
    description: 'Get safe LLM provider and model-routing metadata, including enabled providers, active chat-provider resolution, and routing rules without exposing secrets. Use this when the operator asks which provider/model path is active or how AI routing is configured.',
  },
  {
    name: 'get_sensor_status',
    permission: 'read_only',
    description: 'Get metadata-only sensor and video status, including telemetry freshness, camera freshness, configured video delivery, and current perception limitations. Use this for questions about whether the agent can currently see live camera data or rely on sensor freshness. This tool does not expose raw frames, detections, or vision inference output.',
  },
];

// Per-session live state — keyed by session ID.
// Each entry tracks: messages (including in-progress pending), sending flag,
// abort controller, and pending message IDs. This allows multiple sessions to
// stream concurrently and independently, so switching sessions does not
// interrupt or corrupt an in-flight response.
const _sessionLive = new Map();

function liveStateFor(sessionId) {
  if (!_sessionLive.has(sessionId)) {
    _sessionLive.set(sessionId, {
      messages: [],
      sending: false,
      pendingUserMessageId: '',
      pendingAssistantMessageId: '',
      abortController: null,
      // Phase 2: workbench interrupt/resume state
      pendingInterrupt: null,  // { threadId, approvalPayload } when graph is suspended
      workbenchThreadId: '',
      scrollTop: 0,
      pinnedToBottom: true,
    });
  }
  return _sessionLive.get(sessionId);
}

function isSending() {
  const id = aiState.activeSession?.id;
  return id ? liveStateFor(id).sending : false;
}

function activeAbortController() {
  const id = aiState.activeSession?.id;
  return id ? liveStateFor(id).abortController : null;
}

function isMessageActivityOpen(messageId, pending = false) {
  const key = String(messageId || '');
  if (!key) return Boolean(pending);
  if (Object.prototype.hasOwnProperty.call(aiState.messageActivityOpen, key)) {
    return Boolean(aiState.messageActivityOpen[key]);
  }
  return Boolean(pending);
}

function setMessageActivityOpen(messageId, open) {
  const key = String(messageId || '');
  if (!key) return;
  aiState.messageActivityOpen[key] = Boolean(open);
}

const AI_LAYOUT_WIDTH_KEY = 'gcs-ai-sidebar-width';
const AI_LAYOUT_HEIGHT_KEY = 'gcs-ai-chat-shell-height';
const AI_SIDEBAR_MIN = 240;
const AI_SIDEBAR_MAX = 560;
const AI_SHELL_HEIGHT_MIN = 420;
const AI_SHELL_HEIGHT_MAX = 1100;
const AI_MOBILE_QUERY = '(max-width: 1100px)';
const AI_ARCHIVED_SESSION_LIMIT = 500;
const AI_INFLIGHT_MARKER_KEY = 'gcs-ai-inflight-stream';
let sessionOpenTimer = 0;

const aiEls = {
  shell: document.querySelector('.ai-chat-shell'),
  newSession: document.getElementById('ai-new-session'),
  showActive: document.getElementById('ai-show-active'),
  showArchived: document.getElementById('ai-show-archived'),
  layoutResizer: document.getElementById('ai-layout-resizer'),
  heightResizer: document.getElementById('ai-height-resizer'),
  sessionSearch: document.getElementById('ai-session-search'),
  sessionList: document.getElementById('ai-session-list'),
  sessionTitle: document.getElementById('ai-session-title'),
  providerSelect: document.getElementById('ai-provider-select'),
  providerPill: document.getElementById('ai-provider-pill'),
  statusPill: document.getElementById('ai-status-pill'),
  sourceControls: document.getElementById('ai-source-controls'),
  sourcesControl: document.querySelector('[data-ai-sources-control]'),
  sourcesToggle: document.getElementById('ai-sources-toggle'),
  sourcesToggleCount: document.getElementById('ai-sources-toggle-count'),
  sourcesPopover: document.getElementById('ai-sources-popover'),
  sourcesPopoverCount: document.getElementById('ai-sources-popover-count'),
  renameSession: document.getElementById('ai-rename-session'),
  archiveSession: document.getElementById('ai-archive-session'),
  messageList: document.getElementById('ai-message-list'),
  messageForm: document.getElementById('ai-message-form'),
  messageInput: document.getElementById('ai-message-input'),
  slashMenu: document.getElementById('ai-slash-menu'),
  retryResponse: document.getElementById('ai-retry-response'),
  stopMessage: document.getElementById('ai-stop-message'),
  sendMessage: document.getElementById('ai-send-message'),
  status: document.getElementById('ai-status'),
  runModeButtons: document.querySelectorAll('[data-run-mode]'),
};

function loadInflightMarker() {
  try {
    const raw = window.localStorage.getItem(AI_INFLIGHT_MARKER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const sessionId = String(parsed.sessionId || '').trim();
    const endpoint = String(parsed.endpoint || '').trim();
    if (!sessionId || !endpoint) return null;
    return { sessionId, endpoint };
  } catch (_) {
    return null;
  }
}

function saveInflightMarker(sessionId, endpoint) {
  if (!sessionId || !endpoint) return;
  try {
    window.localStorage.setItem(AI_INFLIGHT_MARKER_KEY, JSON.stringify({
      sessionId: String(sessionId),
      endpoint: String(endpoint),
      updatedAt: Date.now(),
    }));
  } catch (_) {
    // Best effort only.
  }
}

function clearInflightMarker(sessionId = '') {
  try {
    const marker = loadInflightMarker();
    if (!marker) return;
    if (sessionId && marker.sessionId !== sessionId) return;
    window.localStorage.removeItem(AI_INFLIGHT_MARKER_KEY);
  } catch (_) {
    // Ignore storage errors.
  }
}

async function serverStreamInProgress(sessionId) {
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/stream-status`);
  return Boolean(result?.in_progress);
}

async function aiFetchJson(url, options = {}) {
  const response = await fetch(url, withAiTimezone(options));
  if (!response.ok) {
    let detail = await response.text();
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.detail || detail;
    } catch (_) {
      // Use the raw response body.
    }
    throw new Error(detail || `${response.status}`);
  }
  return response.json();
}

function operatorTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch (_) {
    return '';
  }
}

function withAiTimezone(options = {}) {
  const timezone = operatorTimezone();
  const headers = new Headers(options.headers || {});
  if (timezone) {
    headers.set('X-Operator-Timezone', timezone);
  }
  return { ...options, headers };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function normalizeSourceControls(value) {
  const source = value && typeof value === 'object' ? value : {};
  const out = {};
  Object.keys(AI_SOURCE_CONTROL_META).forEach((key) => {
    if (key === 'project_docs' || key === 'mission_history' || key === 'replay_reports') {
      out[key] = source[key] !== false;
    } else {
      out[key] = Boolean(source[key]);
    }
  });
  return out;
}

let _markdownReady = false;

function ensureMarkdown() {
  if (_markdownReady || typeof marked === 'undefined') return;
  _markdownReady = true;
  marked.use({
    breaks: true,
    gfm: true,
    renderer: {
      code({ text, lang }) {
        const language = (lang || '').split(/\s/)[0];
        const displayLang = language || 'plain';
        const safeCode = text
          .replaceAll('&', '&amp;')
          .replaceAll('<', '&lt;')
          .replaceAll('>', '&gt;');
        return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-block-lang">${displayLang}</span><button class="code-copy-btn" type="button">Copy</button></div><pre><code class="language-${escapeHtml(language || 'plaintext')}">${safeCode}</code></pre></div>`;
      },
    },
  });
}

const _MARKDOWN_PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    'h1','h2','h3','h4','h5','h6',
    'p','br','strong','em','b','i','u','s','del','mark',
    'code','pre','blockquote','hr',
    'ul','ol','li',
    'a','img',
    'table','thead','tbody','tr','th','td',
    'div','span','button',
  ],
  ALLOWED_ATTR: ['href','title','alt','src','class','type','rel','target'],
  KEEP_CONTENT: true,
};

function renderMarkdown(content) {
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    return escapeHtml(content);
  }
  ensureMarkdown();
  const rawHtml = marked.parse(String(content || ''));
  return DOMPurify.sanitize(rawHtml, _MARKDOWN_PURIFY_CONFIG);
}

function postRenderMessages() {
  const list = aiEls.messageList;
  const activeLive = aiState.activeSession ? liveStateFor(aiState.activeSession.id) : null;
  const isStreaming = Boolean(activeLive?.pendingAssistantMessageId);

  // Syntax highlight only when not streaming (avoids re-running hljs on every delta)
  if (typeof hljs !== 'undefined' && !isStreaming) {
    list.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
  }

  // Copy raw markdown button
  list.querySelectorAll('.ai-message-copy-md').forEach(btn => {
    btn.addEventListener('click', () => {
      const md = btn.dataset.md || '';
      navigator.clipboard.writeText(md).then(() => {
        btn.innerHTML = aiCheckIcon();
        btn.dataset.tooltip = 'Copied!';
        setTimeout(() => {
          btn.innerHTML = aiCopyIcon();
          btn.dataset.tooltip = 'Copy markdown';
        }, 1500);
      }).catch(() => {});
    });
  });

  // Re-attach copy button handlers (DOM is rebuilt each render)
  list.querySelectorAll('.code-copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const code = btn.closest('.code-block-wrapper')?.querySelector('code');
      if (!code) return;
      navigator.clipboard.writeText(code.textContent).then(() => {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
      }).catch(() => {});
    });
  });
}

function fmtTokens(n) {
  const value = Number(n);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value >= 10000) return `${Math.round(value / 1000)}K`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(Math.round(value));
}

function fmtTokPerSec(n) {
  if (!Number.isFinite(n) || n <= 0) return '';
  if (n >= 10) return `${Math.round(n)} tok/s`;
  return `${n.toFixed(1)} tok/s`;
}

function messageStats(message) {
  const meta = message.meta || {};
  const rm = meta.response_metadata || {};
  const latencyMs = message.latency_ms;

  // OpenAI-compatible (NIM, vLLM, OpenAI) + LangChain usage_metadata
  const usage = meta.usage_metadata || rm.usage_metadata || rm.token_usage || rm.usage || {};
  let inputTok = usage.prompt_tokens ?? usage.input_tokens ?? usage.input_token_details?.total_tokens ?? null;
  let outputTok = usage.completion_tokens ?? usage.output_tokens ?? usage.output_token_details?.total_tokens ?? null;
  const totalTok = usage.total_tokens ?? null;
  if (inputTok == null) inputTok = usage.input_tokens ?? usage.prompt_tokens ?? null;
  if (outputTok == null) outputTok = usage.output_tokens ?? usage.completion_tokens ?? null;

  // Ollama shape
  if (inputTok === null && rm.prompt_eval_count != null) inputTok = rm.prompt_eval_count;
  if (outputTok === null && rm.eval_count != null) outputTok = rm.eval_count;

  // tok/s: prefer Ollama's precise eval_duration (nanoseconds), else wall-clock latency
  let tokPerSec = null;
  if (outputTok != null) {
    if (rm.eval_duration > 0) {
      tokPerSec = outputTok / (rm.eval_duration / 1e9);
    } else if (latencyMs > 0) {
      tokPerSec = outputTok / (latencyMs / 1000);
    }
  }

  const finishReason = rm.finish_reason || rm.stop_reason || null;
  const showFinish = finishReason && finishReason !== 'stop' && finishReason !== 'end_turn';

  // Context window fill — from provider config
  const provider = providerById(message.provider_id || '');
  const ctxMax = provider?.context_window || null;

  const parts = [];
  if (inputTok != null && ctxMax) {
    const pct = Math.round((Number(inputTok) / Number(ctxMax)) * 100);
    parts.push(`ctx ${fmtTokens(inputTok)}/${fmtTokens(ctxMax)} (${pct}%)`);
  } else if (inputTok != null) {
    parts.push(`↑${fmtTokens(inputTok)}`);
  }
  if (outputTok != null) parts.push(`↓${fmtTokens(outputTok)} tok`);
  else if (inputTok == null && totalTok != null) parts.push(`tok ${fmtTokens(totalTok)}`);
  if (tokPerSec != null) parts.push(fmtTokPerSec(tokPerSec));
  if (showFinish) parts.push(`[${finishReason}]`);
  return parts.join(' · ');
}

function agentToolCalls(message) {
  const meta = message.meta || {};
  if (Array.isArray(meta.agent_tool_progress) && meta.agent_tool_progress.length) {
    return meta.agent_tool_progress;
  }
  if (Array.isArray(meta.tool_calls) && meta.tool_calls.length) {
    return meta.tool_calls.map((call) => ({ ...call, status: 'complete' }));
  }
  return [];
}

function agentTraceEvents(message) {
  const meta = message?.meta || {};
  return Array.isArray(meta.agent_trace) ? meta.agent_trace : [];
}

function summarizeAgentToolResult(result) {
  if (result == null) return '';
  if (typeof result !== 'object') return String(result);
  if (result.ok === false && result.error) return `error: ${result.error}`;
  if (Array.isArray(result)) return `${result.length} item${result.length === 1 ? '' : 's'}`;
  if (Array.isArray(result.objects)) return `${result.objects.length} object${result.objects.length === 1 ? '' : 's'}`;
  if (Array.isArray(result.sessions)) return `${result.sessions.length} session${result.sessions.length === 1 ? '' : 's'}`;
  if (typeof result.available === 'boolean' && !result.available) return result.reason || result.error || 'unavailable';
  const keys = Object.keys(result).filter((key) => result[key] != null);
  return keys.slice(0, 4).join(', ');
}

function summarizeAgentToolArgs(args) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return '';
  const entries = Object.entries(args).filter(([, value]) => value != null && value !== '');
  if (!entries.length) return '';
  return entries.slice(0, 3).map(([key, value]) => {
    if (Array.isArray(value)) return `${key}: ${value.length} item${value.length === 1 ? '' : 's'}`;
    if (typeof value === 'object') return `${key}: object`;
    return `${key}: ${String(value)}`;
  }).join(' · ');
}

function prettyAgentJson(value, maxChars = 3600) {
  if (value == null) return '';
  let text = '';
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  } catch (_) {
    text = String(value);
  }
  const normalized = String(text || '').trim();
  if (!normalized) return '';
  if (normalized.length <= maxChars) return escapeHtml(normalized);
  return `${escapeHtml(normalized.slice(0, maxChars))}\n…`;
}

function distinctAgentIterations(message) {
  const iterations = new Set();
  agentTraceEvents(message).forEach((event) => {
    const value = Number(event?.iteration ?? event?.tool_call?.iteration);
    if (Number.isFinite(value) && value > 0) iterations.add(value);
  });
  agentToolCalls(message).forEach((call) => {
    const value = Number(call?.iteration);
    if (Number.isFinite(value) && value > 0) iterations.add(value);
  });
  const metaIterations = Number(message?.meta?.agent_iterations);
  if (Number.isFinite(metaIterations) && metaIterations > 0) {
    for (let index = 1; index <= metaIterations; index += 1) iterations.add(index);
  }
  return Array.from(iterations).sort((a, b) => a - b);
}

function renderAgentToolRows(message) {
  const calls = agentToolCalls(message);
  return calls.map((call) => {
    const status = call.status || (call.result !== undefined ? 'complete' : 'running');
    const resultSummary = status === 'running' ? 'running' : summarizeAgentToolResult(call.result);
    const argsSummary = summarizeAgentToolArgs(call.args);
    const latency = Number.isFinite(call.latency_ms) ? ` · ${Math.round(call.latency_ms)} ms` : '';
    const iteration = Number.isFinite(call.iteration) ? `Iteration ${call.iteration}` : '';
    return `
      <details class="ai-activity-step ai-agent-tool-row ai-agent-tool-${escapeHtml(status)}">
        <summary>
          <span class="ai-agent-tool-dot" aria-hidden="true"></span>
          <span class="ai-activity-step-main">
            <span class="ai-agent-tool-name">${escapeHtml(call.name || 'tool')}</span>
            <span class="ai-activity-step-meta">
              ${iteration ? `<span>${escapeHtml(iteration)}</span>` : ''}
              ${argsSummary ? `<span>${escapeHtml(argsSummary)}</span>` : ''}
            </span>
          </span>
          <span class="ai-agent-tool-status">${escapeHtml(resultSummary || status)}${latency}</span>
        </summary>
        <div class="ai-activity-step-body">
          ${call.args && typeof call.args === 'object' && Object.keys(call.args).length
            ? `<div class="ai-activity-block"><div class="ai-activity-block-label">Arguments</div><pre>${prettyAgentJson(call.args, 2400)}</pre></div>`
            : ''}
          ${call.result !== undefined
            ? `<div class="ai-activity-block"><div class="ai-activity-block-label">Result</div><pre>${prettyAgentJson(call.result)}</pre></div>`
            : '<div class="ai-activity-note">Waiting for tool result.</div>'}
        </div>
      </details>
    `;
  }).join('');
}

function renderPromptContextRows(message) {
  const promptCalls = Array.isArray(message?.meta?.prompt_context_tool_calls)
    ? message.meta.prompt_context_tool_calls
    : [];
  if (!promptCalls.length) return '';
  const rows = promptCalls.map((call) => {
    const summary = summarizeAgentToolResult(call?.result);
    return `
      <details class="ai-activity-step">
        <summary>
          <span class="ai-activity-step-kind">Context</span>
          <span class="ai-activity-step-main">
            <span class="ai-agent-tool-name">${escapeHtml(call?.name || 'context')}</span>
          </span>
          <span class="ai-agent-tool-status">${escapeHtml(summary || 'available')}</span>
        </summary>
        <div class="ai-activity-step-body">
          <div class="ai-activity-block">
            <div class="ai-activity-block-label">Injected result</div>
            <pre>${prettyAgentJson(call?.result)}</pre>
          </div>
        </div>
      </details>
    `;
  }).join('');
  return `
    <section class="ai-activity-section">
      <div class="ai-activity-section-title">Context used</div>
      <div class="ai-activity-step-list">${rows}</div>
    </section>
  `;
}

function renderAgentTraceChips(message) {
  const trace = agentTraceEvents(message);
  const chips = trace.map((event) => {
    if (!event || typeof event !== 'object') return '';
    if (event.type === 'agent_iteration_start') {
      return `<span class="ai-activity-chip">Iteration ${escapeHtml(String(event.iteration || '?'))}</span>`;
    }
    if (event.type === 'agent_run_end') {
      return `<span class="ai-activity-chip">Done · ${escapeHtml(String(event.stop_reason || 'complete'))}</span>`;
    }
    if (event.type === 'agent_run_start') {
      return `<span class="ai-activity-chip">Agent run</span>`;
    }
    return '';
  }).filter(Boolean).join('');
  if (!chips) return '';
  return `
    <section class="ai-activity-section">
      <div class="ai-activity-section-title">Run trace</div>
      <div class="ai-activity-chip-row">${chips}</div>
    </section>
  `;
}

function renderAgentActivityDisclosure(message, options = {}) {
  const pending = Boolean(options.pending);
  const mode = messageRunMode(message);
  if (mode !== 'agent') return '';
  const calls = agentToolCalls(message);
  const trace = agentTraceEvents(message);
  const promptCalls = Array.isArray(message?.meta?.prompt_context_tool_calls)
    ? message.meta.prompt_context_tool_calls
    : [];
  const fallbackError = String(message?.meta?.agent_tool_fallback_error || '').trim();
  const iterations = distinctAgentIterations(message);
  const hasContent = calls.length || trace.length || promptCalls.length || fallbackError || pending;
  if (!hasContent) return '';

  const title = pending ? 'Thinking now' : 'Agent activity';
  const status = calls.some((call) => (call?.status || '') === 'running')
    ? 'running'
    : (pending ? 'pending' : 'complete');
  const summaryParts = [];
  if (iterations.length) summaryParts.push(`${iterations.length} iteration${iterations.length === 1 ? '' : 's'}`);
  if (calls.length) summaryParts.push(`${calls.length} tool${calls.length === 1 ? '' : 's'}`);
  const stateLabel = pending
    ? (calls.length ? 'Live' : 'Starting')
    : (calls.length ? 'Complete' : 'Recorded');
  const toolRows = renderAgentToolRows(message);
  const openAttr = isMessageActivityOpen(message.id, pending) ? ' open' : '';

  return `
    <details class="ai-activity-disclosure ai-activity-${escapeHtml(status)}${pending ? ' ai-activity-live' : ''}" data-message-disclosure="activity" data-message-id="${escapeHtml(message.id)}"${openAttr}>
      <summary>
        <span class="ai-activity-summary-main">
          ${pending
            ? `<span class="ai-thinking ai-thinking-inline" role="status" aria-live="polite" aria-label="Assistant is working">
                <span class="ai-thinking-core" aria-hidden="true"></span>
                <span class="ai-thinking-rings" aria-hidden="true">
                  <span></span><span></span><span></span>
                </span>
              </span>`
            : '<span class="ai-activity-caret" aria-hidden="true"></span>'}
          <span class="ai-activity-title">${escapeHtml(title)}</span>
        </span>
        <span class="ai-activity-summary-side">
          <span class="ai-activity-state ai-activity-state-${escapeHtml(status)}">${escapeHtml(stateLabel)}</span>
          ${summaryParts.length
            ? `<span class="ai-activity-summary-meta">${escapeHtml(summaryParts.join(' · '))}</span>`
            : ''}
        </span>
      </summary>
      <div class="ai-activity-panel">
        ${renderAgentTraceChips(message)}
        ${toolRows
          ? `<section class="ai-activity-section">
              <div class="ai-activity-section-title">Tools used</div>
              <div class="ai-activity-step-list">${toolRows}</div>
            </section>`
          : (pending ? '<div class="ai-activity-note">Waiting for the first tool call.</div>' : '')}
        ${renderPromptContextRows(message)}
        ${fallbackError
          ? `<section class="ai-activity-section">
              <div class="ai-activity-section-title">Fallback</div>
              <div class="ai-activity-note">${escapeHtml(fallbackError)}</div>
            </section>`
          : ''}
      </div>
    </details>
  `;
}

function renderIntentPanel(message) {
  const meta = message?.meta || {};
  const intent = meta.intent;
  if (!intent) return '';

  const intentType = escapeHtml(intent.intent_type || 'unknown');
  const summary = escapeHtml(intent.summary || '');
  const confidence = Number.isFinite(intent.confidence) ? `${Math.round(intent.confidence * 100)}%` : '—';
  const requiresMotion = intent.requires_rover_motion ? 'Yes — operator approval required' : 'No';

  const target = intent.target || {};
  const targetParts = [
    target.description ? `"${escapeHtml(String(target.description))}"` : null,
    target.kind ? `kind: ${escapeHtml(String(target.kind))}` : null,
    target.side ? `side: ${escapeHtml(String(target.side))}` : null,
    target.max_distance_m != null ? `max ${escapeHtml(String(target.max_distance_m))} m` : null,
  ].filter(Boolean).join(' · ');

  const missing = Array.isArray(intent.missing_information) && intent.missing_information.length
    ? `<div class="ai-intent-row"><span class="ai-intent-label">Missing</span><span class="ai-intent-value ai-intent-warn">${intent.missing_information.map((s) => escapeHtml(String(s))).join(', ')}</span></div>`
    : '';

  const parseErrors = Array.isArray(meta.parse_errors) && meta.parse_errors.length
    ? `<div class="ai-intent-row"><span class="ai-intent-label">Parse errors</span><span class="ai-intent-value ai-intent-warn">${meta.parse_errors.map((s) => escapeHtml(String(s))).join('; ')}</span></div>`
    : '';

  const resolution = meta.target_resolution || {};
  let candidateRows = '';
  if (Array.isArray(resolution.candidates) && resolution.candidates.length) {
    const items = resolution.candidates.slice(0, 5).map((c) => {
      const label = escapeHtml(c.label || c.kind || c.id || 'object');
      const dist = Number.isFinite(c.distance_m) ? ` · ${c.distance_m} m` : '';
      const side = c.side ? ` · ${escapeHtml(c.side)}` : '';
      const selected = c === resolution.selected ? ' ✓' : '';
      return `<li>${label}${dist}${side}${selected}</li>`;
    }).join('');
    candidateRows = `<div class="ai-intent-row"><span class="ai-intent-label">Candidates</span><ul class="ai-intent-candidates">${items}</ul></div>`;
  } else if (resolution.available === false) {
    candidateRows = `<div class="ai-intent-row"><span class="ai-intent-label">Target</span><span class="ai-intent-value ai-intent-warn">Rover pose or scene unavailable</span></div>`;
  } else if (resolution.needs_clarification) {
    candidateRows = `<div class="ai-intent-row"><span class="ai-intent-label">Target</span><span class="ai-intent-value ai-intent-warn">Needs clarification</span></div>`;
  }

  return `
    <div class="ai-intent-panel" aria-label="Parsed rover intent">
      <div class="ai-intent-title">Rover intent</div>
      <div class="ai-intent-row"><span class="ai-intent-label">Type</span><span class="ai-intent-value">${intentType}</span></div>
      ${summary ? `<div class="ai-intent-row"><span class="ai-intent-label">Summary</span><span class="ai-intent-value">${summary}</span></div>` : ''}
      <div class="ai-intent-row"><span class="ai-intent-label">Confidence</span><span class="ai-intent-value">${confidence}</span></div>
      <div class="ai-intent-row"><span class="ai-intent-label">Requires motion</span><span class="ai-intent-value">${requiresMotion}</span></div>
      ${targetParts ? `<div class="ai-intent-row"><span class="ai-intent-label">Target</span><span class="ai-intent-value">${targetParts}</span></div>` : ''}
      ${candidateRows}
      ${missing}
      ${parseErrors}
    </div>
  `;
}

function renderRetrievalPanel(message) {
  const meta = message?.meta || {};
  const request = meta.retrieval_request || {};
  const sources = Array.isArray(meta.retrieved_sources) ? meta.retrieved_sources : [];
  if (!sources.length) return '';
  const citations = Array.isArray(meta.retrieval_citations) ? meta.retrieval_citations : [];
  const loadedRefs = Array.isArray(meta.loaded_data_refs) ? meta.loaded_data_refs : [];
  const usedSources = sources.filter((source) => source?.requested || source?.loaded || source?.status === 'loaded_summary');
  if (!usedSources.length && !citations.length && !loadedRefs.length) return '';
  const visibleSources = usedSources.length ? usedSources : sources;

  const enabled = Array.isArray(request.enabled_sources) ? request.enabled_sources : [];
  const scope = String(request.request_scope || '');
  const rows = visibleSources.map((source) => {
    const label = AI_SOURCE_CONTROL_META[source.source]?.label || source.source || 'source';
    const status = source.status || 'planned';
    const requested = source.requested ? '<span class="ai-retrieval-pill">lazy</span>' : '';
    const note = source.note ? `<div class="ai-retrieval-note">${escapeHtml(String(source.note))}</div>` : '';
    return `
      <li class="ai-retrieval-row">
        <div class="ai-retrieval-row-top">
          <span class="ai-retrieval-name">${escapeHtml(label)}</span>
          <span class="ai-retrieval-status">${escapeHtml(status)}</span>
          ${requested}
        </div>
        ${note}
      </li>
    `;
  }).join('');

  return `
    <div class="ai-retrieval-panel" aria-label="Retrieval surfaces">
      <div class="ai-retrieval-title">Retrieval surfaces</div>
      <div class="ai-retrieval-meta">
        ${scope ? `<span>scope: ${escapeHtml(scope)}</span>` : ''}
        ${enabled.length ? `<span>enabled: ${escapeHtml(enabled.join(', '))}</span>` : ''}
      </div>
      <ul class="ai-retrieval-list">${rows}</ul>
    </div>
  `;
}

function renderSourceControls() {
  if (!aiEls.sourceControls) return;
  const session = aiState.activeSession;
  const sourceControls = normalizeSourceControls(session?.source_controls);
  const disabled = !session || Boolean(session.archived_at) || isSending();
  const sourceKeys = Object.keys(AI_SOURCE_CONTROL_META);
  const enabledCount = sourceKeys.filter((key) => sourceControls[key]).length;
  const totalCount = sourceKeys.length;
  const items = sourceKeys.map((key) => {
    const meta = AI_SOURCE_CONTROL_META[key];
    return `
      <label class="ai-source-control-item">
        <input
          type="checkbox"
          data-source-control="${escapeHtml(key)}"
          ${sourceControls[key] ? 'checked' : ''}
          ${disabled ? 'disabled' : ''}
        >
        <span class="ai-source-control-copy">
          <strong>${escapeHtml(meta.label)}</strong>
          <span>${escapeHtml(meta.description)}</span>
        </span>
      </label>
    `;
  }).join('');
  aiEls.sourceControls.innerHTML = items;
  if (aiEls.sourcesToggleCount) {
    aiEls.sourcesToggleCount.textContent = `${enabledCount}/${totalCount}`;
  }
  if (aiEls.sourcesPopoverCount) {
    aiEls.sourcesPopoverCount.textContent = `${enabledCount}/${totalCount} enabled`;
  }
  if (aiEls.sourcesToggle) {
    aiEls.sourcesToggle.disabled = !session;
    aiEls.sourcesToggle.classList.toggle('has-enabled', enabledCount > 0);
    if (!session) closeSourcesPopover();
  }
}

function isSourcesPopoverOpen() {
  return aiEls.sourcesPopover && !aiEls.sourcesPopover.hidden;
}

function openSourcesPopover(options = {}) {
  if (!aiEls.sourcesPopover || !aiEls.sourcesToggle) return;
  if (aiEls.sourcesToggle.disabled) return;
  aiEls.sourcesPopover.hidden = false;
  aiEls.sourcesToggle.setAttribute('aria-expanded', 'true');
  if (options.focusFirst) {
    const firstControl = aiEls.sourcesPopover.querySelector('input, button');
    firstControl?.focus();
  }
}

function closeSourcesPopover() {
  if (!aiEls.sourcesPopover || !aiEls.sourcesToggle) return;
  aiEls.sourcesPopover.hidden = true;
  aiEls.sourcesToggle.setAttribute('aria-expanded', 'false');
}

function toggleSourcesPopover() {
  if (isSourcesPopoverOpen()) closeSourcesPopover();
  else openSourcesPopover();
}

async function sendIntentTestRequest(sessionId, content, abortController) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  const response = await fetch(`/api/ai/sessions/${encodeURIComponent(sessionId)}/intent-test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Operator-Timezone': timezone },
    body: JSON.stringify({ content, timezone }),
    signal: abortController.signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Intent test failed (${response.status})`);
  }
  const result = await response.json();
  const live = liveStateFor(sessionId);
  if (Array.isArray(result.user_message) || result.user_message) {
    const msgs = live.messages.filter((m) => !m.id?.startsWith('pending-'));
    if (result.user_message) msgs.push(result.user_message);
    if (result.assistant_message) msgs.push(result.assistant_message);
    live.messages = msgs;
  }
}

async function sendSessionCommand(sessionId, command) {
  const response = await fetch(`/api/ai/sessions/${encodeURIComponent(sessionId)}/commands`, withAiTimezone({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
  }));
  if (response.ok) {
    return response.json();
  }
  if (response.status === 404) {
    return runLocalSessionCommand(sessionId, command);
  }
  const data = await response.json().catch(() => ({}));
  throw new Error(data.detail || `Command failed (${response.status})`);
}

function toolPermissionLabel(value) {
  const labels = {
    read_only: 'read-only',
    analysis: 'analysis',
    planning: 'planning',
    command_staging: 'command staging',
    execution: 'execution',
  };
  const key = String(value || '').trim().toLowerCase();
  return labels[key] || key || 'unknown';
}

function formatRetrievalSurfacesMarkdown(session) {
  const sourceControls = normalizeSourceControls(session?.source_controls);
  const enabled = Object.entries(AI_SOURCE_CONTROL_META).filter(([key]) => sourceControls[key]);
  const disabled = Object.entries(AI_SOURCE_CONTROL_META).filter(([key]) => !sourceControls[key]);
  const lines = ['## Retrieval Surfaces', ''];
  if (enabled.length) {
    lines.push('Enabled for this session:');
    enabled.forEach(([key, meta]) => {
      const status = key === 'web_research' ? 'planned' : 'available';
      lines.push(`- \`${meta.label}\`: ${status}`);
      if (meta.description) {
        lines.push(`  ${meta.description}`);
      }
    });
  } else {
    lines.push('No retrieval surfaces are enabled for this session.');
  }
  if (disabled.length) {
    lines.push('', 'Disabled for this session:');
    disabled.forEach(([, meta]) => {
      lines.push(`- \`${meta.label}\``);
    });
  }
  return lines.join('\n').trim();
}

function allowedToolNamesForSourceControls(sourceControls) {
  const normalized = normalizeSourceControls(sourceControls);
  const allowed = new Set(AI_ALWAYS_ALLOWED_TOOL_NAMES);
  Object.entries(AI_OPTIONAL_TOOL_NAMES_BY_SOURCE).forEach(([sourceKey, toolNames]) => {
    if (!normalized[sourceKey]) return;
    toolNames.forEach((name) => allowed.add(name));
  });
  return allowed;
}

function formatToolCatalogMarkdownBrief(session) {
  const allowed = allowedToolNamesForSourceControls(session?.source_controls);
  const tools = AI_AGENT_TOOL_DEFINITIONS.filter((tool) => allowed.has(tool.name));
  const count = tools.length;
  const noun = count === 1 ? 'tool' : 'tools';
  const lines = ['## Agent Tools', '', `${count} ${noun} available in agent mode.`, ''];
  tools.forEach((tool) => {
    lines.push(`- **\`${tool.name}\`**: ${tool.description}`);
  });
  return lines.join('\n').trim();
}

function formatToolCatalogMarkdownFull(session) {
  const allowed = allowedToolNamesForSourceControls(session?.source_controls);
  const tools = AI_AGENT_TOOL_DEFINITIONS.filter((tool) => allowed.has(tool.name));
  const count = tools.length;
  const noun = count === 1 ? 'tool' : 'tools';
  const lines = ['## Agent Tools', '', `${count} ${noun} available in agent mode.`];
  tools.forEach((tool) => {
    lines.push(
      '',
      `### \`${tool.name}\``,
      `- Permission: \`${toolPermissionLabel(tool.permission)}\``,
      `- Description: ${tool.description}`,
    );
  });
  return lines.join('\n').trim();
}

function formatAgentToolActivityMarkdown(sessionId) {
  const messages = liveStateFor(sessionId).messages || [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (String(message?.role || '') !== 'assistant') continue;
    const meta = message?.meta && typeof message.meta === 'object' ? message.meta : {};
    let toolCalls = Array.isArray(meta.agent_tool_progress) ? meta.agent_tool_progress : [];
    if (!toolCalls.length && Array.isArray(meta.tool_calls)) {
      toolCalls = meta.tool_calls;
    }
    if (!toolCalls.length) continue;
    const lines = ['## Agent Tool Activity', ''];
    if (message.created_at) {
      lines.push(`Latest assistant message: \`${formatAiTime(message.created_at)}\``);
      lines.push('');
    }
    toolCalls.forEach((call) => {
      if (!call || typeof call !== 'object') return;
      const name = String(call.name || call.tool || 'tool');
      const status = String(call.status || (call.result != null ? 'complete' : 'recorded'));
      lines.push(`- \`${name}\`: ${status}`);
    });
    return lines.join('\n').trim();
  }
  return '## Agent Tool Activity\n\nNo agent tool activity has been recorded in this session yet.';
}

function buildLocalSessionCommandResponse(sessionId, command) {
  const session = aiState.activeSession?.id === sessionId
    ? aiState.activeSession
    : aiState.sessions.find((item) => item.id === sessionId);
  const normalized = String(command || '').trim().toLowerCase();
  if (!session) {
    throw new Error('AI session not found');
  }
  if (normalized === 'retrieval-surfaces') {
    return { rawCommand: '/retrieval-surfaces', assistantContent: formatRetrievalSurfacesMarkdown(session) };
  }
  if (normalized === 'tool-activity') {
    return { rawCommand: '/tool-activity', assistantContent: formatAgentToolActivityMarkdown(sessionId) };
  }
  if (normalized === 'capabilities brief') {
    return {
      rawCommand: '/capabilities brief',
      assistantContent: `${formatRetrievalSurfacesMarkdown(session)}\n\n${formatToolCatalogMarkdownBrief(session)}`,
    };
  }
  if (normalized === 'capabilities full') {
    return {
      rawCommand: '/capabilities full',
      assistantContent: `${formatRetrievalSurfacesMarkdown(session)}\n\n${formatToolCatalogMarkdownFull(session)}`,
    };
  }
  throw new Error(`unsupported command '${command}'`);
}

function applySessionPreviewUpdate(sessionId, assistantContent, timestamp) {
  aiState.sessions = aiState.sessions.map((session) => {
    if (session.id !== sessionId) return session;
    return {
      ...session,
      updated_at: timestamp,
      message_count: Number(session.message_count || 0) + 2,
      last_message: assistantContent,
    };
  });
  if (aiState.activeSession?.id === sessionId) {
    aiState.activeSession = {
      ...aiState.activeSession,
      updated_at: timestamp,
      message_count: Number(aiState.activeSession.message_count || 0) + 2,
      last_message: assistantContent,
    };
  }
}

function runLocalSessionCommand(sessionId, command) {
  const live = liveStateFor(sessionId);
  const { rawCommand, assistantContent } = buildLocalSessionCommandResponse(sessionId, command);
  const providerId = aiState.activeSession?.id === sessionId
    ? (activeProviderId() || generalChatProviderId())
    : generalChatProviderId();
  const timestamp = Date.now() / 1000;
  const userMessage = {
    id: `local-command-user-${crypto.randomUUID()}`,
    role: 'user',
    content: rawCommand,
    created_at: timestamp,
    provider_id: providerId,
    model_id: '',
    meta: { run_mode: 'chat', local_command: rawCommand, local_only: true },
  };
  const assistantMessage = {
    id: `local-command-assistant-${crypto.randomUUID()}`,
    role: 'assistant',
    content: assistantContent,
    created_at: timestamp,
    provider_id: providerId,
    model_id: '',
    latency_ms: 0,
    meta: { run_mode: 'chat', local_command: rawCommand, local_only: true },
  };
  live.messages = [...live.messages, userMessage, assistantMessage];
  applySessionPreviewUpdate(sessionId, assistantContent, timestamp);
  renderSessionList();
  if (aiState.activeSession?.id === sessionId) {
    renderMessages({ forceScrollBottom: true });
  }
  return { ok: true, user_message: userMessage, assistant_message: assistantMessage, local_fallback: true };
}

function mergeServerAndLocalMessages(serverMessages, existingMessages) {
  const serverList = Array.isArray(serverMessages) ? serverMessages : [];
  const existingList = Array.isArray(existingMessages) ? existingMessages : [];
  const localOnly = existingList.filter((message) => message?.meta?.local_only === true);
  if (!localOnly.length) {
    return [...serverList];
  }
  const merged = [...serverList];
  localOnly.forEach((message) => {
    if (!merged.some((item) => item?.id === message.id)) {
      merged.push(message);
    }
  });
  merged.sort((left, right) => {
    const leftTime = Number(left?.created_at || 0);
    const rightTime = Number(right?.created_at || 0);
    if (leftTime !== rightTime) return leftTime - rightTime;
    return String(left?.id || '').localeCompare(String(right?.id || ''));
  });
  return merged;
}

// ── Workbench streaming and approval ──────────────────────────────────────────

function handleWorkbenchStreamEvent(sessionId, eventData) {
  const live = liveStateFor(sessionId);
  if (eventData.type === 'graph_run_start') {
    live.workbenchThreadId = eventData.thread_id || '';
    setAiStatus('Workbench planning graph started.');
  } else if (eventData.type === 'graph_resume_start') {
    setAiStatus(`Submitting ${eventData.decision || 'decision'}...`);
  } else if (eventData.type === 'graph_node_result') {
    const node = String(eventData.node || '').replace(/_/g, ' ');
    setAiStatus(`Workbench: ${node}...`);
  } else if (eventData.type === 'graph_retrieval_result') {
    updatePendingRetrievalState(
      sessionId,
      eventData.retrieval_request || {},
      eventData.retrieved_sources || [],
      eventData.retrieval_citations || [],
    );
  } else if (eventData.type === 'mission_draft_created') {
    setAiStatus(`Draft created (${eventData.draft_id || '?'}). Awaiting approval.`);
  } else if (eventData.type === 'mission_draft_decision') {
    const status = eventData.approval_status || '';
    setAiStatus(`Draft ${status}.`, status === 'approved' ? 'ok' : 'warn');
  } else if (eventData.type === 'graph_interrupt') {
    live.pendingInterrupt = {
      threadId: eventData.thread_id || live.workbenchThreadId || '',
      approvalPayload: eventData.interrupt_value || {},
    };
    // Remove the spinner pending message — graph is paused, not running
    live.messages = live.messages.filter((m) => m.id !== live.pendingAssistantMessageId);
    live.pendingAssistantMessageId = '';
    const interruptType = (eventData.interrupt_value || {}).type || '';
    setAiStatus(
      interruptType === 'clarification_request'
        ? 'Clarification needed before planning can continue.'
        : 'Mission draft awaiting your approval.',
      'warn',
    );
    if (aiState.activeSession?.id === sessionId) renderMessages();
  } else if (eventData.type === 'graph_run_error') {
    throw new Error(String(eventData.error || 'Workbench graph error'));
  } else if (eventData.type === 'graph_run_end') {
    live.pendingInterrupt = null;
    setAiStatus('Workbench graph complete.', 'ok');
  }
  if (aiState.activeSession?.id === sessionId) renderMessages();
}

async function sendWorkbenchRequest(sessionId, content, abortController) {
  const url = `/api/ai/sessions/${encodeURIComponent(sessionId)}/workbench/stream`;
  const response = await fetch(url, withAiTimezone({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
    signal: abortController.signal,
  }));
  if (!response.ok) {
    let detail = await response.text();
    try { const p = JSON.parse(detail); detail = p.detail || detail; } catch (_) {}
    throw new Error(detail || `${response.status}`);
  }
  await readJsonLinesStream(response, (event) => handleWorkbenchStreamEvent(sessionId, event));
}

async function resumeWorkbenchApproval(sessionId, threadId, decision, note) {
  const live = liveStateFor(sessionId);
  live.pendingInterrupt = null;
  live.sending = true;
  const abortController = new AbortController();
  live.abortController = abortController;
  renderMessages();
  setAiStatus(`Submitting ${decision}...`);
  try {
    const url = `/api/ai/sessions/${encodeURIComponent(sessionId)}/workbench/thread/${encodeURIComponent(threadId)}/resume`;
    const response = await fetch(url, withAiTimezone({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, note: note || '' }),
      signal: abortController.signal,
    }));
    if (!response.ok) {
      let detail = await response.text();
      try { const p = JSON.parse(detail); detail = p.detail || detail; } catch (_) {}
      throw new Error(detail || `${response.status}`);
    }
    await readJsonLinesStream(response, (event) => handleWorkbenchStreamEvent(sessionId, event));
    await refreshSessionLive(sessionId);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    setAiStatus(isAbort ? 'Interrupted.' : (error.message || 'Approval failed.'), isAbort ? 'warn' : 'danger');
  } finally {
    clearSessionLiveState(sessionId);
    renderMessages();
  }
}

function renderWorkbenchApprovalCard(sessionId, interrupt) {
  const payload = interrupt.approvalPayload || {};
  if (payload.type === 'clarification_request') {
    return renderClarificationCard(sessionId, interrupt);
  }
  const threadId = interrupt.threadId || '';
  const safeThreadId = escapeHtml(threadId);
  const goal = escapeHtml(String(payload.goal || payload.summary || ''));
  const draftId = escapeHtml(String(payload.draft_id || ''));
  const revisionId = escapeHtml(String(payload.mission_revision_id || ''));
  const risks = Array.isArray(payload.risks) ? payload.risks : [];
  const routeSummary = payload.route_summary && typeof payload.route_summary === 'object' ? payload.route_summary : {};
  const waypointCount = Number(routeSummary.waypoint_count || 0);
  const distanceM = Number(routeSummary.total_distance_m || 0);
  const routeLabel = waypointCount > 0
    ? `${waypointCount} waypoint${waypointCount === 1 ? '' : 's'}${distanceM > 0 ? ` · ${distanceM.toFixed(1)} m` : ''}`
    : '';
  const riskItems = risks.length
    ? `<ul class="ai-approval-risks">${risks.map((r) => `<li>${escapeHtml(String(r))}</li>`).join('')}</ul>`
    : '';
  return `
    <div class="ai-approval-card" role="region" aria-label="Mission draft approval">
      <div class="ai-approval-title">Mission Draft — Awaiting Approval</div>
      ${draftId ? `<div class="ai-approval-row"><span class="ai-approval-label">Draft ID</span><span class="ai-approval-value">${draftId}</span></div>` : ''}
      ${revisionId ? `<div class="ai-approval-row"><span class="ai-approval-label">Revision ID</span><span class="ai-approval-value">${revisionId}</span></div>` : ''}
      ${goal ? `<div class="ai-approval-row"><span class="ai-approval-label">Goal</span><span class="ai-approval-value">${goal}</span></div>` : ''}
      ${routeLabel ? `<div class="ai-approval-row"><span class="ai-approval-label">Route</span><span class="ai-approval-value">${escapeHtml(routeLabel)}</span></div>` : ''}
      ${riskItems ? `<div class="ai-approval-row"><span class="ai-approval-label">Risks</span>${riskItems}</div>` : ''}
      <div class="ai-approval-note-row">
        <label class="ai-approval-note-label" for="ai-approval-note-input">Note (optional)</label>
        <input type="text" id="ai-approval-note-input" class="ai-approval-note-input" placeholder="Reason for approval or rejection…" />
      </div>
      <div class="ai-approval-actions">
        <button class="ai-approval-btn ai-approval-approve" type="button"
          data-approval-action="approve"
          data-thread-id="${safeThreadId}"
          data-session-id="${escapeHtml(sessionId)}">Approve</button>
        <button class="ai-approval-btn ai-approval-reject" type="button"
          data-approval-action="reject"
          data-thread-id="${safeThreadId}"
          data-session-id="${escapeHtml(sessionId)}">Reject</button>
      </div>
    </div>
  `;
}

function renderClarificationCard(sessionId, interrupt) {
  const payload = interrupt.approvalPayload || {};
  const threadId = interrupt.threadId || '';
  const safeThreadId = escapeHtml(threadId);
  const questions = Array.isArray(payload.questions) ? payload.questions : [];
  const intentSummary = escapeHtml(String(payload.intent_summary || ''));
  const questionItems = questions.map((q) => `<li>${escapeHtml(String(q))}</li>`).join('');
  return `
    <div class="ai-approval-card ai-clarification-card" role="region" aria-label="Clarification needed">
      <div class="ai-approval-title">Clarification Needed</div>
      ${intentSummary ? `<div class="ai-approval-row"><span class="ai-approval-label">Request</span><span class="ai-approval-value">${intentSummary}</span></div>` : ''}
      ${questionItems ? `<div class="ai-approval-row"><span class="ai-approval-label">Missing</span><ul class="ai-approval-risks ai-clarification-questions">${questionItems}</ul></div>` : ''}
      <div class="ai-approval-note-row">
        <label class="ai-approval-note-label" for="ai-clarification-input">Your answer</label>
        <textarea id="ai-clarification-input" class="ai-approval-note-input ai-clarification-input" rows="2" placeholder="Provide the missing information…"></textarea>
      </div>
      <div class="ai-approval-actions">
        <button class="ai-approval-btn ai-approval-approve" type="button"
          data-clarification-action="continue"
          data-thread-id="${safeThreadId}"
          data-session-id="${escapeHtml(sessionId)}">Continue</button>
        <button class="ai-approval-btn ai-approval-reject" type="button"
          data-clarification-action="cancel"
          data-thread-id="${safeThreadId}"
          data-session-id="${escapeHtml(sessionId)}">Cancel</button>
      </div>
    </div>
  `;
}

function formatAiTime(value) {
  if (!value) return '';
  return new Date(value * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function setAiStatus(text, level = 'warn') {
  aiEls.status.textContent = text;
  aiEls.statusPill.textContent = text;
  aiEls.statusPill.className = `pill ${level}`;
}

function activeProviderId() {
  return aiState.activeSession?.provider_id || aiEls.providerSelect.value || '';
}

function generalChatProviderId() {
  const rule = aiState.routing?.general_chat || {};
  return rule.primary_provider_id || '';
}

function currentProvider() {
  return providerById(activeProviderId() || generalChatProviderId());
}

function enabledChatProviders() {
  return aiState.providers.filter((provider) => provider.enabled !== false && (provider.capabilities || []).includes('chat'));
}

function providerLabel(provider) {
  if (!provider) return 'Routing default';
  return `${provider.display_name || provider.id} (${provider.model_id || 'no model'})`;
}

function providerById(providerId) {
  return aiState.providers.find((provider) => provider.id === providerId);
}

function providerNameForMessage(message) {
  const provider = providerById(message.provider_id || '');
  return provider?.display_name || message.provider_id || 'Unknown provider';
}

function normalizeRunMode(value) {
  const clean = String(value || '').trim().toLowerCase();
  if (clean === 'agent') return 'agent';
  if (clean === 'intent' || clean === 'rover_intent_test') return 'intent';
  if (clean === 'workbench') return 'workbench';
  return 'chat';
}

function sessionModeToRunMode(session) {
  const mode = normalizeRunMode(session?.mode);
  return mode === 'intent' || mode === 'workbench' ? 'agent' : mode;
}

function runModeToSessionMode(runMode) {
  const mode = normalizeRunMode(runMode);
  if (mode === 'agent') return 'agent';
  if (mode === 'intent') return 'rover_intent_test';
  if (mode === 'workbench') return 'workbench';
  return 'general_chat';
}

function currentRunMode() {
  return normalizeRunMode(aiState.runMode);
}

function messageRunMode(message) {
  return normalizeRunMode(message?.meta?.run_mode);
}

function runModeLabel(runMode) {
  const mode = normalizeRunMode(runMode);
  if (mode === 'agent') return 'Agent';
  if (mode === 'intent') return 'Intent Test';
  if (mode === 'workbench') return 'Workbench';
  return 'Chat';
}

function providerSupportsAgentMode(provider) {
  if (!provider) return true;
  const capabilities = Array.isArray(provider.capabilities) ? provider.capabilities : [];
  if (capabilities.includes('tool_calling') || capabilities.includes('planner')) {
    return true;
  }
  return String(provider.provider_type || '').trim().toLowerCase() !== 'ollama';
}

function providerToolsSupportLabel(provider) {
  if (!provider) return 'Tools: unknown';
  return providerSupportsAgentMode(provider) ? 'Tools: supported' : 'Tools: not supported';
}

function renderRunModeToggle() {
  const provider = currentProvider();
  const runMode = currentRunMode();
  const agentSupported = providerSupportsAgentMode(provider);
  aiEls.runModeButtons.forEach((button) => {
    const buttonRunMode = normalizeRunMode(button.dataset.runMode);
    const active = buttonRunMode === runMode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    button.disabled = isSending() || Boolean(aiState.activeSession?.archived_at);
    if (buttonRunMode === 'agent') {
      const title = agentSupported
        ? 'Use read-only rover tools when the provider supports tool calling'
        : 'This provider may fall back to plain agent chat without tool calls';
      button.title = title;
      button.setAttribute('aria-label', title);
    }
  });
}

function aiSpeechSupported() {
  return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
}

function cancelAiSpeech() {
  if (aiSpeechSupported()) {
    window.speechSynthesis.cancel();
  }
  if (aiState.activeSpeechAbortController) {
    aiState.activeSpeechAbortController.abort();
  }
  if (aiState.activeSpeechAudio) {
    aiState.activeSpeechAudio.pause();
    aiState.activeSpeechAudio.src = '';
  }
  if (aiState.activeSpeechAudioUrl) {
    URL.revokeObjectURL(aiState.activeSpeechAudioUrl);
  }
  aiState.activeSpeechMessageId = '';
  aiState.activeSpeechUtterance = null;
  aiState.activeSpeechAudio = null;
  aiState.activeSpeechAudioUrl = '';
  aiState.activeSpeechAbortController = null;
  aiState.activeSpeechPaused = false;
}

function aiTtsSettings() {
  return aiState.aiSettings?.tts || {};
}

function resolveAiSpeechVoice(voiceName) {
  if (!voiceName || !aiSpeechSupported()) return null;
  return window.speechSynthesis.getVoices().find((voice) => voice.name === voiceName) || null;
}

function waitForAiSpeechVoices(voiceName) {
  if (!voiceName || !aiSpeechSupported() || window.speechSynthesis.getVoices().length) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const finish = () => {
      window.clearTimeout(timeoutId);
      window.speechSynthesis.removeEventListener?.('voiceschanged', finish);
      resolve();
    };
    const timeoutId = window.setTimeout(finish, 800);
    if (window.speechSynthesis.addEventListener) {
      window.speechSynthesis.addEventListener('voiceschanged', finish, { once: true });
    } else if (window.speechSynthesis.onvoiceschanged === null) {
      window.speechSynthesis.onvoiceschanged = finish;
    }
  });
}

function aiTtsUsesService() {
  return aiTtsSettings().engine === 'kokoro_service';
}

function aiCanSpeak() {
  const tts = aiTtsSettings();
  return tts.enabled !== false && (aiTtsUsesService() || aiSpeechSupported());
}

function aiPlayIcon() {
  return `
    <svg class="ai-message-speak-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M8 6v12l10-6z"></path>
    </svg>
  `;
}

function aiPauseIcon() {
  return `
    <svg class="ai-message-speak-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M8 6h3v12H8z"></path>
      <path d="M13 6h3v12h-3z"></path>
    </svg>
  `;
}

function aiStopIcon() {
  return `
    <svg class="ai-message-speak-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 7h10v10H7z"></path>
    </svg>
  `;
}

function aiCopyIcon() {
  return `
    <svg class="ai-message-speak-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="9" y="2" width="10" height="14" rx="2"/>
      <path d="M5 6H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1"/>
    </svg>
  `;
}

function aiCheckIcon() {
  return `
    <svg class="ai-message-speak-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M20 6 9 17l-5-5"/>
    </svg>
  `;
}

function clearAiSpeechPlayback(messageId) {
  if (aiState.activeSpeechMessageId !== messageId) return;
  aiState.activeSpeechMessageId = '';
  aiState.activeSpeechUtterance = null;
  aiState.activeSpeechAudio = null;
  aiState.activeSpeechAudioUrl = '';
  aiState.activeSpeechAbortController = null;
  aiState.activeSpeechPaused = false;
  renderMessages({ preserveScroll: true });
}

async function pauseAiSpeech() {
  if (!aiState.activeSpeechMessageId || aiState.activeSpeechPaused) return;
  if (aiState.activeSpeechAudio) {
    aiState.activeSpeechAudio.pause();
    aiState.activeSpeechPaused = true;
    renderMessages({ preserveScroll: true });
    setAiStatus('Speech paused.', 'ok');
    return;
  }
  if (aiSpeechSupported() && window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
    window.speechSynthesis.pause();
    aiState.activeSpeechPaused = true;
    renderMessages({ preserveScroll: true });
    setAiStatus('Speech paused.', 'ok');
  }
}

async function resumeAiSpeech() {
  if (!aiState.activeSpeechMessageId || !aiState.activeSpeechPaused) return;
  if (aiState.activeSpeechAudio) {
    await aiState.activeSpeechAudio.play();
    aiState.activeSpeechPaused = false;
    renderMessages({ preserveScroll: true });
    setAiStatus('Speech resumed.', 'ok');
    return;
  }
  if (aiSpeechSupported() && (window.speechSynthesis.paused || aiState.activeSpeechUtterance)) {
    window.speechSynthesis.resume();
    aiState.activeSpeechPaused = false;
    renderMessages({ preserveScroll: true });
    setAiStatus('Speech resumed.', 'ok');
  }
}

function stopAiSpeech() {
  if (!aiState.activeSpeechMessageId) return;
  cancelAiSpeech();
  renderMessages({ preserveScroll: true });
  setAiStatus('Speech stopped.', 'ok');
}

async function toggleAiSpeech(messageId) {
  if (aiState.activeSpeechMessageId === messageId) {
    if (aiState.activeSpeechPaused) {
      await resumeAiSpeech();
    } else {
      await pauseAiSpeech();
    }
    return;
  }
  await speakAiMessage(messageId);
}

async function speakAiMessage(messageId) {
  if (aiTtsSettings().enabled === false) {
    setAiStatus('Text to speech is disabled in AI Settings.', 'warn');
    return;
  }
  if (!aiCanSpeak()) {
    setAiStatus('Text to speech is not supported by this browser.', 'warn');
    return;
  }
  const activeLive = aiState.activeSession ? liveStateFor(aiState.activeSession.id) : null;
  const message = (activeLive?.messages || []).find((item) => item.id === messageId);
  const content = String(message?.content || '').trim();
  if (!content) return;
  if (aiState.activeSpeechMessageId === messageId) {
    return;
  }

  cancelAiSpeech();
  aiState.activeSpeechMessageId = messageId;
  aiState.activeSpeechPaused = false;
  renderMessages({ preserveScroll: true });
  if (aiTtsUsesService()) {
    try {
      await speakAiMessageWithService(messageId, content);
      return;
    } catch (error) {
      aiState.activeSpeechAbortController = null;
      if (error?.name === 'AbortError') return;
      if (aiState.activeSpeechAudio) {
        aiState.activeSpeechAudio.pause();
        aiState.activeSpeechAudio.src = '';
      }
      if (aiState.activeSpeechAudioUrl) {
        URL.revokeObjectURL(aiState.activeSpeechAudioUrl);
      }
      aiState.activeSpeechAudio = null;
      aiState.activeSpeechAudioUrl = '';
      if (!aiTtsSettings().browser_fallback) {
        clearAiSpeechPlayback(messageId);
        setAiStatus(`Kokoro speech failed: ${error.message}`, 'warn');
        return;
      }
      setAiStatus('Kokoro speech failed. Falling back to browser voice.', 'warn');
    }
  }
  await speakAiMessageWithBrowser(messageId, content);
}

async function speakAiMessageWithService(messageId, content) {
  const tts = aiTtsSettings();
  const abortController = new AbortController();
  aiState.activeSpeechAbortController = abortController;
  setAiStatus('Requesting Kokoro voice audio.', 'ok');
  const response = await fetch('/api/ai-tts/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      input: content,
      voice: tts.voice || 'af_sky',
      format: tts.format || 'wav',
      speed: Number.isFinite(Number(tts.speed)) ? Number(tts.speed) : 1,
    }),
    signal: abortController.signal,
  });
  aiState.activeSpeechAbortController = null;
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  if (aiState.activeSpeechMessageId !== messageId) return;
  const blob = await response.blob();
  if (aiState.activeSpeechMessageId !== messageId) return;
  const audioUrl = URL.createObjectURL(blob);
  const audio = new Audio(audioUrl);
  audio.onended = () => {
    if (aiState.activeSpeechMessageId === messageId) {
      cancelAiSpeech();
      renderMessages({ preserveScroll: true });
    }
  };
  audio.onerror = () => {
    if (aiState.activeSpeechMessageId === messageId) {
      cancelAiSpeech();
      renderMessages({ preserveScroll: true });
      setAiStatus('Speech playback failed.', 'warn');
    }
  };
  aiState.activeSpeechAudio = audio;
  aiState.activeSpeechAudioUrl = audioUrl;
  aiState.activeSpeechPaused = false;
  await audio.play();
  renderMessages({ preserveScroll: true });
  setAiStatus('Reading assistant response with Kokoro.', 'ok');
}

async function speakAiMessageWithBrowser(messageId, content) {
  if (!aiSpeechSupported()) {
    setAiStatus('Text to speech is not supported by this browser.', 'warn');
    return;
  }
  const tts = aiTtsSettings();
  await waitForAiSpeechVoices(String(tts.voice_name || ''));
  if (aiState.activeSpeechMessageId !== messageId) return;
  const utterance = new SpeechSynthesisUtterance(content);
  const voice = resolveAiSpeechVoice(String(tts.voice_name || ''));
  if (voice) utterance.voice = voice;
  utterance.rate = Number.isFinite(Number(tts.rate)) ? Number(tts.rate) : 1;
  utterance.pitch = Number.isFinite(Number(tts.pitch)) ? Number(tts.pitch) : 1;
  utterance.onend = () => {
    if (aiState.activeSpeechMessageId === messageId) {
      aiState.activeSpeechMessageId = '';
      aiState.activeSpeechUtterance = null;
      renderMessages({ preserveScroll: true });
    }
  };
  utterance.onerror = () => {
    if (aiState.activeSpeechMessageId === messageId) {
      aiState.activeSpeechMessageId = '';
      aiState.activeSpeechUtterance = null;
      renderMessages({ preserveScroll: true });
      setAiStatus('Speech playback failed.', 'warn');
    }
  };
  aiState.activeSpeechUtterance = utterance;
  aiState.activeSpeechPaused = false;
  window.speechSynthesis.speak(utterance);
  renderMessages({ preserveScroll: true });
  setAiStatus('Reading assistant response.', 'ok');
}

async function loadAiSettings() {
  const result = await aiFetchJson('/api/ai-settings');
  aiState.aiSettings = result.ai_settings || aiState.aiSettings;
  if (aiTtsSettings().enabled === false) {
    cancelAiSpeech();
  }
}

function renderProviderSelect() {
  const selectedProviderId = aiState.activeSession?.provider_id || '';
  const defaultProvider = providerById(generalChatProviderId());
  const providers = enabledChatProviders();
  aiEls.providerSelect.innerHTML = [
    `<option value="">Routing default${defaultProvider ? `: ${escapeHtml(defaultProvider.display_name)}` : ''}</option>`,
    ...providers.map((provider) => (
      `<option value="${escapeHtml(provider.id)}"${provider.id === selectedProviderId ? ' selected' : ''}>${escapeHtml(providerLabel(provider))}</option>`
    )),
  ].join('');
  const active = selectedProviderId ? providerById(selectedProviderId) : defaultProvider;
  const toolsLabel = currentRunMode() === 'agent' ? ` · ${providerToolsSupportLabel(active)}` : '';
  aiEls.providerPill.textContent = `Provider: ${providerLabel(active)}${toolsLabel}`;
}

function filteredSessions() {
  const query = aiEls.sessionSearch.value.trim().toLowerCase();
  const visibleSessions = aiState.sessions.filter((session) => Boolean(session.archived_at) === aiState.showArchived);
  if (!query) return visibleSessions;
  return visibleSessions.filter((session) => {
    const haystack = `${session.title || ''} ${session.last_message || ''}`.toLowerCase();
    return haystack.includes(query);
  });
}

function renderSessionList() {
  const sessions = filteredSessions();
  if (!sessions.length) {
    aiEls.sessionList.innerHTML = `<p class="status-banner ai-session-empty">No ${aiState.showArchived ? 'archived ' : ''}sessions found.</p>`;
    return;
  }
  aiEls.sessionList.innerHTML = sessions.map((session) => {
    const active = aiState.activeSession?.id === session.id ? ' active' : '';
    const missionState = session.mission_state && typeof session.mission_state === 'object' ? session.mission_state : {};
    const missionStatus = String(missionState.status || '').trim();
    const missionGoal = String(missionState.goal || '').trim();
    const missionPreview = missionStatus && missionStatus !== 'no_active_mission'
      ? `Mission ${missionStatus.replace(/_/g, ' ')}${missionGoal ? ` · ${missionGoal}` : ''}`
      : '';
    const preview = missionPreview || session.last_message || 'No messages yet';
    const isEditing = aiState.editingSessionId === session.id;
    const missionMeta = missionStatus && missionStatus !== 'no_active_mission'
      ? ` · mission ${missionStatus.replace(/_/g, ' ')}`
      : '';
    return `
      <div class="ai-session-row${active}" tabindex="0" data-session-id="${escapeHtml(session.id)}" aria-label="Open ${escapeHtml(session.title || 'New chat')}">
        <span class="ai-session-row-main">
          <span class="ai-session-row-title-wrap">
            ${isEditing
              ? `<input class="ai-session-title-input" type="text" value="${escapeHtml(session.title || 'New chat')}" autocomplete="off" aria-label="Session name">`
              : `<span class="ai-session-row-title">${escapeHtml(session.title || 'New chat')}</span>`}
            <span class="ai-session-count">${session.message_count || 0}</span>
          </span>
          <span class="ai-session-actions">
            <button
              class="ghost ai-session-action ai-session-archive"
              type="button"
              data-action="toggle-archive-session"
              data-session-id="${escapeHtml(session.id)}"
              title="${session.archived_at ? 'Restore session' : 'Archive session'}"
              aria-label="${session.archived_at ? 'Restore session' : 'Archive session'}"
            >${session.archived_at ? '↺' : '📥'}</button>
            <button
              class="ghost ai-session-action ai-session-delete"
              type="button"
              data-action="delete-session"
              data-session-id="${escapeHtml(session.id)}"
              title="Delete session"
              aria-label="Delete session"
            >✕</button>
          </span>
        </span>
        <span class="ai-session-row-meta">${escapeHtml(formatAiTime(session.updated_at))} · ${session.message_count || 0} msg${escapeHtml(missionMeta)}</span>
        <span class="ai-session-row-preview">${escapeHtml(preview)}</span>
      </div>
    `;
  }).join('');
  if (aiState.editingSessionId) {
    const row = Array.from(aiEls.sessionList.querySelectorAll('[data-session-id]'))
      .find((item) => item.dataset.sessionId === aiState.editingSessionId);
    const input = row?.querySelector('.ai-session-title-input');
    if (input) {
      input.focus();
      input.select();
    }
  }
}

function isMessageListNearBottom(threshold = 40) {
  if (!aiEls.messageList) return true;
  const { scrollTop, scrollHeight, clientHeight } = aiEls.messageList;
  return (scrollHeight - clientHeight - scrollTop) <= threshold;
}

function saveSessionScrollState(sessionId = aiState.activeSession?.id) {
  if (!sessionId || !aiEls.messageList) return;
  const live = liveStateFor(sessionId);
  live.scrollTop = aiEls.messageList.scrollTop;
  live.pinnedToBottom = isMessageListNearBottom();
}

function updateMessageListScrollIntent() {
  aiState.messageListPinnedToBottom = isMessageListNearBottom();
  saveSessionScrollState();
}

function renderMessages(options = {}) {
  const preserveScroll = Boolean(options.preserveScroll);
  const forceScrollBottom = Boolean(options.forceScrollBottom);
  const restoreScrollTop = Number.isFinite(options.restoreScrollTop)
    ? Number(options.restoreScrollTop)
    : null;
  const previousScrollTop = aiEls.messageList.scrollTop;
  const shouldStickToBottom = forceScrollBottom || (!preserveScroll && aiState.messageListPinnedToBottom);
  const activeLive = aiState.activeSession ? liveStateFor(aiState.activeSession.id) : null;
  const messages = activeLive?.messages || [];
  const pendingAssistantId = activeLive?.pendingAssistantMessageId || '';
  const sending = Boolean(activeLive?.sending);
  const viewingArchived = Boolean(aiState.activeSession?.archived_at);
  aiEls.sessionTitle.textContent = aiState.activeSession?.title || 'New chat';
  aiEls.renameSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.textContent = viewingArchived ? 'Restore' : 'Archive';
  aiEls.archiveSession.title = viewingArchived ? 'Restore this archived chat' : 'Archive this chat';
  aiEls.retryResponse.disabled = !aiState.activeSession || sending || !messages.length || viewingArchived;
  aiEls.stopMessage.disabled = !sending || !activeLive?.abortController;
  aiEls.retryResponse.title = 'Retry the last model response without adding a new user message.';
  aiEls.retryResponse.setAttribute('aria-label', 'Retry the last model response');
  aiEls.messageInput.disabled = viewingArchived;
  aiEls.messageInput.placeholder = viewingArchived
    ? 'Restore this archived chat to continue messaging'
    : currentRunMode() === 'agent'
      ? 'Ask the read-only rover agent'
      : 'Ask the configured General Chat provider';
  aiEls.showArchived.setAttribute('aria-pressed', aiState.showArchived ? 'true' : 'false');
  aiEls.showActive.setAttribute('aria-pressed', aiState.showArchived ? 'false' : 'true');
  renderProviderSelect();
  renderRunModeToggle();
  updateComposerState();
  renderSourceControls();

  if (!aiState.activeSession) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${aiState.showArchived ? 'Open an archived chat to review it, or switch back to Active chats.' : 'Type a message to start a new chat.'}</div>`;
    return;
  }
  if (!messages.length) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${viewingArchived ? 'Archived chat has no messages.' : 'Start a new conversation.'}</div>`;
    return;
  }
  const pendingInterrupt = activeLive?.pendingInterrupt || null;
  const sessionIdForApproval = aiState.activeSession?.id || '';

  aiEls.messageList.innerHTML = messages.map((message) => {
    const isPendingAssistant = message.role === 'assistant'
      && message.id === pendingAssistantId
      && !String(message.content || '').trim();
    const mode = messageRunMode(message);
    const canSpeak = aiCanSpeak()
      && message.role === 'assistant'
      && !isPendingAssistant
      && Boolean(String(message.content || '').trim());
    const isSpeaking = aiState.activeSpeechMessageId === message.id;
    const isPaused = isSpeaking && aiState.activeSpeechPaused;
    const toggleLabel = !isSpeaking
      ? 'Read this response aloud'
      : (isPaused ? 'Resume reading this response' : 'Pause reading');
    const stopLabel = 'Stop reading';
    return `
    <article class="ai-message ai-message-${escapeHtml(message.role)}${isPendingAssistant ? ' ai-message-pending' : ''}">
      <div class="ai-message-meta">
        <strong>${message.role === 'assistant' ? `Assistant · ${escapeHtml(providerNameForMessage(message))}` : 'You'} <span class="ai-mode-chip">${escapeHtml(runModeLabel(mode))}</span></strong>
        <span class="ai-message-meta-actions">
          ${canSpeak
            ? `<button
                class="ghost ai-message-speak ai-message-tts-btn${isSpeaking && !isPaused ? ' active' : ''}"
                type="button"
                data-message-action="toggle-speech"
                data-message-id="${escapeHtml(message.id)}"
                data-tooltip="${escapeHtml(toggleLabel)}"
                title="${escapeHtml(toggleLabel)}"
                aria-label="${escapeHtml(toggleLabel)}"
                aria-pressed="${isSpeaking ? 'true' : 'false'}"
              >${isSpeaking && !isPaused ? aiPauseIcon() : aiPlayIcon()}</button>
              <button
                class="ghost ai-message-speak ai-message-tts-btn"
                type="button"
                data-message-action="stop-speech"
                data-message-id="${escapeHtml(message.id)}"
                data-tooltip="${escapeHtml(stopLabel)}"
                title="${escapeHtml(stopLabel)}"
                aria-label="${escapeHtml(stopLabel)}"
                ${isSpeaking ? '' : 'disabled'}
              >${aiStopIcon()}</button>`
            : ''}
          ${message.role === 'assistant' && !isPendingAssistant && String(message.content || '').trim()
            ? `<button
                class="ghost ai-message-copy-md"
                type="button"
                data-message-action="copy-md"
                data-message-id="${escapeHtml(message.id)}"
                data-md="${escapeHtml(message.content)}"
                data-tooltip="Copy markdown"
                title="Copy markdown"
                aria-label="Copy markdown"
              >${aiCopyIcon()}</button>`
            : ''}
          <button class="ghost ai-message-resend" type="button" data-message-action="resend" data-message-id="${escapeHtml(message.id)}" title="Resend this message">Resend</button>
          <span>${escapeHtml(formatAiTime(message.created_at))}</span>
        </span>
      </div>
      <div class="ai-message-body">${isPendingAssistant
        ? `${renderAgentActivityDisclosure(message, { pending: true })}`
        : (message.role === 'assistant'
            ? `${renderMarkdown(message.content)}${renderAgentActivityDisclosure(message)}`
            : escapeHtml(message.content))}
        ${message.role === 'assistant' && messageRunMode(message) === 'intent' ? renderIntentPanel(message) : ''}</div>
      ${message.role === 'assistant'
        ? (() => {
            const stats = messageStats(message);
            return `<div class="ai-message-foot">${escapeHtml(providerNameForMessage(message))}${message.model_id ? ` · ${escapeHtml(message.model_id)}` : ''}${message.latency_ms ? ` · ${message.latency_ms} ms` : ''}${stats ? ` · ${escapeHtml(stats)}` : ''}</div>`;
          })()
        : ''}
    </article>
  `;
  }).join('') + (pendingInterrupt ? renderWorkbenchApprovalCard(sessionIdForApproval, pendingInterrupt) : '');
  postRenderMessages();
  if (shouldStickToBottom) {
    aiEls.messageList.scrollTop = aiEls.messageList.scrollHeight;
  } else if (restoreScrollTop !== null) {
    aiEls.messageList.scrollTop = restoreScrollTop;
  } else {
    aiEls.messageList.scrollTop = previousScrollTop;
  }
  updateMessageListScrollIntent();
}

function pushLocalPendingMessages(sessionId, content, runMode = 'chat') {
  const live = liveStateFor(sessionId);
  const now = Date.now() / 1000;
  const pendingUserId = `pending-user-${crypto.randomUUID()}`;
  const pendingAssistantId = `pending-assistant-${crypto.randomUUID()}`;
  const normalizedRunMode = normalizeRunMode(runMode);
  live.pendingUserMessageId = pendingUserId;
  live.pendingAssistantMessageId = pendingAssistantId;
  setMessageActivityOpen(pendingAssistantId, normalizedRunMode === 'agent');
  const providerId = aiState.activeSession?.id === sessionId
    ? (activeProviderId() || generalChatProviderId())
    : generalChatProviderId();
  live.messages = [
    ...live.messages,
    {
      id: pendingUserId,
      role: 'user',
      content,
      created_at: now,
      provider_id: providerId,
      model_id: '',
      meta: { run_mode: normalizedRunMode },
    },
    {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      created_at: now,
      provider_id: providerId,
      model_id: '',
      latency_ms: null,
      meta: { interrupted: false, run_mode: normalizedRunMode, agent_trace: [], agent_tool_progress: [] },
    },
  ];
}

function pushLocalRetryPendingAssistant(sessionId) {
  const live = liveStateFor(sessionId);
  const now = Date.now() / 1000;
  const pendingAssistantId = `pending-assistant-${crypto.randomUUID()}`;
  const messages = [...live.messages];
  if (messages[messages.length - 1]?.role === 'assistant') {
    messages.pop();
  }
  const runMode = messageRunMode(messages[messages.length - 1]);
  live.pendingAssistantMessageId = pendingAssistantId;
  setMessageActivityOpen(pendingAssistantId, runMode === 'agent');
  live.messages = [
    ...messages,
    {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      created_at: now,
      provider_id: activeProviderId() || generalChatProviderId(),
      model_id: '',
      latency_ms: null,
      meta: { interrupted: false, run_mode: runMode, agent_trace: [], agent_tool_progress: [] },
    },
  ];
}

function replacePendingUserMessage(sessionId, serverMessage) {
  const live = liveStateFor(sessionId);
  if (!live.pendingUserMessageId) return;
  live.messages = live.messages.map((message) => (
    message.id === live.pendingUserMessageId ? serverMessage : message
  ));
}

function appendAssistantDelta(sessionId, delta) {
  const live = liveStateFor(sessionId);
  if (!live.pendingAssistantMessageId) return;
  live.messages = live.messages.map((message) => (
    message.id === live.pendingAssistantMessageId
      ? { ...message, content: `${message.content || ''}${delta}` }
      : message
  ));
}

function replacePendingAssistantMessage(sessionId, serverMessage) {
  const live = liveStateFor(sessionId);
  if (!live.pendingAssistantMessageId) return;
  const pendingId = live.pendingAssistantMessageId;
  if (isMessageActivityOpen(pendingId, true)) {
    setMessageActivityOpen(serverMessage?.id, true);
  }
  live.messages = live.messages.map((message) => (
    message.id === pendingId ? serverMessage : message
  ));
}

function updatePendingAgentToolCall(sessionId, toolCall, status) {
  const live = liveStateFor(sessionId);
  if (!live.pendingAssistantMessageId || !toolCall) return;
  live.messages = live.messages.map((message) => {
    if (message.id !== live.pendingAssistantMessageId) return message;
    const meta = { ...(message.meta || {}) };
    const progress = Array.isArray(meta.agent_tool_progress) ? [...meta.agent_tool_progress] : [];
    const id = String(toolCall.id || `${toolCall.name || 'tool'}-${progress.length}`);
    const index = progress.findIndex((item) => String(item.id || '') === id);
    const nextCall = {
      ...(index >= 0 ? progress[index] : {}),
      ...toolCall,
      id,
      status,
    };
    if (index >= 0) progress[index] = nextCall;
    else progress.push(nextCall);
    meta.agent_tool_progress = progress;
    return { ...message, meta };
  });
}

function updatePendingAgentTrace(sessionId, eventData) {
  const live = liveStateFor(sessionId);
  if (!live.pendingAssistantMessageId || !eventData) return;
  live.messages = live.messages.map((message) => {
    if (message.id !== live.pendingAssistantMessageId) return message;
    const meta = { ...(message.meta || {}) };
    const trace = Array.isArray(meta.agent_trace) ? [...meta.agent_trace] : [];
    trace.push(eventData);
    meta.agent_trace = trace;
    return { ...message, meta };
  });
}

function updatePendingRetrievalState(sessionId, retrievalRequest, retrievedSources, retrievalCitations) {
  const live = liveStateFor(sessionId);
  if (!live.pendingAssistantMessageId) return;
  live.messages = live.messages.map((message) => {
    if (message.id !== live.pendingAssistantMessageId) return message;
    const meta = { ...(message.meta || {}) };
    if (retrievalRequest && typeof retrievalRequest === 'object') meta.retrieval_request = retrievalRequest;
    if (Array.isArray(retrievedSources)) meta.retrieved_sources = retrievedSources;
    if (Array.isArray(retrievalCitations)) meta.retrieval_citations = retrievalCitations;
    return { ...message, meta };
  });
}

function clearSessionLiveState(sessionId) {
  const live = liveStateFor(sessionId);
  live.sending = false;
  live.abortController = null;
  live.pendingUserMessageId = '';
  live.pendingAssistantMessageId = '';
}

function removePendingMessages(sessionId) {
  const live = liveStateFor(sessionId);
  live.messages = live.messages.filter((message) => !String(message.id || '').startsWith('pending-'));
  live.pendingUserMessageId = '';
  live.pendingAssistantMessageId = '';
}

async function readJsonLinesStream(response, onEvent) {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      onEvent(JSON.parse(trimmed));
    }
  }
  const tail = buffer.trim();
  if (tail) {
    onEvent(JSON.parse(tail));
  }
}

function handleAiStreamEvent(sessionId, eventData) {
  let autoSpeakMessageId = '';
  if (eventData.type === 'user_message' && eventData.message) {
    replacePendingUserMessage(sessionId, eventData.message);
  } else if (eventData.type === 'assistant_delta') {
    appendAssistantDelta(sessionId, String(eventData.delta || ''));
  } else if (eventData.type === 'assistant_message' && eventData.message) {
    replacePendingAssistantMessage(sessionId, eventData.message);
    if (aiState.activeSession?.id === sessionId && aiTtsSettings().enabled !== false && aiTtsSettings().auto_read) {
      autoSpeakMessageId = eventData.message.id;
    }
  } else if (eventData.type === 'agent_run_start' || eventData.type === 'agent_iteration_start' || eventData.type === 'agent_run_end') {
    updatePendingAgentTrace(sessionId, eventData);
  } else if (eventData.type === 'agent_tool_start') {
    updatePendingAgentTrace(sessionId, eventData);
    updatePendingAgentToolCall(sessionId, eventData.tool_call || {}, 'running');
  } else if (eventData.type === 'agent_tool_result') {
    updatePendingAgentTrace(sessionId, eventData);
    updatePendingAgentToolCall(sessionId, eventData.tool_call || {}, 'complete');
  } else if (eventData.type === 'graph_retrieval_result') {
    updatePendingRetrievalState(
      sessionId,
      eventData.retrieval_request || {},
      eventData.retrieved_sources || [],
      eventData.retrieval_citations || [],
    );
  } else if (eventData.type === 'error') {
    throw new Error(String(eventData.detail || 'Chat streaming failed.'));
  }
  // Only re-render if this session is currently viewed — avoids clobbering the active session's UI
  if (aiState.activeSession?.id === sessionId) {
    renderMessages();
  }
  if (autoSpeakMessageId) {
    speakAiMessage(autoSpeakMessageId).catch((error) => setAiStatus(error.message, 'warn'));
  }
}

async function streamAiRequest(url, payload, abortController, sessionId, options = {}) {
  const resume = Boolean(options.resume);
  const requestUrl = resume ? `${url}${url.includes('?') ? '&' : '?'}resume=1` : url;
  const response = await fetch(requestUrl, withAiTimezone({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
    signal: abortController.signal,
  }));
  if (!response.ok) {
    let detail = await response.text();
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.detail || detail;
    } catch (_) {
      // Use the raw response body.
    }
    throw new Error(detail || `${response.status}`);
  }
  await readJsonLinesStream(response, (event) => handleAiStreamEvent(sessionId, event));
}

async function deleteSession(sessionId) {
  const session = aiState.sessions.find((item) => item.id === sessionId);
  const title = session?.title || 'this chat';
  if (!window.confirm(`Delete "${title}" permanently? This cannot be undone.`)) return;
  await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/purge`, { method: 'DELETE' });
  _sessionLive.delete(sessionId);
  if (aiState.activeSession?.id === sessionId) {
    aiState.activeSession = null;
  }
  await loadSessions(true);
  renderMessages();
  setAiStatus('Session deleted.', 'ok');
}

async function loadLlmSettings() {
  const result = await aiFetchJson('/api/llm-settings');
  aiState.providers = result.providers || [];
  aiState.routing = result.routing || {};
  renderProviderSelect();
}

async function loadSessions(selectFirst = false) {
  const query = aiState.showArchived
    ? `?include_archived=true&limit=${AI_ARCHIVED_SESSION_LIMIT}`
    : '';
  const result = await aiFetchJson(`/api/ai/sessions${query}`);
  aiState.sessions = result.sessions || [];
  renderSessionList();
  if (selectFirst && !aiState.activeSession && filteredSessions().length) {
    await openSession(filteredSessions()[0].id);
  }
}

async function createSession(options = {}) {
  const { title = 'New chat', providerId = '' } = options;
  if (aiState.showArchived) {
    aiState.showArchived = false;
  }
  setAiStatus('Creating session.');
  const result = await aiFetchJson('/api/ai/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      mode: runModeToSessionMode(currentRunMode()),
      provider_id: providerId || undefined,
      source_controls: normalizeSourceControls(aiState.activeSession?.source_controls),
    }),
  });
  await loadSessions();
  await openSession(result.session.id);
  setAiStatus('Ready.', 'ok');
  return result.session;
}

async function openSession(sessionId) {
  saveSessionScrollState();
  const session = aiState.sessions.find((item) => item.id === sessionId);
  const includeArchived = Boolean(session?.archived_at);
  const live = liveStateFor(sessionId);
  const shouldRestoreScroll = !live.pinnedToBottom;

  if (live.sending) {
    // Session is actively streaming in the background — switch the view to it without reloading
    // messages from server (the in-progress stream owns the messages array right now).
    aiState.activeSession = session || aiState.activeSession;
    aiState.runMode = sessionModeToRunMode(session);
    aiState.messageListPinnedToBottom = live.pinnedToBottom;
    renderSessionList();
    renderMessages({
      forceScrollBottom: live.pinnedToBottom,
      restoreScrollTop: shouldRestoreScroll ? live.scrollTop : null,
    });
    setAiStatus('Response in progress…', 'ok');
    return;
  }

  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}${includeArchived ? '?include_archived=true' : ''}`);
  aiState.activeSession = result.session;
  // Initialise (or refresh) the live state from the server's message list.
  live.messages = mergeServerAndLocalMessages(result.session.messages || [], live.messages);
  aiState.runMode = sessionModeToRunMode(result.session);
  aiState.messageListPinnedToBottom = live.pinnedToBottom;
  renderSessionList();
  renderMessages({
    forceScrollBottom: live.pinnedToBottom,
    restoreScrollTop: shouldRestoreScroll ? live.scrollTop : null,
  });
  setAiStatus('Ready.', 'ok');
}

// Fetch a session's latest data from the server and update its live state and
// (if it is the currently viewed session) also update aiState.activeSession.
// Called after a stream finishes — including for background sessions.
async function refreshSessionLive(sessionId) {
  const listSession = aiState.sessions.find((s) => s.id === sessionId);
  const includeArchived = Boolean(listSession?.archived_at);
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}${includeArchived ? '?include_archived=true' : ''}`);
  const live = liveStateFor(sessionId);
  live.messages = mergeServerAndLocalMessages(result.session.messages || [], live.messages);
  if (aiState.activeSession?.id === sessionId) {
    aiState.activeSession = result.session;
    aiState.messageListPinnedToBottom = live.pinnedToBottom;
    renderMessages({
      forceScrollBottom: live.pinnedToBottom,
      restoreScrollTop: live.pinnedToBottom ? null : live.scrollTop,
    });
  }
  return result.session;
}

function ensurePendingAssistantForResume(sessionId) {
  const live = liveStateFor(sessionId);
  if (live.pendingAssistantMessageId) return;
  const now = Date.now() / 1000;
  const pendingAssistantId = `pending-assistant-${crypto.randomUUID()}`;
  const recentMessages = live.messages || [];
  const runMode = messageRunMode(recentMessages[recentMessages.length - 1]) || currentRunMode();
  live.pendingAssistantMessageId = pendingAssistantId;
  setMessageActivityOpen(pendingAssistantId, runMode === 'agent');
  live.messages = [
    ...recentMessages,
    {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      created_at: now,
      provider_id: activeProviderId() || generalChatProviderId(),
      model_id: '',
      latency_ms: null,
      meta: { interrupted: false, run_mode: runMode, agent_trace: [], agent_tool_progress: [] },
    },
  ];
}

async function resumeInflightStreamIfPresent() {
  const marker = loadInflightMarker();
  if (!marker) return false;
  const { sessionId, endpoint } = marker;
  if (!sessionId || (endpoint !== 'messages' && endpoint !== 'retry')) {
    clearInflightMarker();
    return false;
  }
  const inProgress = await serverStreamInProgress(sessionId).catch(() => false);
  if (!inProgress) {
    clearInflightMarker(sessionId);
    return false;
  }
  if (!aiState.sessions.some((session) => session.id === sessionId)) {
    clearInflightMarker(sessionId);
    return false;
  }
  await openSession(sessionId);
  const live = liveStateFor(sessionId);
  const abortController = new AbortController();
  live.sending = true;
  live.abortController = abortController;
  ensurePendingAssistantForResume(sessionId);
  renderMessages();
  setAiStatus('Reconnected to in-progress response.', 'ok');
  try {
    const baseUrl = endpoint === 'retry'
      ? `/api/ai/sessions/${encodeURIComponent(sessionId)}/retry/stream`
      : `/api/ai/sessions/${encodeURIComponent(sessionId)}/messages/stream`;
    await streamAiRequest(baseUrl, {}, abortController, sessionId, { resume: true });
    await refreshSessionLive(sessionId);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
    return true;
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    setAiStatus(isAbort ? 'Response interrupted.' : (error.message || 'Reconnect failed.'), isAbort ? 'warn' : 'danger');
    await refreshSessionLive(sessionId).catch(() => {});
    await loadSessions().catch(() => {});
    return false;
  } finally {
    clearSessionLiveState(sessionId);
    clearInflightMarker(sessionId);
    renderMessages();
  }
}

async function renameSession() {
  if (!aiState.activeSession) return;
  const title = window.prompt('Session name', aiState.activeSession.title || 'New chat');
  if (title === null) return;
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  aiState.activeSession = { ...aiState.activeSession, ...result.session };
  await loadSessions();
  renderMessages();
}

async function saveSessionTitle(sessionId, title) {
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (aiState.activeSession?.id === sessionId) {
    aiState.activeSession = { ...aiState.activeSession, ...result.session };
  }
  aiState.editingSessionId = '';
  await loadSessions();
  renderMessages();
}

function startSessionTitleEdit(sessionId) {
  if (sessionOpenTimer) {
    window.clearTimeout(sessionOpenTimer);
    sessionOpenTimer = 0;
  }
  aiState.editingSessionId = sessionId;
  renderSessionList();
}

function cancelSessionTitleEdit() {
  aiState.editingSessionId = '';
  renderSessionList();
}

function queueOpenSession(sessionId) {
  if (sessionOpenTimer) {
    window.clearTimeout(sessionOpenTimer);
  }
  sessionOpenTimer = window.setTimeout(() => {
    sessionOpenTimer = 0;
    if (aiState.editingSessionId) return;
    if (aiState.activeSession?.id === sessionId) return;
    openSession(sessionId).catch((error) => setAiStatus(error.message, 'danger'));
  }, 220);
}

async function archiveSession() {
  if (!aiState.activeSession) return;
  await toggleSessionArchive(aiState.activeSession.id);
}

async function toggleSessionArchive(sessionId) {
  const session = aiState.sessions.find((item) => item.id === sessionId);
  const isArchived = Boolean(session?.archived_at || (aiState.activeSession?.id === sessionId && aiState.activeSession?.archived_at));
  if (isArchived) {
    await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/restore`, { method: 'POST' });
    aiState.showArchived = false;
    aiState.activeSession = null;
    _sessionLive.delete(sessionId);
    await loadSessions();
    await openSession(sessionId);
    setAiStatus('Session restored.', 'ok');
    return;
  }
  await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  const archivedActiveSession = aiState.activeSession?.id === sessionId;
  if (archivedActiveSession) {
    aiState.activeSession = null;
    aiState.showArchived = true;
  }
  _sessionLive.delete(sessionId);
  await loadSessions(false);
  renderMessages();
  setAiStatus('Session archived.', 'ok');
}

async function setArchiveFilter(showArchived) {
  aiState.showArchived = showArchived;
  if (!showArchived || !aiState.activeSession?.archived_at) {
    aiState.activeSession = null;
  }
  renderMessages();
  await loadSessions(true);
  setAiStatus(showArchived ? 'Viewing archived chats.' : 'Viewing active chats.', 'ok');
}

async function updateSessionProvider() {
  if (!aiState.activeSession) return;
  const providerId = aiEls.providerSelect.value;
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_id: providerId }),
  });
  aiState.activeSession = { ...aiState.activeSession, ...result.session };
  if (currentRunMode() === 'agent' && !providerSupportsAgentMode(currentProvider())) {
    setAiStatus('Selected provider may answer in agent mode without tool calls.', 'warn');
  }
  await loadSessions();
  renderMessages();
}

async function updateSessionRunMode(runMode) {
  aiState.runMode = normalizeRunMode(runMode);
  if (aiState.runMode === 'agent' && !providerSupportsAgentMode(currentProvider())) {
    setAiStatus('Selected provider may answer in agent mode without tool calls.', 'warn');
  }
  renderRunModeToggle();
  renderMessages({ preserveScroll: true });
  if (!aiState.activeSession) return;
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: runModeToSessionMode(aiState.runMode) }),
  });
  aiState.activeSession = { ...aiState.activeSession, ...result.session };
  await loadSessions();
  renderMessages({ preserveScroll: true });
}

async function updateSessionSourceControl(key, enabled) {
  if (!aiState.activeSession) return;
  const nextSourceControls = normalizeSourceControls(aiState.activeSession.source_controls);
  nextSourceControls[key] = Boolean(enabled);
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_controls: nextSourceControls }),
  });
  aiState.activeSession = { ...aiState.activeSession, ...result.session };
  await loadSessions();
  renderMessages({ preserveScroll: true });
  setAiStatus('Source controls updated.', 'ok');
}

const AI_SLASH_COMMANDS = [
  {
    command: '/capabilities brief',
    kind: 'session_command',
    serverCommand: 'capabilities brief',
    description: 'List retrieval surfaces and available tools with one-line descriptions.',
  },
  {
    command: '/capabilities full',
    kind: 'session_command',
    serverCommand: 'capabilities full',
    description: 'Show retrieval surfaces and tools with all attributes and contract details.',
  },
  {
    command: '/retrieval-surfaces',
    kind: 'session_command',
    serverCommand: 'retrieval-surfaces',
    description: 'Show enabled retrieval surfaces and their current availability.',
  },
  {
    command: '/tool-activity',
    kind: 'session_command',
    serverCommand: 'tool-activity',
    description: 'Show the latest recorded agent tool activity for this session.',
  },
  {
    command: '/intent',
    kind: 'run_mode',
    runMode: 'intent',
    description: 'Parse a rover task into structured intent without executing it.',
  },
  {
    command: '/plan',
    kind: 'run_mode',
    runMode: 'workbench',
    description: 'Run the workbench planner for the current prompt.',
  },
];

function slashCommandDefinition(command) {
  const normalized = String(command || '').trim().toLowerCase();
  return AI_SLASH_COMMANDS.find((item) => item.command === normalized) || null;
}

function parseSlashCommand(rawContent) {
  const twoWordMatch = rawContent.match(/^(\/[a-zA-Z-]+ [a-zA-Z-]+)(\s+([\s\S]+))?$/);
  if (twoWordMatch) {
    const command = twoWordMatch[1].toLowerCase();
    const definition = slashCommandDefinition(command);
    if (definition) {
      const body = (twoWordMatch[3] || '').trim();
      return { definition, runMode: null, content: body, command };
    }
  }
  const match = rawContent.match(/^(\/[a-zA-Z-]+)(\s+([\s\S]+))?$/);
  if (!match) return { definition: null, runMode: null, content: rawContent };
  const command = match[1].toLowerCase();
  const definition = slashCommandDefinition(command);
  if (!definition) return { definition: null, runMode: null, content: rawContent };
  const body = (match[3] || '').trim();
  return {
    definition,
    runMode: definition.kind === 'run_mode' ? definition.runMode : null,
    content: body,
    command,
  };
}

function slashQueryState() {
  if (!aiEls.messageInput) return null;
  const value = aiEls.messageInput.value || '';
  const cursor = aiEls.messageInput.selectionStart ?? value.length;
  const head = value.slice(0, cursor);
  if (!head.startsWith('/')) return null;
  const spaceCount = (head.match(/ /g) || []).length;
  if (spaceCount > 1) return null;
  const query = head.toLowerCase();
  const items = AI_SLASH_COMMANDS.filter((item) => item.command.startsWith(query));
  return items.length ? { query, items } : null;
}

function isSlashMenuOpen() {
  return Boolean(aiEls.slashMenu && !aiEls.slashMenu.hidden);
}

function closeSlashMenu() {
  if (!aiEls.slashMenu) return;
  aiState.slashMenuItems = [];
  aiState.slashMenuIndex = 0;
  aiEls.slashMenu.hidden = true;
  aiEls.slashMenu.innerHTML = '';
}

function renderSlashMenu(items, selectedIndex = 0) {
  if (!aiEls.slashMenu) return;
  if (!items.length) {
    closeSlashMenu();
    return;
  }
  aiState.slashMenuItems = items;
  aiState.slashMenuIndex = Math.max(0, Math.min(selectedIndex, items.length - 1));
  aiEls.slashMenu.innerHTML = items.map((item, index) => `
    <button
      class="ai-slash-item${index === aiState.slashMenuIndex ? ' active' : ''}"
      type="button"
      role="option"
      aria-selected="${index === aiState.slashMenuIndex ? 'true' : 'false'}"
      data-slash-command="${escapeHtml(item.command)}"
    >
      <span class="ai-slash-item-command">${escapeHtml(item.command)}</span>
      <span class="ai-slash-item-description">${escapeHtml(item.description)}</span>
    </button>
  `).join('');
  aiEls.slashMenu.hidden = false;
}

function updateSlashMenu() {
  const state = slashQueryState();
  if (!state || !state.items.length) {
    closeSlashMenu();
    return;
  }
  const previous = aiState.slashMenuItems[aiState.slashMenuIndex]?.command || '';
  const nextIndex = Math.max(0, state.items.findIndex((item) => item.command === previous));
  renderSlashMenu(state.items, nextIndex);
}

function selectSlashMenuStep(step) {
  if (!aiState.slashMenuItems.length) return;
  const count = aiState.slashMenuItems.length;
  const nextIndex = (aiState.slashMenuIndex + step + count) % count;
  renderSlashMenu(aiState.slashMenuItems, nextIndex);
}

function applySlashCommand(command) {
  if (!aiEls.messageInput) return;
  const definition = slashCommandDefinition(command);
  if (!definition) return;
  aiEls.messageInput.value = definition.kind === 'run_mode'
    ? `${definition.command} `
    : definition.command;
  closeSlashMenu();
  resizeComposer();
  updateComposerState();
  aiEls.messageInput.focus();
  const position = aiEls.messageInput.value.length;
  aiEls.messageInput.setSelectionRange(position, position);
}

async function sendMessage(event) {
  event.preventDefault();
  // Per-session guard: only block sending if THIS session is already streaming.
  const activeId = aiState.activeSession?.id || '';
  if (activeId && liveStateFor(activeId).sending) return;
  const rawContent = aiEls.messageInput.value.trim();
  if (!rawContent) return;
  const slash = parseSlashCommand(rawContent);
  if (slash.runMode && !slash.content) {
    setAiStatus(`Usage: ${slash.command} <prompt>`, 'warn');
    return;
  }
  if (slash.definition?.kind === 'session_command' && slash.content) {
    setAiStatus(`${slash.command} does not accept additional text.`, 'warn');
    return;
  }
  const content = slash.runMode ? slash.content : rawContent;
  const runMode = slash.runMode || currentRunMode();

  aiEls.messageInput.value = '';
  closeSlashMenu();
  resizeComposer();

  let sessionId = activeId;
  const abortController = new AbortController();
  const isSessionCommand = slash.definition?.kind === 'session_command';

  if (sessionId && !isSessionCommand) {
    const live = liveStateFor(sessionId);
    live.sending = true;
    live.abortController = abortController;
    pushLocalPendingMessages(sessionId, content, runMode);
  }
  renderMessages();
  setAiStatus(
    isSessionCommand ? `Running ${slash.command}...`
    : runMode === 'agent' ? 'Agent is checking rover context.'
    : runMode === 'intent' ? 'Parsing rover intent...'
    : runMode === 'workbench' ? 'Workbench graph starting...'
    : 'Waiting for model response.'
  );

  try {
    if (!sessionId) {
      const createdSession = await createSession({ providerId: activeProviderId() });
      sessionId = createdSession.id;
      // createSession calls openSession internally, so activeSession is now set.
      if (!isSessionCommand) {
        const live = liveStateFor(sessionId);
        live.sending = true;
        live.abortController = abortController;
      }
    }
    if (slash.definition?.kind === 'session_command') {
      const result = await sendSessionCommand(sessionId, slash.definition.serverCommand);
      if (!result?.local_fallback) {
        await refreshSessionLive(sessionId);
        await loadSessions();
      }
      if (aiState.activeSession?.id === sessionId) setAiStatus('Ready.', 'ok');
      return;
    }
    if (!aiState.activeSession) {
      await openSession(sessionId);
      const live = liveStateFor(sessionId);
      live.sending = true;
      live.abortController = abortController;
      pushLocalPendingMessages(sessionId, content, runMode);
      renderMessages();
    }
    if (runMode === 'intent') {
      await sendIntentTestRequest(sessionId, content, abortController);
    } else if (runMode === 'workbench') {
      await sendWorkbenchRequest(sessionId, content, abortController);
    } else {
      saveInflightMarker(sessionId, 'messages');
      await streamAiRequest(
        `/api/ai/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
        { content, run_mode: runMode },
        abortController,
        sessionId,
      );
    }
    // Refresh from server and update live state (works even if user switched away).
    // Skip refresh if workbench is suspended at interrupt (pendingInterrupt is set).
    if (!liveStateFor(sessionId).pendingInterrupt) {
      await refreshSessionLive(sessionId);
      await loadSessions();
    }
    if (aiState.activeSession?.id === sessionId && !liveStateFor(sessionId).pendingInterrupt) {
      setAiStatus('Ready.', 'ok');
    }
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const message = isAbort ? 'Response interrupted.' : error.message;
    if (sessionId) {
      removePendingMessages(sessionId);
      clearInflightMarker(sessionId);
    }
    if (aiState.activeSession?.id === sessionId) {
      setAiStatus(message, isAbort ? 'warn' : 'danger');
    }
    if (sessionId) {
      await refreshSessionLive(sessionId).catch(() => {});
      await loadSessions().catch(() => {});
      if (aiState.activeSession?.id === sessionId) {
        setAiStatus(message, isAbort ? 'warn' : 'danger');
      }
    } else {
      renderMessages();
    }
  } finally {
    if (sessionId) {
      clearSessionLiveState(sessionId);
      clearInflightMarker(sessionId);
    }
    renderMessages();
    aiEls.messageInput.focus();
  }
}

async function resendMessage(messageId) {
  const sessionId = aiState.activeSession?.id;
  if (!sessionId || liveStateFor(sessionId).sending) return;
  const live = liveStateFor(sessionId);
  const message = live.messages.find((item) => item.id === messageId);
  const content = String(message?.content || '').trim();
  if (!content) return;
  const runMode = messageRunMode(message);
  live.sending = true;
  const abortController = new AbortController();
  live.abortController = abortController;
  pushLocalPendingMessages(sessionId, content, runMode);
  renderMessages();
  setAiStatus('Resending message.');
  try {
    if (runMode === 'intent') {
      await sendIntentTestRequest(sessionId, content, abortController);
    } else if (runMode === 'workbench') {
      await sendWorkbenchRequest(sessionId, content, abortController);
    } else {
      saveInflightMarker(sessionId, 'messages');
      await streamAiRequest(
        `/api/ai/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
        { content, run_mode: runMode },
        abortController,
        sessionId,
      );
    }
    // Workbench sessions can pause at interrupt() waiting for operator input.
    if (!liveStateFor(sessionId).pendingInterrupt) {
      await refreshSessionLive(sessionId);
      await loadSessions();
      if (aiState.activeSession?.id === sessionId) setAiStatus('Ready.', 'ok');
    }
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const messageText = isAbort ? 'Response interrupted.' : error.message;
    removePendingMessages(sessionId);
    if (aiState.activeSession?.id === sessionId) setAiStatus(messageText, isAbort ? 'warn' : 'danger');
    await refreshSessionLive(sessionId).catch(() => {});
    await loadSessions().catch(() => {});
    if (aiState.activeSession?.id === sessionId) setAiStatus(messageText, isAbort ? 'warn' : 'danger');
  } finally {
    clearSessionLiveState(sessionId);
    clearInflightMarker(sessionId);
    renderMessages();
  }
}

async function retryResponse() {
  const sessionId = aiState.activeSession?.id;
  if (!sessionId || liveStateFor(sessionId).sending) return;
  const live = liveStateFor(sessionId);
  live.sending = true;
  const abortController = new AbortController();
  live.abortController = abortController;
  pushLocalRetryPendingAssistant(sessionId);
  renderMessages();
  setAiStatus('Retrying last model response.');
  try {
    saveInflightMarker(sessionId, 'retry');
    await streamAiRequest(
      `/api/ai/sessions/${encodeURIComponent(sessionId)}/retry/stream`,
      {},
      abortController,
      sessionId,
    );
    await refreshSessionLive(sessionId);
    await loadSessions();
    if (aiState.activeSession?.id === sessionId) setAiStatus('Ready.', 'ok');
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const message = isAbort ? 'Response interrupted.' : error.message;
    if (aiState.activeSession?.id === sessionId) setAiStatus(message, isAbort ? 'warn' : 'danger');
    await refreshSessionLive(sessionId).catch(() => {});
    await loadSessions().catch(() => {});
    if (aiState.activeSession?.id === sessionId) setAiStatus(message, isAbort ? 'warn' : 'danger');
  } finally {
    clearSessionLiveState(sessionId);
    clearInflightMarker(sessionId);
    renderMessages();
  }
}

function updateComposerState() {
  if (!aiEls.sendMessage) return;
  const hasContent = Boolean(aiEls.messageInput.value.trim());
  aiEls.sendMessage.disabled = isSending() || !hasContent || Boolean(aiState.activeSession?.archived_at);
  if (aiEls.stopMessage) {
    aiEls.stopMessage.disabled = !isSending() || !activeAbortController();
  }
}

function resizeComposer() {
  if (!aiEls.messageInput) return;
  aiEls.messageInput.style.height = 'auto';
  aiEls.messageInput.style.height = `${Math.min(aiEls.messageInput.scrollHeight, 220)}px`;
}

function handleComposerKeydown(event) {
  if (event.isComposing) return;
  if (isSlashMenuOpen()) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      selectSlashMenuStep(1);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      selectSlashMenuStep(-1);
      return;
    }
    if (event.key === 'Tab') {
      event.preventDefault();
      const item = aiState.slashMenuItems[aiState.slashMenuIndex];
      if (item) applySlashCommand(item.command);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      closeSlashMenu();
      return;
    }
  }
  if (event.key !== 'Enter') return;
  if (event.shiftKey) return;
  if (isSlashMenuOpen()) {
    const item = aiState.slashMenuItems[aiState.slashMenuIndex];
    if (item) {
      event.preventDefault();
      applySlashCommand(item.command);
      return;
    }
  }
  event.preventDefault();
  if (!aiEls.sendMessage.disabled) {
    aiEls.messageForm.requestSubmit();
  }
}

function clampSidebarWidth(value) {
  return Math.max(AI_SIDEBAR_MIN, Math.min(AI_SIDEBAR_MAX, Number(value) || 340));
}

function setSidebarWidth(width, persist = true) {
  const nextWidth = clampSidebarWidth(width);
  aiEls.shell?.style.setProperty('--ai-sidebar-width', `${nextWidth}px`);
  aiEls.layoutResizer?.setAttribute('aria-valuenow', String(nextWidth));
  if (persist) {
    try {
      window.localStorage.setItem(AI_LAYOUT_WIDTH_KEY, String(nextWidth));
    } catch (_) {
      // Layout resizing still works for the current page when storage is unavailable.
    }
  }
}

function restoreSidebarWidth() {
  let storedWidth = 340;
  try {
    storedWidth = window.localStorage.getItem(AI_LAYOUT_WIDTH_KEY) || storedWidth;
  } catch (_) {
    // Keep the default width.
  }
  setSidebarWidth(storedWidth, false);
}

function updateSidebarWidthFromPointer(event) {
  if (!aiEls.shell) return;
  const shellRect = aiEls.shell.getBoundingClientRect();
  const nextWidth = event.clientX - shellRect.left;
  setSidebarWidth(nextWidth);
}

function bindLayoutResizer() {
  if (!aiEls.layoutResizer || !aiEls.shell) return;
  restoreSidebarWidth();
  aiEls.layoutResizer.addEventListener('pointerdown', (event) => {
    if (window.matchMedia(AI_MOBILE_QUERY).matches) return;
    event.preventDefault();
    aiEls.layoutResizer.setPointerCapture(event.pointerId);
    aiEls.shell.classList.add('is-resizing');
    updateSidebarWidthFromPointer(event);
  });
  aiEls.layoutResizer.addEventListener('pointermove', (event) => {
    if (!aiEls.layoutResizer.hasPointerCapture(event.pointerId)) return;
    updateSidebarWidthFromPointer(event);
  });
  aiEls.layoutResizer.addEventListener('pointerup', (event) => {
    if (aiEls.layoutResizer.hasPointerCapture(event.pointerId)) {
      aiEls.layoutResizer.releasePointerCapture(event.pointerId);
    }
    aiEls.shell.classList.remove('is-resizing');
  });
  aiEls.layoutResizer.addEventListener('pointercancel', () => {
    aiEls.shell.classList.remove('is-resizing');
  });
  aiEls.layoutResizer.addEventListener('lostpointercapture', () => {
    aiEls.shell.classList.remove('is-resizing');
  });
  aiEls.layoutResizer.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const currentWidth = Number(aiEls.layoutResizer.getAttribute('aria-valuenow')) || 340;
    if (event.key === 'Home') setSidebarWidth(AI_SIDEBAR_MIN);
    else if (event.key === 'End') setSidebarWidth(AI_SIDEBAR_MAX);
    else setSidebarWidth(currentWidth + (event.key === 'ArrowRight' ? 24 : -24));
  });
}

function clampShellHeight(value) {
  return Math.max(AI_SHELL_HEIGHT_MIN, Math.min(AI_SHELL_HEIGHT_MAX, Number(value) || 680));
}

function setShellHeight(height, persist = true) {
  const nextHeight = clampShellHeight(height);
  aiEls.shell?.style.setProperty('--ai-shell-height', `${nextHeight}px`);
  aiEls.heightResizer?.setAttribute('aria-valuenow', String(nextHeight));
  if (persist) {
    try {
      window.localStorage.setItem(AI_LAYOUT_HEIGHT_KEY, String(nextHeight));
    } catch (_) {
      // Height resizing still works for the current page when storage is unavailable.
    }
  }
}

function restoreShellHeight() {
  let storedHeight = 680;
  try {
    storedHeight = window.localStorage.getItem(AI_LAYOUT_HEIGHT_KEY) || storedHeight;
  } catch (_) {
    // Keep the default height.
  }
  setShellHeight(storedHeight, false);
}

function updateShellHeightFromPointer(event) {
  if (!aiEls.shell) return;
  const shellRect = aiEls.shell.getBoundingClientRect();
  const nextHeight = event.clientY - shellRect.top;
  setShellHeight(nextHeight);
}

function bindHeightResizer() {
  if (!aiEls.heightResizer || !aiEls.shell) return;
  restoreShellHeight();
  aiEls.heightResizer.addEventListener('pointerdown', (event) => {
    if (window.matchMedia(AI_MOBILE_QUERY).matches) return;
    event.preventDefault();
    aiEls.heightResizer.setPointerCapture(event.pointerId);
    aiEls.shell.classList.add('is-height-resizing');
    updateShellHeightFromPointer(event);
  });
  aiEls.heightResizer.addEventListener('pointermove', (event) => {
    if (!aiEls.heightResizer.hasPointerCapture(event.pointerId)) return;
    updateShellHeightFromPointer(event);
  });
  aiEls.heightResizer.addEventListener('pointerup', (event) => {
    if (aiEls.heightResizer.hasPointerCapture(event.pointerId)) {
      aiEls.heightResizer.releasePointerCapture(event.pointerId);
    }
    aiEls.shell.classList.remove('is-height-resizing');
  });
  aiEls.heightResizer.addEventListener('pointercancel', () => {
    aiEls.shell.classList.remove('is-height-resizing');
  });
  aiEls.heightResizer.addEventListener('lostpointercapture', () => {
    aiEls.shell.classList.remove('is-height-resizing');
  });
  aiEls.heightResizer.addEventListener('keydown', (event) => {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const currentHeight = Number(aiEls.heightResizer.getAttribute('aria-valuenow')) || 680;
    if (event.key === 'Home') setShellHeight(AI_SHELL_HEIGHT_MIN);
    else if (event.key === 'End') setShellHeight(AI_SHELL_HEIGHT_MAX);
    else setShellHeight(currentHeight + (event.key === 'ArrowDown' ? 32 : -32));
  });
}

function bindAi() {
  bindLayoutResizer();
  bindHeightResizer();
  aiEls.newSession.addEventListener('click', () => createSession().catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.showActive.addEventListener('click', () => setArchiveFilter(false).catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.showArchived.addEventListener('click', () => setArchiveFilter(true).catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.sessionSearch.addEventListener('input', renderSessionList);
  aiEls.sessionList.addEventListener('click', (event) => {
    const archiveButton = event.target.closest('[data-action="toggle-archive-session"]');
    if (archiveButton) {
      event.preventDefault();
      event.stopPropagation();
      toggleSessionArchive(archiveButton.dataset.sessionId).catch((error) => setAiStatus(error.message, 'danger'));
      return;
    }
    const removeButton = event.target.closest('[data-action="delete-session"]');
    if (removeButton) {
      event.preventDefault();
      event.stopPropagation();
      deleteSession(removeButton.dataset.sessionId).catch((error) => setAiStatus(error.message, 'danger'));
      return;
    }
    if (event.target.closest('.ai-session-title-input')) return;
    if (event.detail > 1) return;
    const row = event.target.closest('[data-session-id]');
    if (!row) return;
    queueOpenSession(row.dataset.sessionId);
  });
  aiEls.sessionList.addEventListener('dblclick', (event) => {
    if (event.target.closest('.ai-session-title-input, [data-action], button')) return;
    const row = event.target.closest('[data-session-id]');
    if (!row) return;
    event.preventDefault();
    event.stopPropagation();
    startSessionTitleEdit(row.dataset.sessionId);
  });
  aiEls.sessionList.addEventListener('keydown', (event) => {
    const input = event.target.closest('.ai-session-title-input');
    if (!input) {
      if (event.target.closest('button')) return;
      const row = event.target.closest('[data-session-id]');
      if (!row || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      openSession(row.dataset.sessionId).catch((error) => setAiStatus(error.message, 'danger'));
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const row = input.closest('[data-session-id]');
      if (aiState.editingSessionId !== row.dataset.sessionId) return;
      saveSessionTitle(row.dataset.sessionId, input.value).catch((error) => setAiStatus(error.message, 'danger'));
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelSessionTitleEdit();
    }
  });
  aiEls.sessionList.addEventListener('focusout', (event) => {
    const input = event.target.closest('.ai-session-title-input');
    if (!input) return;
    const row = input.closest('[data-session-id]');
    if (aiState.editingSessionId !== row.dataset.sessionId) return;
    saveSessionTitle(row.dataset.sessionId, input.value).catch((error) => setAiStatus(error.message, 'danger'));
  });
  aiEls.renameSession.addEventListener('click', () => renameSession().catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.archiveSession.addEventListener('click', () => archiveSession().catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.providerSelect.addEventListener('change', () => updateSessionProvider().catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.sourceControls?.addEventListener('change', (event) => {
    const input = event.target.closest('[data-source-control]');
    if (!input) return;
    updateSessionSourceControl(input.dataset.sourceControl, input.checked)
      .catch((error) => setAiStatus(error.message, 'danger'));
  });
  aiEls.sourcesToggle?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleSourcesPopover();
  });
  document.addEventListener('click', (event) => {
    if (!isSourcesPopoverOpen()) return;
    if (aiEls.sourcesControl?.contains(event.target)) return;
    closeSourcesPopover();
  });
  document.addEventListener('mousedown', (event) => {
    if (!isSlashMenuOpen()) return;
    if (event.target.closest('#ai-slash-menu, #ai-message-input')) return;
    closeSlashMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.altKey && !event.ctrlKey && !event.metaKey && event.key.toLowerCase() === 's') {
      if (!aiEls.sourcesToggle || aiEls.sourcesToggle.disabled) return;
      event.preventDefault();
      if (isSourcesPopoverOpen()) {
        closeSourcesPopover();
        aiEls.sourcesToggle?.focus();
      } else {
        openSourcesPopover({ focusFirst: true });
      }
      return;
    }
    if (event.key === 'Escape' && isSourcesPopoverOpen()) {
      closeSourcesPopover();
      aiEls.sourcesToggle?.focus();
    }
  });
  aiEls.runModeButtons.forEach((button) => {
    button.addEventListener('click', () => updateSessionRunMode(button.dataset.runMode).catch((error) => setAiStatus(error.message, 'danger')));
  });
  aiEls.messageForm.addEventListener('submit', sendMessage);
  aiEls.messageInput.addEventListener('keydown', handleComposerKeydown);
  aiEls.messageInput.addEventListener('input', () => {
    resizeComposer();
    updateComposerState();
    updateSlashMenu();
  });
  aiEls.messageInput.addEventListener('click', updateSlashMenu);
  aiEls.messageInput.addEventListener('focus', updateSlashMenu);
  aiEls.messageInput.addEventListener('blur', () => {
    window.setTimeout(() => {
      if (!aiEls.slashMenu?.matches(':hover')) closeSlashMenu();
    }, 80);
  });
  aiEls.slashMenu?.addEventListener('mousedown', (event) => {
    const item = event.target.closest('[data-slash-command]');
    if (!item) return;
    event.preventDefault();
    applySlashCommand(item.dataset.slashCommand || '');
  });
  aiEls.messageList.addEventListener('toggle', (event) => {
    const disclosure = event.target.closest('[data-message-disclosure="activity"]');
    if (!disclosure) return;
    setMessageActivityOpen(disclosure.dataset.messageId, disclosure.open);
  }, true);
  aiEls.messageList.addEventListener('scroll', updateMessageListScrollIntent, { passive: true });
  aiEls.messageList.addEventListener('click', (event) => {
    // Workbench clarification card buttons
    const clarificationBtn = event.target.closest('[data-clarification-action]');
    if (clarificationBtn) {
      const action = clarificationBtn.dataset.clarificationAction;
      const threadId = clarificationBtn.dataset.threadId || '';
      const sid = clarificationBtn.dataset.sessionId || '';
      const answerInput = document.getElementById('ai-clarification-input');
      const answer = answerInput ? answerInput.value.trim() : '';
      if (sid && threadId) {
        resumeWorkbenchApproval(sid, threadId, action, answer)
          .catch((err) => setAiStatus(err.message || 'Clarification failed.', 'danger'));
      }
      return;
    }

    // Workbench approval card buttons
    const approvalBtn = event.target.closest('[data-approval-action]');
    if (approvalBtn) {
      const decision = approvalBtn.dataset.approvalAction;
      const threadId = approvalBtn.dataset.threadId || '';
      const sid = approvalBtn.dataset.sessionId || '';
      const noteInput = document.getElementById('ai-approval-note-input');
      const note = noteInput ? noteInput.value.trim() : '';
      if (sid && threadId && (decision === 'approve' || decision === 'reject')) {
        resumeWorkbenchApproval(sid, threadId, decision, note)
          .catch((err) => setAiStatus(err.message || 'Approval failed.', 'danger'));
      }
      return;
    }

    const action = event.target.closest('[data-message-action]');
    if (!action) return;
    if (action.dataset.messageAction === 'toggle-speech') {
      toggleAiSpeech(action.dataset.messageId).catch((error) => setAiStatus(error.message, 'warn'));
      return;
    }
    if (action.dataset.messageAction === 'stop-speech') {
      stopAiSpeech();
      return;
    }
    if (action.dataset.messageAction === 'resend') {
      resendMessage(action.dataset.messageId).catch((error) => setAiStatus(error.message, 'danger'));
    }
  });
  aiEls.retryResponse.addEventListener('click', () => retryResponse().catch((error) => setAiStatus(error.message, 'danger')));
  aiEls.stopMessage.addEventListener('click', () => {
    activeAbortController()?.abort();
  });
  window.addEventListener('beforeunload', cancelAiSpeech);
}

async function initAi() {
  window.GCSCommon?.initShell({
    page: 'ai',
    title: 'AI Chat',
    subtitle: 'Provider-backed chat sessions for testing configured LLMs.',
  });
  const intro = document.querySelector('[data-page-intro]');
  if (intro && !intro.querySelector('.ai-intro-grid')) {
    intro.innerHTML = `
      <div class="ai-intro-grid">
        <div class="ai-intro-main">
          <p class="page-kicker">AI Chat</p>
          <h2>AI Chat</h2>
          <p class="page-lede">
            AI Chat is a provider-routed conversation workspace for configured language models. Each session preserves model selection, message history, and response metadata, while requests are dispatched through a unified backend chat runtime that supports OpenAI-compatible providers and local Ollama models.
          </p>
          <p class="page-lede">
            Under the hood, the service resolves the active provider, applies the provider-specific adapter, and records timing and model details alongside each assistant response. The interface is scoped to conversational workflows, with storage and routing handled inside this GCS instance.
          </p>
        </div>
      </div>
    `;
  }
  bindAi();
  await loadAiSettings().catch((error) => setAiStatus(error.message, 'warn'));
  renderMessages();
  await loadLlmSettings();
  await loadSessions(true);
  await resumeInflightStreamIfPresent().catch((error) => setAiStatus(error.message, 'warn'));
  renderMessages();
}

initAi().catch((error) => {
  setAiStatus(error.message, 'danger');
});
