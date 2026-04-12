const replayState = {
  sessions: [],
  currentSessionId: null,
  loadedSession: null,
  playbackIndex: 0,
  playing: false,
  playbackTimer: null,
  speed: 1,
  map: null,
  trackLine: null,
  roverMarker: null,
};

const replayEls = {
  sessionList: document.getElementById('session-list'),
  currentSessionPill: document.getElementById('current-session-pill'),
  loadedSessionPill: document.getElementById('loaded-session-pill'),
  refreshSessions: document.getElementById('refresh-sessions'),
  rolloverSession: document.getElementById('rollover-session'),
  playPause: document.getElementById('play-pause'),
  seekStart: document.getElementById('seek-start'),
  replaySpeed: document.getElementById('replay-speed'),
  timelineScrubber: document.getElementById('timeline-scrubber'),
  timelineStatus: document.getElementById('timeline-status'),
  pos: document.getElementById('replay-pos'),
  speed: document.getElementById('replay-speed-card'),
  heading: document.getElementById('replay-heading'),
  gps: document.getElementById('replay-gps'),
  camera: document.getElementById('replay-camera'),
  power: document.getElementById('replay-power'),
  eventList: document.getElementById('event-list'),
};

function replayNum(value, digits = 2) {
  return typeof value === 'number' && !Number.isNaN(value) ? value.toFixed(digits) : '-';
}

