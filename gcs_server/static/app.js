const state = {
  clientId: crypto.randomUUID ? crypto.randomUUID() : `gcs-${Date.now()}`,
  socket: null,
  controller: null,
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
  controllerOwner: document.getElementById('controller-owner'),
  telemetryFreshness: document.getElementById('telemetry-freshness'),
  cameraFreshness: document.getElementById('camera-freshness'),
  clientId: document.getElementById('client-id'),
  statusBanner: document.getElementById('status-banner'),
  pos: document.getElementById('pos'),
  speed: document.getElementById('speed'),
  heading: document.getElementById('heading'),
  gps: document.getElementById('gps'),
  cameraMode: document.getElementById('camera-mode'),
  power: document.getElementById('power'),
  videoFrame: document.getElementById('video-frame'),
  videoEmpty: document.getElementById('video-empty'),
  videoModePill: document.getElementById('video-mode-pill'),
  ingestMode: document.getElementById('ingest-mode'),
  deliveryMode: document.getElementById('delivery-mode'),
  videoEnabled: document.getElementById('video-enabled'),
};

els.clientId.textContent = state.clientId;

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
  els.statusBanner.textContent = text;
}

function updateBrokerPill(broker = {}) {
  const status = broker.status || 'disconnected';
  els.brokerPill.textContent = status;
  els.brokerPill.className = 'pill';
  if (status === 'connected') els.brokerPill.classList.add('ok');
  else if (status === 'reconnecting' || status === 'connecting') els.brokerPill.classList.add('warn');
  else els.brokerPill.classList.add('danger');
  els.telemetryFreshness.textContent = broker.telemetry_stale ? 'Stale' : 'Fresh';
  els.cameraFreshness.textContent = broker.camera_stale ? 'Stale' : 'Fresh';
}

function updateController(controller = {}) {
  state.controller = controller;
  const owner = controller.active_client_id;
  els.controllerOwner.textContent = owner || 'Unclaimed';
}

function updateTelemetry(data = {}) {
  const pos = data.position || {};
  const speed = data.speed || {};
  const gps = data.gps || {};
  const orientation = data.orientation || {};
  const camera = data.camera || {};
  const power = data.power || {};

  els.pos.textContent = `${num(pos.x)} ${num(pos.y)} ${num(pos.z)}`;
  els.speed.textContent = `${num(speed.km_h)} km/h | ${num(speed.m_s)} m/s`;
  els.heading.textContent = `${num(orientation.heading_deg)} deg`;
  els.gps.textContent = `${num(gps.lat, 5)}, ${num(gps.lon, 5)}, alt ${num(gps.alt)}m`;
  els.cameraMode.textContent = `${camera.mode || '-'} | ${camera.video_endpoint || '-'}`;
  els.power.textContent = `${num(power.battery_pct)}% | ${num(power.voltage_v)}V | ${num(power.current_a)}A | ${num(power.temperature_c)}C`;
}

function updateVideoMode(mode = {}) {
  els.ingestMode.value = mode.ingest_mode || 'mqtt_frames';
  els.deliveryMode.value = mode.delivery_mode || 'websocket_mjpeg';
  els.videoEnabled.checked = mode.enabled !== false;
  els.videoModePill.textContent = `${els.ingestMode.value} -> ${els.deliveryMode.value}`;
}

function updateVideoFrame(frame = {}) {
  if (!frame.data || !frame.mime_type) return;
  els.videoFrame.src = `data:${frame.mime_type};base64,${frame.data}`;
  els.videoFrame.style.display = 'block';
  els.videoEmpty.style.display = 'none';
}

function num(value, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return value.toFixed(digits);
}

function sendSocketMessage(payload) {
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
  state.socket.send(JSON.stringify(payload));
}

function sendControlState() {
  sendSocketMessage({ type: 'control', buttons: state.buttons });
}

function clearControls() {
  Object.keys(state.buttons).forEach((key) => { state.buttons[key] = false; });
  syncButtons();
  sendControlState();
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
      state.buttons[key] = true;
      syncButtons();
      sendControlState();
    };
    const deactivate = (ev) => {
      ev.preventDefault();
      state.buttons[key] = false;
      syncButtons();
      sendControlState();
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
    if (state.buttons[key]) return;
    state.buttons[key] = true;
    syncButtons();
    sendControlState();
    event.preventDefault();
  });
  window.addEventListener('keyup', (event) => {
    const key = KEY_TO_CONTROL[event.key] || KEY_TO_CONTROL[event.key.toLowerCase?.()];
    if (!key) return;
    state.buttons[key] = false;
    syncButtons();
    sendControlState();
    event.preventDefault();
  });
  window.addEventListener('blur', clearControls);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return response.json();
}

function bindActions() {
  document.getElementById('take-control').addEventListener('click', () => {
    sendSocketMessage({ type: 'take_control' });
  });
  document.getElementById('release-control').addEventListener('click', () => {
    clearControls();
    sendSocketMessage({ type: 'release_control' });
  });
  document.getElementById('save-video-settings').addEventListener('click', async () => {
    const result = await postJson('/api/video-mode', {
      enabled: els.videoEnabled.checked,
      ingest_mode: els.ingestMode.value,
      delivery_mode: els.deliveryMode.value,
    });
    updateVideoMode(result.video);
    setStatus('Video settings saved.');
  });
}

async function loadSnapshot() {
  const response = await fetch('/api/snapshot');
  const snapshot = await response.json();
  updateBrokerPill(snapshot.broker);
  updateController(snapshot.controller);
  updateTelemetry(snapshot.telemetry);
  updateVideoMode(snapshot.video);
  if (snapshot.video.latest_frame) updateVideoFrame(snapshot.video.latest_frame);
}

function connectSocket() {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  state.socket = new WebSocket(`${scheme}://${window.location.host}/ws?client_id=${encodeURIComponent(state.clientId)}`);

  state.socket.addEventListener('open', () => setStatus('Connected to GCS runtime.'));
  state.socket.addEventListener('close', () => setStatus('WebSocket disconnected. Reload to reconnect.'));
  state.socket.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'snapshot') {
      updateBrokerPill(msg.data.broker);
      updateController(msg.data.controller);
      updateTelemetry(msg.data.telemetry);
      updateVideoMode(msg.data.video);
      if (msg.data.video.latest_frame) updateVideoFrame(msg.data.video.latest_frame);
    } else if (msg.type === 'telemetry') {
      updateTelemetry(msg.data);
      updateBrokerPill(msg.broker);
    } else if (msg.type === 'broker') {
      updateBrokerPill(msg.data);
    } else if (msg.type === 'controller') {
      updateController(msg.data);
    } else if (msg.type === 'video_frame') {
      updateVideoFrame(msg.data);
    } else if (msg.type === 'video_mode') {
      updateVideoMode(msg.data);
    } else if (msg.type === 'error') {
      setStatus(msg.message);
      clearControls();
    } else if (msg.type === 'take_control_result') {
      setStatus(msg.ok ? 'Control granted.' : 'Control already owned by another client.');
    }
  });
}

bindControlButtons();
bindKeyboard();
bindActions();
loadSnapshot();
connectSocket();
