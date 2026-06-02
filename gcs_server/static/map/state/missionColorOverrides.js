// Curated swatch palette for the colour picker — distinct hues + a few neutrals.
export const MISSION_COLOR_PALETTE = [
  '#d16b5b', '#6f86c7', '#c27aa6', '#d0b24a',
  '#8e98a3', '#3f6f9f', '#b85c5c', '#7b68b2',
  '#4fa3a5', '#d08a6b', '#b96aa0', '#4f6a8a',
  '#8f4f7e', '#c79b5f', '#6e5f9c', '#a56f6f',
  '#667789', '#2f8f83', '#8fbf5a', '#0f9d58',
  '#3aaed8', '#f08c4a', '#a06cd5', '#c06078',
];

const OVERRIDE_STORAGE_KEY = 'gcs-map-widget-mission-colors';

function _loadAll() {
  try { return JSON.parse(localStorage.getItem(OVERRIDE_STORAGE_KEY) || '{}'); } catch { return {}; }
}
function _saveAll(obj) {
  try { localStorage.setItem(OVERRIDE_STORAGE_KEY, JSON.stringify(obj)); } catch {}
}

// Per-mission colour overrides stored in localStorage. Resolution order:
// override → auto palette (assignPaletteColor by visibility order).
export const missionColorOverrides = {
  get(missionId) { return _loadAll()[String(missionId)] || null; },
  set(missionId, color) {
    const m = _loadAll(); m[String(missionId)] = color; _saveAll(m);
  },
  clear(missionId) {
    const m = _loadAll(); delete m[String(missionId)]; _saveAll(m);
  },
  getAll() { return _loadAll(); },
};
