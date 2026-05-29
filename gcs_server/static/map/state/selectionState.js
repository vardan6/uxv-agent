// Pure in-memory store — no DOM, no Leaflet imports.
// Mission-level selection shared by the sidebar and the map overlay.
// Mirrors the editState.js pattern (waypoint-level edit state).

const _subscribers = new Set();

const _state = {
  activeMissionId: '',
  selectedMissionIds: new Set(),
  // Last plain-clicked mission id; anchors shift-range. Shift- and cmd-clicks
  // do not move the anchor (per design).
  anchorMissionId: '',
};

function _notify() {
  const snapshot = {
    activeMissionId: _state.activeMissionId,
    selectedMissionIds: new Set(_state.selectedMissionIds),
    anchorMissionId: _state.anchorMissionId,
  };
  for (const fn of _subscribers) {
    try { fn(snapshot); } catch {}
  }
}

export const selectionState = {
  get activeMissionId() { return _state.activeMissionId; },
  get selectedMissionIds() { return _state.selectedMissionIds; },
  get anchorMissionId() { return _state.anchorMissionId; },

  // Plain click: replace selection with {id}; activate; move anchor.
  selectSingle(missionId) {
    const id = String(missionId || '');
    if (!id) return;
    _state.selectedMissionIds = new Set([id]);
    _state.activeMissionId = id;
    _state.anchorMissionId = id;
    _notify();
  },

  // Cmd/Ctrl click: toggle membership; activate; move anchor.
  toggle(missionId) {
    const id = String(missionId || '');
    if (!id) return;
    if (_state.selectedMissionIds.has(id)) _state.selectedMissionIds.delete(id);
    else _state.selectedMissionIds.add(id);
    _state.activeMissionId = id;
    _state.anchorMissionId = id;
    _notify();
  },

  // Shift click: replace selection with the supplied range; activate clicked;
  // anchor unchanged (caller passes range derived from existing anchor).
  selectRange(missionIds, clickedId) {
    _state.selectedMissionIds = new Set(missionIds);
    if (clickedId) _state.activeMissionId = String(clickedId);
    _notify();
  },

  // Sidebar "Selected" checkbox — additive without disturbing anchor/active.
  setSelectedFlag(missionId, checked) {
    const id = String(missionId || '');
    if (!id) return;
    const has = _state.selectedMissionIds.has(id);
    if (checked && !has) _state.selectedMissionIds.add(id);
    else if (!checked && has) _state.selectedMissionIds.delete(id);
    else return;
    _notify();
  },

  // Set the active mission without disturbing selection size; used for
  // programmatic focus (e.g. setFocus from the map widget).
  setActive(missionId) {
    const id = String(missionId || '');
    if (_state.activeMissionId === id) return;
    _state.activeMissionId = id;
    if (id && !_state.selectedMissionIds.has(id)) {
      // Active is always ∈ selection (design rule).
      _state.selectedMissionIds.add(id);
    }
    _notify();
  },

  // Drop ids that no longer exist (after a refresh removed a mission).
  prune(knownMissionIds) {
    let changed = false;
    for (const id of [..._state.selectedMissionIds]) {
      if (!knownMissionIds.has(id)) {
        _state.selectedMissionIds.delete(id);
        changed = true;
      }
    }
    if (_state.activeMissionId && !knownMissionIds.has(_state.activeMissionId)) {
      _state.activeMissionId = '';
      changed = true;
    }
    if (_state.anchorMissionId && !knownMissionIds.has(_state.anchorMissionId)) {
      _state.anchorMissionId = '';
      changed = true;
    }
    if (changed) _notify();
  },

  clearSelection() {
    if (!_state.selectedMissionIds.size && !_state.activeMissionId && !_state.anchorMissionId) return;
    _state.selectedMissionIds = new Set();
    _state.activeMissionId = '';
    _state.anchorMissionId = '';
    _notify();
  },

  subscribe(fn) { _subscribers.add(fn); },
  unsubscribe(fn) { _subscribers.delete(fn); },
};
