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
  roverConnectedThreshold: document.getElementById('rover-connected-threshold'),
  roverUnavailableThreshold: document.getElementById('rover-unavailable-threshold'),
  roverRolloverOnReconnect: document.getElementById('rover-rollover-on-reconnect'),
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
  aiTtsEnabled: document.getElementById('ai-tts-enabled'),
  aiTtsAutoRead: document.getElementById('ai-tts-auto-read'),
  aiTtsEngine: document.getElementById('ai-tts-engine'),
  aiTtsServiceUrl: document.getElementById('ai-tts-service-url'),
  aiTtsServiceVoice: document.getElementById('ai-tts-service-voice'),
  aiTtsServiceSpeed: document.getElementById('ai-tts-service-speed'),
  aiTtsBrowserFallback: document.getElementById('ai-tts-browser-fallback'),
  aiTtsVoice: document.getElementById('ai-tts-voice'),
  aiTtsRate: document.getElementById('ai-tts-rate'),
  aiTtsPitch: document.getElementById('ai-tts-pitch'),
  aiSettingsPill: document.getElementById('ai-settings-pill'),
  aiSettingsStatus: document.getElementById('ai-settings-status'),
  saveAiSettings: document.getElementById('save-ai-settings'),
  testAiVoice: document.getElementById('test-ai-voice'),
  llmProviderForm: document.getElementById('llm-provider-form'),
  llmProviderId: document.getElementById('llm-provider-id'),
  llmFormModePill: document.getElementById('llm-form-mode-pill'),
  llmProviderTemplate: document.getElementById('llm-provider-template'),
  llmApplyTemplate: document.getElementById('llm-apply-template'),
  llmDisplayName: document.getElementById('llm-display-name'),
  llmProviderType: document.getElementById('llm-provider-type'),
  llmAuthMode: document.getElementById('llm-auth-mode'),
  llmSecretRefLabel: document.getElementById('llm-secret-ref-label'),
  llmSecretRef: document.getElementById('llm-secret-ref'),
  llmSecretValueRow: document.getElementById('llm-secret-value-row'),
  llmSecretValue: document.getElementById('llm-secret-value'),
  llmBaseUrl: document.getElementById('llm-base-url'),
  llmModelId: document.getElementById('llm-model-id'),
  llmContextWindow: document.getElementById('llm-context-window'),
  llmCapabilities: document.getElementById('llm-capabilities'),
  llmEnabled: document.getElementById('llm-enabled'),
  llmCheckDraft: document.getElementById('llm-check-draft'),
  llmNewProvider: document.getElementById('llm-new-provider'),
  llmCancelEdit: document.getElementById('llm-cancel-edit'),
  llmProviderStatus: document.getElementById('llm-provider-status'),
  llmRegistryPill: document.getElementById('llm-registry-pill'),
  llmAddExampleProviders: document.getElementById('llm-add-example-providers'),
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
    display_name: 'OpenRouter Claude Sonnet',
    provider_type: 'openrouter',
    auth_mode: 'env_var',
    secret_ref: 'OPENROUTER_API_KEY',
    base_url: 'https://openrouter.ai/api/v1',
    model_id: 'anthropic/claude-sonnet-4.5',
    capabilities: ['chat', 'reasoning'],
  },
  nvidia_nim: {
    display_name: 'NVIDIA NIM GLM',
    provider_type: 'nvidia_nim',
    auth_mode: 'env_var',
    secret_ref: 'NVIDIA_API_KEY',
    base_url: 'https://integrate.api.nvidia.com/v1',
    model_id: 'z-ai/glm4.7',
    capabilities: ['chat', 'planner', 'tool_calling'],
  },
  openai: {
    display_name: 'OpenAI GPT',
    provider_type: 'openai',
    auth_mode: 'env_var',
    secret_ref: 'OPENAI_API_KEY',
    base_url: 'https://api.openai.com/v1',
    model_id: 'gpt-5.2',
    capabilities: ['chat', 'reasoning'],
  },
  anthropic: {
    display_name: 'Anthropic Claude Sonnet',
    provider_type: 'anthropic',
    auth_mode: 'env_var',
    secret_ref: 'ANTHROPIC_API_KEY',
    base_url: 'https://api.anthropic.com/v1',
    model_id: 'claude-sonnet-4-5',
    capabilities: ['chat', 'reasoning'],
  },
  google_gemini: {
    display_name: 'Google Gemini Flash',
    provider_type: 'google_gemini',
    auth_mode: 'env_var',
    secret_ref: 'GEMINI_API_KEY',
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
    model_id: 'gemini-2.5-flash',
    capabilities: ['chat', 'vision'],
  },
  ollama: {
    display_name: 'Ollama Local Llama',
    provider_type: 'ollama',
    auth_mode: 'none',
    secret_ref: '',
    base_url: 'http://localhost:11434',
    model_id: 'llama3:latest',
    capabilities: ['chat'],
  },
  lm_studio: {
    display_name: 'LM Studio Local',
    provider_type: 'lm_studio',
    auth_mode: 'none',
    secret_ref: '',
    base_url: 'http://localhost:1234/v1',
    model_id: 'local-model',
    capabilities: ['chat'],
  },
  mistral: {
    display_name: 'Mistral Large',
    provider_type: 'mistral',
    auth_mode: 'env_var',
    secret_ref: 'MISTRAL_API_KEY',
    base_url: 'https://api.mistral.ai/v1',
    model_id: 'mistral-large-latest',
    capabilities: ['chat', 'reasoning'],
  },
  cohere: {
    display_name: 'Cohere Command A',
    provider_type: 'cohere',
    auth_mode: 'env_var',
    secret_ref: 'COHERE_API_KEY',
    base_url: 'https://api.cohere.com/v2',
    model_id: 'command-a-03-2025',
    capabilities: ['chat', 'embeddings'],
  },
  together: {
    display_name: 'Together GPT OSS',
    provider_type: 'together',
    auth_mode: 'env_var',
    secret_ref: 'TOGETHER_API_KEY',
    base_url: 'https://api.together.xyz/v1',
    model_id: 'openai/gpt-oss-20b',
    capabilities: ['chat', 'reasoning'],
  },
  groq: {
    display_name: 'Groq GPT OSS',
    provider_type: 'groq',
    auth_mode: 'env_var',
    secret_ref: 'GROQ_API_KEY',
    base_url: 'https://api.groq.com/openai/v1',
    model_id: 'openai/gpt-oss-20b',
    capabilities: ['chat', 'reasoning'],
  },
  huggingface: {
    display_name: 'Hugging Face Router GPT OSS',
    provider_type: 'huggingface',
    auth_mode: 'env_var',
    secret_ref: 'HF_TOKEN',
    base_url: 'https://router.huggingface.co/v1',
    model_id: 'openai/gpt-oss-120b',
    capabilities: ['chat', 'reasoning'],
  },
  openai_compatible: {
    display_name: 'Custom OpenAI-compatible',
    provider_type: 'openai_compatible',
    auth_mode: 'env_var',
    secret_ref: 'OPENAI_COMPATIBLE_API_KEY',
    base_url: 'https://example-openai-compatible.local/v1',
    model_id: 'custom-model-id',
    capabilities: ['chat'],
  },
};

