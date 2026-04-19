const replayState = {
  sessions: [],
  currentSessionId: null,
  loadedSession: null,
  playbackIndex: 0,
  playing: false,
  playbackTimer: null,
  speed: 1,
  map: null,
  mapMode: null,
  mapFocused: false,
  sceneMap: null,
  terrainOverlay: null,
  staticSceneLayer: null,
  fullTrackLine: null,
  trackLine: null,
  roverMarker: null,
  baseTileLayer: null,
};

const replayEls = {
  splitPane: document.getElementById('replay-split-pane'),
  replayShell: document.querySelector('.replay-shell'),
  splitDivider: document.getElementById('replay-split-divider'),
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

const REPLAY_SPLIT_STORAGE_KEY = 'gcs-replay-sidebar-width';
const REPLAY_SPLIT_MIN = 260;
const REPLAY_SPLIT_MAX_FRACTION = 0.42;

function isDesktopReplayLayout() {
  return window.matchMedia('(min-width: 1101px)').matches;
}

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

function latLngFromScenePoint(point) {
  return [point.y, point.x];
}

function colorBlend(colorA, colorB, ratio) {
  const blend = Math.max(0, Math.min(1, ratio));
  return colorA.map((channel, index) => Math.round(channel * (1 - blend) + colorB[index] * blend));
}

function terrainColorForNormalizedHeight(level) {
  const ratio = Math.max(0, Math.min(1, level / 255));
  if (ratio < 0.22) {
    return colorBlend([22, 61, 35], [55, 92, 54], ratio / 0.22);
  }
  if (ratio < 0.48) {
    return colorBlend([55, 92, 54], [106, 124, 71], (ratio - 0.22) / 0.26);
  }
  if (ratio < 0.72) {
    return colorBlend([106, 124, 71], [135, 115, 79], (ratio - 0.48) / 0.24);
  }
  return colorBlend([135, 115, 79], [173, 168, 158], (ratio - 0.72) / 0.28);
}

function buildTerrainOverlayDataUrl(sceneMap) {
  const grid = sceneMap.heightmap || [];
  const size = sceneMap.grid_size || grid.length || 0;
  if (!size || !grid.length) return null;

  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(size, size);

  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      const normalized = grid[row]?.[col] ?? 0;
      const tint = terrainColorForNormalizedHeight(normalized);
      const idx = (row * size + col) * 4;
      image.data[idx] = tint[0];
      image.data[idx + 1] = tint[1];
      image.data[idx + 2] = tint[2];
      image.data[idx + 3] = 255;
    }
  }

  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL('image/png');
}

function destroyMap() {
  if (!replayState.map) return;
  replayState.map.remove();
  replayState.map = null;
  replayState.mapMode = null;
  replayState.mapFocused = false;
  replayState.terrainOverlay = null;
  replayState.staticSceneLayer = null;
  replayState.fullTrackLine = null;
  replayState.trackLine = null;
  replayState.roverMarker = null;
  replayState.baseTileLayer = null;
}

function invalidateReplayMap() {
  if (!replayState.map) return;
  window.requestAnimationFrame(() => {
    replayState.map?.invalidateSize(false);
  });
}

function clampReplaySidebarWidth(rawWidth) {
  if (!replayEls.splitPane) return REPLAY_SPLIT_MIN;
  const paneWidth = replayEls.splitPane.getBoundingClientRect().width;
  const dividerWidth = replayEls.splitDivider?.getBoundingClientRect().width || 22;
  const maxByPane = Math.max(REPLAY_SPLIT_MIN, Math.floor((paneWidth - dividerWidth) * REPLAY_SPLIT_MAX_FRACTION));
  return Math.max(REPLAY_SPLIT_MIN, Math.min(Math.round(rawWidth), maxByPane));
}

function setReplaySidebarWidth(width, persist = true) {
  if (!replayEls.splitPane || !isDesktopReplayLayout()) {
    replayEls.splitPane?.style.removeProperty('--replay-sidebar-width');
    return;
  }
  const safeWidth = clampReplaySidebarWidth(width);
  replayEls.splitPane.style.setProperty('--replay-sidebar-width', `${safeWidth}px`);
  if (persist) {
    try {
      window.localStorage.setItem(REPLAY_SPLIT_STORAGE_KEY, String(safeWidth));
    } catch (_) {
      // Ignore storage failures.
    }
  }
}

