const aiState = {
  sessions: [],
  providers: [],
  routing: {},
  activeSession: null,
  sending: false,
  editingSessionId: '',
  showArchived: false,
};

const AI_LAYOUT_WIDTH_KEY = 'gcs-ai-sidebar-width';
const AI_LAYOUT_HEIGHT_KEY = 'gcs-ai-chat-shell-height';
const AI_SIDEBAR_MIN = 240;
const AI_SIDEBAR_MAX = 560;
const AI_SHELL_HEIGHT_MIN = 420;
const AI_SHELL_HEIGHT_MAX = 1100;
const AI_MOBILE_QUERY = '(max-width: 1100px)';
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
  sendMessage: document.getElementById('ai-send-message'),
  status: document.getElementById('ai-status'),
};

async function aiFetchJson(url, options = {}) {
  const response = await fetch(url, options);
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
      <div class="ai-session-row${active}" role="button" tabindex="0" data-session-id="${escapeHtml(session.id)}">
        <span class="ai-session-row-main">
          <span class="ai-session-row-title-wrap">
            ${isEditing
              ? `<input class="ai-session-title-input" type="text" value="${escapeHtml(session.title || 'New chat')}" autocomplete="off" aria-label="Session name">`
              : `<span class="ai-session-row-title">${escapeHtml(session.title || 'New chat')}</span>`}
            <span class="ai-session-count">${session.message_count || 0}</span>
          </span>
          <button class="ghost ai-session-delete" type="button" data-action="delete-session" data-session-id="${escapeHtml(session.id)}" title="Delete session" aria-label="Delete session">✕</button>
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

function renderMessages() {
  const messages = aiState.activeSession?.messages || [];
  const viewingArchived = Boolean(aiState.activeSession?.archived_at);
  aiEls.sessionTitle.textContent = aiState.activeSession?.title || 'New chat';
  aiEls.renameSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.disabled = !aiState.activeSession;
  aiEls.archiveSession.textContent = viewingArchived ? 'Restore' : 'Archive';
  aiEls.archiveSession.title = viewingArchived ? 'Restore this archived chat' : 'Archive this chat';
  aiEls.retryResponse.disabled = !aiState.activeSession || aiState.sending || !messages.length || viewingArchived;
  aiEls.retryResponse.title = 'Retry the last model response without adding a new user message.';
  aiEls.retryResponse.setAttribute('aria-label', 'Retry the last model response');
  aiEls.messageInput.disabled = aiState.sending || viewingArchived;
  aiEls.messageInput.placeholder = viewingArchived
    ? 'Restore this archived chat to continue messaging'
    : 'Ask the configured General Chat provider';
  aiEls.showArchived.setAttribute('aria-pressed', aiState.showArchived ? 'true' : 'false');
  aiEls.showActive.setAttribute('aria-pressed', aiState.showArchived ? 'false' : 'true');
  renderProviderSelect();
  updateComposerState();

  if (!aiState.activeSession) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${aiState.showArchived ? 'Open an archived chat to review it, or switch back to Active chats.' : 'Type a message to start a new chat.'}</div>`;
    return;
  }
  if (!messages.length) {
    aiEls.messageList.innerHTML = `<div class="ai-empty-state">${viewingArchived ? 'Archived chat has no messages.' : 'Start a new conversation.'}</div>`;
    return;
  }
  aiEls.messageList.innerHTML = messages.map((message) => `
    <article class="ai-message ai-message-${escapeHtml(message.role)}">
      <div class="ai-message-meta">
        <strong>${message.role === 'assistant' ? `Assistant · ${escapeHtml(providerNameForMessage(message))}` : 'You'}</strong>
        <span class="ai-message-meta-actions">
          <button class="ghost ai-message-resend" type="button" data-message-action="resend" data-message-id="${escapeHtml(message.id)}" title="Resend this message">Resend</button>
          <span>${escapeHtml(formatAiTime(message.created_at))}</span>
        </span>
      </div>
      <div class="ai-message-body">${escapeHtml(message.content)}</div>
      ${message.role === 'assistant'
        ? `<div class="ai-message-foot">${escapeHtml(providerNameForMessage(message))}${message.model_id ? ` · ${escapeHtml(message.model_id)}` : ''}${message.latency_ms ? ` · ${message.latency_ms} ms` : ''}</div>`
        : ''}
    </article>
  `).join('');
  aiEls.messageList.scrollTop = aiEls.messageList.scrollHeight;
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
  const result = await aiFetchJson(`/api/ai/sessions${aiState.showArchived ? '?include_archived=true' : ''}`);
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
      mode: 'general_chat',
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
  const sessionId = aiState.activeSession.id;
  if (aiState.activeSession.archived_at) {
    await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/restore`, { method: 'POST' });
    aiState.showArchived = false;
    aiState.activeSession = null;
    await loadSessions();
    await openSession(sessionId);
    setAiStatus('Session restored.', 'ok');
    return;
  }
  await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  aiState.activeSession = null;
  aiState.showArchived = true;
  await loadSessions(true);
  renderMessages();
  setAiStatus('Session archived. Switch back to Active chats to return to the main list.', 'ok');
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

