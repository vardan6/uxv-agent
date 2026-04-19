const state = {
  clientId: crypto.randomUUID ? crypto.randomUUID() : `gcs-${Date.now()}`,
  socket: null,
  controller: null,
  controlActivationPending: false,
  browserControlActive: false,
  lastTelemetryTs: 0,
  latestTelemetry: {},
  simulation: {},
  themeMode: 'system',
  lightTheme: 'vscode-light',
  darkTheme: 'vscode-dark',
  buttons: {
    forward: false,
    backward: false,
    left: false,
    right: false,
    stop: false,
    camera_toggle: false,
  },
};

const els = {
  brokerPill: document.getElementById('broker-pill'),
  roverPill: document.getElementById('rover-pill'),
  controlStatePill: document.getElementById('control-state-pill'),
  controllerOwner: document.getElementById('controller-owner'),
  telemetryFreshness: document.getElementById('telemetry-freshness'),
  cameraFreshness: document.getElementById('camera-freshness'),
  simulationBackend: document.getElementById('simulation-backend'),
  clientId: document.getElementById('client-id'),
  statusBanner: document.getElementById('status-banner'),
  telemetryLastReceived: document.getElementById('telemetry-last-received'),
  osdLinePosition: document.getElementById('osd-line-position'),
  osdLineSpeed: document.getElementById('osd-line-speed'),
  osdLineGps: document.getElementById('osd-line-gps'),
  osdLinePower: document.getElementById('osd-line-power'),
  osdLineCamera: document.getElementById('osd-line-camera'),
  pos: document.getElementById('pos'),
  speed: document.getElementById('speed'),
  heading: document.getElementById('heading'),
  gps: document.getElementById('gps'),
  cameraMode: document.getElementById('camera-mode'),
  power: document.getElementById('power'),
  videoFrame: document.getElementById('video-frame'),
  videoEmpty: document.getElementById('video-empty'),
  videoModePill: document.getElementById('video-mode-pill'),
};

const THEME_MODE_STORAGE_KEY = 'gcs-theme-mode';
const LIGHT_THEME_STORAGE_KEY = 'gcs-theme-light';
const DARK_THEME_STORAGE_KEY = 'gcs-theme-dark';
const THEME_MODES = new Set(['system', 'light', 'dark']);
const LIGHT_THEMES = new Set(['vscode-light', 'quiet-light', 'cool-light', 'sandstone-light']);
const DARK_THEMES = new Set(['vscode-dark', 'graphite-dark', 'midnight-dark', 'deep-forest-dark']);
const themeMedia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const ROVER_CONNECTED_THRESHOLD_SECONDS = 2;
const ROVER_WARNING_THRESHOLD_SECONDS = 60;

if (els.clientId) {
  els.clientId.textContent = state.clientId;
}

const KEY_TO_CONTROL = {
  ArrowUp: 'forward',
  ArrowDown: 'backward',
  ArrowLeft: 'left',
  ArrowRight: 'right',
  w: 'forward',
  s: 'backward',
  a: 'left',
  d: 'right',
};

function setStatus(text) {
  if (!els.statusBanner) return;
  els.statusBanner.textContent = text;
}

function getResolvedThemeMode() {
  if (state.themeMode === 'system') {
    return themeMedia?.matches ? 'dark' : 'light';
  }
  return state.themeMode;
}

function getActiveThemeName() {
  return getResolvedThemeMode() === 'dark' ? state.darkTheme : state.lightTheme;
}

function syncThemeControls() {
  // Dashboard has no theme controls; keep this as a no-op for shared theme state logic.
}

function applyThemeState() {
  const resolvedMode = getResolvedThemeMode();
  const activeTheme = getActiveThemeName();
  document.documentElement.dataset.themeMode = state.themeMode;
  document.documentElement.dataset.colorMode = resolvedMode;
  document.documentElement.dataset.theme = activeTheme;
  syncThemeControls();
}

function persistThemeState() {
  try {
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, state.themeMode);
    window.localStorage.setItem(LIGHT_THEME_STORAGE_KEY, state.lightTheme);
    window.localStorage.setItem(DARK_THEME_STORAGE_KEY, state.darkTheme);
  } catch (_) {
    // Ignore storage failures and still apply the theme for this session.
  }
}

