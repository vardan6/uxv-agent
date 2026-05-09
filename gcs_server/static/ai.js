const aiState = {
  sessions: [],
  providers: [],
  routing: {},
  activeSession: null,
  sending: false,
  editingSessionId: '',
  showArchived: false,
  activeRequestAbortController: null,
  pendingUserMessageId: '',
  pendingAssistantMessageId: '',
  runMode: 'chat',
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
};

const AI_LAYOUT_WIDTH_KEY = 'gcs-ai-sidebar-width';
const AI_LAYOUT_HEIGHT_KEY = 'gcs-ai-chat-shell-height';
const AI_SIDEBAR_MIN = 240;
const AI_SIDEBAR_MAX = 560;
const AI_SHELL_HEIGHT_MIN = 420;
const AI_SHELL_HEIGHT_MAX = 1100;
const AI_MOBILE_QUERY = '(max-width: 1100px)';
const AI_ARCHIVED_SESSION_LIMIT = 500;
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
  renameSession: document.getElementById('ai-rename-session'),
  archiveSession: document.getElementById('ai-archive-session'),
  messageList: document.getElementById('ai-message-list'),
  messageForm: document.getElementById('ai-message-form'),
  messageInput: document.getElementById('ai-message-input'),
  retryResponse: document.getElementById('ai-retry-response'),
  stopMessage: document.getElementById('ai-stop-message'),
  sendMessage: document.getElementById('ai-send-message'),
  status: document.getElementById('ai-status'),
  runModeButtons: document.querySelectorAll('[data-run-mode]'),
};

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
  return clean === 'agent' ? 'agent' : 'chat';
}

function sessionModeToRunMode(session) {
  return normalizeRunMode(session?.mode);
}

function runModeToSessionMode(runMode) {
  return normalizeRunMode(runMode) === 'agent' ? 'agent' : 'general_chat';
}

function currentRunMode() {
  return normalizeRunMode(aiState.runMode);
}

function messageRunMode(message) {
  return normalizeRunMode(message?.meta?.run_mode);
}

function runModeLabel(runMode) {
  return normalizeRunMode(runMode) === 'agent' ? 'Agent' : 'Chat';
}

