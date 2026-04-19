const settingsEls = {
  tabLinks: Array.from(document.querySelectorAll('[data-settings-tab-link]')),
  tabs: Array.from(document.querySelectorAll('[data-settings-tab]')),
  mqttForm: document.getElementById('mqtt-form'),
  brokerPill: document.getElementById('setup-broker-pill'),
  settingsPath: document.getElementById('settings-path'),
  setupStatus: document.getElementById('setup-status'),
  backendConfigPath: document.getElementById('backend-config-path'),
  loadBackendPath: document.getElementById('load-backend-path'),
  saveBackendPath: document.getElementById('save-backend-path'),
  localConfigFile: document.getElementById('local-config-file'),
  saveLocalFile: document.getElementById('save-local-file'),
  jsonSettingsStatus: document.getElementById('json-settings-status'),
  brokerHost: document.getElementById('broker-host'),
  brokerPort: document.getElementById('broker-port'),
  topicPrefix: document.getElementById('topic-prefix'),
  clientId: document.getElementById('client-id-input'),
  controlTopic: document.getElementById('control-topic'),
  stateTopic: document.getElementById('state-topic'),
  cameraTopic: document.getElementById('camera-topic'),
  controlHz: document.getElementById('control-hz'),
  simulationBackend: document.getElementById('simulation-backend-select'),
  reload: document.getElementById('reload-config'),
  ingestMode: document.getElementById('ingest-mode'),
  deliveryMode: document.getElementById('delivery-mode'),
  videoEnabled: document.getElementById('video-enabled'),
  saveVideoSettings: document.getElementById('save-video-settings'),
  videoSettingsPill: document.getElementById('video-settings-pill'),
  videoSettingsStatus: document.getElementById('video-settings-status'),
  themeModeSelect: document.getElementById('theme-mode-select'),
  lightThemeSelect: document.getElementById('light-theme-select'),
  darkThemeSelect: document.getElementById('dark-theme-select'),
  appearanceStatus: document.getElementById('appearance-status'),
};

function setSetupStatus(text) {
  if (settingsEls.setupStatus) settingsEls.setupStatus.textContent = text;
}

function setJsonStatus(text) {
  if (settingsEls.jsonSettingsStatus) settingsEls.jsonSettingsStatus.textContent = text;
}

function setVideoStatus(text) {
  if (settingsEls.videoSettingsStatus) settingsEls.videoSettingsStatus.textContent = text;
}

function setAppearanceStatus(text) {
  if (settingsEls.appearanceStatus) settingsEls.appearanceStatus.textContent = text;
}

function brokerBadgeState(broker = {}) {
  if (!broker.connected) {
    return { label: broker.status || 'disconnected', tone: 'danger' };
  }
  if (!broker.last_telemetry_ts && !broker.last_camera_ts) {
    return { label: 'Connected, waiting for data', tone: 'warn' };
  }
  if (broker.telemetry_stale && broker.camera_stale) {
    return { label: 'Connected, stale data', tone: 'warn' };
  }
  if (broker.telemetry_stale || broker.camera_stale) {
    return { label: 'Connected, partial data', tone: 'warn' };
  }
  return { label: 'Connected', tone: 'ok' };
}

function updateSetupBrokerPill(broker) {
  if (!settingsEls.brokerPill) return;
  const badge = typeof broker === 'string'
    ? { label: broker, tone: broker === 'loading' ? 'warn' : 'danger' }
    : brokerBadgeState(broker);
  settingsEls.brokerPill.textContent = badge.label || 'unknown';
  settingsEls.brokerPill.className = 'pill';
  settingsEls.brokerPill.classList.add(badge.tone || 'danger');
}

function updateVideoPill(video = {}) {
  if (!settingsEls.videoSettingsPill) return;
  const ingest = video.ingest_mode || 'mqtt_frames';
  const delivery = video.delivery_mode || 'websocket_mjpeg';
  const enabled = video.enabled !== false;
  settingsEls.videoSettingsPill.textContent = enabled ? `${ingest} -> ${delivery}` : 'Disabled';
}

function fillForm(mqtt = {}, simulation = {}) {
  settingsEls.brokerHost.value = mqtt.broker_host || '';
  settingsEls.brokerPort.value = mqtt.broker_port ?? 1883;
  settingsEls.topicPrefix.value = mqtt.topic_prefix || '';
  settingsEls.clientId.value = mqtt.client_id || '';
  settingsEls.controlTopic.value = mqtt.control_topic || 'control/manual';
  settingsEls.stateTopic.value = mqtt.state_topic || 'telemetry/state';
  settingsEls.cameraTopic.value = mqtt.camera_topic || 'camera-feed';
  settingsEls.controlHz.value = mqtt.control_hz ?? 20;
  settingsEls.simulationBackend.value = simulation.backend || '3d-env';
}