function initTheme() {
  let savedMode = 'system';
  let savedLightTheme = 'vscode-light';
  let savedDarkTheme = 'vscode-dark';
  try {
    const storedMode = window.localStorage.getItem(THEME_MODE_STORAGE_KEY);
    const storedLight = window.localStorage.getItem(LIGHT_THEME_STORAGE_KEY);
    const storedDark = window.localStorage.getItem(DARK_THEME_STORAGE_KEY);
    savedMode = THEME_MODES.has(storedMode) ? storedMode : 'system';
    savedLightTheme = LIGHT_THEMES.has(storedLight) ? storedLight : 'vscode-light';
    savedDarkTheme = DARK_THEMES.has(storedDark) ? storedDark : 'vscode-dark';
  } catch (_) {
    savedMode = 'system';
    savedLightTheme = 'vscode-light';
    savedDarkTheme = 'vscode-dark';
  }
  state.themeMode = savedMode;
  state.lightTheme = savedLightTheme;
  state.darkTheme = savedDarkTheme;
  applyThemeState();
}

function themeLabel(themeName) {
  const labels = {
    system: 'System',
    light: 'Light',
    dark: 'Dark',
    'vscode-light': 'VS Code Light',
    'quiet-light': 'Quiet Light',
    'cool-light': 'Cool Light',
    'sandstone-light': 'Sandstone Light',
    'vscode-dark': 'VS Code Dark',
    'graphite-dark': 'Graphite Dark',
    'midnight-dark': 'Midnight Dark',
    'deep-forest-dark': 'Deep Forest Dark',
  };
  return labels[themeName] || themeName;
}

function setThemeMode(mode) {
  state.themeMode = THEME_MODES.has(mode) ? mode : 'system';
  applyThemeState();
  persistThemeState();
}

function setLightTheme(theme) {
  state.lightTheme = LIGHT_THEMES.has(theme) ? theme : 'vscode-light';
  applyThemeState();
  persistThemeState();
}

function setDarkTheme(theme) {
  state.darkTheme = DARK_THEMES.has(theme) ? theme : 'vscode-dark';
  applyThemeState();
  persistThemeState();
}

function renderControlToggle() {
  if (!els.controlStatePill) return;
  const owner = state.controller?.active_client_id;
  const isController = owner === state.clientId;
  let label = 'Inactive';
  let tone = 'warn';
  if (state.controlActivationPending) {
    label = state.browserControlActive ? 'Activating' : 'Deactivating';
  } else if (state.browserControlActive && isController) {
    label = 'Active';
    tone = 'ok';
  } else if (owner && !isController) {
    label = 'Other Browser Active';
    tone = 'warn';
  }
  setPillState(els.controlStatePill, label, tone);
}

function setPillState(element, label, tone) {
  if (!element) return;
  element.textContent = label;
  element.className = 'pill';
  element.classList.add(tone);
}

function renderBrokerIndicator(broker = {}) {
  if (!els.brokerPill) return;
  if (broker.connected === true) {
    setPillState(els.brokerPill, 'Connected', 'ok');
    return;
  }
  if (broker.status === 'connecting') {
    setPillState(els.brokerPill, 'Connecting', 'warn');
    return;
  }
  setPillState(els.brokerPill, 'Disconnected', 'danger');
}

function renderRoverIndicator() {
  if (!els.roverPill) return;
  if (!state.lastTelemetryTs) {
    setPillState(els.roverPill, 'No data', 'danger');
    return;
  }
  const ageSeconds = Math.max(0, Math.floor((Date.now() - (state.lastTelemetryTs * 1000)) / 1000));
  if (ageSeconds < ROVER_CONNECTED_THRESHOLD_SECONDS) {
    setPillState(els.roverPill, 'Connected', 'ok');
    return;
  }
  if (ageSeconds < ROVER_WARNING_THRESHOLD_SECONDS) {
    setPillState(els.roverPill, `${ageSeconds}s delayed`, 'warn');
    return;
  }
  setPillState(els.roverPill, 'Unavailable', 'danger');
}

function updateBrokerPill(broker = {}) {
  renderBrokerIndicator(broker);
  state.lastTelemetryTs = typeof broker.last_telemetry_ts === 'number' ? broker.last_telemetry_ts : 0;
  if (els.telemetryFreshness) {
    els.telemetryFreshness.textContent = broker.telemetry_stale ? 'Stale' : 'Fresh';
  }
  if (els.cameraFreshness) {
    els.cameraFreshness.textContent = broker.camera_stale ? 'Stale' : 'Fresh';
  }
  renderTelemetryLastReceived();
}

function renderTelemetryLastReceived() {
  if (!els.telemetryLastReceived) return;
  if (!state.lastTelemetryTs) {
    els.telemetryLastReceived.textContent = 'No data';
    renderRoverIndicator();
    renderTelemetryOsd();
    return;
  }

  const nowMs = Date.now();
  const telemetryMs = state.lastTelemetryTs * 1000;
  const ageSeconds = Math.max(0, Math.floor((nowMs - telemetryMs) / 1000));
  const exactTime = new Date(telemetryMs).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  els.telemetryLastReceived.textContent = `${formatAge(ageSeconds)} ago (${exactTime})`;
  renderRoverIndicator();
  renderTelemetryOsd();
}