async function replayFetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status}`);
  }
  return response.json();
}

function ensureMap() {
  if (replayState.map || !window.L) return;
  replayState.map = L.map('replay-map').setView([40.1772, 44.5035], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(replayState.map);
  replayState.trackLine = L.polyline([], { color: '#005fb8', weight: 3 }).addTo(replayState.map);
  replayState.roverMarker = L.circleMarker([40.1772, 44.5035], {
    radius: 7,
    color: '#c72e0f',
    fillColor: '#c72e0f',
    fillOpacity: 0.9,
  }).addTo(replayState.map);
}

function sessionLabel(session) {
  const start = session.started_at ? new Date(session.started_at * 1000).toLocaleString() : 'unknown';
  return `${session.backend_type} • ${start}`;
}

function renderSessions() {
  if (!replayEls.sessionList) return;
  replayEls.sessionList.innerHTML = '';
  replayEls.currentSessionPill.textContent = replayState.currentSessionId || 'No active session';
  for (const session of replayState.sessions) {
    const item = document.createElement('button');
    item.className = 'session-item';
    if (session.session_id === replayState.loadedSession?.session?.session_id) {
      item.classList.add('active');
    }
    item.innerHTML = `
      <strong>${sessionLabel(session)}</strong>
      <span>${session.telemetry_count} telemetry • ${session.runtime_event_count} events</span>
      <span>${session.session_id}</span>
    `;
    item.addEventListener('click', () => loadSession(session.session_id));
    replayEls.sessionList.appendChild(item);
  }
}

function renderEvents(events = []) {
  if (!replayEls.eventList) return;
  replayEls.eventList.innerHTML = '';
  for (const event of events.slice(-30).reverse()) {
    const row = document.createElement('div');
    row.className = 'event-row';
    const when = event.ts ? new Date(event.ts * 1000).toLocaleTimeString() : '-';
    row.innerHTML = `<strong>${event.event_type}</strong><span>${when}</span>`;
    replayEls.eventList.appendChild(row);
  }
}

function renderTelemetry(payload = {}) {
  const pos = payload.position || {};
  const speed = payload.speed || {};
  const orientation = payload.orientation || {};
  const gps = payload.gps || {};
  const camera = payload.camera || {};
  const power = payload.power || {};
  replayEls.pos.textContent = `${replayNum(pos.x)} ${replayNum(pos.y)} ${replayNum(pos.z)}`;
  replayEls.speed.textContent = `${replayNum(speed.km_h)} km/h | ${replayNum(speed.m_s)} m/s`;
  replayEls.heading.textContent = `${replayNum(orientation.heading_deg)} deg`;
  replayEls.gps.textContent = `${replayNum(gps.lat, 5)}, ${replayNum(gps.lon, 5)}, alt ${replayNum(gps.alt)}m`;
  replayEls.camera.textContent = `${camera.mode || '-'} | ${camera.video_endpoint || '-'}`;
  replayEls.power.textContent = `${replayNum(power.battery_pct)}% | ${replayNum(power.voltage_v)}V | ${replayNum(power.current_a)}A | ${replayNum(power.temperature_c)}C`;
}

function updateMapForIndex(index) {
  ensureMap();
  if (!replayState.map || !replayState.loadedSession) return;
  const telemetry = replayState.loadedSession.timeline.telemetry || [];
  const track = telemetry
    .slice(0, index + 1)
    .map((entry) => {
      const gps = entry.payload?.gps || {};
      return [gps.lat, gps.lon];
    })
    .filter(([lat, lon]) => typeof lat === 'number' && typeof lon === 'number' && (lat !== 0 || lon !== 0));
  if (!track.length) return;
  replayState.trackLine.setLatLngs(track);
  replayState.roverMarker.setLatLng(track[track.length - 1]);
  replayState.map.fitBounds(replayState.trackLine.getBounds(), { padding: [24, 24], maxZoom: 17 });
}

function stopPlayback() {
  replayState.playing = false;
  replayEls.playPause.textContent = 'Play';
  if (replayState.playbackTimer) {
    window.clearTimeout(replayState.playbackTimer);
    replayState.playbackTimer = null;
  }
}

function advancePlayback() {
  const telemetry = replayState.loadedSession?.timeline?.telemetry || [];
  if (!telemetry.length) {
    stopPlayback();
    return;
  }
  if (replayState.playbackIndex >= telemetry.length - 1) {
    stopPlayback();
    return;
  }
  replayState.playbackIndex += 1;
  replayEls.timelineScrubber.value = String(replayState.playbackIndex);
  applyPlaybackIndex(replayState.playbackIndex);
  const currentTs = telemetry[replayState.playbackIndex].ts || 0;
  const nextTs = telemetry[replayState.playbackIndex + 1]?.ts || currentTs;
  const delayMs = Math.max(100, ((nextTs - currentTs) * 1000) / replayState.speed);
  replayState.playbackTimer = window.setTimeout(advancePlayback, delayMs);
}

function applyPlaybackIndex(index) {
  const telemetry = replayState.loadedSession?.timeline?.telemetry || [];
  if (!telemetry.length) return;
  const safeIndex = Math.max(0, Math.min(index, telemetry.length - 1));
  replayState.playbackIndex = safeIndex;
  const entry = telemetry[safeIndex];
  renderTelemetry(entry.payload);
  updateMapForIndex(safeIndex);
  const ts = entry.ts ? new Date(entry.ts * 1000).toLocaleString() : '-';
  replayEls.timelineStatus.textContent = `Frame ${safeIndex + 1}/${telemetry.length} • ${ts} • ${replayState.speed}x`;
}

async function loadSession(sessionId) {
  stopPlayback();
  const result = await replayFetchJson(`/api/replay/sessions/${encodeURIComponent(sessionId)}`);
  replayState.loadedSession = result;
  replayState.playbackIndex = 0;
  replayEls.loadedSessionPill.textContent = sessionId;
  replayEls.timelineScrubber.max = String(Math.max(0, (result.timeline.telemetry || []).length - 1));
  replayEls.timelineScrubber.value = '0';
  renderEvents(result.timeline.events || []);
  applyPlaybackIndex(0);
  renderSessions();
}

async function loadSessions() {
  const result = await replayFetchJson('/api/replay/sessions');
  replayState.sessions = result.sessions || [];
  replayState.currentSessionId = result.current_session_id;
  renderSessions();
}

async function rolloverSession() {
  const result = await replayFetchJson('/api/replay/sessions/rollover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: 'replay_ui_rollover' }),
  });
  replayState.currentSessionId = result.current_session_id;
  await loadSessions();
}

function bindReplayActions() {
  replayEls.refreshSessions?.addEventListener('click', loadSessions);
  replayEls.rolloverSession?.addEventListener('click', rolloverSession);
  replayEls.seekStart?.addEventListener('click', () => {
    stopPlayback();
    replayEls.timelineScrubber.value = '0';
    applyPlaybackIndex(0);
  });
  replayEls.playPause?.addEventListener('click', () => {
    if (!replayState.loadedSession) return;
    if (replayState.playing) {
      stopPlayback();
      return;
    }
    replayState.playing = true;
    replayEls.playPause.textContent = 'Pause';
    advancePlayback();
  });
  replayEls.replaySpeed?.addEventListener('change', (event) => {
    replayState.speed = Number(event.target.value) || 1;
  });
  replayEls.timelineScrubber?.addEventListener('input', (event) => {
    stopPlayback();
    applyPlaybackIndex(Number(event.target.value) || 0);
  });
}

async function initReplay() {
  ensureMap();
  bindReplayActions();
  await loadSessions();
  if (replayState.currentSessionId) {
    await loadSession(replayState.currentSessionId);
  } else if (replayState.sessions[0]) {
    await loadSession(replayState.sessions[0].session_id);
  }
}

initReplay().catch((error) => {
  if (replayEls.timelineStatus) {
    replayEls.timelineStatus.textContent = `Replay load failed: ${error.message}`;
  }
});
