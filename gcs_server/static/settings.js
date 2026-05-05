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
  selectAllExportSections: document.getElementById('select-all-export-sections'),
  selectAllImportSections: document.getElementById('select-all-import-sections'),
  applyJsonSettings: document.getElementById('apply-json-settings'),
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
  llmProviderForm: document.getElementById('llm-provider-form'),
  llmProviderId: document.getElementById('llm-provider-id'),
  llmFormModePill: document.getElementById('llm-form-mode-pill'),
  llmProviderTemplate: document.getElementById('llm-provider-template'),
  llmApplyTemplate: document.getElementById('llm-apply-template'),
  llmDisplayName: document.getElementById('llm-display-name'),
  llmProviderType: document.getElementById('llm-provider-type'),
  llmAuthMode: document.getElementById('llm-auth-mode'),
  llmSecretRef: document.getElementById('llm-secret-ref'),
  llmBaseUrl: document.getElementById('llm-base-url'),
  llmModelId: document.getElementById('llm-model-id'),
  llmCapabilities: document.getElementById('llm-capabilities'),
  llmEnabled: document.getElementById('llm-enabled'),
  llmCheckDraft: document.getElementById('llm-check-draft'),
  llmNewProvider: document.getElementById('llm-new-provider'),
  llmCancelEdit: document.getElementById('llm-cancel-edit'),
  llmProviderStatus: document.getElementById('llm-provider-status'),
  llmRegistryPill: document.getElementById('llm-registry-pill'),
  llmProviderList: document.getElementById('llm-provider-list'),
  llmRoutingList: document.getElementById('llm-routing-list'),
  saveModelRouting: document.getElementById('save-model-routing'),
  reloadModelRouting: document.getElementById('reload-model-routing'),
  llmRoutingStatus: document.getElementById('llm-routing-status'),
  jsonExportToggles: Array.from(document.querySelectorAll('.json-export-toggle')),
  jsonImportToggles: Array.from(document.querySelectorAll('.json-import-toggle')),
  jsonPreview: document.getElementById('json-preview'),
};