function formatAge(totalSeconds) {
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours ? `${days}d ${remainingHours}h` : `${days}d`;
}

function updateController(controller = {}) {
  state.controller = controller;
  const owner = controller.active_client_id;
  const isController = owner === state.clientId;
  if (state.controlActivationPending) {
    if (isController || owner === null) {
      state.controlActivationPending = false;
    }
  }
  if (els.controllerOwner) {
    if (isController) {
      els.controllerOwner.textContent = 'This browser';
    } else if (owner) {
      els.controllerOwner.textContent = 'Another browser';
    } else {
      els.controllerOwner.textContent = 'Inactive';
    }
  }
  renderControlToggle();
}

function updateSimulation(simulation = {}) {
  state.simulation = simulation || {};
  if (els.simulationBackend) {
    const backend = simulation.backend || '-';
    const version = simulation.backend_version ? ` (${simulation.backend_version})` : '';
    els.simulationBackend.textContent = `${backend}${version}`;
  }
}

function updateTelemetry(data = {}) {
  state.latestTelemetry = data;
  if (els.pos) els.pos.textContent = telemetryCardPosition(data);
  if (els.speed) els.speed.textContent = telemetryCardSpeed(data);
  if (els.heading) els.heading.textContent = telemetryCardHeading(data);
  if (els.gps) els.gps.textContent = telemetryCardGps(data);
  if (els.cameraMode) els.cameraMode.textContent = telemetryCardCamera(data);
  if (els.power) els.power.textContent = telemetryCardPower(data);
  renderTelemetryOsd();
}

function updateVideoMode(mode = {}) {
  if (!els.videoModePill) return;
  const ingest = mode.ingest_mode || 'mqtt_frames';
  const delivery = mode.delivery_mode || 'websocket_mjpeg';
  const enabled = mode.enabled !== false;
  els.videoModePill.textContent = enabled ? `${ingest} -> ${delivery}` : 'Disabled';
}

function updateVideoFrame(frame = {}) {
  if (!els.videoFrame || !els.videoEmpty) return;
  if (!frame.data || !frame.mime_type) return;
  els.videoFrame.src = `data:${frame.mime_type};base64,${frame.data}`;
  els.videoFrame.style.display = 'block';
  els.videoEmpty.style.display = 'none';
}

function num(value, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return value.toFixed(digits);
}

function fmt(value, digits = 2, fallback = 0) {
  if (typeof value !== 'number' || Number.isNaN(value)) return fallback.toFixed(digits);
  return value.toFixed(digits);
}

function signedFmt(value, digits = 2, width = 6) {
  const safe = typeof value === 'number' && !Number.isNaN(value) ? value : 0;
  const abs = Math.abs(safe).toFixed(digits);
  return `${safe >= 0 ? '+' : '-'}${abs.padStart(width - 1, '0')}`;
}

function telemetryCardPosition(data = {}) {
  const pos = data.position || {};
  return `${num(pos.x)} ${num(pos.y)} ${num(pos.z)}`;
}

function telemetryCardSpeed(data = {}) {
  const speed = data.speed || {};
  return `${num(speed.km_h)} km/h | ${num(speed.m_s)} m/s`;
}

function telemetryCardHeading(data = {}) {
  const orientation = data.orientation || {};
  return `${num(orientation.heading_deg)} deg`;
}

function telemetryCardGps(data = {}) {
  const gps = data.gps || {};
  return `${num(gps.lat, 5)}, ${num(gps.lon, 5)}, alt ${num(gps.alt)}m`;
}

function telemetryCardCamera(data = {}) {
  const camera = data.camera || {};
  return `${camera.mode || '-'} | ${camera.video_endpoint || '-'}`;
}

function telemetryCardPower(data = {}) {
  const power = data.power || {};
  return `${num(power.battery_pct)}% | ${num(power.voltage_v)}V | ${num(power.current_a)}A | ${num(power.temperature_c)}C`;
}

function telemetryOsdPosition(data = {}) {
  const pos = data.position || {};
  return `position x:${signedFmt(pos.x, 2, 6)} y:${signedFmt(pos.y, 2, 6)} z:${signedFmt(pos.z, 2, 5)}`;
}

