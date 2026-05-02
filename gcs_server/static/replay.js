const replayState = {
  sessions: [],
  currentSessionId: null,
  loadedSession: null,
  playbackIndex: 0,
  playing: false,
  playbackTimer: null,
  speed: 1,
  visualMode: 'virtual',
  navMode: 'free',
  recordView: 'telemetry',
  selectedObjectId: null,
  layerVisibility: {
    terrain: true,
    roads: true,
    objects: true,
    grid: true,
    points: true,
    path: true,
  },
  map: null,
  mapMode: null,
  mapFocused: false,
  sceneMap: null,
  mapPointerBound: false,
  terrainOverlay: null,
  terrainCanvasLayer: null,
  staticSceneLayer: null,
  sceneGridLayer: null,
  roadLayer: null,
  objectLayer: null,
  telemetryPointsLayer: null,
  currentFrameMarker: null,
  sceneCompassControl: null,
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
  mapViewMode: document.getElementById('map-view-mode'),
  mapNavMode: document.getElementById('map-nav-mode'),
  mapOverlayControls: document.getElementById('map-overlay-controls'),
  mapModeNote: document.getElementById('map-mode-note'),
  mapCursor: document.getElementById('map-cursor'),
  mapPathStats: document.getElementById('map-path-stats'),
  mapObjectDetail: document.getElementById('map-object-detail'),
  fitTerrain: document.getElementById('fit-terrain'),
  fitPath: document.getElementById('fit-path'),
  jumpRover: document.getElementById('jump-rover'),
  layerToggles: {
    terrain: document.getElementById('layer-terrain'),
    roads: document.getElementById('layer-roads'),
    objects: document.getElementById('layer-objects'),
    grid: document.getElementById('layer-grid'),
    points: document.getElementById('layer-points'),
    path: document.getElementById('layer-path'),
  },
  timelineScrubber: document.getElementById('timeline-scrubber'),
  timelineStatus: document.getElementById('timeline-status'),
  pos: document.getElementById('replay-pos'),
  speed: document.getElementById('replay-speed-card'),
  heading: document.getElementById('replay-heading'),
  gps: document.getElementById('replay-gps'),
  camera: document.getElementById('replay-camera'),
  power: document.getElementById('replay-power'),
  eventList: document.getElementById('event-list'),
  recordTabs: Array.from(document.querySelectorAll('[data-record-view]')),
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

function replayDistance(a, b) {
  if (!a || !b) return 0;
  const dx = (b.x || 0) - (a.x || 0);
  const dy = (b.y || 0) - (a.y || 0);
  const dz = (b.z || 0) - (a.z || 0);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
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

function scenePointFromLatLng(latLng) {
  return { x: latLng.lng, y: latLng.lat, z: 0 };
}

function scenePointFromGps(gps) {
  const georef = replayState.sceneMap?.coordinate_system?.georeference;
  if (
    !georef
    || typeof gps?.lat !== 'number'
    || typeof gps?.lon !== 'number'
    || typeof georef.origin_lat !== 'number'
    || typeof georef.origin_lon !== 'number'
  ) {
    return null;
  }

  const earthRadiusM = 6378137.0;
  const originLatRad = (georef.origin_lat * Math.PI) / 180;
  const localOrigin = georef.origin_local || [0, 0, 0];
  const dy = ((gps.lat - georef.origin_lat) * Math.PI / 180) * earthRadiusM;
  const dx = ((gps.lon - georef.origin_lon) * Math.PI / 180) * earthRadiusM * Math.cos(originLatRad);
  return {
    x: dx + (Number(localOrigin[0]) || 0),
    y: dy + (Number(localOrigin[1]) || 0),
    z: (typeof gps.alt === 'number' ? gps.alt : 0) + (Number(localOrigin[2]) || 0),
  };
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
    const sourceRow = grid[size - 1 - row] || [];
    for (let col = 0; col < size; col += 1) {
      const normalized = sourceRow[col] ?? 0;
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

function buildTerrainCanvas(sceneMap) {
  const grid = sceneMap.heightmap || [];
  const size = sceneMap.grid_size || grid.length || 0;
  if (!size || !grid.length) return null;

  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const image = ctx.createImageData(size, size);

  for (let row = 0; row < size; row += 1) {
    const sourceRow = grid[size - 1 - row] || [];
    for (let col = 0; col < size; col += 1) {
      const normalized = sourceRow[col] ?? 0;
      const tint = terrainColorForNormalizedHeight(normalized);
      const idx = (row * size + col) * 4;
      image.data[idx] = tint[0];
      image.data[idx + 1] = tint[1];
      image.data[idx + 2] = tint[2];
      image.data[idx + 3] = 255;
    }
  }

  ctx.putImageData(image, 0, 0);
  return canvas;
}

function sceneBoundsLatLng(sceneMap) {
  return [
    [sceneMap.bounds.min_y, sceneMap.bounds.min_x],
    [sceneMap.bounds.max_y, sceneMap.bounds.max_x],
  ];
}

function fitSceneMapBounds() {
  if (!replayState.map || !replayState.sceneMap || replayState.mapMode !== 'scene') return;
  replayState.map.fitBounds(sceneBoundsLatLng(replayState.sceneMap), { padding: [24, 24], animate: false });
  replayState.mapFocused = true;
  invalidateReplayMap();
}

function isSatelliteDebugMode() {
  return replayState.visualMode === 'satellite-debug';
}

function sceneMapLabel() {
  const labels = {
    virtual: 'Virtual Terrain',
    cad: 'CAD/Object View',
    heightmap: 'Heightmap',
    'satellite-debug': 'GPS/Satellite Debug',
  };
  return labels[replayState.visualMode] || 'Virtual Terrain';
}

function makeTerrainCanvasLayer(sceneMap) {
  const sourceCanvas = buildTerrainCanvas(sceneMap);
  if (!sourceCanvas || !window.L) return null;

  const TerrainCanvasLayer = L.Layer.extend({
    onAdd(map) {
      this._map = map;
      this._canvas = L.DomUtil.create('canvas', 'replay-terrain-canvas leaflet-layer');
      this._ctx = this._canvas.getContext('2d');
      const pane = map.getPane('terrainPane') || map.getPanes().overlayPane;
      pane.appendChild(this._canvas);
      map.on('move zoom resize viewreset zoomend moveend', this._reset, this);
      this._reset();
    },
    onRemove(map) {
      map.off('move zoom resize viewreset zoomend moveend', this._reset, this);
      L.DomUtil.remove(this._canvas);
      this._canvas = null;
      this._ctx = null;
      this._map = null;
    },
    _reset() {
      if (!this._map || !this._canvas || !this._ctx) return;
      const size = this._map.getSize();
      this._canvas.width = size.x;
      this._canvas.height = size.y;
      L.DomUtil.setPosition(this._canvas, L.point(0, 0));

      const northWest = this._map.latLngToContainerPoint([sceneMap.bounds.max_y, sceneMap.bounds.min_x]);
      const southEast = this._map.latLngToContainerPoint([sceneMap.bounds.min_y, sceneMap.bounds.max_x]);
      const left = Math.min(northWest.x, southEast.x);
      const top = Math.min(northWest.y, southEast.y);
      const width = Math.abs(southEast.x - northWest.x);
      const height = Math.abs(southEast.y - northWest.y);

      this._ctx.clearRect(0, 0, size.x, size.y);
      this._ctx.imageSmoothingEnabled = false;
      this._ctx.drawImage(sourceCanvas, left, top, width, height);
    },
  });
  return new TerrainCanvasLayer();
}

function sceneObjectStyle(object) {
  const styles = {
    boulder: ['#71685b', 0.36],
    building: ['#8c6b4d', 0.38],
    charger: ['#f2b134', 0.72],
    guard_rail: ['#b8c1c5', 0.45],
    pad: ['#a88b64', 0.26],
    solar_frame: ['#8d969a', 0.22],
    solar_panel: ['#1e4f6d', 0.34],
    stone: ['#777267', 0.34],
    tree: ['#3d7b45', 0.32],
  };
  const [color, fillOpacity] = styles[object.kind] || ['#5b8a57', 0.28];
  return { color, fillOpacity };
}

function speedColor(speedMps) {
  const speed = Math.max(0, Math.min(4, Number(speedMps) || 0));
  if (speed < 0.25) return '#8d969a';
  if (speed < 1.25) return '#2ea043';
  if (speed < 2.5) return '#f2b134';
  return '#c72e0f';
}

function makeRoverIcon(headingDeg = 0) {
  const heading = Number.isFinite(headingDeg) ? headingDeg : 0;
  return L.divIcon({
    className: 'rover-marker-icon',
    html: `<div class="rover-heading-arrow" style="transform: rotate(${heading}deg)"><span></span></div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function makeCurrentFrameIcon() {
  return L.divIcon({
    className: 'current-frame-icon',
    html: '<span></span>',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function bringReplayMarkersToFront() {
  replayState.roverMarker?.setZIndexOffset?.(1200);
  replayState.currentFrameMarker?.setZIndexOffset?.(1100);
}

function destroyMap() {
  if (!replayState.map) return;
  replayState.map.remove();
  replayState.map = null;
  replayState.mapMode = null;
  replayState.mapFocused = false;
  replayState.mapPointerBound = false;
  replayState.terrainOverlay = null;
  replayState.terrainCanvasLayer = null;
  replayState.staticSceneLayer = null;
  replayState.sceneGridLayer = null;
  replayState.roadLayer = null;
  replayState.objectLayer = null;
  replayState.telemetryPointsLayer = null;
  replayState.currentFrameMarker = null;
  replayState.sceneCompassControl = null;
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
      maxZoom: 4,
      zoomSnap: 0.25,
      attributionControl: false,
      zoomControl: true,
    });
    replayState.mapMode = 'scene';
    replayState.map.createPane('terrainPane');
    replayState.map.getPane('terrainPane').style.zIndex = 180;
    replayState.map.getPane('terrainPane').style.pointerEvents = 'none';
    replayState.map.createPane('scenePane');
    replayState.map.getPane('scenePane').style.zIndex = 420;
    replayState.map.createPane('replayPathPane');
    replayState.map.getPane('replayPathPane').style.zIndex = 470;
    replayState.staticSceneLayer = L.layerGroup().addTo(replayState.map);
    replayState.roadLayer = L.layerGroup().addTo(replayState.map);
    replayState.objectLayer = L.layerGroup().addTo(replayState.map);
    replayState.telemetryPointsLayer = L.layerGroup().addTo(replayState.map);
    replayState.fullTrackLine = L.polyline([], {
      color: '#c9d4de',
      weight: 3,
      opacity: 0.95,
      dashArray: '8 8',
      pane: 'replayPathPane',
    }).addTo(replayState.map);
    replayState.trackLine = L.polyline([], {
      color: '#005fb8',
      weight: 4,
      opacity: 0.98,
      pane: 'replayPathPane',
    }).addTo(replayState.map);
    replayState.roverMarker = L.marker([0, 0], {
      icon: makeRoverIcon(0),
      pane: 'replayPathPane',
    }).addTo(replayState.map);
    replayState.currentFrameMarker = L.marker([0, 0], {
      icon: makeCurrentFrameIcon(),
      pane: 'replayPathPane',
      interactive: false,
    }).addTo(replayState.map);

    if (replayState.sceneMap) {
      fitSceneMapBounds();
    } else {
      replayState.map.setView([0, 0], 0);
    }
    bindMapPointerReadout();
    return;
  }

  const georef = replayState.sceneMap?.coordinate_system?.georeference || {};
  const origin = [
    typeof georef.origin_lat === 'number' ? georef.origin_lat : 40.17,
    typeof georef.origin_lon === 'number' ? georef.origin_lon : 44.5,
  ];
  replayState.map = L.map('replay-map').setView(origin, 18);
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
  replayState.telemetryPointsLayer = L.layerGroup().addTo(replayState.map);
  replayState.roverMarker = L.marker(origin, {
    icon: makeRoverIcon(0),
  }).addTo(replayState.map);
  replayState.currentFrameMarker = L.marker(origin, {
    icon: makeCurrentFrameIcon(),
    interactive: false,
  }).addTo(replayState.map);
  bindMapPointerReadout();
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
  renderReplayRecords({});
  destroyMap();
  ensureMap(replayState.sceneMap && !isSatelliteDebugMode() ? 'scene' : 'geo');
  renderStaticScene(replayState.sceneMap);
}

function renderSessions() {
  if (!replayEls.sessionList) return;
  replayEls.sessionList.innerHTML = '';
  replayEls.currentSessionPill.textContent = replayState.currentSessionId || 'No active session';
  if (!replayState.sessions.length) {
    const empty = document.createElement('article');
    empty.className = 'session-item';
    empty.innerHTML = '<span>No replay sessions yet. Start the simulator/GCS and record telemetry.</span>';
    replayEls.sessionList.appendChild(empty);
    return;
  }
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
      <span>${session.telemetry_count} telemetry • ${session.control_count || 0} controls • ${session.runtime_event_count} events</span>
      <span>${session.session_id}</span>
    `;
    selectButton.addEventListener('click', async () => {
      try {
        await loadSession(session.session_id);
      } catch (error) {
        replayEls.timelineStatus.textContent = `Load failed: ${error.message}`;
      }
    });

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
  renderReplayRecords({ events });
}

function formatReplayTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString() : '-';
}

function telemetryRecordLine(entry, index) {
  const payload = entry.payload || {};
  const pos = payload.position || {};
  const speed = payload.speed || {};
  return {
    title: `Frame ${index + 1}`,
    meta: `${formatReplayTime(entry.ts)} | pos ${replayNum(pos.x)}, ${replayNum(pos.y)}, ${replayNum(pos.z)} | ${replayNum(speed.m_s)} m/s`,
  };
}

function controlRecordLine(entry) {
  const buttons = entry.payload?.buttons || {};
  const active = Object.entries(buttons)
    .filter(([, value]) => value)
    .map(([key]) => key)
    .join(', ') || 'neutral';
  return {
    title: `Control | ${active}`,
    meta: `${formatReplayTime(entry.ts)} | ${entry.source || 'gcs'}`,
  };
}

function eventRecordLine(entry) {
  return {
    title: entry.event_type || 'system_event',
    meta: `${formatReplayTime(entry.ts)} | ${entry.level || 'info'}`,
  };
}

function renderReplayRecords(timeline = replayState.loadedSession?.timeline || {}) {
  if (!replayEls.eventList) return;
  const telemetry = timeline.telemetry || [];
  const controls = timeline.controls || [];
  const events = timeline.events || [];
  let records = [];

  if (replayState.recordView === 'telemetry') {
    records = telemetry.map((entry, index) => ({ ...telemetryRecordLine(entry, index), ts: entry.ts }));
  } else if (replayState.recordView === 'controls') {
    records = controls.map((entry) => ({ ...controlRecordLine(entry), ts: entry.ts }));
  } else if (replayState.recordView === 'events') {
    records = events.map((entry) => ({ ...eventRecordLine(entry), ts: entry.ts }));
  } else {
    records = [
      ...telemetry.map((entry, index) => ({ ...telemetryRecordLine(entry, index), ts: entry.ts, kind: 'Telemetry' })),
      ...controls.map((entry) => ({ ...controlRecordLine(entry), ts: entry.ts, kind: 'Control' })),
      ...events.map((entry) => ({ ...eventRecordLine(entry), ts: entry.ts, kind: 'System' })),
    ].sort((a, b) => (a.ts || 0) - (b.ts || 0));
  }

  replayEls.eventList.innerHTML = '';
  const visible = records.slice(-150).reverse();
  if (!visible.length) {
    const empty = document.createElement('div');
    empty.className = 'event-row';
    empty.innerHTML = '<strong>No records</strong><span>This session has no records for this view.</span>';
    replayEls.eventList.appendChild(empty);
    return;
  }

  for (const record of visible) {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.innerHTML = `<strong>${record.kind ? `${record.kind}: ` : ''}${record.title}</strong><span>${record.meta}</span>`;
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
  replayEls.gps.textContent = `${replayNum(gps.lat, 6)}, ${replayNum(gps.lon, 6)}, alt ${replayNum(gps.alt)}m`;
  replayEls.camera.textContent = `${camera.mode || '-'} | ${camera.video_endpoint || '-'}`;
  replayEls.power.textContent = `${replayNum(power.battery_pct)}% | ${replayNum(power.voltage_v)}V | ${replayNum(power.current_a)}A | ${replayNum(power.temperature_c)}C`;
}

function selectSceneObject(object) {
  replayState.selectedObjectId = object.id;
  if (!replayEls.mapObjectDetail) return;
  const center = object.center || {};
  replayEls.mapObjectDetail.textContent = `Selection: ${object.label || object.id} | ${object.kind} | x ${replayNum(center.x)}, y ${replayNum(center.y)}, z ${replayNum(center.z)}`;
}

function renderPathStats(telemetry = []) {
  if (!replayEls.mapPathStats) return;
  const stats = calculatePathStats(telemetry);
  replayEls.mapPathStats.textContent = `Path: ${stats.samples} samples | ${replayNum(stats.distanceM, 1)} m | ${replayNum(stats.durationS, 1)} s | avg ${replayNum(stats.avgSpeed)} m/s | max ${replayNum(stats.maxSpeed)} m/s`;
}

function renderTelemetryPoints(telemetry = []) {
  replayState.telemetryPointsLayer?.clearLayers();
  if (!replayState.telemetryPointsLayer || !replayState.layerVisibility.points) return;
  const sceneMode = replayState.mapMode === 'scene';
  const points = getTrackPoints(telemetry, sceneMode);
  const stride = Math.max(1, Math.ceil(points.length / 500));
  points.forEach((entry, index) => {
    if (index % stride !== 0 && index !== points.length - 1) return;
    const speed = entry.payload?.speed?.m_s;
    L.circleMarker(entry.latLng, {
      radius: index === points.length - 1 ? 4 : 2.5,
      color: speedColor(speed),
      weight: 1,
      fillColor: speedColor(speed),
      fillOpacity: 0.72,
      opacity: 0.88,
      pane: sceneMode ? 'replayPathPane' : undefined,
    })
      .bindTooltip(`${formatReplayTime(entry.ts)} | ${replayNum(speed)} m/s`, { direction: 'top' })
      .addTo(replayState.telemetryPointsLayer);
  });
}

function syncPathLayerVisibility() {
  const visible = replayState.layerVisibility.path;
  replayState.fullTrackLine?.setStyle({ opacity: visible ? 0.95 : 0 });
  replayState.trackLine?.setStyle({ opacity: visible ? 0.98 : 0 });
  [replayState.roverMarker, replayState.currentFrameMarker].forEach((marker) => {
    const el = marker?.getElement?.();
    if (el) el.style.display = visible ? '' : 'none';
  });
}

function getSceneTrack(telemetry = []) {
  return telemetry
    .map((entry) => {
      const position = entry.payload?.position;
      if (position && typeof position.x === 'number' && typeof position.y === 'number') {
        return position;
      }
      return scenePointFromGps(entry.payload?.gps);
    })
    .filter((pos) => pos && typeof pos.x === 'number' && typeof pos.y === 'number')
    .map((pos) => latLngFromScenePoint(pos));
}

function getGeoTrack(telemetry = []) {
  return telemetry
    .map((entry) => entry.payload?.gps || {})
    .filter((gps) => typeof gps.lat === 'number' && typeof gps.lon === 'number' && (gps.lat !== 0 || gps.lon !== 0))
    .map((gps) => [gps.lat, gps.lon]);
}

function getTrackPoints(telemetry = [], sceneMode = true) {
  return telemetry
    .map((entry) => {
      if (sceneMode) {
        const position = entry.payload?.position;
        const point = position && typeof position.x === 'number' && typeof position.y === 'number'
          ? position
          : scenePointFromGps(entry.payload?.gps);
        return point ? { point, latLng: latLngFromScenePoint(point), payload: entry.payload || {}, ts: entry.ts } : null;
      }
      const gps = entry.payload?.gps || {};
      if (typeof gps.lat !== 'number' || typeof gps.lon !== 'number' || (gps.lat === 0 && gps.lon === 0)) return null;
      return { point: { x: gps.lon, y: gps.lat, z: gps.alt || 0 }, latLng: [gps.lat, gps.lon], payload: entry.payload || {}, ts: entry.ts };
    })
    .filter(Boolean);
}

function calculatePathStats(telemetry = []) {
  const points = telemetry
    .map((entry) => entry.payload?.position)
    .filter((pos) => pos && typeof pos.x === 'number' && typeof pos.y === 'number');
  let distanceM = 0;
  for (let index = 1; index < points.length; index += 1) {
    distanceM += replayDistance(points[index - 1], points[index]);
  }
  const speeds = telemetry
    .map((entry) => Number(entry.payload?.speed?.m_s))
    .filter((value) => Number.isFinite(value));
  const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
  const avgSpeed = speeds.length ? speeds.reduce((sum, value) => sum + value, 0) / speeds.length : 0;
  const startTs = telemetry[0]?.ts || 0;
  const endTs = telemetry[telemetry.length - 1]?.ts || startTs;
  return { distanceM, maxSpeed, avgSpeed, durationS: Math.max(0, endTs - startTs), samples: telemetry.length };
}

function shouldUseSceneMap(sessionDetail) {
  return Boolean(replayState.sceneMap) && !isSatelliteDebugMode();
}

function renderStaticScene(sceneMap, options = {}) {
  if (!replayState.map || replayState.mapMode !== 'scene' || !sceneMap) return;
  const fitBounds = options.fitBounds !== false;
  replayState.staticSceneLayer?.clearLayers();
  replayState.roadLayer?.clearLayers();
  replayState.objectLayer?.clearLayers();
  if (replayState.terrainOverlay) {
    replayState.map.removeLayer(replayState.terrainOverlay);
    replayState.terrainOverlay = null;
  }
  if (replayState.terrainCanvasLayer) {
    replayState.map.removeLayer(replayState.terrainCanvasLayer);
    replayState.terrainCanvasLayer = null;
  }
  if (replayState.sceneGridLayer) {
    replayState.map.removeLayer(replayState.sceneGridLayer);
    replayState.sceneGridLayer = null;
  }
  if (replayState.sceneCompassControl) {
    replayState.map.removeControl(replayState.sceneCompassControl);
    replayState.sceneCompassControl = null;
  }

  const bounds = sceneBoundsLatLng(sceneMap);
  const overlayDataUrl = buildTerrainOverlayDataUrl(sceneMap);
  if (overlayDataUrl && replayState.visualMode !== 'cad' && replayState.layerVisibility.terrain) {
    const opacity = replayState.visualMode === 'heightmap' ? 1.0 : 0.92;
    replayState.terrainOverlay = L.imageOverlay(overlayDataUrl, bounds, {
      opacity,
      pane: 'terrainPane',
      interactive: false,
    }).addTo(replayState.map);
  }

  replayState.sceneGridLayer = L.layerGroup();
  if (replayState.layerVisibility.grid) replayState.sceneGridLayer.addTo(replayState.map);
  const gridColor = replayState.visualMode === 'cad' ? '#496070' : '#f6efe4';
  const gridMinX = Math.ceil(sceneMap.bounds.min_x / 50) * 50;
  const gridMaxX = Math.floor(sceneMap.bounds.max_x / 50) * 50;
  const gridMinY = Math.ceil(sceneMap.bounds.min_y / 50) * 50;
  const gridMaxY = Math.floor(sceneMap.bounds.max_y / 50) * 50;
  for (let coord = gridMinX; coord <= gridMaxX; coord += 50) {
    L.polyline(
      [
        [sceneMap.bounds.min_y, coord],
        [sceneMap.bounds.max_y, coord],
      ],
      { color: gridColor, weight: coord === 0 ? 1.5 : 1, opacity: coord === 0 ? 0.46 : 0.24 },
    ).addTo(replayState.sceneGridLayer);
  }
  for (let coord = gridMinY; coord <= gridMaxY; coord += 50) {
    L.polyline(
      [
        [coord, sceneMap.bounds.min_x],
        [coord, sceneMap.bounds.max_x],
      ],
      { color: gridColor, weight: coord === 0 ? 1.5 : 1, opacity: coord === 0 ? 0.46 : 0.24 },
    ).addTo(replayState.sceneGridLayer);
  }

  if (replayState.visualMode !== 'heightmap' && replayState.layerVisibility.roads) for (const road of sceneMap.roads || []) {
    L.polyline(
      [
        [road.from.y, road.from.x],
        [road.to.y, road.to.x],
      ],
      {
        color: replayState.visualMode === 'cad' ? '#25445c' : '#6f6559',
        weight: Math.max(3, Math.min(14, road.width || 9)),
        opacity: replayState.visualMode === 'cad' ? 0.72 : 0.42,
        lineCap: 'round',
        pane: 'scenePane',
      },
    ).addTo(replayState.roadLayer || replayState.staticSceneLayer);
  }

  if (replayState.visualMode !== 'heightmap' && replayState.layerVisibility.objects) for (const object of sceneMap.objects || []) {
    if (object.metadata?.visible === false) continue;
    const halfWidth = object.pad_half_extents?.x ?? (object.size?.width || 0) / 2;
    const halfHeight = object.pad_half_extents?.y ?? (object.size?.height || 0) / 2;
    const minX = object.center.x - halfWidth;
    const maxX = object.center.x + halfWidth;
    const minY = object.center.y - halfHeight;
    const maxY = object.center.y + halfHeight;
    const { color, fillOpacity } = sceneObjectStyle(object);
    L.rectangle(
      [
        [minY, minX],
        [maxY, maxX],
      ],
      {
        color,
        weight: 1.5,
        fillColor: color,
        fillOpacity: replayState.visualMode === 'cad' ? Math.min(0.72, fillOpacity + 0.24) : fillOpacity,
        pane: 'scenePane',
      },
    )
      .on('click', () => selectSceneObject(object))
      .bindTooltip(`${object.label} • ${object.model_ref}`, { direction: 'top' })
      .addTo(replayState.objectLayer || replayState.staticSceneLayer);
  }

  if (sceneMap.spawn) {
    L.circleMarker([sceneMap.spawn.y, sceneMap.spawn.x], {
      radius: 6,
      color: '#ffffff',
      weight: 2,
      fillColor: '#f2b134',
      fillOpacity: 0.95,
      pane: 'scenePane',
    })
      .bindTooltip('Spawn', { direction: 'top' })
      .addTo(replayState.staticSceneLayer);
  }

  const CompassControl = L.Control.extend({
    options: { position: 'bottomleft' },
    onAdd() {
      const el = L.DomUtil.create('div', 'replay-map-compass');
      el.innerHTML = `
        <strong>N</strong>
        <span class="compass-arrow" aria-hidden="true"></span>
        <small>${sceneMapLabel()}<br>X east / Y north | 50 m grid</small>
      `;
      L.DomEvent.disableClickPropagation(el);
      return el;
    },
  });
  replayState.sceneCompassControl = new CompassControl();
  replayState.sceneCompassControl.addTo(replayState.map);
  replayState.fullTrackLine?.bringToFront();
  replayState.trackLine?.bringToFront();
  bringReplayMarkersToFront();
  if (fitBounds) fitSceneMapBounds();
}

function resetMapForSession(sessionDetail) {
  const useSceneMap = shouldUseSceneMap(sessionDetail);
  ensureMap(useSceneMap ? 'scene' : 'geo');
  if (useSceneMap) {
    renderStaticScene(replayState.sceneMap, { fitBounds: false });
  }

  const telemetry = sessionDetail?.timeline?.telemetry || [];
  const fullTrack = useSceneMap ? getSceneTrack(telemetry) : getGeoTrack(telemetry);
  replayState.fullTrackLine?.setLatLngs(fullTrack);
  replayState.trackLine?.setLatLngs([]);
  renderTelemetryPoints(telemetry);
  renderPathStats(telemetry);
  syncPathLayerVisibility();

  if (fullTrack.length) {
    replayState.roverMarker?.setLatLng(fullTrack[0]);
    replayState.currentFrameMarker?.setLatLng(fullTrack[0]);
  }
  replayState.fullTrackLine?.bringToFront();
  replayState.trackLine?.bringToFront();
  bringReplayMarkersToFront();

  replayState.mapFocused = false;
  if (!replayState.map) return;

  if (fullTrack.length) {
    replayState.map.fitBounds(L.latLngBounds(fullTrack), {
      padding: [40, 40],
      maxZoom: useSceneMap ? 3 : 17,
    });
    replayState.mapFocused = true;
    return;
  }

  if (useSceneMap && replayState.sceneMap) {
    fitSceneMapBounds();
  }
}

function updateMapForIndex(index) {
  if (!replayState.map || !replayState.loadedSession) return;
  const telemetry = replayState.loadedSession.timeline.telemetry || [];
  const sceneMode = replayState.mapMode === 'scene';
  const sourceTrack = sceneMode ? getSceneTrack(telemetry.slice(0, index + 1)) : getGeoTrack(telemetry.slice(0, index + 1));
  if (!sourceTrack.length) return;
  const payload = telemetry[index]?.payload || {};
  const heading = payload.orientation?.heading_deg;
  replayState.trackLine.setLatLngs(sourceTrack);
  replayState.roverMarker.setLatLng(sourceTrack[sourceTrack.length - 1]);
  replayState.roverMarker.setIcon(makeRoverIcon(heading));
  replayState.currentFrameMarker?.setLatLng(sourceTrack[sourceTrack.length - 1]);
  replayState.trackLine.bringToFront();
  bringReplayMarkersToFront();
  syncPathLayerVisibility();
  if (replayState.navMode === 'follow') {
    replayState.map.panTo(sourceTrack[sourceTrack.length - 1], { animate: false });
  }
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
  if (!telemetry.length) {
    renderTelemetry({});
    replayState.trackLine?.setLatLngs([]);
    replayEls.timelineStatus.textContent = `No telemetry frames in ${replayState.loadedSession?.session?.session_id || 'this session'}. Select a session with telemetry.`;
    return;
  }
  const safeIndex = Math.max(0, Math.min(index, telemetry.length - 1));
  replayState.playbackIndex = safeIndex;
  const entry = telemetry[safeIndex];
  renderTelemetry(entry.payload);
  updateMapForIndex(safeIndex);
  const ts = entry.ts ? new Date(entry.ts * 1000).toLocaleString() : '-';
  const mapLabel = replayState.mapMode === 'scene' ? 'terrain scene' : 'GPS map';
  replayEls.timelineStatus.textContent = `Frame ${safeIndex + 1}/${telemetry.length} • ${ts} • ${replayState.speed}x • ${mapLabel} • ${sceneMapLabel()}`;
}

async function loadSession(sessionId) {
  stopPlayback();
  const result = await replayFetchJson(`/api/replay/sessions/${encodeURIComponent(sessionId)}`);
  replayState.loadedSession = result;
  replayState.playbackIndex = 0;
  replayEls.loadedSessionPill.textContent = sessionId;
  replayEls.timelineScrubber.max = String(Math.max(0, (result.timeline.telemetry || []).length - 1));
  replayEls.timelineScrubber.value = '0';
  renderReplayRecords(result.timeline || {});
  resetMapForSession(result);
  applyPlaybackIndex(0);
  renderSessions();
}

async function loadSessions() {
  const result = await replayFetchJson('/api/replay/sessions');
  replayState.sessions = result.sessions || [];
  replayState.currentSessionId = result.current_session_id;
  renderSessions();
  return replayState.sessions;
}

async function deleteSession(sessionId) {
  const result = await replayFetchJson(`/api/replay/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
  replayState.currentSessionId = result.current_session_id;
  replayState.sessions = replayState.sessions.filter((session) => session.session_id !== sessionId);

  if (replayState.loadedSession?.session?.session_id === sessionId) {
    const fallbackSessionId = replayState.sessions.find((session) => session.telemetry_count > 0)?.session_id
      || replayState.sessions.find((session) => session.session_id === replayState.currentSessionId)?.session_id
      || replayState.sessions[0]?.session_id
      || null;
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

function syncMapControls() {
  if (replayEls.mapViewMode) replayEls.mapViewMode.value = replayState.visualMode;
  if (replayEls.mapNavMode) replayEls.mapNavMode.value = replayState.navMode;
  if (replayEls.mapModeNote) {
    replayEls.mapModeNote.textContent = isSatelliteDebugMode()
      ? 'Debug only: artificial GPS over real map tiles. Virtual objects are hidden because they do not belong to real satellite imagery.'
      : `${sceneMapLabel()}: local scene meters, X east, Y north.`;
  }
  Object.entries(replayState.layerVisibility).forEach(([name, value]) => {
    if (replayEls.layerToggles[name]) replayEls.layerToggles[name].checked = Boolean(value);
  });
}

function resetCurrentMapView() {
  stopPlayback();
  const mode = isSatelliteDebugMode() ? 'geo' : 'scene';
  ensureMap(mode);
  if (mode === 'scene') {
    renderStaticScene(replayState.sceneMap, { fitBounds: !replayState.loadedSession });
  }
  if (replayState.loadedSession) {
    resetMapForSession(replayState.loadedSession);
    applyPlaybackIndex(replayState.playbackIndex);
  } else {
    fitSceneMapBounds();
  }
  syncMapControls();
}

function bindMapPointerReadout() {
  if (!replayState.map || !replayEls.mapCursor) return;
  if (replayState.mapPointerBound) return;
  replayState.mapPointerBound = true;
  replayState.map.on('mousemove', (event) => {
    if (replayState.mapMode === 'scene') {
      const point = scenePointFromLatLng(event.latlng);
      replayEls.mapCursor.textContent = `Cursor: x ${replayNum(point.x, 1)}, y ${replayNum(point.y, 1)} m`;
      return;
    }
    replayEls.mapCursor.textContent = `Cursor: ${replayNum(event.latlng.lat, 6)}, ${replayNum(event.latlng.lng, 6)}`;
  });
  replayState.map.on('mouseout', () => {
    replayEls.mapCursor.textContent = 'Cursor: -';
  });
}

function fitCurrentPath() {
  const telemetry = replayState.loadedSession?.timeline?.telemetry || [];
  const track = replayState.mapMode === 'scene' ? getSceneTrack(telemetry) : getGeoTrack(telemetry);
  if (!replayState.map || !track.length) return;
  replayState.map.fitBounds(L.latLngBounds(track), { padding: [32, 32], maxZoom: replayState.mapMode === 'scene' ? 3 : 19 });
}

function jumpToRover() {
  if (!replayState.map || !replayState.loadedSession) return;
  const telemetry = replayState.loadedSession.timeline.telemetry || [];
  const entry = telemetry[replayState.playbackIndex];
  if (!entry) return;
  const sceneMode = replayState.mapMode === 'scene';
  const points = getTrackPoints([entry], sceneMode);
  if (points.length) {
    replayState.map.panTo(points[0].latLng, { animate: false });
  }
}

function rerenderCurrentLayers() {
  if (replayState.mapMode === 'scene') {
    renderStaticScene(replayState.sceneMap, { fitBounds: false });
  }
  const telemetry = replayState.loadedSession?.timeline?.telemetry || [];
  renderTelemetryPoints(telemetry);
  syncPathLayerVisibility();
}

function bindReplayActions() {
  if (replayEls.mapOverlayControls && window.L?.DomEvent) {
    L.DomEvent.disableClickPropagation(replayEls.mapOverlayControls);
    L.DomEvent.disableScrollPropagation(replayEls.mapOverlayControls);
  }
  replayEls.refreshSessions?.addEventListener('click', loadSessions);
  replayEls.rolloverSession?.addEventListener('click', rolloverSession);
  replayEls.mapViewMode?.addEventListener('change', (event) => {
    replayState.visualMode = event.target.value || 'virtual';
    resetCurrentMapView();
  });
  replayEls.mapNavMode?.addEventListener('change', (event) => {
    replayState.navMode = event.target.value || 'free';
    resetCurrentMapView();
  });
  replayEls.fitTerrain?.addEventListener('click', fitSceneMapBounds);
  replayEls.fitPath?.addEventListener('click', fitCurrentPath);
  replayEls.jumpRover?.addEventListener('click', jumpToRover);
  Object.entries(replayEls.layerToggles).forEach(([name, input]) => {
    input?.addEventListener('change', (event) => {
      replayState.layerVisibility[name] = Boolean(event.target.checked);
      rerenderCurrentLayers();
    });
  });
  replayEls.recordTabs.forEach((button) => {
    button.addEventListener('click', () => {
      replayState.recordView = button.dataset.recordView || 'telemetry';
      replayEls.recordTabs.forEach((tab) => tab.classList.toggle('active', tab === button));
      renderReplayRecords();
    });
  });
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
  bindReplaySplitResize();
  bindReplayActions();
  syncMapControls();
  await loadSceneMap();
  ensureMap(replayState.sceneMap && !isSatelliteDebugMode() ? 'scene' : 'geo');
  renderStaticScene(replayState.sceneMap);
  await loadSessions();
  const preferredSession = replayState.sessions.find((session) => session.telemetry_count > 0)
    || replayState.sessions.find((session) => session.session_id === replayState.currentSessionId)
    || replayState.sessions[0];
  if (preferredSession) {
    await loadSession(preferredSession.session_id);
  }
}

initReplay().catch((error) => {
  if (replayEls.timelineStatus) {
    replayEls.timelineStatus.textContent = `Replay load failed: ${error.message}`;
  }
});