function readConnectivityFromForm() {
  return {
    mqtt: {
      broker_host: settingsEls.brokerHost.value.trim(),
      broker_port: Number.parseInt(settingsEls.brokerPort.value, 10),
      topic_prefix: settingsEls.topicPrefix.value.trim(),
      client_id: settingsEls.clientId.value.trim(),
      control_topic: settingsEls.controlTopic.value.trim(),
      state_topic: settingsEls.stateTopic.value.trim(),
      camera_topic: settingsEls.cameraTopic.value.trim(),
      control_hz: Number.parseInt(settingsEls.controlHz.value, 10),
    },
    simulation: {
      backend: settingsEls.simulationBackend.value,
    },
  };
}

function applyConnectivityPayload(payload = {}) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Connectivity payload must be a JSON object.');
  }
  if (!payload.mqtt || typeof payload.mqtt !== 'object') {
    throw new Error('Connectivity payload must include an "mqtt" object.');
  }
  const simulation = payload.simulation && typeof payload.simulation === 'object' ? payload.simulation : {};
  fillForm(payload.mqtt, {
    backend: simulation.backend || settingsEls.simulationBackend.value || '3d-env',
  });
}

function fillVideoSettings(video = {}) {
  settingsEls.ingestMode.value = video.ingest_mode || 'mqtt_frames';
  settingsEls.deliveryMode.value = video.delivery_mode || 'websocket_mjpeg';
  settingsEls.videoEnabled.checked = video.enabled !== false;
  updateVideoPill(video);
}

function syncThemeControls() {
  const theme = window.GCSCommon.getThemeState();
  settingsEls.themeModeSelect.value = theme.themeMode;
  settingsEls.lightThemeSelect.value = theme.lightTheme;
  settingsEls.darkThemeSelect.value = theme.darkTheme;
}

function readSelectedTab() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  return ['connectivity', 'video', 'appearance', 'json'].includes(tab) ? tab : 'connectivity';
}

function renderTabs(tab) {
  for (const pane of settingsEls.tabs) {
    pane.hidden = pane.dataset.settingsTab !== tab;
  }
  for (const link of settingsEls.tabLinks) {
    const active = link.getAttribute('href') === `?tab=${tab}`;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
}

async function readJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Request failed');
  }
  return data;
}

async function loadConnectivity() {
  updateSetupBrokerPill('loading');
  setSetupStatus('Loading shared MQTT settings.');
  const [config, snapshot] = await Promise.all([
    readJson('/api/mqtt-config'),
    readJson('/api/snapshot'),
  ]);
  fillForm(config.mqtt, snapshot.simulation || {});
  settingsEls.settingsPath.textContent = config.settings_path || '-';
  if (settingsEls.backendConfigPath) {
    settingsEls.backendConfigPath.value = config.settings_path || '';
  }
  updateSetupBrokerPill(snapshot.broker || { status: 'disconnected', connected: false });
  setSetupStatus(`Current broker target: ${config.mqtt.broker_host}:${config.mqtt.broker_port}.`);
  setJsonStatus(`Runtime settings file: ${config.settings_path || '-'}. Backend path load/save does not change active runtime settings until Connectivity is saved.`);
}

async function loadVideoSettings() {
  setVideoStatus('Loading current video mode.');
  const snapshot = await readJson('/api/snapshot');
  fillVideoSettings(snapshot.video || {});
  setVideoStatus(`Current delivery path: ${(snapshot.video?.ingest_mode || 'mqtt_frames')} -> ${(snapshot.video?.delivery_mode || 'websocket_mjpeg')}.`);
}

async function saveConnectivity(event) {
  event.preventDefault();
  setSetupStatus('Saving shared config and reconnecting the GCS broker client.');
  updateSetupBrokerPill('connecting');

  const connectivity = readConnectivityFromForm();
  const result = await readJson('/api/mqtt-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mqtt: connectivity.mqtt }),
  });
  await readJson('/api/simulation-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      simulation: {
        backend: connectivity.simulation.backend,
      },
    }),
  });
  fillForm(result.mqtt, { backend: connectivity.simulation.backend });
  settingsEls.settingsPath.textContent = result.settings_path || '-';
  setSetupStatus(`Saved. GCS is reconnecting to ${result.mqtt.broker_host}:${result.mqtt.broker_port}.`);
  window.setTimeout(() => {
    loadConnectivity().catch((error) => {
      updateSetupBrokerPill('error');
      setSetupStatus(error.message);
    });
  }, 800);
}

async function loadConnectivityFromBackendPath() {
  const path = settingsEls.backendConfigPath.value.trim();
  if (!path) {
    throw new Error('Backend path is required.');
  }
  setJsonStatus(`Loading connectivity from backend path: ${path}`);
  const result = await readJson('/api/connectivity/load-from-path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  applyConnectivityPayload(result);
  settingsEls.backendConfigPath.value = result.resolved_path || path;
  setJsonStatus(`Loaded connectivity from ${result.resolved_path || path}. Runtime settings are unchanged until Connectivity is saved.`);
}

async function saveConnectivityToBackendPath() {
  const path = settingsEls.backendConfigPath.value.trim();
  if (!path) {
    throw new Error('Backend path is required.');
  }
  const connectivity = readConnectivityFromForm();
  setJsonStatus(`Saving connectivity to backend path: ${path}`);
  const result = await readJson('/api/connectivity/save-to-path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      mqtt: connectivity.mqtt,
      simulation: connectivity.simulation,
    }),
  });
  settingsEls.backendConfigPath.value = result.resolved_path || path;
  setJsonStatus(`Saved connectivity to ${result.resolved_path || path}. Active runtime settings file is unchanged.`);
}