const EXAMPLE_PROVIDER_ORDER = Object.keys(LLM_TEMPLATES);

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
  ai_settings: 'AI Settings',
  llm_providers: 'LLM Providers',
  model_routing: 'Model Routing',
};

let llmProviders = [];
let modelRouting = {};
let editingFallbackPurpose = null;
let pendingJsonImport = null;
let llmProviderSort = { key: 'display_name', direction: 'asc' };

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

function setAiSettingsStatus(text) {
  if (settingsEls.aiSettingsStatus) settingsEls.aiSettingsStatus.textContent = text;
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
  const roverAvailability = (mqtt.rover_availability && typeof mqtt.rover_availability === 'object')
    ? mqtt.rover_availability
    : {};
  const connectedThresholdRaw = Number.parseInt(roverAvailability.connected_threshold_seconds, 10);
  const unavailableThresholdRaw = Number.parseInt(roverAvailability.unavailable_threshold_seconds, 10);
  const connectedThreshold = Number.isFinite(connectedThresholdRaw) ? Math.max(0, connectedThresholdRaw) : 2;
  let unavailableThreshold = Number.isFinite(unavailableThresholdRaw) ? Math.max(1, unavailableThresholdRaw) : 60;
  if (unavailableThreshold < connectedThreshold) unavailableThreshold = connectedThreshold;
  settingsEls.brokerHost.value = mqtt.broker_host || '';
  settingsEls.brokerPort.value = mqtt.broker_port ?? 1883;
  settingsEls.topicPrefix.value = mqtt.topic_prefix || '';
  settingsEls.clientId.value = mqtt.client_id || '';
  settingsEls.controlTopic.value = mqtt.control_topic || 'control/manual';
  settingsEls.stateTopic.value = mqtt.state_topic || 'telemetry/state';
  settingsEls.cameraTopic.value = mqtt.camera_topic || 'camera-feed';
  settingsEls.controlHz.value = mqtt.control_hz ?? 20;
  settingsEls.roverConnectedThreshold.value = connectedThreshold;
  settingsEls.roverUnavailableThreshold.value = unavailableThreshold;
  settingsEls.roverRolloverOnReconnect.checked = roverAvailability.rollover_on_reconnect !== false;
  settingsEls.simulationBackend.value = simulation.backend || '3d-env';
}

