// Sidebar sort preference, persisted in localStorage. Pure store + comparator
// so the panel can stay rendering-only.

const STORAGE_KEY = 'gcs-map-widget-mission-sort';

export const SORT_OPTIONS = [
  { id: 'updated_desc',   label: 'Updated newest' },
  { id: 'created_desc',   label: 'Created newest' },
  { id: 'waypoints_desc', label: 'Waypoint count high-low' },
  { id: 'waypoints_asc',  label: 'Waypoint count low-high' },
  { id: 'status',         label: 'Status' },
  { id: 'label_asc',      label: 'Label A–Z' },
  { id: 'selected_first', label: 'Selected first' },
  { id: 'visible_first',  label: 'Visible first' },
];

export const DEFAULT_SORT = 'updated_desc';

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SORT;
    return SORT_OPTIONS.some((o) => o.id === raw) ? raw : DEFAULT_SORT;
  } catch (_) { return DEFAULT_SORT; }
}

export const missionSortPreference = {
  _id: load(),
  get() { return this._id; },
  set(id) {
    if (!SORT_OPTIONS.some((o) => o.id === id)) return;
    this._id = id;
    try { localStorage.setItem(STORAGE_KEY, id); } catch (_) {}
  },
};

// Status ordering for the "Status" sort — actionable first, terminal last.
const STATUS_ORDER = [
  'executing', 'armed', 'awaiting_confirmation',
  'proposed', 'planning', 'exported', 'cutover_pending',
  'completed', 'superseded', 'rejected', 'validation_failed',
  'unknown', '',
];
const statusRank = (s) => {
  const idx = STATUS_ORDER.indexOf(String(s || ''));
  return idx === -1 ? STATUS_ORDER.length : idx;
};

const titleOf = (row) => String(row?.mission?.goal || row?.goal || row?.label || row?.name || `Mission ${row?.id || ''}`).toLowerCase();

export function sortMissions(missions, sortId, { selectedMissionIds = new Set(), visibleMissionIds = new Set() } = {}) {
  const arr = Array.isArray(missions) ? [...missions] : [];
  const tiebreak = (a, b) => (Number(b.updatedAt || b.updated_at || 0) - Number(a.updatedAt || a.updated_at || 0)) || String(a.id).localeCompare(String(b.id));
  switch (sortId) {
    case 'created_desc':
      arr.sort((a, b) => (Number(b.createdAt || b.created_at || 0) - Number(a.createdAt || a.created_at || 0)) || tiebreak(a, b));
      break;
    case 'waypoints_desc':
      arr.sort((a, b) => (Number(b.waypointCount || b.waypoint_count || 0) - Number(a.waypointCount || a.waypoint_count || 0)) || tiebreak(a, b));
      break;
    case 'waypoints_asc':
      arr.sort((a, b) => (Number(a.waypointCount || a.waypoint_count || 0) - Number(b.waypointCount || b.waypoint_count || 0)) || tiebreak(a, b));
      break;
    case 'status':
      arr.sort((a, b) => (statusRank(a.activeRevisionStatus) - statusRank(b.activeRevisionStatus)) || tiebreak(a, b));
      break;
    case 'label_asc':
      arr.sort((a, b) => titleOf(a).localeCompare(titleOf(b)) || tiebreak(a, b));
      break;
    case 'selected_first':
      arr.sort((a, b) => {
        const aSel = selectedMissionIds.has(String(a.id)) ? 0 : 1;
        const bSel = selectedMissionIds.has(String(b.id)) ? 0 : 1;
        return (aSel - bSel) || tiebreak(a, b);
      });
      break;
    case 'visible_first':
      arr.sort((a, b) => {
        const aVis = visibleMissionIds.has(String(a.id)) ? 0 : 1;
        const bVis = visibleMissionIds.has(String(b.id)) ? 0 : 1;
        return (aVis - bVis) || tiebreak(a, b);
      });
      break;
    case 'updated_desc':
    default:
      arr.sort((a, b) => tiebreak(a, b));
      break;
  }
  return arr;
}