async function loadConnectivityFromLocalFile() {
  const file = settingsEls.localConfigFile.files && settingsEls.localConfigFile.files[0];
  if (!file) {
    return;
  }
  setJsonStatus(`Loading connectivity from local file: ${file.name}`);
  const text = await file.text();
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`Invalid JSON in local file: ${error.message}`);
  }
  applyConnectivityPayload(parsed);
  setJsonStatus(`Loaded connectivity from local file ${file.name}. Runtime settings are unchanged until Connectivity is saved.`);
}

function saveConnectivityToLocalFile() {
  const connectivity = readConnectivityFromForm();
  const data = JSON.stringify(connectivity, null, 2);
  const blob = new Blob([`${data}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const stamp = new Date().toISOString().replaceAll(':', '-');
  anchor.href = url;
  anchor.download = `gcs-connectivity-${stamp}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  setJsonStatus(`Saved local connectivity file: ${anchor.download}`);
}

async function saveVideoSettings() {
  setVideoStatus('Saving video settings.');
  const result = await readJson('/api/video-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled: settingsEls.videoEnabled.checked,
      ingest_mode: settingsEls.ingestMode.value,
      delivery_mode: settingsEls.deliveryMode.value,
    }),
  });
  fillVideoSettings(result.video || {});
  setVideoStatus('Video settings saved.');
}

function bindAppearance() {
  syncThemeControls();
  settingsEls.themeModeSelect.addEventListener('change', (event) => {
    const theme = window.GCSCommon.setThemeMode(event.target.value);
    setAppearanceStatus(`Theme mode set to ${window.GCSCommon.themeLabel(theme.themeMode)}. Active ${theme.resolvedMode} theme: ${window.GCSCommon.themeLabel(theme.activeTheme)}.`);
  });
  settingsEls.lightThemeSelect.addEventListener('change', (event) => {
    const theme = window.GCSCommon.setLightTheme(event.target.value);
    setAppearanceStatus(
      theme.resolvedMode === 'light'
        ? `Active light theme: ${window.GCSCommon.themeLabel(theme.lightTheme)}.`
        : `Light default saved as ${window.GCSCommon.themeLabel(theme.lightTheme)}.`
    );
  });
  settingsEls.darkThemeSelect.addEventListener('change', (event) => {
    const theme = window.GCSCommon.setDarkTheme(event.target.value);
    setAppearanceStatus(
      theme.resolvedMode === 'dark'
        ? `Active dark theme: ${window.GCSCommon.themeLabel(theme.darkTheme)}.`
        : `Dark default saved as ${window.GCSCommon.themeLabel(theme.darkTheme)}.`
    );
  });
}

function bindTabs() {
  for (const link of settingsEls.tabLinks) {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const href = link.getAttribute('href') || '?tab=connectivity';
      const params = new URLSearchParams(href.slice(1));
      const tab = params.get('tab') || 'connectivity';
      history.replaceState({}, '', `/settings?tab=${encodeURIComponent(tab)}`);
      renderTabs(tab);
    });
  }
  window.addEventListener('popstate', () => {
    renderTabs(readSelectedTab());
  });
}

function initSettings() {
  window.GCSCommon.initShell({
    page: 'settings',
    title: 'Settings',
    subtitle: 'Persistent GCS configuration lives here. Connectivity, video transport, appearance, and JSON config exchange are grouped into one stable settings area.',
  });
  renderTabs(readSelectedTab());
  bindTabs();
  bindAppearance();

  settingsEls.mqttForm.addEventListener('submit', (event) => {
    saveConnectivity(event).catch((error) => {
      updateSetupBrokerPill('error');
      setSetupStatus(error.message);
    });
  });

  settingsEls.reload.addEventListener('click', () => {
    loadConnectivity().catch((error) => {
      updateSetupBrokerPill('error');
      setSetupStatus(error.message);
    });
  });

  settingsEls.loadBackendPath.addEventListener('click', () => {
    loadConnectivityFromBackendPath().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.saveBackendPath.addEventListener('click', () => {
    saveConnectivityToBackendPath().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.localConfigFile.addEventListener('change', () => {
    loadConnectivityFromLocalFile().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.saveLocalFile.addEventListener('click', () => {
    try {
      saveConnectivityToLocalFile();
    } catch (error) {
      setJsonStatus(error.message);
    }
  });

  settingsEls.saveVideoSettings.addEventListener('click', () => {
    saveVideoSettings().catch((error) => {
      setVideoStatus(error.message);
    });
  });

  loadConnectivity().catch((error) => {
    updateSetupBrokerPill('error');
    setSetupStatus(error.message);
    setJsonStatus(error.message);
  });
  loadVideoSettings().catch((error) => {
    setVideoStatus(error.message);
  });
}

initSettings();
