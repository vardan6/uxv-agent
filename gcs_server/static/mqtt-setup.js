const setupEls = {
  form: document.getElementById('mqtt-form'),
  brokerPill: document.getElementById('setup-broker-pill'),
  settingsPath: document.getElementById('settings-path'),
  status: document.getElementById('setup-status'),
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
};

function setSetupStatus(text) {
  setupEls.status.textContent = text;
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
  const badge = typeof broker === 'string' ? { label: broker, tone: broker === 'loading' ? 'warn' : 'danger' } : brokerBadgeState(broker);
  setupEls.brokerPill.textContent = badge.label || 'unknown';
  setupEls.brokerPill.className = 'pill';
  setupEls.brokerPill.classList.add(badge.tone || 'danger');
}

function fillForm(mqtt = {}, simulation = {}) {
  setupEls.brokerHost.value = mqtt.broker_host || '';
  setupEls.brokerPort.value = mqtt.broker_port ?? 1883;
  setupEls.topicPrefix.value = mqtt.topic_prefix || '';
  setupEls.clientId.value = mqtt.client_id || '';
  setupEls.controlTopic.value = mqtt.control_topic || 'control/manual';
  setupEls.stateTopic.value = mqtt.state_topic || 'telemetry/state';
  setupEls.cameraTopic.value = mqtt.camera_topic || 'camera-feed';
  setupEls.controlHz.value = mqtt.control_hz ?? 20;
  setupEls.simulationBackend.value = simulation.backend || '3d-env';
}

async function readJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Request failed');
  }
  return data;
}

async function loadSetup() {
  updateSetupBrokerPill('loading');
  setSetupStatus('Loading shared MQTT settings.');
  const [config, snapshot] = await Promise.all([
    readJson('/api/mqtt-config'),
    readJson('/api/snapshot'),
  ]);
  fillForm(config.mqtt, snapshot.simulation || {});
  setupEls.settingsPath.textContent = config.settings_path || '-';
  updateSetupBrokerPill(snapshot.broker || { status: 'disconnected', connected: false });
  setSetupStatus(`Current broker target: ${config.mqtt.broker_host}:${config.mqtt.broker_port}.`);
}

async function saveSetup(event) {
  event.preventDefault();
  setSetupStatus('Saving shared config and reconnecting the GCS broker client.');
  updateSetupBrokerPill('connecting');

  const payload = {
    mqtt: {
      broker_host: setupEls.brokerHost.value.trim(),
      broker_port: Number.parseInt(setupEls.brokerPort.value, 10),
      topic_prefix: setupEls.topicPrefix.value.trim(),
      client_id: setupEls.clientId.value.trim(),
      control_topic: setupEls.controlTopic.value.trim(),
      state_topic: setupEls.stateTopic.value.trim(),
      camera_topic: setupEls.cameraTopic.value.trim(),
      control_hz: Number.parseInt(setupEls.controlHz.value, 10),
    },
  };

  const result = await readJson('/api/mqtt-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  await readJson('/api/simulation-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      simulation: {
        backend: setupEls.simulationBackend.value,
      },
    }),
  });
  fillForm(result.mqtt, { backend: setupEls.simulationBackend.value });
  setupEls.settingsPath.textContent = result.settings_path || '-';
  setSetupStatus(`Saved. GCS is reconnecting to ${result.mqtt.broker_host}:${result.mqtt.broker_port}.`);
  window.setTimeout(loadSetup, 800);
}

setupEls.form.addEventListener('submit', (event) => {
  saveSetup(event).catch((error) => {
    updateSetupBrokerPill('error');
    setSetupStatus(error.message);
  });
});

setupEls.reload.addEventListener('click', () => {
  loadSetup().catch((error) => {
    updateSetupBrokerPill('error');
    setSetupStatus(error.message);
  });
});

loadSetup().catch((error) => {
  updateSetupBrokerPill('error');
  setSetupStatus(error.message);
});
