// Per-mission colour overrides, persisted in localStorage. Slice 6 ships
// without a schema change; lift to a server-side mission.color column when
// the feature stabilises.

const STORAGE_KEY = 'gcs-map-widget-mission-colors';

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

function save(map) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch (_) {}
}

export const missionColorOverrides = {
  _map: load(),
  get(missionId) {
    const key = String(missionId || '');
    return key ? this._map[key] || null : null;
  },
  set(missionId, color) {
    const key = String(missionId || '');
    if (!key) return;
    this._map[key] = color;
    save(this._map);
  },
  clear(missionId) {
    const key = String(missionId || '');
    if (!key) return;
    delete this._map[key];
    save(this._map);
  },
  applyTo(paletteMap) {
    for (const [id, color] of Object.entries(this._map)) {
      if (paletteMap.has(id)) paletteMap.set(id, color);
    }
    return paletteMap;
  },
};

// Curated swatch palette for the picker — distinct hues + a few neutrals.
export const MISSION_COLOR_PALETTE = [
  '#66c2a5', '#fc8d62', '#8da0cb', '#e78ac3',
  '#a6d854', '#ffd92f', '#e5c494', '#b3b3b3',
  '#1f77b4', '#d62728', '#9467bd', '#17becf',
];