function telemetryOsdSpeed(data = {}) {
  const speed = data.speed || {};
  const orientation = data.orientation || {};
  return `speed ${fmt(speed.km_h, 1, 0.0)} km/h (${fmt(speed.m_s, 2, 0.0)} m/s)  heading ${fmt(orientation.heading_deg, 1, 0.0)} deg`;
}

function telemetryOsdGps(data = {}) {
  const gps = data.gps || {};
  return `gps lat:${fmt(gps.lat, 6, 0.0)} lon:${fmt(gps.lon, 6, 0.0)} alt:${fmt(gps.alt, 2, 0.0)} m`;
}

function telemetryOsdPower(data = {}) {
  const power = data.power || {};
  return `power batt:${fmt(power.battery_pct, 0, 0)}%  ${fmt(power.voltage_v, 2, 0.0)}V  ${fmt(power.current_a, 1, 0.0)}A  ${fmt(power.temperature_c, 1, 0.0)}C`;
}

function telemetryOsdCamera(data = {}) {
  const camera = data.camera || {};
  const endpoint = camera.video_endpoint || '-';
  const ageSeconds = state.lastTelemetryTs
    ? Math.max(0, Math.floor((Date.now() - (state.lastTelemetryTs * 1000)) / 1000))
    : null;
  const rx = ageSeconds === null ? 'rx:no data' : `rx:${formatAge(ageSeconds)} ago`;
  return `camera mode:${camera.mode || '-'}  endpoint:${endpoint}  ${rx}`;
}

function renderTelemetryOsd() {
  if (els.osdLinePosition) els.osdLinePosition.textContent = telemetryOsdPosition(state.latestTelemetry);
  if (els.osdLineSpeed) els.osdLineSpeed.textContent = telemetryOsdSpeed(state.latestTelemetry);
  if (els.osdLineGps) els.osdLineGps.textContent = telemetryOsdGps(state.latestTelemetry);
  if (els.osdLinePower) els.osdLinePower.textContent = telemetryOsdPower(state.latestTelemetry);
  if (els.osdLineCamera) els.osdLineCamera.textContent = telemetryOsdCamera(state.latestTelemetry);
}

function sendSocketMessage(payload) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
  state.socket.send(JSON.stringify(payload));
}

function sendControlState() {
  sendSocketMessage({ type: 'control', buttons: state.buttons });
}

async function setControlEnabled(enabled) {
  state.browserControlActive = enabled;
  state.controlActivationPending = true;
  renderControlToggle();
  try {
    const action = enabled ? 'take' : 'release';
    if (enabled) {
      setStatus('Activating browser control for this dashboard.');
    } else {
      clearControls();
      setStatus('Deactivating browser control for this dashboard.');
    }
    const result = await postJson(`/api/controller/${action}`, { client_id: state.clientId });
    state.controlActivationPending = false;
    updateController(result.controller || {});
    setStatus(
      enabled
        ? 'Browser control active while this dashboard remains focused.'
        : 'Browser control inactive while this dashboard is unfocused.'
    );
  } catch (error) {
    state.controlActivationPending = false;
    state.browserControlActive = !!(state.controller?.active_client_id === state.clientId);
    renderControlToggle();
    setStatus(`Control state update failed: ${error.message}`);
  }
}

function clearControls(sendUpdate = true) {
  Object.keys(state.buttons).forEach((key) => { state.buttons[key] = false; });
  syncButtons();
  if (sendUpdate) {
    sendControlState();
  }
}

function canControlLocally() {
  return state.browserControlActive && state.controller?.active_client_id === state.clientId;
}

function syncButtons() {
  document.querySelectorAll('[data-control]').forEach((btn) => {
    btn.classList.toggle('active', !!state.buttons[btn.dataset.control]);
  });
}

function bindControlButtons() {
  document.querySelectorAll('[data-control]').forEach((btn) => {
    const key = btn.dataset.control;
    const activate = (ev) => {
      ev.preventDefault();
      if (!canControlLocally()) {
        setStatus('Control is inactive until this dashboard is focused.');
        return;
      }
      state.buttons[key] = true;
      syncButtons();
      sendControlState();
    };
    const deactivate = (ev) => {
      ev.preventDefault();
      if (!state.buttons[key]) return;
      state.buttons[key] = false;
      syncButtons();
      if (canControlLocally()) {
        sendControlState();
      }
    };
    btn.addEventListener('mousedown', activate);
    btn.addEventListener('touchstart', activate, { passive: false });
    btn.addEventListener('mouseup', deactivate);
    btn.addEventListener('mouseleave', deactivate);
    btn.addEventListener('touchend', deactivate);
    btn.addEventListener('touchcancel', deactivate);
  });
}