const LLM_TEMPLATES = {
  openrouter: {
    display_name: 'OpenRouter Model',
    provider_type: 'openrouter',
    auth_mode: 'env_var',
    secret_ref: 'OPENROUTER_API_KEY',
    base_url: 'https://openrouter.ai/api/v1',
    model_id: '',
    capabilities: ['chat', 'reasoning'],
  },
  nvidia_nim: {
    display_name: 'NVIDIA NIM Model',
    provider_type: 'nvidia_nim',
    auth_mode: 'env_var',
    secret_ref: 'NVIDIA_API_KEY',
    base_url: 'https://integrate.api.nvidia.com/v1',
    model_id: '',
    capabilities: ['chat', 'planner', 'tool_calling'],
  },
  openai: {
    display_name: 'OpenAI API Model',
    provider_type: 'openai',
    auth_mode: 'env_var',
    secret_ref: 'OPENAI_API_KEY',
    base_url: 'https://api.openai.com/v1',
    model_id: '',
    capabilities: ['chat', 'reasoning'],
  },
  anthropic: {
    display_name: 'Anthropic Claude API',
    provider_type: 'anthropic',
    auth_mode: 'env_var',
    secret_ref: 'ANTHROPIC_API_KEY',
    base_url: 'https://api.anthropic.com/v1',
    model_id: '',
    capabilities: ['chat', 'reasoning'],
  },
  google_gemini: {
    display_name: 'Google Gemini API',
    provider_type: 'google_gemini',
    auth_mode: 'env_var',
    secret_ref: 'GOOGLE_API_KEY',
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
    model_id: '',
    capabilities: ['chat', 'vision'],
  },
  ollama: {
    display_name: 'Local Ollama',
    provider_type: 'ollama',
    auth_mode: 'none',
    secret_ref: '',
    base_url: 'http://localhost:11434',
    model_id: 'llama3.1:8b',
    capabilities: ['chat'],
  },
  lm_studio: {
    display_name: 'LM Studio Local',
    provider_type: 'lm_studio',
    auth_mode: 'none',
    secret_ref: '',
    base_url: 'http://localhost:1234/v1',
    model_id: '',
    capabilities: ['chat'],
  },
  mistral: {
    display_name: 'Mistral API',
    provider_type: 'mistral',
    auth_mode: 'env_var',
    secret_ref: 'MISTRAL_API_KEY',
    base_url: 'https://api.mistral.ai/v1',
    model_id: '',
    capabilities: ['chat'],
  },
  cohere: {
    display_name: 'Cohere API',
    provider_type: 'cohere',
    auth_mode: 'env_var',
    secret_ref: 'COHERE_API_KEY',
    base_url: 'https://api.cohere.com/v2',
    model_id: '',
    capabilities: ['chat', 'embeddings'],
  },
  together: {
    display_name: 'Together AI',
    provider_type: 'together',
    auth_mode: 'env_var',
    secret_ref: 'TOGETHER_API_KEY',
    base_url: 'https://api.together.xyz/v1',
    model_id: '',
    capabilities: ['chat'],
  },
  groq: {
    display_name: 'Groq',
    provider_type: 'groq',
    auth_mode: 'env_var',
    secret_ref: 'GROQ_API_KEY',
    base_url: 'https://api.groq.com/openai/v1',
    model_id: '',
    capabilities: ['chat'],
  },
  huggingface: {
    display_name: 'Hugging Face Inference',
    provider_type: 'huggingface',
    auth_mode: 'env_var',
    secret_ref: 'HF_TOKEN',
    base_url: 'https://router.huggingface.co/v1',
    model_id: '',
    capabilities: ['chat'],
  },
  openai_compatible: {
    display_name: 'Custom OpenAI-compatible',
    provider_type: 'openai_compatible',
    auth_mode: 'env_var',
    secret_ref: '',
    base_url: '',
    model_id: '',
    capabilities: ['chat'],
  },
};

const ROUTING_LABELS = {
  general_chat: 'General Chat',
  rover_intent_parser: 'Rover Intent Parser',
  mission_planner: 'Mission Planner',
  reporter: 'Reporter',
  embeddings: 'Embeddings',
  vision_object_description: 'Vision / Object Description',
};

const JSON_SECTION_LABELS = {
  connectivity: 'Connectivity',
  video: 'Video',
  appearance: 'Appearance',
  llm_providers: 'LLM Providers',
  model_routing: 'Model Routing',
};

let llmProviders = [];
let modelRouting = {};
let editingFallbackPurpose = null;
let pendingJsonImport = null;

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

function setLlmStatus(text) {
  if (settingsEls.llmProviderStatus) settingsEls.llmProviderStatus.textContent = text;
}

function setRoutingStatus(text) {
  if (settingsEls.llmRoutingStatus) settingsEls.llmRoutingStatus.textContent = text;
}