function readConnectivityFromForm() {
  const connectedThresholdRaw = Number.parseInt(settingsEls.roverConnectedThreshold.value, 10);
  const unavailableThresholdRaw = Number.parseInt(settingsEls.roverUnavailableThreshold.value, 10);
  const connectedThreshold = Number.isFinite(connectedThresholdRaw) ? Math.max(0, connectedThresholdRaw) : 2;
  let unavailableThreshold = Number.isFinite(unavailableThresholdRaw) ? Math.max(1, unavailableThresholdRaw) : 60;
  if (unavailableThreshold < connectedThreshold) unavailableThreshold = connectedThreshold;
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
      rover_availability: {
        connected_threshold_seconds: connectedThreshold,
        unavailable_threshold_seconds: unavailableThreshold,
        rollover_on_reconnect: settingsEls.roverRolloverOnReconnect.checked,
      },
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
  return ['connectivity', 'video', 'appearance', 'ai-settings', 'llm-provider', 'json'].includes(tab) ? tab : 'connectivity';
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

function aiSpeechSupported() {
  return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
}

function clampNumber(value, fallback, min, max) {
  const number = Number.parseFloat(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function populateAiVoiceOptions(selectedVoiceName = '') {
  if (!settingsEls.aiTtsVoice) return;
  const voices = aiSpeechSupported() ? window.speechSynthesis.getVoices() : [];
  const options = ['<option value="">Browser default voice</option>'];
  const hasSelectedVoice = selectedVoiceName && voices.some((voice) => voice.name === selectedVoiceName);
  for (const voice of voices) {
    const label = `${voice.name} (${voice.lang || 'unknown'})${voice.default ? ' default' : ''}`;
    options.push(`<option value="${escapeHtml(voice.name)}"${voice.name === selectedVoiceName ? ' selected' : ''}>${escapeHtml(label)}</option>`);
  }
  if (selectedVoiceName && !hasSelectedVoice) {
    options.push(`<option value="${escapeHtml(selectedVoiceName)}" selected>${escapeHtml(`${selectedVoiceName} (saved voice)`)}</option>`);
  }
  settingsEls.aiTtsVoice.innerHTML = options.join('');
  settingsEls.aiTtsVoice.value = selectedVoiceName || '';
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

function fillAiSettings(settings = {}) {
  const tts = settings.tts || {};
  settingsEls.aiTtsEnabled.checked = tts.enabled !== false;
  settingsEls.aiTtsAutoRead.checked = Boolean(tts.auto_read);
  settingsEls.aiTtsEngine.value = tts.engine === 'kokoro_service' ? 'kokoro_service' : 'browser';
  settingsEls.aiTtsServiceUrl.value = tts.service_url || 'http://127.0.0.1:9101';
  settingsEls.aiTtsServiceVoice.value = tts.voice || 'af_sky';
  settingsEls.aiTtsServiceSpeed.value = String(clampNumber(tts.speed, 1, 0.5, 2));
  settingsEls.aiTtsBrowserFallback.checked = tts.browser_fallback !== false;
  settingsEls.aiTtsRate.value = String(clampNumber(tts.rate, 1, 0.5, 2));
  settingsEls.aiTtsPitch.value = String(clampNumber(tts.pitch, 1, 0, 2));
  populateAiVoiceOptions(String(tts.voice_name || ''));
  if (settingsEls.aiSettingsPill) {
    settingsEls.aiSettingsPill.textContent = settingsEls.aiTtsEnabled.checked
      ? `Voice: ${settingsEls.aiTtsEngine.value === 'kokoro_service' ? 'Kokoro' : 'Browser'}`
      : 'Voice disabled';
    settingsEls.aiSettingsPill.className = `pill ${settingsEls.aiTtsEnabled.checked ? 'ok' : 'warn'}`;
  }
}

function readAiSettings() {
  return {
    tts: {
      enabled: settingsEls.aiTtsEnabled.checked,
      engine: settingsEls.aiTtsEngine.value,
      auto_read: settingsEls.aiTtsAutoRead.checked,
      service_url: settingsEls.aiTtsServiceUrl.value.trim() || 'http://127.0.0.1:9101',
      voice: settingsEls.aiTtsServiceVoice.value.trim() || 'af_sky',
      format: 'wav',
      speed: clampNumber(settingsEls.aiTtsServiceSpeed.value, 1, 0.5, 2),
      browser_fallback: settingsEls.aiTtsBrowserFallback.checked,
      voice_name: settingsEls.aiTtsVoice.value,
      rate: clampNumber(settingsEls.aiTtsRate.value, 1, 0.5, 2),
      pitch: clampNumber(settingsEls.aiTtsPitch.value, 1, 0, 2),
    },
  };
}

async function loadAiSettings() {
  if (!settingsEls.aiTtsEnabled) return;
  setAiSettingsStatus('Loading AI settings.');
  const result = await readJson('/api/ai-settings');
  fillAiSettings(result.ai_settings || {});
  setAiSettingsStatus(aiSpeechSupported()
    ? 'AI voice settings loaded.'
    : 'This browser does not expose text-to-speech voices.');
}

async function saveAiSettings() {
  setAiSettingsStatus('Saving AI settings.');
  const result = await readJson('/api/ai-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ai_settings: readAiSettings() }),
  });
  fillAiSettings(result.ai_settings || {});
  setAiSettingsStatus('AI settings saved.');
}

async function testAiVoice() {
  const settings = readAiSettings();
  if (settings.tts.engine === 'kokoro_service') {
    await saveAiSettings();
    setAiSettingsStatus('Requesting Kokoro voice test.');
    const response = await fetch('/api/ai-tts/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input: 'Remote Rover AI voice test.',
        voice: settings.tts.voice,
        format: settings.tts.format,
        speed: settings.tts.speed,
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    await audio.play();
    setAiSettingsStatus('Playing Kokoro voice test.');
    return;
  }
  if (!aiSpeechSupported()) {
    setAiSettingsStatus('Text to speech is not supported by this browser.');
    return;
  }
  await waitForAiSpeechVoices(settings.tts.voice_name);
  const utterance = new SpeechSynthesisUtterance('Remote Rover AI voice test.');
  const voiceName = settings.tts.voice_name;
  const voice = window.speechSynthesis.getVoices().find((item) => item.name === voiceName);
  if (voice) utterance.voice = voice;
  utterance.rate = settings.tts.rate;
  utterance.pitch = settings.tts.pitch;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
  setAiSettingsStatus('Playing voice test.');
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
  const authMode = settingsEls.llmAuthMode.value;
  const payload = {
    id: settingsEls.llmProviderId.value || undefined,
    display_name: settingsEls.llmDisplayName.value.trim(),
    provider_type: settingsEls.llmProviderType.value,
    auth_mode: authMode,
    secret_ref: normalizeSecretRef(settingsEls.llmSecretRef.value),
    base_url: settingsEls.llmBaseUrl.value.trim(),
    model_id: settingsEls.llmModelId.value.trim(),
    capabilities: settingsEls.llmCapabilities.value.split(',').map((item) => item.trim()).filter(Boolean),
    context_window: settingsEls.llmContextWindow.value ? parseInt(settingsEls.llmContextWindow.value, 10) : null,
    enabled: settingsEls.llmEnabled.checked,
  };
  if (authMode === 'stored_secret') {
    payload.secret_ref = settingsEls.llmSecretRef.value.trim();
    const secretValue = settingsEls.llmSecretValue.value.trim();
    if (secretValue) payload.secret_value = secretValue;
  }
  if (authMode === 'none') payload.secret_ref = '';
  return payload;
}

function templateKeyForProvider(provider = {}) {
  const providerType = String(provider.provider_type || '').trim();
  if (!providerType) return 'openrouter';
  const exactKey = Object.keys(LLM_TEMPLATES).find((key) => LLM_TEMPLATES[key]?.provider_type === providerType);
  return exactKey || 'openai_compatible';
}

function fillProviderForm(provider = {}) {
  settingsEls.llmProviderId.value = provider.id || '';
  settingsEls.llmProviderTemplate.value = templateKeyForProvider(provider);
  settingsEls.llmDisplayName.value = provider.display_name || '';
  settingsEls.llmProviderType.value = provider.provider_type || 'openai_compatible';
  settingsEls.llmAuthMode.value = provider.auth_mode || 'env_var';
  settingsEls.llmSecretRef.value = provider.secret_ref || '';
  settingsEls.llmSecretValue.value = '';
  settingsEls.llmBaseUrl.value = provider.base_url || '';
  settingsEls.llmModelId.value = provider.model_id || '';
  settingsEls.llmCapabilities.value = Array.isArray(provider.capabilities) ? provider.capabilities.join(', ') : '';
  settingsEls.llmContextWindow.value = provider.context_window || '';
  settingsEls.llmEnabled.checked = provider.enabled !== false;
  if (settingsEls.llmFormModePill) {
    settingsEls.llmFormModePill.textContent = provider.id ? 'Editing selected provider' : 'New provider';
    settingsEls.llmFormModePill.className = provider.id ? 'pill warn' : 'pill';
  }
  updateProviderAuthFields();
}

function applyProviderTemplate() {
  const template = LLM_TEMPLATES[settingsEls.llmProviderTemplate.value] || LLM_TEMPLATES.openai_compatible;
  fillProviderForm({ ...template, enabled: true });
  setLlmStatus(`Applied ${settingsEls.llmProviderTemplate.options[settingsEls.llmProviderTemplate.selectedIndex].text} template. Save Provider is still required.`);
}

function clearProviderForm() {
  fillProviderForm({ ...LLM_TEMPLATES.openrouter, enabled: true });
}

function scrollToProviderEditor() {
  const form = settingsEls.llmProviderForm;
  if (!form) return;
  const panel = form.closest('.llm-settings-panel') || form;
  const headerHeight = document.querySelector('.app-header')?.getBoundingClientRect().height || 0;
  const top = window.scrollY + panel.getBoundingClientRect().top - headerHeight - 12;
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
}

function updateProviderAuthFields() {
  const authMode = settingsEls.llmAuthMode.value;
  if (authMode === 'env_var') {
    settingsEls.llmSecretRefLabel.textContent = 'Secret / Env Var';
    settingsEls.llmSecretRef.placeholder = 'OPENROUTER_API_KEY';
    settingsEls.llmSecretRef.disabled = false;
    settingsEls.llmSecretValueRow.hidden = true;
    return;
  }
  if (authMode === 'stored_secret') {
    settingsEls.llmSecretRefLabel.textContent = 'Stored Secret Reference';
    settingsEls.llmSecretRef.placeholder = 'secret://provider-...';
    settingsEls.llmSecretRef.disabled = false;
    settingsEls.llmSecretValueRow.hidden = false;
    return;
  }
  settingsEls.llmSecretRefLabel.textContent = 'Secret / Env Var';
  settingsEls.llmSecretRef.placeholder = '';
  settingsEls.llmSecretRef.value = '';
  settingsEls.llmSecretRef.disabled = true;
  settingsEls.llmSecretValueRow.hidden = true;
}

function renderProviderList() {
  if (!settingsEls.llmProviderList) return;
  const enabledCount = llmProviders.filter((provider) => provider.enabled !== false).length;
  if (settingsEls.llmRegistryPill) settingsEls.llmRegistryPill.textContent = `${enabledCount} enabled`;
  if (!llmProviders.length) {
    settingsEls.llmProviderList.innerHTML = '<p class="settings-note">No LLM providers configured yet.</p>';
    return;
  }
  const rows = llmProviders.map((provider) => {
    const check = provider.last_check || { status: 'not_tested' };
    const capabilities = Array.isArray(provider.capabilities) ? provider.capabilities : [];
    const authSummary = provider.auth_mode === 'stored_secret'
      ? (provider.has_secret ? 'stored secret configured' : 'stored secret missing')
      : provider.auth_mode === 'env_var'
        ? `env: ${provider.secret_ref || 'missing'}`
        : 'no auth';
    return { provider, check, capabilities, authSummary };
  });
  const direction = llmProviderSort.direction === 'desc' ? -1 : 1;
  rows.sort((left, right) => compareProviderRows(left, right, llmProviderSort.key) * direction);
  settingsEls.llmProviderList.innerHTML = `
    <table class="llm-provider-table">
      <thead>
        <tr>
          ${renderProviderSortHeader('Name', 'display_name')}
          ${renderProviderSortHeader('Type', 'provider_type')}
          ${renderProviderSortHeader('Model', 'model_id')}
          ${renderProviderSortHeader('Auth', 'auth_summary')}
          ${renderProviderSortHeader('Capabilities', 'capabilities')}
          ${renderProviderSortHeader('Enabled', 'enabled')}
          ${renderProviderSortHeader('Status', 'status')}
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(({ provider, check, capabilities, authSummary }) => {
    const tone = statusTone(check.status);
    const capabilitiesMarkup = capabilities.map((capability) => `<span class="llm-chip">${escapeHtml(capability)}</span>`).join('');
    return `
      <tr class="llm-provider-row" data-provider-id="${escapeHtml(provider.id)}">
        <td><strong>${escapeHtml(provider.display_name)}</strong></td>
        <td><span class="llm-chip">${escapeHtml(provider.provider_type)}</span></td>
        <td><span class="llm-chip">${escapeHtml(provider.model_id || 'no model id')}</span></td>
        <td><span class="llm-chip">${escapeHtml(authSummary)}</span></td>
        <td><div class="llm-provider-meta">${capabilitiesMarkup || '<span class="llm-chip">none</span>'}</div></td>
        <td><span class="pill ${provider.enabled === false ? 'warn' : 'ok'}">${provider.enabled === false ? 'disabled' : 'enabled'}</span></td>
        <td><span class="pill ${tone}">${escapeHtml(check.status || 'not_tested')}</span></td>
        <td>
          <div class="llm-actions">
            <button type="button" class="ghost llm-action-icon" data-llm-action="check" title="Check provider" aria-label="Check provider"><span aria-hidden="true">✓</span></button>
            <button type="button" class="ghost llm-action-icon" data-llm-action="edit" title="Edit provider" aria-label="Edit provider"><span aria-hidden="true">✎</span></button>
            <button type="button" class="ghost llm-action-icon" data-llm-action="toggle" title="${provider.enabled === false ? 'Enable provider' : 'Disable provider'}" aria-label="${provider.enabled === false ? 'Enable provider' : 'Disable provider'}"><span aria-hidden="true">${provider.enabled === false ? '⏻' : '⏼'}</span></button>
            <button type="button" class="ghost llm-action-icon llm-action-danger" data-llm-action="delete" title="Delete provider" aria-label="Delete provider"><span aria-hidden="true">🗑</span></button>
          </div>
        </td>
      </tr>
    `;
  }).join('')}
      </tbody>
    </table>
  `;
}

function renderProviderSortHeader(label, key) {
  const active = llmProviderSort.key === key;
  const arrow = active ? (llmProviderSort.direction === 'asc' ? ' ▲' : ' ▼') : '';
  return `<th><button type="button" class="llm-sort-button${active ? ' is-active' : ''}" data-llm-sort="${escapeHtml(key)}" aria-label="Sort by ${escapeHtml(label)}">${escapeHtml(label)}${arrow}</button></th>`;
}

function providerSortText(value) {
  return String(value || '').toLowerCase();
}

function compareProviderRows(left, right, key) {
  if (key === 'enabled') return Number(left.provider.enabled === false) - Number(right.provider.enabled === false);
  if (key === 'status') return providerSortText(left.check.status).localeCompare(providerSortText(right.check.status));
  if (key === 'auth_summary') return providerSortText(left.authSummary).localeCompare(providerSortText(right.authSummary));
  if (key === 'capabilities') return providerSortText(left.capabilities.join(',')).localeCompare(providerSortText(right.capabilities.join(',')));
  return providerSortText(left.provider[key]).localeCompare(providerSortText(right.provider[key]));
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
  settingsEls.llmSecretValue.value = '';
  renderProviderList();
  renderRoutingList();
  setLlmStatus(`Saved provider: ${result.provider.display_name}.`);
}

function hasProviderType(providerType) {
  return llmProviders.some((provider) => provider.provider_type === providerType);
}

async function addMissingExampleProviders() {
  const missingTemplateKeys = EXAMPLE_PROVIDER_ORDER.filter((key) => {
    const template = LLM_TEMPLATES[key];
    return template && !hasProviderType(template.provider_type);
  });
  if (!missingTemplateKeys.length) {
    setLlmStatus('All provider example rows already exist.');
    return;
  }

  settingsEls.llmAddExampleProviders.disabled = true;
  setLlmStatus(`Adding ${missingTemplateKeys.length} missing provider example(s).`);
  try {
    for (const key of missingTemplateKeys) {
      const template = LLM_TEMPLATES[key];
      const result = await readJson('/api/llm-providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...template,
          display_name: `${template.display_name} Example`,
          enabled: false,
        }),
      });
      llmProviders.push(result.provider);
    }
    renderProviderList();
    renderRoutingList();
    setLlmStatus(`Added ${missingTemplateKeys.length} editable provider example(s). Examples are disabled until you edit and enable them.`);
  } finally {
    settingsEls.llmAddExampleProviders.disabled = false;
  }
}

async function checkDraftProvider() {
  setLlmStatus('Checking draft provider.');
  const result = await readJson('/api/llm-providers/check-draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(readProviderForm()),
  });
  settingsEls.llmSecretValue.value = '';
  setLlmStatus(`Draft check: ${result.check.status}. ${result.check.message || ''}`);
}