function bindKeyboard() {
  window.addEventListener('keydown', (event) => {
    const key = KEY_TO_CONTROL[event.key] || KEY_TO_CONTROL[event.key.toLowerCase?.()];
    if (!key) return;
    if (!canControlLocally()) return;
    if (state.buttons[key]) return;
    state.buttons[key] = true;
    syncButtons();
    sendControlState();
    event.preventDefault();
  });
  window.addEventListener('keyup', (event) => {
    const key = KEY_TO_CONTROL[event.key] || KEY_TO_CONTROL[event.key.toLowerCase?.()];
    if (!key) return;
    if (!canControlLocally()) return;
    state.buttons[key] = false;
    syncButtons();
    sendControlState();
    event.preventDefault();
  });
  window.addEventListener('focus', syncBrowserControlState);
  window.addEventListener('blur', syncBrowserControlState);
  document.addEventListener('visibilitychange', syncBrowserControlState);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return response.json();
}

function desiredBrowserControlState() {
  return document.visibilityState === 'visible' && document.hasFocus();
}

async function syncBrowserControlState() {
  const desired = desiredBrowserControlState();
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
    state.browserControlActive = desired;
    renderControlToggle();
    return;
  }
  if (state.controlActivationPending) return;
  const currentlyOwned = state.controller?.active_client_id === state.clientId;
  if (desired === currentlyOwned && desired === state.browserControlActive) {
    renderControlToggle();
    return;
  }
  await setControlEnabled(desired);
}

function initDashboard() {
  if (!document.querySelector('.controls-panel')) return;
  if (window.GCSCommon?.initShell) {
    window.GCSCommon.initShell({
      page: 'dashboard',
      title: 'Dashboard',
      subtitle: 'Browser-based monitoring and low-latency manual control for the rover simulator.',
    });
  }
  initTheme();
  renderControlToggle();
  window.setInterval(renderTelemetryLastReceived, 1000);
  bindControlButtons();
  bindKeyboard();
  if (themeMedia) {
    const onThemeChange = () => {
      if (state.themeMode !== 'system') return;
      applyThemeState();
      setStatus(`System theme changed. Active ${getResolvedThemeMode()} theme: ${themeLabel(getActiveThemeName())}.`);
    };
    if (typeof themeMedia.addEventListener === 'function') {
      themeMedia.addEventListener('change', onThemeChange);
    } else if (typeof themeMedia.addListener === 'function') {
      themeMedia.addListener(onThemeChange);
    }
  }
  loadSnapshot();
  connectSocket();
}

async function loadSnapshot() {
  const response = await fetch('/api/snapshot');
  const snapshot = await response.json();
  updateBrokerPill(snapshot.broker);
  updateController(snapshot.controller);
  updateTelemetry(snapshot.telemetry);
  updateVideoMode(snapshot.video);
  updateSimulation(snapshot.simulation || {});
  if (snapshot.video.latest_frame) updateVideoFrame(snapshot.video.latest_frame);
}

function connectSocket() {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  state.socket = new WebSocket(`${scheme}://${window.location.host}/ws?client_id=${encodeURIComponent(state.clientId)}`);

  state.socket.addEventListener('open', () => {
    setStatus('Connected to GCS runtime.');
    state.browserControlActive = desiredBrowserControlState();
    renderControlToggle();
    void syncBrowserControlState();
  });
  state.socket.addEventListener('close', () => setStatus('WebSocket disconnected. Reload to reconnect.'));
  state.socket.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'snapshot') {
      updateBrokerPill(msg.data.broker);
      updateController(msg.data.controller);
      updateTelemetry(msg.data.telemetry);
      updateVideoMode(msg.data.video);
      updateSimulation(msg.data.simulation || {});
      if (msg.data.video.latest_frame) updateVideoFrame(msg.data.video.latest_frame);
    } else if (msg.type === 'telemetry') {
      updateTelemetry(msg.data);
      updateBrokerPill(msg.broker);
    } else if (msg.type === 'simulation_config') {
      updateSimulation(msg.data);
    } else if (msg.type === 'broker') {
      updateBrokerPill(msg.data);
    } else if (msg.type === 'controller') {
      updateController(msg.data);
      void syncBrowserControlState();
    } else if (msg.type === 'video_frame') {
      updateVideoFrame(msg.data);
    } else if (msg.type === 'video_mode') {
      updateVideoMode(msg.data);
    } else if (msg.type === 'error') {
      state.controlActivationPending = false;
      renderControlToggle();
      setStatus(msg.message);
      clearControls(false);
    }
  });
}

initDashboard();