function setJsonPreview(text, visible = true) {
  if (!settingsEls.jsonPreview) return;
  settingsEls.jsonPreview.hidden = !visible;
  settingsEls.jsonPreview.textContent = text;
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
  return ['connectivity', 'video', 'appearance', 'llm-provider', 'json'].includes(tab) ? tab : 'connectivity';
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

function jsonSectionLabel(section) {
  return JSON_SECTION_LABELS[section] || section;
}

function selectedJsonSections(toggles, actionLabel) {
  const sections = toggles.filter((item) => item.checked).map((item) => item.value);
  if (!sections.length) {
    throw new Error(`Select at least one JSON section to ${actionLabel}.`);
  }
  return sections;
}

function selectedExportSections() {
  return selectedJsonSections(settingsEls.jsonExportToggles, 'export');
}

function selectedImportSections() {
  return selectedJsonSections(settingsEls.jsonImportToggles, 'import');
}

function setScopePills(toggles) {
  for (const toggle of toggles) {
    const pill = toggle.closest('.json-scope-item')?.querySelector('.pill');
    if (pill) pill.textContent = toggle.checked ? (toggle.classList.contains('json-export-toggle') ? 'on' : 'safe') : 'off';
  }
}

function importedSectionPayload(settings, section) {
  if (!settings || typeof settings !== 'object') return undefined;
  if (section === 'connectivity') {
    if (settings.connectivity && typeof settings.connectivity === 'object') return settings.connectivity;
    if (settings.mqtt && typeof settings.mqtt === 'object') {
      return {
        mqtt: settings.mqtt,
        simulation: settings.simulation && typeof settings.simulation === 'object' ? settings.simulation : {},
      };
    }
    return undefined;
  }
  return Object.prototype.hasOwnProperty.call(settings, section) ? settings[section] : undefined;
}

function importSummary(settings, sections) {
  const found = [];
  const missing = [];
  for (const section of sections) {
    if (importedSectionPayload(settings, section) === undefined) missing.push(section);
    else found.push(section);
  }
  return { found, missing };
}

function selectedImportedSettings(settings, sections) {
  const payload = { schema_version: settings && settings.schema_version ? settings.schema_version : 1 };
  for (const section of sections) {
    const sectionPayload = importedSectionPayload(settings, section);
    if (sectionPayload !== undefined) {
      payload[section] = sectionPayload;
    }
  }
  return payload;
}

function describeSections(sections) {
  return sections.length ? sections.map(jsonSectionLabel).join(', ') : 'none';
}

function updateJsonPreview() {
  if (!pendingJsonImport) return;
  const sections = selectedImportSections();
  const { found, missing } = importSummary(pendingJsonImport.settings, sections);
  const previewPayload = selectedImportedSettings(pendingJsonImport.settings, sections);
  setJsonPreview(
    [
      `Preview from ${pendingJsonImport.sourceLabel}`,
      `Will apply: ${describeSections(found)}`,
      `Missing and preserved: ${describeSections(missing)}`,
      'Unchecked sections are preserved.',
      '',
      JSON.stringify(previewPayload, null, 2),
    ].join('\n')
  );
  setJsonStatus(`Preview ready. ${found.length} checked section(s) will apply; ${missing.length} missing checked section(s) will be preserved.`);
}

async function currentSettingsPayload(sections) {
  const payload = await readJson('/api/settings/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sections }),
  });
  if (sections.includes('appearance')) {
    payload.appearance = readAppearanceSettings();
  }
  return payload;
}

async function loadJsonFromBackendPath() {
  const path = settingsEls.backendConfigPath.value.trim();
  if (!path) {
    throw new Error('Backend path is required.');
  }
  const sections = selectedImportSections();
  setJsonStatus(`Loading selected settings from backend path: ${path}`);
  const result = await readJson('/api/settings/load-from-path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, sections }),
  });
  settingsEls.backendConfigPath.value = result.resolved_path || path;
  previewJsonSettings(result.settings || {}, result.resolved_path || path);
}

async function saveJsonToBackendPath() {
  const path = settingsEls.backendConfigPath.value.trim();
  if (!path) {
    throw new Error('Backend path is required.');
  }
  const sections = selectedExportSections();
  const settings = await currentSettingsPayload(sections);
  setJsonStatus(`Saving selected settings to backend path: ${path}`);
  const result = await readJson('/api/settings/save-to-path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, sections, settings }),
  });
  settingsEls.backendConfigPath.value = result.resolved_path || path;
  setJsonPreview(JSON.stringify(settings, null, 2));
  setJsonStatus(`Saved ${describeSections(sections)} to ${result.resolved_path || path}. Active runtime settings were not changed.`);
}