async function handleProviderListClick(event) {
  const sortButton = event.target.closest('button[data-llm-sort]');
  if (sortButton) {
    const key = sortButton.dataset.llmSort;
    if (llmProviderSort.key === key) {
      llmProviderSort.direction = llmProviderSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
      llmProviderSort = { key, direction: 'asc' };
    }
    renderProviderList();
    return;
  }
  const button = event.target.closest('button[data-llm-action]');
  if (!button) return;
  const row = button.closest('[data-provider-id]');
  const provider = llmProviders.find((item) => item.id === row.dataset.providerId);
  if (!provider) return;
  const action = button.dataset.llmAction;
  if (action === 'edit') {
    fillProviderForm(provider);
    scrollToProviderEditor();
    settingsEls.llmDisplayName?.focus();
    settingsEls.llmDisplayName?.select();
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
  } else if (action === 'delete') {
    if (!window.confirm(`Delete provider "${provider.display_name}"?`)) return;
    await readJson(`/api/llm-providers/${encodeURIComponent(provider.id)}`, { method: 'DELETE' });
    llmProviders = llmProviders.filter((item) => item.id !== provider.id);
    if (settingsEls.llmProviderId.value === provider.id) clearProviderForm();
    renderProviderList();
    renderRoutingList();
    setLlmStatus(`Deleted provider: ${provider.display_name}.`);
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
    loadAiSettings().catch((error) => setAiSettingsStatus(error.message)),
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

function bindAiSettings() {
  if (!settingsEls.aiTtsEnabled) return;
  if (aiSpeechSupported() && window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = () => {
      populateAiVoiceOptions(settingsEls.aiTtsVoice.value);
    };
  }
  settingsEls.saveAiSettings.addEventListener('click', () => {
    saveAiSettings().catch((error) => setAiSettingsStatus(error.message));
  });
  settingsEls.testAiVoice.addEventListener('click', () => {
    testAiVoice().catch((error) => setAiSettingsStatus(`Voice test failed: ${error.message}`));
  });
  settingsEls.aiTtsEnabled.addEventListener('change', () => {
    if (settingsEls.aiSettingsPill) {
      settingsEls.aiSettingsPill.textContent = settingsEls.aiTtsEnabled.checked ? 'Voice enabled' : 'Voice disabled';
      settingsEls.aiSettingsPill.className = `pill ${settingsEls.aiTtsEnabled.checked ? 'ok' : 'warn'}`;
    }
  });
  settingsEls.aiTtsEngine.addEventListener('change', () => {
    setAiSettingsStatus(settingsEls.aiTtsEngine.value === 'kokoro_service'
      ? 'Kokoro local service selected. Make sure tts_service is running on the configured URL.'
      : 'Browser speech selected. Voice quality depends on this browser and operating system.');
  });
}

function bindLlmSettings() {
  if (!settingsEls.llmProviderForm) return;
  settingsEls.llmAuthMode.addEventListener('change', updateProviderAuthFields);
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
  settingsEls.llmAddExampleProviders.addEventListener('click', () => {
    addMissingExampleProviders().catch((error) => setLlmStatus(error.message));
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
  bindAiSettings();
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
  loadAiSettings().catch((error) => {
    setAiSettingsStatus(error.message);
  });
  loadLlmSettings().catch((error) => {
    setLlmStatus(error.message);
    setRoutingStatus(error.message);
  });
  clearProviderForm();
}

initSettings();