function renderRunModeToggle() {
  const runMode = currentRunMode();
  aiEls.runModeButtons.forEach((button) => {
    const active = normalizeRunMode(button.dataset.runMode) === runMode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    button.disabled = aiState.sending || Boolean(aiState.activeSession?.archived_at);
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
  const message = (aiState.activeSession?.messages || []).find((item) => item.id === messageId);
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
  aiEls.providerPill.textContent = `Provider: ${providerLabel(active)}`;
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
    const preview = session.last_message || 'No messages yet';
    const isEditing = aiState.editingSessionId === session.id;
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
        <span class="ai-session-row-meta">${escapeHtml(formatAiTime(session.updated_at))} · ${session.message_count || 0} msg</span>
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

function renderMessages(options = {}) {
  const preserveScroll = Boolean(options.preserveScroll);
  const previousScrollTop = preserveScroll ? aiEls.messageList.scrollTop : 0;
  const messages = aiState.activeSession?.messages || [];
  const pendingAssistantId = aiState.pendingAssistantMessageId;
  const viewingArchived = Boolean(aiState.activeSession?.archived_at);
  aiEls.sessionTitle.textContent = aiState.activeSession?.title || 'New chat';
  aiEls.renameSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.textContent = viewingArchived ? 'Restore' : 'Archive';
  aiEls.archiveSession.title = viewingArchived ? 'Restore this archived chat' : 'Archive this chat';
  aiEls.retryResponse.disabled = !aiState.activeSession || aiState.sending || !messages.length || viewingArchived;
  aiEls.stopMessage.disabled = !aiState.sending || !aiState.activeRequestAbortController;
  aiEls.retryResponse.title = 'Retry the last model response without adding a new user message.';
  aiEls.retryResponse.setAttribute('aria-label', 'Retry the last model response');
  aiEls.messageInput.disabled = aiState.sending || viewingArchived;
  aiEls.messageInput.placeholder = viewingArchived
    ? 'Restore this archived chat to continue messaging'
    : (currentRunMode() === 'agent' ? 'Ask the read-only rover agent' : 'Ask the configured General Chat provider');
  aiEls.showArchived.setAttribute('aria-pressed', aiState.showArchived ? 'true' : 'false');
  aiEls.showActive.setAttribute('aria-pressed', aiState.showArchived ? 'false' : 'true');
  renderProviderSelect();
  renderRunModeToggle();
  updateComposerState();

  if (!aiState.activeSession) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${aiState.showArchived ? 'Open an archived chat to review it, or switch back to Active chats.' : 'Type a message to start a new chat.'}</div>`;
    return;
  }
  if (!messages.length) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${viewingArchived ? 'Archived chat has no messages.' : 'Start a new conversation.'}</div>`;
    return;
  }
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
          <button class="ghost ai-message-resend" type="button" data-message-action="resend" data-message-id="${escapeHtml(message.id)}" title="Resend this message">Resend</button>
          <span>${escapeHtml(formatAiTime(message.created_at))}</span>
        </span>
      </div>
      <div class="ai-message-body">${isPendingAssistant
        ? `<span class="ai-thinking" role="status" aria-live="polite" aria-label="Assistant is working">
            <span class="ai-thinking-core" aria-hidden="true"></span>
            <span class="ai-thinking-rings" aria-hidden="true">
              <span></span><span></span><span></span>
            </span>
            <span class="ai-thinking-text">Thinking</span>
          </span>`
        : escapeHtml(message.content)}</div>
      ${message.role === 'assistant'
        ? `<div class="ai-message-foot">${escapeHtml(providerNameForMessage(message))}${message.model_id ? ` · ${escapeHtml(message.model_id)}` : ''}${message.latency_ms ? ` · ${message.latency_ms} ms` : ''}</div>`
        : ''}
    </article>
  `;
  }).join('');
  aiEls.messageList.scrollTop = preserveScroll ? previousScrollTop : aiEls.messageList.scrollHeight;
}

function pushLocalPendingMessages(content, runMode = currentRunMode()) {
  if (!aiState.activeSession) return;
  const now = Date.now() / 1000;
  const pendingUserId = `pending-user-${crypto.randomUUID()}`;
  const pendingAssistantId = `pending-assistant-${crypto.randomUUID()}`;
  aiState.pendingUserMessageId = pendingUserId;
  aiState.pendingAssistantMessageId = pendingAssistantId;
  aiState.activeSession.messages = [
    ...(aiState.activeSession.messages || []),
    {
      id: pendingUserId,
      role: 'user',
      content,
      created_at: now,
      provider_id: activeProviderId() || generalChatProviderId(),
      model_id: '',
      meta: { run_mode: normalizeRunMode(runMode) },
    },
    {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      created_at: now,
      provider_id: activeProviderId() || generalChatProviderId(),
      model_id: '',
      latency_ms: null,
      meta: { interrupted: false, run_mode: normalizeRunMode(runMode) },
    },
  ];
}

function pushLocalRetryPendingAssistant() {
  if (!aiState.activeSession) return;
  const now = Date.now() / 1000;
  const pendingAssistantId = `pending-assistant-${crypto.randomUUID()}`;
  const messages = [...(aiState.activeSession.messages || [])];
  if (messages[messages.length - 1]?.role === 'assistant') {
    messages.pop();
  }
  const runMode = messageRunMode(messages[messages.length - 1]);
  aiState.pendingAssistantMessageId = pendingAssistantId;
  aiState.activeSession.messages = [
    ...messages,
    {
      id: pendingAssistantId,
      role: 'assistant',
      content: '',
      created_at: now,
      provider_id: activeProviderId() || generalChatProviderId(),
      model_id: '',
      latency_ms: null,
      meta: { interrupted: false, run_mode: runMode },
    },
  ];
}

function replacePendingUserMessage(serverMessage) {
  if (!aiState.activeSession || !aiState.pendingUserMessageId) return;
  aiState.activeSession.messages = (aiState.activeSession.messages || []).map((message) => (
    message.id === aiState.pendingUserMessageId ? serverMessage : message
  ));
}

function appendAssistantDelta(delta) {
  if (!aiState.activeSession || !aiState.pendingAssistantMessageId) return;
  aiState.activeSession.messages = (aiState.activeSession.messages || []).map((message) => (
    message.id === aiState.pendingAssistantMessageId
      ? { ...message, content: `${message.content || ''}${delta}` }
      : message
  ));
}

function replacePendingAssistantMessage(serverMessage) {
  if (!aiState.activeSession || !aiState.pendingAssistantMessageId) return;
  aiState.activeSession.messages = (aiState.activeSession.messages || []).map((message) => (
    message.id === aiState.pendingAssistantMessageId ? serverMessage : message
  ));
}

function clearPendingMessageIds() {
  aiState.pendingUserMessageId = '';
  aiState.pendingAssistantMessageId = '';
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

function handleAiStreamEvent(eventData) {
  let autoSpeakMessageId = '';
  if (eventData.type === 'user_message' && eventData.message) {
    replacePendingUserMessage(eventData.message);
  } else if (eventData.type === 'assistant_delta') {
    appendAssistantDelta(String(eventData.delta || ''));
  } else if (eventData.type === 'assistant_message' && eventData.message) {
    replacePendingAssistantMessage(eventData.message);
    if (aiTtsSettings().enabled !== false && aiTtsSettings().auto_read) {
      autoSpeakMessageId = eventData.message.id;
    }
  } else if (eventData.type === 'error') {
    throw new Error(String(eventData.detail || 'Chat streaming failed.'));
  }
  renderMessages();
  if (autoSpeakMessageId) {
    speakAiMessage(autoSpeakMessageId).catch((error) => setAiStatus(error.message, 'warn'));
  }
}

async function streamAiRequest(url, payload, abortController) {
  const response = await fetch(url, withAiTimezone({
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
  await readJsonLinesStream(response, handleAiStreamEvent);
}

async function deleteSession(sessionId) {
  const session = aiState.sessions.find((item) => item.id === sessionId);
  const title = session?.title || 'this chat';
  if (!window.confirm(`Delete "${title}" permanently? This cannot be undone.`)) return;
  await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/purge`, { method: 'DELETE' });
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
    }),
  });
  await loadSessions();
  await openSession(result.session.id);
  setAiStatus('Ready.', 'ok');
  return result.session;
}

