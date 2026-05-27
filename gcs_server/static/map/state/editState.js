// Pure in-memory store — no DOM, no Leaflet imports.
// Waypoint indices everywhere in this module are 0-based (JS convention).
// The API layer converts to 1-based before calling the server.

const _subscribers = new Set();

const _state = {
  missionId: null,
  operationId: null,
  status: '',
  waypoints: [],        // [{id, x, y, z, label, kind, provenance}]
  clientVersion: 0,
  selectedIndices: new Set(),  // 0-based
  editMode: null,       // null | 'vertex' | 'add'
  busy: false,
};

function _notify() {
  const snapshot = {
    missionId: _state.missionId,
    operationId: _state.operationId,
    status: _state.status,
    waypoints: [..._state.waypoints],
    clientVersion: _state.clientVersion,
    selectedIndices: new Set(_state.selectedIndices),
    editMode: _state.editMode,
    busy: _state.busy,
  };
  for (const fn of _subscribers) {
    try { fn(snapshot); } catch {}
  }
}

export const editState = {
  get missionId() { return _state.missionId; },
  get operationId() { return _state.operationId; },
  get status() { return _state.status; },
  get waypoints() { return _state.waypoints; },
  get clientVersion() { return _state.clientVersion; },
  get selectedIndices() { return _state.selectedIndices; },
  get editMode() { return _state.editMode; },
  get busy() { return _state.busy; },

  isEditable() {
    return _state.missionId !== null && _state.status !== 'executing' && !_state.busy;
  },

  beginEdit(mission) {
    const provenance = mission.provenance || {};
    const wps = (mission.mission?.waypoints || []).map((wp) => ({
      id: wp.id || '',
      x: Number(wp.x) || 0,
      y: Number(wp.y) || 0,
      z: Number(wp.z) || 0,
      label: wp.label || '',
      kind: wp.kind || 'waypoint',
      provenance: provenance[wp.id] || 'ai',
    }));
    _state.missionId = String(mission.id || '');
    _state.operationId = String(mission.operation_id || '');
    _state.status = String(mission.status || '');
    _state.waypoints = wps;
    _state.clientVersion = Number(mission.client_version) || 0;
    _state.selectedIndices = new Set();
    // preserve editMode across mutation-driven refreshes
    _state.busy = false;
    _notify();
  },

  clearEdit() {
    _state.missionId = null;
    _state.operationId = null;
    _state.status = '';
    _state.waypoints = [];
    _state.clientVersion = 0;
    _state.selectedIndices = new Set();
    _state.editMode = null;
    _state.busy = false;
    _notify();
  },

  setEditMode(mode) {
    _state.editMode = _state.editMode === mode ? null : mode;
    _notify();
  },

  setSelection(indices, { shift = false, toggle = false } = {}) {
    if (toggle) {
      for (const idx of indices) {
        if (_state.selectedIndices.has(idx)) {
          _state.selectedIndices.delete(idx);
        } else {
          _state.selectedIndices.add(idx);
        }
      }
    } else if (shift) {
      for (const idx of indices) _state.selectedIndices.add(idx);
    } else {
      _state.selectedIndices = new Set(indices);
    }
    _notify();
  },

  clearSelection() {
    if (_state.selectedIndices.size) {
      _state.selectedIndices = new Set();
      _notify();
    }
  },

  stepSelection(delta) {
    if (!_state.waypoints.length) return;
    const current = _state.selectedIndices.size ? Math.min(..._state.selectedIndices) : -1;
    const next = Math.max(0, Math.min(_state.waypoints.length - 1, current + delta));
    _state.selectedIndices = new Set([next]);
    _notify();
  },

  setBusy(busy) {
    _state.busy = Boolean(busy);
    _notify();
  },

  subscribe(fn) { _subscribers.add(fn); },
  unsubscribe(fn) { _subscribers.delete(fn); },
};