function loadReplaySidebarWidth() {
  try {
    const stored = Number(window.localStorage.getItem(REPLAY_SPLIT_STORAGE_KEY));
    if (Number.isFinite(stored) && stored >= REPLAY_SPLIT_MIN) {
      return stored;
    }
  } catch (_) {
    // Ignore storage failures.
  }
  return 320;
}

function syncReplaySplitLayout() {
  if (!replayEls.splitPane) return;
  if (!isDesktopReplayLayout()) {
    replayEls.splitPane.style.removeProperty('--replay-sidebar-width');
    return;
  }
  setReplaySidebarWidth(loadReplaySidebarWidth(), false);
  invalidateReplayMap();
}

function bindReplaySplitResize() {
  if (!replayEls.splitDivider || !replayEls.splitPane || !replayEls.replayShell) return;

  replayEls.splitDivider.addEventListener('pointerdown', (event) => {
    if (!isDesktopReplayLayout()) return;
    event.preventDefault();
    const onMove = (moveEvent) => {
      const bounds = replayEls.splitPane.getBoundingClientRect();
      const nextWidth = moveEvent.clientX - bounds.left;
      setReplaySidebarWidth(nextWidth);
    };
    const onStop = () => {
      replayEls.replayShell.classList.remove('is-resizing');
      replayEls.splitDivider.releasePointerCapture?.(event.pointerId);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onStop);
      window.removeEventListener('pointercancel', onStop);
      invalidateReplayMap();
    };

    replayEls.replayShell.classList.add('is-resizing');
    replayEls.splitDivider.setPointerCapture?.(event.pointerId);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onStop);
    window.addEventListener('pointercancel', onStop);
  });

  window.addEventListener('resize', syncReplaySplitLayout);
  syncReplaySplitLayout();
}

function ensureMap(mode = 'geo') {
  if (!window.L) return;
  if (replayState.map && replayState.mapMode === mode) return;

  destroyMap();

  if (mode === 'scene') {
    replayState.map = L.map('replay-map', {
      crs: L.CRS.Simple,
      minZoom: -2,
      maxZoom: 3,
      zoomSnap: 0.25,
      attributionControl: false,
    });
    replayState.mapMode = 'scene';
    replayState.staticSceneLayer = L.layerGroup().addTo(replayState.map);
    replayState.fullTrackLine = L.polyline([], {
      color: '#c9d4de',
      weight: 3,
      opacity: 0.95,
      dashArray: '8 8',
    }).addTo(replayState.map);
    replayState.trackLine = L.polyline([], {
      color: '#005fb8',
      weight: 4,
      opacity: 0.98,
    }).addTo(replayState.map);
    replayState.roverMarker = L.circleMarker([0, 0], {
      radius: 8,
      color: '#ffffff',
      weight: 2,
      fillColor: '#c72e0f',
      fillOpacity: 0.95,
    }).addTo(replayState.map);
    return;
  }

  replayState.map = L.map('replay-map').setView([40.1772, 44.5035], 13);
  replayState.mapMode = 'geo';
  replayState.baseTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(replayState.map);
  replayState.fullTrackLine = L.polyline([], {
    color: '#9fb7cf',
    weight: 3,
    opacity: 0.85,
    dashArray: '8 8',
  }).addTo(replayState.map);
  replayState.trackLine = L.polyline([], { color: '#005fb8', weight: 4 }).addTo(replayState.map);
  replayState.roverMarker = L.circleMarker([40.1772, 44.5035], {
    radius: 7,
    color: '#ffffff',
    weight: 2,
    fillColor: '#c72e0f',
    fillOpacity: 0.95,
  }).addTo(replayState.map);
}

function sessionLabel(session) {
  const start = session.started_at ? new Date(session.started_at * 1000).toLocaleString() : 'unknown';
  return `${session.backend_type} • ${start}`;
}

function clearReplaySelection() {
  stopPlayback();
  replayState.loadedSession = null;
  replayState.playbackIndex = 0;
  replayEls.loadedSessionPill.textContent = 'No session loaded';
  replayEls.timelineScrubber.max = '0';
  replayEls.timelineScrubber.value = '0';
  replayEls.timelineStatus.textContent = 'Load a session to begin replay.';
  renderTelemetry({});
  renderEvents([]);
  destroyMap();
  ensureMap('geo');
}