async function loadJsonFromLocalFile() {
  const file = settingsEls.localConfigFile.files && settingsEls.localConfigFile.files[0];
  if (!file) {
    return;
  }
  const sections = selectedImportSections();
  setJsonStatus(`Loading selected settings from local file: ${file.name}`);
  const text = await file.text();
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`Invalid JSON in local file: ${error.message}`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Local JSON file must contain a top-level object.');
  }
  previewJsonSettings(parsed, file.name);
}

async function saveJsonToLocalFile() {
  const sections = selectedExportSections();
  const data = JSON.stringify(await currentSettingsPayload(sections), null, 2);
  const blob = new Blob([`${data}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const stamp = new Date().toISOString().replaceAll(':', '-');
  anchor.href = url;
  anchor.download = `gcs-settings-${stamp}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  setJsonStatus(`Saved local settings file: ${anchor.download}`);
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

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

function statusTone(status) {
  if (status === 'available') return 'ok';
  if (status === 'missing_key' || status === 'not_tested') return 'warn';
  return 'danger';
}

function providerLabel(providerId) {
  const provider = llmProviders.find((item) => item.id === providerId);
  return provider ? provider.display_name : 'No provider';
}

function normalizeSecretRef(value) {
  const secretRef = String(value || '').trim().split('=', 1)[0].trim();
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(secretRef) ? secretRef : '';
}

function providerOptions(selectedId = '', category = '') {
  const options = ['<option value="">No provider</option>'];
  for (const provider of llmProviders) {
    const capabilities = Array.isArray(provider.capabilities) ? provider.capabilities : [];
    const compatible = !category || capabilities.includes(category) || category === 'reasoning' && capabilities.includes('chat');
    const disabled = provider.enabled === false || !compatible;
    options.push(`<option value="${escapeHtml(provider.id)}"${provider.id === selectedId ? ' selected' : ''}${disabled ? ' disabled' : ''}>${escapeHtml(provider.display_name)}${disabled ? ' (unavailable)' : ''}</option>`);
  }
  return options.join('');
}

function readProviderForm() {
  return {
    id: settingsEls.llmProviderId.value || undefined,
    display_name: settingsEls.llmDisplayName.value.trim(),
    provider_type: settingsEls.llmProviderType.value,
    auth_mode: settingsEls.llmAuthMode.value,
    secret_ref: normalizeSecretRef(settingsEls.llmSecretRef.value),
    base_url: settingsEls.llmBaseUrl.value.trim(),
    model_id: settingsEls.llmModelId.value.trim(),
    capabilities: settingsEls.llmCapabilities.value.split(',').map((item) => item.trim()).filter(Boolean),
    enabled: settingsEls.llmEnabled.checked,
  };
}

function fillProviderForm(provider = {}) {
  settingsEls.llmProviderId.value = provider.id || '';
  settingsEls.llmDisplayName.value = provider.display_name || '';
  settingsEls.llmProviderType.value = provider.provider_type || 'openai_compatible';
  settingsEls.llmAuthMode.value = provider.auth_mode || 'env_var';
  settingsEls.llmSecretRef.value = provider.secret_ref || '';
  settingsEls.llmBaseUrl.value = provider.base_url || '';
  settingsEls.llmModelId.value = provider.model_id || '';
  settingsEls.llmCapabilities.value = Array.isArray(provider.capabilities) ? provider.capabilities.join(', ') : '';
  settingsEls.llmEnabled.checked = provider.enabled !== false;
  if (settingsEls.llmFormModePill) {
    settingsEls.llmFormModePill.textContent = provider.id ? 'Editing selected provider' : 'New provider';
    settingsEls.llmFormModePill.className = provider.id ? 'pill warn' : 'pill';
  }
}

function applyProviderTemplate() {
  const template = LLM_TEMPLATES[settingsEls.llmProviderTemplate.value] || LLM_TEMPLATES.openai_compatible;
  fillProviderForm({ ...template, enabled: true });
  setLlmStatus(`Applied ${settingsEls.llmProviderTemplate.options[settingsEls.llmProviderTemplate.selectedIndex].text} template. Save Provider is still required.`);
}

function clearProviderForm() {
  fillProviderForm({ ...LLM_TEMPLATES.openrouter, enabled: true });
}

function renderProviderList() {
  if (!settingsEls.llmProviderList) return;
  const enabledCount = llmProviders.filter((provider) => provider.enabled !== false).length;
  if (settingsEls.llmRegistryPill) settingsEls.llmRegistryPill.textContent = `${enabledCount} enabled`;
  if (!llmProviders.length) {
    settingsEls.llmProviderList.innerHTML = '<p class="settings-note">No LLM providers configured yet.</p>';
    return;
  }
  settingsEls.llmProviderList.innerHTML = llmProviders.map((provider) => {
    const check = provider.last_check || { status: 'not_tested' };
    const tone = statusTone(check.status);
    const capabilities = (provider.capabilities || []).map((capability) => `<span class="llm-chip">${escapeHtml(capability)}</span>`).join('');
    return `
      <div class="llm-provider-row" data-provider-id="${escapeHtml(provider.id)}">
        <div class="llm-provider-title">
          <strong>${escapeHtml(provider.display_name)}</strong>
          <div class="llm-provider-meta"><span class="llm-chip">${escapeHtml(provider.provider_type)}</span></div>
        </div>
        <div class="llm-provider-meta">
          <span class="llm-chip">${escapeHtml(provider.model_id || 'no model id')}</span>
          ${capabilities}
        </div>
        <span class="pill ${tone}">${escapeHtml(check.status || 'not_tested')}</span>
        <div class="llm-actions">
          <button type="button" class="ghost" data-llm-action="check">Check</button>
          <button type="button" class="ghost" data-llm-action="edit">Edit</button>
          <button type="button" class="ghost" data-llm-action="toggle">${provider.enabled === false ? 'Enable' : 'Disable'}</button>
        </div>
      </div>
    `;
  }).join('');
}

function ensureRoutingDefaults() {
  for (const purpose of Object.keys(ROUTING_LABELS)) {
    if (!modelRouting[purpose]) {
      modelRouting[purpose] = { primary_provider_id: '', fallback_provider_ids: [], allow_runtime_override: true };
    }
    if (!Array.isArray(modelRouting[purpose].fallback_provider_ids)) {
      modelRouting[purpose].fallback_provider_ids = [];
    }
  }
}

function renderRoutingList() {
  if (!settingsEls.llmRoutingList) return;
  ensureRoutingDefaults();
  settingsEls.llmRoutingList.innerHTML = Object.entries(ROUTING_LABELS).map(([purpose, label]) => {
    const rule = modelRouting[purpose];
    const fallbackChips = rule.fallback_provider_ids.length
      ? rule.fallback_provider_ids.map((id, index) => `<span class="llm-chip">${index + 1}. ${escapeHtml(providerLabel(id))}</span>`).join('')
      : '<span class="llm-chip">No fallbacks</span>';
    const editor = editingFallbackPurpose === purpose ? renderFallbackEditor(purpose, rule) : '';
    return `
      <div class="llm-routing-row${editingFallbackPurpose === purpose ? ' is-editing' : ''}" data-purpose="${escapeHtml(purpose)}">
        <span>${escapeHtml(label)}</span>
        <select data-routing-field="primary">${providerOptions(rule.primary_provider_id)}</select>
        <div class="llm-fallback-chips">
          ${fallbackChips}
          <button type="button" class="ghost" data-routing-action="${editingFallbackPurpose === purpose ? 'close-fallbacks' : 'edit-fallbacks'}">${editingFallbackPurpose === purpose ? 'Close editor' : 'Edit fallbacks'}</button>
        </div>
        ${editor}
      </div>
    `;
  }).join('');
}

function renderFallbackEditor(purpose, rule) {
  const rows = rule.fallback_provider_ids.map((id, index) => `
    <div class="llm-fallback-editor-row" data-fallback-index="${index}">
      <span>${index + 1}</span>
      <select data-fallback-field="provider">${providerOptions(id)}</select>
      <button type="button" class="ghost" data-fallback-action="up">Up</button>
      <button type="button" class="ghost" data-fallback-action="down">Down</button>
      <button type="button" class="ghost" data-fallback-action="remove">Remove</button>
    </div>
  `).join('');
  return `
    <div class="llm-fallback-editor">
      <div class="llm-fallback-editor-row">
        <span></span>
        <span class="settings-note">Editing fallback priority for ${escapeHtml(ROUTING_LABELS[purpose])}</span>
        <span class="pill">Editing this route</span>
      </div>
      ${rows}
      <div class="llm-fallback-add-row">
        <span>+</span>
        <select data-fallback-field="add">${providerOptions('')}</select>
        <button type="button" class="ghost" data-fallback-action="add">Add fallback</button>
      </div>
    </div>
  `;
}

async function loadLlmSettings() {
  if (!settingsEls.llmProviderList) return;
  setLlmStatus('Loading LLM providers.');
  const data = await readJson('/api/llm-settings');
  llmProviders = data.providers || [];
  modelRouting = data.routing || {};
  renderProviderList();
  renderRoutingList();
  setLlmStatus(`Loaded ${llmProviders.length} configured LLM provider(s).`);
  setRoutingStatus('Routing rules loaded.');
}

async function saveProvider(event) {
  event.preventDefault();
  const provider = readProviderForm();
  const url = provider.id ? `/api/llm-providers/${encodeURIComponent(provider.id)}` : '/api/llm-providers';
  const method = provider.id ? 'PUT' : 'POST';
  const result = await readJson(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(provider),
  });
  const index = llmProviders.findIndex((item) => item.id === result.provider.id);
  if (index >= 0) llmProviders[index] = result.provider;
  else llmProviders.push(result.provider);
  fillProviderForm(result.provider);
  renderProviderList();
  renderRoutingList();
  setLlmStatus(`Saved provider: ${result.provider.display_name}.`);
}

async function checkDraftProvider() {
  setLlmStatus('Checking draft provider.');
  const result = await readJson('/api/llm-providers/check-draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(readProviderForm()),
  });
  setLlmStatus(`Draft check: ${result.check.status}. ${result.check.message || ''}`);
}

async function handleProviderListClick(event) {
  const button = event.target.closest('button[data-llm-action]');
  if (!button) return;
  const row = button.closest('[data-provider-id]');
  const provider = llmProviders.find((item) => item.id === row.dataset.providerId);
  if (!provider) return;
  const action = button.dataset.llmAction;
  if (action === 'edit') {
    fillProviderForm(provider);
    setLlmStatus(`Editing provider: ${provider.display_name}.`);
  } else if (action === 'toggle') {
    const updated = { ...provider, enabled: provider.enabled === false };
    const result = await readJson(`/api/llm-providers/${encodeURIComponent(provider.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated),
    });
    llmProviders = llmProviders.map((item) => item.id === provider.id ? result.provider : item);
    renderProviderList();
    renderRoutingList();
    setLlmStatus(`${result.provider.enabled === false ? 'Disabled' : 'Enabled'} provider: ${result.provider.display_name}.`);
  } else if (action === 'check') {
    setLlmStatus(`Checking provider: ${provider.display_name}.`);
    const result = await readJson(`/api/llm-providers/${encodeURIComponent(provider.id)}/check`, { method: 'POST' });
    llmProviders = llmProviders.map((item) => item.id === provider.id ? result.provider : item);
    renderProviderList();
    setLlmStatus(`Provider check: ${result.check.status}. ${result.check.message || ''}`);
  }
}

function updateRoutingFromDom() {
  for (const row of settingsEls.llmRoutingList.querySelectorAll('[data-purpose]')) {
    const purpose = row.dataset.purpose;
    const primary = row.querySelector('[data-routing-field="primary"]');
    modelRouting[purpose].primary_provider_id = primary ? primary.value : '';
  }
}

function handleRoutingClick(event) {
  const row = event.target.closest('[data-purpose]');
  if (!row) return;
  const purpose = row.dataset.purpose;
  const routingAction = event.target.closest('[data-routing-action]');
  const fallbackAction = event.target.closest('[data-fallback-action]');
  updateRoutingFromDom();
  if (routingAction) {
    editingFallbackPurpose = routingAction.dataset.routingAction === 'edit-fallbacks' ? purpose : null;
    renderRoutingList();
    return;
  }
  if (!fallbackAction) return;
  const rule = modelRouting[purpose];
  const action = fallbackAction.dataset.fallbackAction;
  const editorRow = fallbackAction.closest('[data-fallback-index]');
  const index = editorRow ? Number.parseInt(editorRow.dataset.fallbackIndex, 10) : -1;
  if (action === 'add') {
    const select = row.querySelector('[data-fallback-field="add"]');
    const id = select ? select.value : '';
    if (id && id !== rule.primary_provider_id && !rule.fallback_provider_ids.includes(id)) {
      rule.fallback_provider_ids.push(id);
    }
  } else if (action === 'remove' && index >= 0) {
    rule.fallback_provider_ids.splice(index, 1);
  } else if (action === 'up' && index > 0) {
    [rule.fallback_provider_ids[index - 1], rule.fallback_provider_ids[index]] = [rule.fallback_provider_ids[index], rule.fallback_provider_ids[index - 1]];
  } else if (action === 'down' && index >= 0 && index < rule.fallback_provider_ids.length - 1) {
    [rule.fallback_provider_ids[index + 1], rule.fallback_provider_ids[index]] = [rule.fallback_provider_ids[index], rule.fallback_provider_ids[index + 1]];
  }
  renderRoutingList();
}

function handleRoutingChange(event) {
  const row = event.target.closest('[data-purpose]');
  if (!row) return;
  const purpose = row.dataset.purpose;
  if (event.target.matches('[data-routing-field="primary"]')) {
    modelRouting[purpose].primary_provider_id = event.target.value;
    modelRouting[purpose].fallback_provider_ids = modelRouting[purpose].fallback_provider_ids.filter((id) => id !== event.target.value);
    renderRoutingList();
  } else if (event.target.matches('[data-fallback-field="provider"]')) {
    const editorRow = event.target.closest('[data-fallback-index]');
    const index = Number.parseInt(editorRow.dataset.fallbackIndex, 10);
    const id = event.target.value;
    if (id && id !== modelRouting[purpose].primary_provider_id && !modelRouting[purpose].fallback_provider_ids.includes(id)) {
      modelRouting[purpose].fallback_provider_ids[index] = id;
    }
    renderRoutingList();
  }
}

async function saveRouting() {
  updateRoutingFromDom();
  const result = await readJson('/api/model-routing', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ routing: modelRouting }),
  });
  modelRouting = result.routing || {};
  renderRoutingList();
  setRoutingStatus('Model routing rules saved.');
}

function readAppearanceSettings() {
  return window.GCSCommon.getThemeState();
}

function applyAppearanceSettings(appearance = {}) {
  if (appearance.themeMode) window.GCSCommon.setThemeMode(appearance.themeMode);
  if (appearance.lightTheme) window.GCSCommon.setLightTheme(appearance.lightTheme);
  if (appearance.darkTheme) window.GCSCommon.setDarkTheme(appearance.darkTheme);
  syncThemeControls();
}

function previewJsonSettings(settings, sourceLabel) {
  pendingJsonImport = { settings, sourceLabel };
  updateJsonPreview();
}

async function applyPendingJsonSettings() {
  if (!pendingJsonImport) {
    throw new Error('Load a JSON file or backend path first.');
  }
  const sections = selectedImportSections();
  const settings = selectedImportedSettings(pendingJsonImport.settings, sections);
  const result = await readJson('/api/settings/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sections, settings }),
  });
  if (sections.includes('appearance') && settings.appearance) {
    applyAppearanceSettings(settings.appearance);
  }
  await Promise.all([
    loadConnectivity().catch((error) => setSetupStatus(error.message)),
    loadVideoSettings().catch((error) => setVideoStatus(error.message)),
    loadLlmSettings().catch((error) => setLlmStatus(error.message)),
  ]);
  setJsonStatus(`Applied sections: ${(result.applied_sections || []).join(', ') || 'none'}.`);
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

function bindLlmSettings() {
  if (!settingsEls.llmProviderForm) return;
  settingsEls.llmProviderForm.addEventListener('submit', (event) => {
    saveProvider(event).catch((error) => setLlmStatus(error.message));
  });
  settingsEls.llmApplyTemplate.addEventListener('click', applyProviderTemplate);
  settingsEls.llmNewProvider.addEventListener('click', () => {
    clearProviderForm();
    setLlmStatus('New provider form ready.');
  });
  settingsEls.llmCancelEdit.addEventListener('click', () => {
    clearProviderForm();
    setLlmStatus('Edit cancelled.');
  });
  settingsEls.llmCheckDraft.addEventListener('click', () => {
    checkDraftProvider().catch((error) => setLlmStatus(error.message));
  });
  settingsEls.llmProviderList.addEventListener('click', (event) => {
    handleProviderListClick(event).catch((error) => setLlmStatus(error.message));
  });
  settingsEls.llmRoutingList.addEventListener('click', handleRoutingClick);
  settingsEls.llmRoutingList.addEventListener('change', handleRoutingChange);
  settingsEls.saveModelRouting.addEventListener('click', () => {
    saveRouting().catch((error) => setRoutingStatus(error.message));
  });
  settingsEls.reloadModelRouting.addEventListener('click', () => {
    loadLlmSettings().catch((error) => setRoutingStatus(error.message));
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
    subtitle: 'Persistent GCS configuration lives here. Connectivity, video transport, appearance, AI provider configuration, and JSON config exchange are grouped into one stable settings area.',
  });
  renderTabs(readSelectedTab());
  bindTabs();
  bindAppearance();
  bindLlmSettings();

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
    loadJsonFromBackendPath().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.saveBackendPath.addEventListener('click', () => {
    saveJsonToBackendPath().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.localConfigFile.addEventListener('change', () => {
    loadJsonFromLocalFile().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.saveLocalFile.addEventListener('click', () => {
    saveJsonToLocalFile().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  settingsEls.applyJsonSettings.addEventListener('click', () => {
    applyPendingJsonSettings().catch((error) => {
      setJsonStatus(error.message);
    });
  });

  for (const toggle of [...settingsEls.jsonExportToggles, ...settingsEls.jsonImportToggles]) {
    toggle.addEventListener('change', () => {
      try {
        setScopePills([...settingsEls.jsonExportToggles, ...settingsEls.jsonImportToggles]);
        updateJsonPreview();
      } catch (error) {
        setJsonStatus(error.message);
      }
    });
  }

  settingsEls.selectAllExportSections.addEventListener('click', () => {
    for (const toggle of settingsEls.jsonExportToggles) toggle.checked = true;
    setScopePills(settingsEls.jsonExportToggles);
    setJsonStatus('All export sections selected.');
  });

  settingsEls.selectAllImportSections.addEventListener('click', () => {
    for (const toggle of settingsEls.jsonImportToggles) toggle.checked = true;
    setScopePills(settingsEls.jsonImportToggles);
    try {
      updateJsonPreview();
    } catch (error) {
      setJsonStatus(error.message);
    }
  });

  setScopePills([...settingsEls.jsonExportToggles, ...settingsEls.jsonImportToggles]);

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
  loadLlmSettings().catch((error) => {
    setLlmStatus(error.message);
    setRoutingStatus(error.message);
  });
  clearProviderForm();
}

initSettings();
