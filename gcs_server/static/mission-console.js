(function () {
  const state = {
    sessions: [],
    currentSessionId: '',
    selectedSessionId: '',
  };

  const els = {
    list: document.getElementById('mission-console-replay-list'),
    count: document.getElementById('mission-console-replay-count'),
    current: document.getElementById('mission-console-replay-current'),
    refresh: document.getElementById('mission-console-refresh-replay'),
    rollover: document.getElementById('mission-console-rollover-replay'),
  };

  function operatorTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch (_) {
      return '';
    }
  }

  async function fetchJson(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const timezone = operatorTimezone();
    if (timezone) headers.set('X-Operator-Timezone', timezone);
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `${response.status}`);
    }
    return response.json();
  }

  function sessionLabel(session) {
    const started = session.started_at ? new Date(session.started_at * 1000) : null;
    if (!started || Number.isNaN(started.getTime())) return session.session_id || 'Replay session';
    return started.toLocaleString([], {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function countMarkup(label, value, path) {
    return `
      <span class="session-stat" title="${label}">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${path}"/></svg>
        <span>${value}</span>
      </span>
    `;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function render() {
    if (!els.list) return;
    els.list.innerHTML = '';
    const count = state.sessions.length;
    if (els.count) els.count.textContent = `${count} session${count === 1 ? '' : 's'}`;
    if (els.current) els.current.textContent = state.selectedSessionId || state.currentSessionId || 'No session selected';

    if (!state.sessions.length) {
      const empty = document.createElement('article');
      empty.className = 'session-item';
      empty.innerHTML = '<span>No replay sessions yet. Start the simulator/GCS and record telemetry.</span>';
      els.list.appendChild(empty);
      return;
    }

    const sessions = [...state.sessions].sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
    for (const session of sessions) {
      const safeSessionId = escapeHtml(session.session_id || '');
      const item = document.createElement('article');
      item.className = 'session-item';
      if (session.session_id === state.selectedSessionId) item.classList.add('active');

      const selectButton = document.createElement('button');
      selectButton.type = 'button';
      selectButton.className = 'session-select';
      selectButton.innerHTML = `
        <strong class="session-title">${sessionLabel(session)}</strong>
        <span class="session-meta">
          ${countMarkup('Telemetry frames', session.telemetry_count || 0, 'M3 13h3.2l1.7-4.6c.12-.33.6-.31.7.03L11.2 17l2.04-6.12c.11-.34.59-.35.72-.02L15.6 15H21v2h-6.8l-1.45-3.2-2.05 6.16c-.11.33-.58.35-.72.03L7.54 11.7 6.8 15H3v-2Z')}
          ${countMarkup('Controls', session.control_count || 0, 'M6 6.5A3.5 3.5 0 0 1 9.5 3h5A3.5 3.5 0 0 1 18 6.5v11a3.5 3.5 0 0 1-3.5 3.5h-5A3.5 3.5 0 0 1 6 17.5v-11Zm3.5-1.5A1.5 1.5 0 0 0 8 6.5v11A1.5 1.5 0 0 0 9.5 19h5a1.5 1.5 0 0 0 1.5-1.5v-11A1.5 1.5 0 0 0 14.5 5h-5Zm-.5 4h2v2H9V9Zm4 0h2v2h-2V9Zm-4 4h6v2H9v-2Z')}
          ${countMarkup('Events', session.runtime_event_count || 0, 'M12 2a5 5 0 0 0-5 5v2.17c0 .53-.21 1.04-.59 1.41L5 12v1h14v-1l-1.41-1.42A2 2 0 0 1 17 9.17V7a5 5 0 0 0-5-5Zm0 20a2.98 2.98 0 0 0 2.82-2H9.18A2.98 2.98 0 0 0 12 22Zm-3-4v-2h6v2H9Z')}
        </span>
        <span class="session-id" title="${safeSessionId}">${safeSessionId}</span>
      `;
      selectButton.addEventListener('click', () => {
        state.selectedSessionId = session.session_id || '';
        render();
      });

      item.append(selectButton);
      els.list.appendChild(item);
    }
  }

  async function loadSessions() {
    const result = await fetchJson('/api/replay/sessions');
    state.sessions = result.sessions || [];
    state.currentSessionId = result.current_session_id || '';
    if (!state.selectedSessionId) state.selectedSessionId = state.currentSessionId || state.sessions[0]?.session_id || '';
    render();
  }

  async function rolloverSession() {
    const result = await fetchJson('/api/replay/sessions/rollover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'mission_console_rollover' }),
    });
    state.currentSessionId = result.current_session_id || '';
    state.selectedSessionId = state.currentSessionId;
    await loadSessions();
  }

  function init() {
    els.refresh?.addEventListener('click', () => loadSessions().catch((error) => {
      if (els.current) els.current.textContent = `Replay load failed: ${error.message}`;
    }));
    els.rollover?.addEventListener('click', () => rolloverSession().catch((error) => {
      if (els.current) els.current.textContent = `Rollover failed: ${error.message}`;
    }));
    loadSessions().catch((error) => {
      if (els.current) els.current.textContent = `Replay load failed: ${error.message}`;
    });
  }

  init();
}());