function renderSessions() {
  if (!replayEls.sessionList) return;
  replayEls.sessionList.innerHTML = '';
  replayEls.currentSessionPill.textContent = replayState.currentSessionId || 'No active session';
  for (const session of replayState.sessions) {
    const item = document.createElement('article');
    item.className = 'session-item';
    if (session.session_id === replayState.loadedSession?.session?.session_id) {
      item.classList.add('active');
    }
    const selectButton = document.createElement('button');
    selectButton.type = 'button';
    selectButton.className = 'session-select';
    selectButton.innerHTML = `
      <strong>${sessionLabel(session)}</strong>
      <span>${session.telemetry_count} telemetry • ${session.runtime_event_count} events</span>
      <span>${session.session_id}</span>
    `;
    selectButton.addEventListener('click', () => loadSession(session.session_id));

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'ghost session-delete';
    deleteButton.textContent = 'Delete';
    const isCurrentSession = session.session_id === replayState.currentSessionId;
    deleteButton.disabled = isCurrentSession;
    deleteButton.title = isCurrentSession ? 'The active session cannot be deleted.' : 'Delete this session';
    deleteButton.addEventListener('click', async (event) => {
      event.stopPropagation();
      if (isCurrentSession) return;
      const confirmed = window.confirm(`Delete session ${session.session_id}? This cannot be undone.`);
      if (!confirmed) return;
      await deleteSession(session.session_id);
    });

    item.append(selectButton, deleteButton);
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

function getSceneTrack(telemetry = []) {
  return telemetry
    .map((entry) => entry.payload?.position)
    .filter((pos) => pos && typeof pos.x === 'number' && typeof pos.y === 'number')
    .map((pos) => latLngFromScenePoint(pos));
}

function getGeoTrack(telemetry = []) {
  return telemetry
    .map((entry) => entry.payload?.gps || {})
    .filter((gps) => typeof gps.lat === 'number' && typeof gps.lon === 'number' && (gps.lat !== 0 || gps.lon !== 0))
    .map((gps) => [gps.lat, gps.lon]);
}

function shouldUseSceneMap(sessionDetail) {
  const backend = sessionDetail?.session?.backend_type;
  if (backend !== '3d-env' || !replayState.sceneMap) return false;
  const telemetry = sessionDetail?.timeline?.telemetry || [];
  return telemetry.some((entry) => {
    const pos = entry.payload?.position;
    return pos && typeof pos.x === 'number' && typeof pos.y === 'number';
  });
}

function renderStaticScene(sceneMap) {
  if (!replayState.map || replayState.mapMode !== 'scene' || !sceneMap) return;
  replayState.staticSceneLayer?.clearLayers();
  if (replayState.terrainOverlay) {
    replayState.map.removeLayer(replayState.terrainOverlay);
    replayState.terrainOverlay = null;
  }

  const bounds = [
    [sceneMap.bounds.min_y, sceneMap.bounds.min_x],
    [sceneMap.bounds.max_y, sceneMap.bounds.max_x],
  ];
  const overlayDataUrl = buildTerrainOverlayDataUrl(sceneMap);
  if (overlayDataUrl) {
    replayState.terrainOverlay = L.imageOverlay(overlayDataUrl, bounds, { opacity: 0.96 }).addTo(replayState.map);
  }

  for (const road of sceneMap.roads || []) {
    L.polyline(
      [
        [road.from.y, road.from.x],
        [road.to.y, road.to.x],
      ],
      {
        color: '#6f6559',
        weight: 9,
        opacity: 0.42,
        lineCap: 'round',
      },
    ).addTo(replayState.staticSceneLayer);
  }

  for (const object of sceneMap.objects || []) {
    const halfWidth = object.pad_half_extents?.x ?? (object.size?.width || 0) / 2;
    const halfHeight = object.pad_half_extents?.y ?? (object.size?.height || 0) / 2;
    const minX = object.center.x - halfWidth;
    const maxX = object.center.x + halfWidth;
    const minY = object.center.y - halfHeight;
    const maxY = object.center.y + halfHeight;
    const color = object.kind === 'building' ? '#8c6b4d' : object.kind === 'hub' ? '#b45f2f' : '#3d7b45';
    L.rectangle(
      [
        [minY, minX],
        [maxY, maxX],
      ],
      {
        color,
        weight: 1.5,
        fillColor: color,
        fillOpacity: 0.28,
      },
    )
      .bindTooltip(`${object.label} • ${object.model_ref}`, { direction: 'top' })
      .addTo(replayState.staticSceneLayer);
  }

  if (sceneMap.spawn) {
    L.circleMarker([sceneMap.spawn.y, sceneMap.spawn.x], {
      radius: 6,
      color: '#ffffff',
      weight: 2,
      fillColor: '#f2b134',
      fillOpacity: 0.95,
    })
      .bindTooltip('Spawn', { direction: 'top' })
      .addTo(replayState.staticSceneLayer);
  }
}

function resetMapForSession(sessionDetail) {
  const useSceneMap = shouldUseSceneMap(sessionDetail);
  ensureMap(useSceneMap ? 'scene' : 'geo');
  if (useSceneMap) {
    renderStaticScene(replayState.sceneMap);
  }

  const telemetry = sessionDetail?.timeline?.telemetry || [];
  const fullTrack = useSceneMap ? getSceneTrack(telemetry) : getGeoTrack(telemetry);
  replayState.fullTrackLine?.setLatLngs(fullTrack);
  replayState.trackLine?.setLatLngs([]);

  if (fullTrack.length) {
    replayState.roverMarker?.setLatLng(fullTrack[0]);
  }

  replayState.mapFocused = false;
  if (!replayState.map) return;

  if (useSceneMap && replayState.sceneMap) {
    const terrainBounds = [
      [replayState.sceneMap.bounds.min_y, replayState.sceneMap.bounds.min_x],
      [replayState.sceneMap.bounds.max_y, replayState.sceneMap.bounds.max_x],
    ];
    replayState.map.fitBounds(terrainBounds, { padding: [24, 24] });
    replayState.mapFocused = true;
    return;
  }

  if (fullTrack.length) {
    replayState.map.fitBounds(L.latLngBounds(fullTrack), { padding: [24, 24], maxZoom: 17 });
    replayState.mapFocused = true;
  }
}

function updateMapForIndex(index) {
  if (!replayState.map || !replayState.loadedSession) return;
  const telemetry = replayState.loadedSession.timeline.telemetry || [];
  const sceneMode = replayState.mapMode === 'scene';
  const sourceTrack = sceneMode ? getSceneTrack(telemetry.slice(0, index + 1)) : getGeoTrack(telemetry.slice(0, index + 1));
  if (!sourceTrack.length) return;
  replayState.trackLine.setLatLngs(sourceTrack);
  replayState.roverMarker.setLatLng(sourceTrack[sourceTrack.length - 1]);
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
  const mapLabel = replayState.mapMode === 'scene' ? 'terrain scene' : 'GPS map';
  replayEls.timelineStatus.textContent = `Frame ${safeIndex + 1}/${telemetry.length} • ${ts} • ${replayState.speed}x • ${mapLabel}`;
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
  resetMapForSession(result);
  applyPlaybackIndex(0);
  renderSessions();
}

async function loadSessions() {
  const result = await replayFetchJson('/api/replay/sessions');
  replayState.sessions = result.sessions || [];
  replayState.currentSessionId = result.current_session_id;
  renderSessions();
}

async function deleteSession(sessionId) {
  const result = await replayFetchJson(`/api/replay/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
  replayState.currentSessionId = result.current_session_id;
  replayState.sessions = replayState.sessions.filter((session) => session.session_id !== sessionId);

  if (replayState.loadedSession?.session?.session_id === sessionId) {
    const fallbackSessionId = replayState.currentSessionId || replayState.sessions[0]?.session_id || null;
    if (fallbackSessionId) {
      await loadSession(fallbackSessionId);
    } else {
      clearReplaySelection();
    }
  }

  renderSessions();
}

async function loadSceneMap() {
  try {
    replayState.sceneMap = await replayFetchJson('/api/replay/scene-map?backend=3d-env&grid_size=128');
  } catch (error) {
    console.warn('Scene map load failed:', error);
    replayState.sceneMap = null;
  }
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
  if (window.GCSCommon?.initShell) {
    window.GCSCommon.initShell({
      page: 'replay',
      title: 'Recorded Sessions',
      subtitle: 'Review rover motion, telemetry, and runtime events from the GCS session log.',
    });
  }
  ensureMap('geo');
  bindReplaySplitResize();
  bindReplayActions();
  await Promise.all([loadSceneMap(), loadSessions()]);
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