async function openSession(sessionId) {
  const session = aiState.sessions.find((item) => item.id === sessionId);
  const includeArchived = Boolean(session?.archived_at);
  const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}${includeArchived ? '?include_archived=true' : ''}`);
  aiState.activeSession = result.session;
  aiState.runMode = sessionModeToRunMode(result.session);
  renderSessionList();
  renderMessages();
  setAiStatus('Ready.', 'ok');
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
  await loadSessions(false);
  renderMessages();
  setAiStatus('Session archived.', 'ok');
}

async function setArchiveFilter(showArchived) {
  aiState.showArchived = showArchived;
  aiState.activeSession = null;
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
  await loadSessions();
  renderMessages();
}

async function updateSessionRunMode(runMode) {
  aiState.runMode = normalizeRunMode(runMode);
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

async function sendMessage(event) {
  event.preventDefault();
  if (aiState.sending) return;
  const content = aiEls.messageInput.value.trim();
  if (!content) return;
  const runMode = currentRunMode();
  aiState.sending = true;
  const abortController = new AbortController();
  aiState.activeRequestAbortController = abortController;
  aiEls.messageInput.value = '';
  resizeComposer();
  if (aiState.activeSession) {
    pushLocalPendingMessages(content, runMode);
  }
  renderMessages();
  setAiStatus(runMode === 'agent' ? 'Agent is checking rover context.' : 'Waiting for model response.');
  let sessionId = aiState.activeSession?.id || '';
  try {
    if (!sessionId) {
      const createdSession = await createSession({ providerId: activeProviderId() });
      sessionId = createdSession.id;
    }
    if (!aiState.activeSession) {
      await openSession(sessionId);
      pushLocalPendingMessages(content, runMode);
      renderMessages();
    }
    await streamAiRequest(
      `/api/ai/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
      { content, run_mode: runMode },
      abortController,
    );
    await openSession(sessionId);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const message = isAbort ? 'Response interrupted.' : error.message;
    setAiStatus(message, isAbort ? 'warn' : 'danger');
    if (sessionId) {
      await openSession(sessionId);
      setAiStatus(message, isAbort ? 'warn' : 'danger');
    } else {
      renderMessages();
    }
  } finally {
    aiState.sending = false;
    aiState.activeRequestAbortController = null;
    clearPendingMessageIds();
    renderMessages();
  }
}