async function sendMessage(event) {
  event.preventDefault();
  if (aiState.sending) return;
  const content = aiEls.messageInput.value.trim();
  if (!content) return;
  aiState.sending = true;
  aiEls.messageInput.value = '';
  resizeComposer();
  renderMessages();
  setAiStatus('Waiting for model response.');
  let sessionId = aiState.activeSession?.id || '';
  try {
    if (!sessionId) {
      const createdSession = await createSession({ providerId: activeProviderId() });
      sessionId = createdSession.id;
    }
    const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    await openSession(result.session.id);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const message = error.message;
    setAiStatus(message, 'danger');
    if (sessionId) {
      await openSession(sessionId);
      setAiStatus(message, 'danger');
    } else {
      renderMessages();
    }
  } finally {
    aiState.sending = false;
    renderMessages();
  }
}

async function resendMessage(messageId) {
  if (!aiState.activeSession || aiState.sending) return;
  const message = (aiState.activeSession.messages || []).find((item) => item.id === messageId);
  const content = String(message?.content || '').trim();
  if (!content) return;
  aiState.sending = true;
  renderMessages();
  setAiStatus('Resending message.');
  try {
    const result = await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    await openSession(result.session.id);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    const messageText = error.message;
    setAiStatus(messageText, 'danger');
    await openSession(aiState.activeSession.id);
    setAiStatus(messageText, 'danger');
  } finally {
    aiState.sending = false;
    renderMessages();
  }
}

async function retryResponse() {
  if (!aiState.activeSession || aiState.sending) return;
  aiState.sending = true;
  renderMessages();
  setAiStatus('Retrying last model response.');
  try {
    await aiFetchJson(`/api/ai/sessions/${encodeURIComponent(aiState.activeSession.id)}/retry`, { method: 'POST' });
    await openSession(aiState.activeSession.id);
    await loadSessions();
    setAiStatus('Ready.', 'ok');
  } catch (error) {
    setAiStatus(error.message, 'danger');
  } finally {
    aiState.sending = false;
    renderMessages();
  }
}

function updateComposerState() {
  if (!aiEls.sendMessage) return;
  const hasContent = Boolean(aiEls.messageInput.value.trim());
  aiEls.sendMessage.disabled = aiState.sending || !hasContent || Boolean(aiState.activeSession?.archived_at);
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
    const row = event.target.closest('[data-session-id]');
    if (!row) return;
    event.preventDefault();
    event.stopPropagation();
    startSessionTitleEdit(row.dataset.sessionId);
  });
  aiEls.sessionList.addEventListener('keydown', (event) => {
    const input = event.target.closest('.ai-session-title-input');
    if (!input) {
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
  aiEls.messageForm.addEventListener('submit', sendMessage);
  aiEls.messageInput.addEventListener('keydown', handleComposerKeydown);
  aiEls.messageInput.addEventListener('input', () => {
    resizeComposer();
    updateComposerState();
  });
  aiEls.messageList.addEventListener('click', (event) => {
    const action = event.target.closest('[data-message-action="resend"]');
    if (!action) return;
    resendMessage(action.dataset.messageId).catch((error) => setAiStatus(error.message, 'danger'));
  });
  aiEls.retryResponse.addEventListener('click', () => retryResponse().catch((error) => setAiStatus(error.message, 'danger')));
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
  renderMessages();
  await loadLlmSettings();
  await loadSessions(true);
  renderMessages();
}

initAi().catch((error) => {
  setAiStatus(error.message, 'danger');
});