async function resendMessage(messageId) {
  if (!aiState.activeSession || aiState.sending) return;
  const message = (aiState.activeSession.messages || []).find((item) => item.id === messageId);
  const content = String(message?.content || '').trim();
  if (!content) return;
  const runMode = messageRunMode(message);
  const sessionId = aiState.activeSession.id;
  aiState.sending = true;
  const abortController = new AbortController();
  aiState.activeRequestAbortController = abortController;
  pushLocalPendingMessages(content, runMode);
  renderMessages();
  setAiStatus('Resending message.');
  try {
    await streamAiRequest(
      `/api/ai/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
      { content, run_mode: runMode },
      abortController,
    );
    await openSession(sessionId);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const messageText = isAbort ? 'Response interrupted.' : error.message;
    setAiStatus(messageText, isAbort ? 'warn' : 'danger');
    await openSession(sessionId);
    setAiStatus(messageText, isAbort ? 'warn' : 'danger');
  } finally {
    aiState.sending = false;
    aiState.activeRequestAbortController = null;
    clearPendingMessageIds();
    renderMessages();
  }
}

async function retryResponse() {
  if (!aiState.activeSession || aiState.sending) return;
  const sessionId = aiState.activeSession.id;
  aiState.sending = true;
  const abortController = new AbortController();
  aiState.activeRequestAbortController = abortController;
  pushLocalRetryPendingAssistant();
  renderMessages();
  setAiStatus('Retrying last model response.');
  try {
    await streamAiRequest(
      `/api/ai/sessions/${encodeURIComponent(sessionId)}/retry/stream`,
      {},
      abortController,
    );
    await openSession(sessionId);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const isAbort = error?.name === 'AbortError';
    const message = isAbort ? 'Response interrupted.' : error.message;
    setAiStatus(message, isAbort ? 'warn' : 'danger');
    await openSession(sessionId);
    setAiStatus(message, isAbort ? 'warn' : 'danger');
  } finally {
    aiState.sending = false;
    aiState.activeRequestAbortController = null;
    clearPendingMessageIds();
    renderMessages();
  }
}

function updateComposerState() {
  if (!aiEls.sendMessage) return;
  const hasContent = Boolean(aiEls.messageInput.value.trim());
  aiEls.sendMessage.disabled = aiState.sending || !hasContent || Boolean(aiState.activeSession?.archived_at);
  if (aiEls.stopMessage) {
    aiEls.stopMessage.disabled = !aiState.sending || !aiState.activeRequestAbortController;
  }
}

function resizeComposer() {
  if (!aiEls.messageInput) return;
  aiEls.messageInput.style.height = 'auto';
  aiEls.messageInput.style.height = `${Math.min(aiEls.messageInput.scrollHeight, 220)}px`;
}

function handleComposerKeydown(event) {
  if (event.isComposing) return;
  if (event.key !== 'Enter') return;
  if (event.shiftKey) return;
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
  aiEls.runModeButtons.forEach((button) => {
    button.addEventListener('click', () => updateSessionRunMode(button.dataset.runMode).catch((error) => setAiStatus(error.message, 'danger')));
  });
  aiEls.messageForm.addEventListener('submit', sendMessage);
  aiEls.messageInput.addEventListener('keydown', handleComposerKeydown);
  aiEls.messageInput.addEventListener('input', () => {
    resizeComposer();
    updateComposerState();
  });
  aiEls.messageList.addEventListener('click', (event) => {
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
    if (!aiState.activeRequestAbortController) return;
    aiState.activeRequestAbortController.abort();
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
  renderMessages();
}

initAi().catch((error) => {
  setAiStatus(error.message, 'danger');
});
