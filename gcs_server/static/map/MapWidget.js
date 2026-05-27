import { getCurrentOverlay, getMissionOverlay, listMissions, executeMission, getControllerState } from './data/missionApi.js';
import { getMission, createMission, updateMissionWaypoint, insertMissionWaypoint, deleteMissionWaypoint, deleteMission, restoreMission } from './data/missionMutationApi.js';
import { getActiveVehicleProfile, listVehicleProfiles } from './data/vehicleProfileApi.js';
import { fetchSceneMap, makeSampler } from './data/terrainApi.js';
import { MissionOverlayLayer } from './layers/MissionOverlayLayer.js';
import { LiveVehicleLayer } from './layers/LiveVehicleLayer.js';
import { TerrainCanvasLayer } from './layers/TerrainCanvasLayer.js';
import { normalizeMissionRows, enforceVisibilityCap, assignPaletteColor } from './missionListLogic.js';
import { MissionListPanel } from './ui/MissionListPanel.js';
import { SelectionPanel } from './ui/SelectionPanel.js';
import { KeyboardHelpOverlay } from './ui/KeyboardHelpOverlay.js';
import { ContextMenu } from './ui/ContextMenu.js';
import { HintToasts } from './ui/HintToasts.js';
import { ElevationProfilePanel } from './ui/ElevationProfilePanel.js';
import { BulkEditActionBar } from './ui/BulkEditActionBar.js';
import { editState } from './state/editState.js';

const LOCKED_STATUSES = new Set(['approved', 'exported', 'cutover_pending', 'executing', 'completed', 'superseded', 'rejected', 'validation_failed']);

function collectEditableWaypoints(mission = {}) {
  if (Array.isArray(mission.waypoints) && mission.waypoints.length) {
    return mission.waypoints
      .filter((wp) => wp && typeof wp === 'object')
      .map((wp, index) => ({
        id: wp.id || `mission-wp-${index + 1}`,
        x: Number(wp.x) || 0,
        y: Number(wp.y) || 0,
        z: Number(wp.z) || 0,
        label: wp.label || '',
        kind: wp.kind || 'waypoint',
      }));
  }

  const routeWaypoints = [];
  for (const [artifactIndex, artifact] of (mission.route_artifacts || []).entries()) {
    const points = Array.isArray(artifact?.waypoints) ? artifact.waypoints : [];
    for (const [waypointIndex, wp] of points.entries()) {
      if (!wp || typeof wp !== 'object') continue;
      routeWaypoints.push({
        id: wp.id || `route-${artifactIndex + 1}-wp-${waypointIndex + 1}`,
        x: Number(wp.x) || 0,
        y: Number(wp.y) || 0,
        z: Number(wp.z) || 0,
        label: wp.label || '',
        kind: wp.kind || 'waypoint',
      });
    }
  }
  if (routeWaypoints.length) return routeWaypoints;

  const stepWaypoints = [];
  for (const [stepIndex, step] of (mission.steps || []).entries()) {
    const points = Array.isArray(step?.waypoints) ? step.waypoints : [];
    for (const [waypointIndex, wp] of points.entries()) {
      if (!wp || typeof wp !== 'object') continue;
      stepWaypoints.push({
        id: wp.id || `step-${stepIndex + 1}-wp-${waypointIndex + 1}`,
        x: Number(wp.x) || 0,
        y: Number(wp.y) || 0,
        z: Number(wp.z) || 0,
        label: wp.label || '',
        kind: wp.kind || 'waypoint',
      });
    }
  }
  return stepWaypoints;
}

function boundsUnion(boundsList = []) {
  const valid = boundsList.filter(Boolean);
  if (!valid.length) return null;
  return {
    min_x: Math.min(...valid.map((bounds) => bounds.min_x)),
    max_x: Math.max(...valid.map((bounds) => bounds.max_x)),
    min_y: Math.min(...valid.map((bounds) => bounds.min_y)),
    max_y: Math.max(...valid.map((bounds) => bounds.max_y)),
  };
}

function opacityForMission(missionId, focusedMissionId) {
  if (!focusedMissionId) return 1;
  return missionId === focusedMissionId ? 1 : 0.25;
}

function missionIdOf(row) {
  return String(row?.id || row?.mission_id || '').trim();
}

export class MapWidget {
  constructor(container, opts = {}) {
    this._container = typeof container === 'string' ? document.getElementById(container) : container;
    this._sessionId = opts.sessionId || '';
    this._map = null;
    this._overlayLayer = null;
    this._errorBanner = null;
    this._errorText = null;
    this._emptyState = null;
    this._mapEl = null;
    this._listEl = null;
    this._shellEl = null;
    this._mapWrapEl = null;
    this._listPanel = null;
    this._selectionPanel = null;
    this._keyboardHelp = null;
    this._contextMenu = null;
    this._editBanner = null;
    this._editBannerText = null;
    this._selectionPanelWrap = null;
    this._mounted = false;
    // Mission state machine (ADR-0021 flat-mission model):
    //   _missions             — full list of mission rows from the server (source of truth).
    //   _missionCache         — per-mission overlay payloads keyed by id (waypoints/bounds).
    //   _visibleMissionOrder  — eye-icon toggled subset, in operator-controlled draw order.
    //   _selectedMissionIds   — sidebar multi-selection (drives bulk actions, not rendering).
    //   _activeMissionId      — single mission currently being edited / armed (at most one).
    this._missions = [];
    this._missionCache = new Map();
    this._visibleMissionOrder = [];
    this._selectedMissionIds = new Set();
    this._activeMissionId = '';
    this._activeProfileId = 'rover_default';
    this._profilesById = {};
    this._controllerVersion = null;
    this._vehicleLayer = null;
    this._pollTimer = null;
    this._confirmModal = null;
    this._confirmResolve = null;
    this._actionBusy = false;
    this._paletteByMissionId = new Map();
    this._editStateSubscriber = null;
    this._keydownHandler = null;
    this._marqueeEl = null;
    this._marqueeHandler = null;
    this._hintToasts = null;
    this._elevationEl = null;
    this._elevationPanel = null;
    this._sampleHeight = () => 0;
    this._terrainLayer = null;
    this._bulkActionBar = null;
    this._didInitialFit = false;
  }

  mount() {
    if (this._mounted || typeof L === 'undefined') {
      if (typeof L === 'undefined') {
        console.error('MapWidget: Leaflet (L) is not loaded. Check that leaflet.js loaded before MapWidget.mount() is called.');
      }
      return;
    }
    this._buildDOM();
    this._map = L.map(this._mapEl, {
      crs: L.CRS.Simple,
      zoom: 1,
      minZoom: -6,
      maxZoom: 8,
      zoomSnap: 0.5,
      attributionControl: false,
    });
    this._map.createPane('missionPane');
    this._map.getPane('missionPane').style.zIndex = 470;
    this._map.setView([0, 0], 1);
    this._overlayLayer = new MissionOverlayLayer(this._map);

    // Dismiss context menu on map click; in add mode, append a waypoint at the clicked position
    this._map.on('click', (e) => {
      this._contextMenu.close();
      if (editState.editMode === 'add' && editState.isEditable()) {
        const ll = e.latlng;
        this._handleGhostClick(editState.waypoints.length, { x: ll.lng, y: ll.lat, z: 0 });
      } else if (editState.missionId) {
        editState.clearSelection();
      }
    });

    this._listPanel = new MissionListPanel(this._listEl, {
      onActivateRequested: (missionId, opts) => this._handleMissionActivated(missionId, opts),
      onVisibilityToggled: (missionId) => this._toggleVisibility(missionId),
      onSelectionToggled: (missionId, opts) => this._toggleMissionSelection(missionId, opts),
      onExecuteRequested: (missionId) => this._handleExecuteRequest(missionId),
      onEditRequested: (missionId) => this._onEditRequested(missionId),
      onCreateRequested: () => this._handleCreateMission(),
      onDeleteRequested: (missionId) => this._handleDeleteMission(missionId),
    });
    this._vehicleLayer = new LiveVehicleLayer(this._map);
    this._vehicleLayer.connect();

    this._elevationPanel = new ElevationProfilePanel(this._elevationEl, {
      onWaypointClick: (idx) => editState.setSelection(new Set([idx])),
    });

    this._bulkActionBar = new BulkEditActionBar(this._mapWrapEl, {
      onDelete: () => this._handleDeleteSelected(),
      onSetAltitude: (z) => this._handleBulkSetAltitude(z),
      onClearSelection: () => editState.clearSelection(),
    });

    fetchSceneMap().then((sceneMap) => {
      if (sceneMap) {
        this._terrainLayer = new TerrainCanvasLayer(sceneMap);
        this._terrainLayer.addTo(this._map);
      }
      this._sampleHeight = makeSampler(sceneMap);
      this._updateElevationProfile();
    });

    this._editStateSubscriber = (snapshot) => this._onEditStateChange(snapshot);
    editState.subscribe(this._editStateSubscriber);

    this._keydownHandler = (e) => this._handleMapKeydown(e);
    this._shellEl.addEventListener('keydown', this._keydownHandler);
    this._shellEl.tabIndex = -1; // allow programmatic focus for keyboard routing

    // Marquee multi-select: capture-phase mousedown on empty map starts a rubber-band selector.
    // stopImmediatePropagation prevents Leaflet's drag handler from panning during the gesture.
    // Only active when a mission is loaded and not in add mode (add mode uses click-to-append).
    this._marqueeHandler = (e) => {
      if (e.button !== 0) return;
      if (!editState.missionId || editState.editMode === 'add') return;
      if (e.target.closest('.leaflet-interactive')) return;
      e.stopImmediatePropagation();
      this._startMarquee(e);
    };
    this._mapEl.addEventListener('mousedown', this._marqueeHandler, true);

    this._mounted = true;
    window.requestAnimationFrame(() => this.invalidateSize());
    this._startPolling();
    this.refresh().catch((error) => this._showError(error?.message || 'Map refresh failed'));
  }

  destroy() {
    this._mounted = false;
    this._stopPolling();
    this._vehicleLayer?.disconnect();
    this._vehicleLayer = null;
    this._terrainLayer?.remove();
    this._terrainLayer = null;
    this._missionCache.clear();
    if (this._editStateSubscriber) {
      editState.unsubscribe(this._editStateSubscriber);
      this._editStateSubscriber = null;
    }
    if (this._mapEl && this._marqueeHandler) {
      this._mapEl.removeEventListener('mousedown', this._marqueeHandler, true);
    }
    if (this._shellEl && this._keydownHandler) {
      this._shellEl.removeEventListener('keydown', this._keydownHandler);
    }
    editState.clearEdit();
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    if (this._container) this._container.innerHTML = '';
  }

  invalidateSize() {
    this._map?.invalidateSize(false);
  }

  setSessionId(sessionId) {
    const nextSessionId = sessionId || '';
    if (nextSessionId !== this._sessionId) {
      this._sessionId = nextSessionId;
      this._missionCache.clear();
      this._missions = [];
      this._visibleMissionOrder = [];
      this._selectedMissionIds.clear();
      this._activeMissionId = '';
    }
    this.refresh();
  }

  async refresh() {
    if (!this._map) return;
    this._hideError();
    await Promise.all([this._loadVehicleProfiles(), this._loadControllerState()]);
    const missionsPayload = await listMissions({ sessionId: this._sessionId, limit: 100 });
    if (!missionsPayload.ok) {
      this._showError(missionsPayload.error || 'fetch failed');
      this._overlayLayer.clear();
      this._listPanel.render();
      this._showEmpty(true);
      return;
    }

    const previousMissionIds = new Set(this._missions.map((mission) => missionIdOf(mission)));
    const missions = normalizeMissionRows(missionsPayload.missions || []);
    this._missions = missions;
    const preferredMissionId = missions.find((mission) => !previousMissionIds.has(missionIdOf(mission)))?.id || '';
    const isInitialFit = !this._didInitialFit;
    this._syncVisibilityState(missions, { preferredMissionId });
    await this._primeVisibleOverlays();
    this._render({ fit: isInitialFit });
    if (isInitialFit && this._missions.length) this._didInitialFit = true;
  }

  async _loadVehicleProfiles() {
    const [activeResult, listResult] = await Promise.all([getActiveVehicleProfile(), listVehicleProfiles()]);
    if (activeResult.ok && activeResult.profile?.id) {
      this._activeProfileId = String(activeResult.profile.id);
    }
    if (listResult.ok && Array.isArray(listResult.profiles)) {
      this._profilesById = Object.fromEntries(
        listResult.profiles
          .filter((profile) => profile && profile.id)
          .map((profile) => [String(profile.id), profile]),
      );
    } else if (!listResult.ok) {
      console.warn('MapWidget: vehicle profiles unavailable, defaulting to rover_default');
    }
  }

  async _loadControllerState() {
    const result = await getControllerState();
    if (result.ok && result.controller_state) {
      this._controllerVersion = result.controller_state.controller_version ?? null;
    }
  }

  _startPolling() {
    this._stopPolling();
    const tick = () => {
      if (!this._mounted) return;
      // Skip automatic refresh while user has an active edit session.
      if (document.visibilityState !== 'hidden' && !editState.missionId) {
        this.refresh().catch(() => {});
      }
      this._pollTimer = setTimeout(tick, 5000);
    };
    this._pollTimer = setTimeout(tick, 5000);
  }

  _stopPolling() {
    if (this._pollTimer !== null) {
      clearTimeout(this._pollTimer);
      this._pollTimer = null;
    }
  }

  async _handleCreateMission() {
    if (this._actionBusy) return;
    this._actionBusy = true;
    const result = await createMission({ waypoints: [], label: '', session_id: this._sessionId });
    this._actionBusy = false;
    if (!result.ok) {
      this._showError(result.error || 'Create mission failed');
      return;
    }
    this._missionCache.clear();
    await this.refresh();
    const newId = result.mission && result.mission.id;
    if (newId) this.setFocus(String(newId));
  }

  async _handleDeleteMission(missionId) {
    if (this._actionBusy || !missionId) return;
    this._actionBusy = true;
    const result = await deleteMission(missionId);
    this._actionBusy = false;
    if (!result.ok) {
      this._showError(result.error || 'Delete failed');
      return;
    }
    this._missionCache.clear();
    await this.refresh();
    this._hintToasts?.showWithAction(`Mission #${missionId} deleted.`, {
      actionLabel: 'Undo',
      onAction: () => this._handleRestoreMission(missionId),
    });
  }

  async _handleRestoreMission(missionId) {
    if (this._actionBusy || !missionId) return;
    this._actionBusy = true;
    const result = await restoreMission(missionId);
    this._actionBusy = false;
    if (!result.ok) {
      this._showError(result.error || 'Restore failed');
      return;
    }
    this._missionCache.clear();
    await this.refresh();
  }

  async _handleExecuteRequest(missionId) {
    if (this._actionBusy || !missionId) return;
    const confirmed = await this._showConfirmModal(missionId);
    if (!confirmed) return;
    this._actionBusy = true;
    const result = await executeMission(missionId, { expectedControllerVersion: this._controllerVersion });
    this._actionBusy = false;
    if (!result.ok) {
      if (result.status === 'stale_controller_version') {
        await this._recoverFromStaleControllerVersion(result, missionId);
        return;
      }
      this._showError(result.error || 'Execute failed');
      return;
    }
    this._missionCache.clear();
    await this.refresh();
  }

  // --- Edit flow ---

  async _onEditRequested(missionId) {
    const rawResult = await getMission(missionId);
    if (!rawResult.ok) {
      this._showError(rawResult.error || 'Could not load mission for editing');
      return;
    }
    let missionToEdit = rawResult;

    if (LOCKED_STATUSES.has(String(rawResult.status || ''))) {
      // Fork: create a new proposed successor so the original stays intact.
      const waypoints = collectEditableWaypoints(rawResult.mission || {});
      const forkResult = await createMission({
        operation_id: rawResult.operation_id,
        waypoints,
        label: `Edit of …${String(missionId).slice(-6)}`,
        from_mission_id: missionId,
      });
      if (!forkResult.ok) {
        this._showError(forkResult.error || 'Could not fork mission for editing');
        return;
      }
      missionToEdit = forkResult.mission;
      this._prepareMissionForEditing(missionToEdit.id || missionId);
      this._missionCache.clear();
      await this.refresh();
    }

    this._prepareMissionForEditing(missionToEdit.id || missionId);
    editState.beginEdit(missionToEdit);
    this.setFocus(missionToEdit.id || missionId, { fit: false });
    this._render(); // drop edited mission from renderMany
  }

  async _handleDragEnd(idx, newPoint, preDragLatLng, marker) {
    if (!editState.isEditable()) return;
    editState.setBusy(true);
    const result = await updateMissionWaypoint(editState.missionId, idx + 1, {
      point: newPoint,
      expected_version: editState.clientVersion,
    });
    if (result.ok) {
      editState.beginEdit(result.mission);
    } else {
      // Snap the marker back to its pre-drag position.
      if (preDragLatLng && marker) marker.setLatLng(preDragLatLng);
      editState.setBusy(false);
      if (result.status === 'version_conflict') {
        this._showError('Edit conflict — refreshing.');
        const fresh = await getMission(editState.missionId);
        if (fresh.ok) editState.beginEdit(fresh);
      } else if (result.status === 'mission_locked' || result.status === 'revision_locked') {
        this._showError('This mission is locked. Use the Edit button to create an editable copy.');
      } else {
        this._showError(result.error || 'Waypoint update failed');
      }
    }
  }

  // afterIndex is the 1-based API after_index value (0 = prepend, N = insert after N-th waypoint).
  async _handleGhostClick(afterIndex, point) {
    if (!editState.isEditable()) return;
    editState.setBusy(true);
    const result = await insertMissionWaypoint(editState.missionId, {
      point,
      expected_version: editState.clientVersion,
      after_index: afterIndex,
    });
    if (result.ok) {
      editState.beginEdit(result.mission);
    } else {
      editState.setBusy(false);
      this._showError(result.error || 'Insert failed');
    }
  }

  async _handleDeleteSelected() {
    if (!editState.isEditable()) return;
    const sortedIndices = [...editState.selectedIndices].sort((a, b) => b - a); // descending
    if (!sortedIndices.length) return;
    editState.setBusy(true);
    let prevMission = null;
    for (const idx of sortedIndices) {
      const missionRowId = prevMission ? prevMission.id : editState.missionId;
      const version = prevMission ? prevMission.client_version : editState.clientVersion;
      const result = await deleteMissionWaypoint(missionRowId, idx + 1, version);
      if (!result.ok) {
        editState.setBusy(false);
        this._showError(result.error || 'Delete failed');
        if (prevMission) editState.beginEdit(prevMission);
        return;
      }
      prevMission = result.mission;
    }
    if (prevMission) editState.beginEdit(prevMission);
  }

  async _handleBulkSetAltitude(z) {
    if (!editState.isEditable()) return;
    const sortedIndices = [...editState.selectedIndices].sort((a, b) => a - b);
    if (!sortedIndices.length) return;
    editState.setBusy(true);
    let prevMission = null;
    for (const idx of sortedIndices) {
      const missionRowId = prevMission ? prevMission.id : editState.missionId;
      const version = prevMission ? prevMission.client_version : editState.clientVersion;
      const wp = editState.waypoints[idx];
      if (!wp) continue;
        const result = await updateMissionWaypoint(missionRowId, idx + 1, {
        point: { x: wp.x, y: wp.y, z },
        expected_version: version,
      });
      if (!result.ok) {
        editState.setBusy(false);
        this._showError(result.error || 'Altitude update failed');
        if (prevMission) editState.beginEdit(prevMission);
        return;
      }
      prevMission = result.mission;
    }
    if (prevMission) editState.beginEdit(prevMission);
  }

  _handleMarkerClick(idx, event) {
    editState.setSelection([idx], {
      shift: event?.shiftKey,
      toggle: event?.metaKey || event?.ctrlKey,
    });
  }

  _handleMarkerRightClick(idx, event) {
    if (!editState.isEditable() || !event) return;
    const rect = this._container.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const items = [
      { label: 'Insert before', action: () => this._insertAdjacentTo(idx, 'before') },
      { label: 'Insert after',  action: () => this._insertAdjacentTo(idx, 'after') },
      { label: 'Delete',        action: () => {
        editState.setSelection([idx]);
        this._handleDeleteSelected();
      }},
    ];
    const vehiclePos = this._vehicleLayer?.getPosition();
    if (vehiclePos) {
      items.push({ label: 'Move to vehicle position', action: () => this._moveWaypointToVehicle(idx, vehiclePos) });
    }
    this._contextMenu.open(x, y, items);
  }

  async _insertAdjacentTo(idx, side) {
    const wp = editState.waypoints[idx];
    if (!wp) return;
    if (side === 'before') {
      const prev = idx > 0 ? editState.waypoints[idx - 1] : null;
      const point = prev
        ? { x: (wp.x + prev.x) / 2, y: (wp.y + prev.y) / 2, z: wp.z }
        : { x: wp.x, y: wp.y - 1, z: wp.z };
      await this._handleGhostClick(idx, point); // after_index=idx means insert before waypoint idx+1 (1-based)
    } else {
      const next = idx + 1 < editState.waypoints.length ? editState.waypoints[idx + 1] : null;
      const point = next
        ? { x: (wp.x + next.x) / 2, y: (wp.y + next.y) / 2, z: wp.z }
        : { x: wp.x, y: wp.y + 1, z: wp.z };
      await this._handleGhostClick(idx + 1, point); // after_index=idx+1 means after current waypoint
    }
  }

  async _moveWaypointToVehicle(idx, vehiclePos) {
    await this._handleDragEnd(idx, { x: vehiclePos.x, y: vehiclePos.y, z: vehiclePos.z }, null, null);
  }

  // --- Marquee multi-select ---

  _startMarquee(e) {
    const rect = this._mapWrapEl.getBoundingClientRect();
    const startX = e.clientX - rect.left;
    const startY = e.clientY - rect.top;

    this._marqueeEl.style.left = `${startX}px`;
    this._marqueeEl.style.top = `${startY}px`;
    this._marqueeEl.style.width = '0px';
    this._marqueeEl.style.height = '0px';

    const onMouseMove = (mv) => {
      const x = mv.clientX - rect.left;
      const y = mv.clientY - rect.top;
      this._marqueeEl.style.left = `${Math.min(startX, x)}px`;
      this._marqueeEl.style.top = `${Math.min(startY, y)}px`;
      this._marqueeEl.style.width = `${Math.abs(x - startX)}px`;
      this._marqueeEl.style.height = `${Math.abs(y - startY)}px`;
      this._marqueeEl.hidden = false;
    };

    const onMouseUp = (mu) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      this._marqueeEl.hidden = true;

      const endX = mu.clientX - rect.left;
      const endY = mu.clientY - rect.top;
      const dx = endX - startX;
      const dy = endY - startY;
      if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return; // treat as click — let the click event clear selection

      // Convert screen corners to scene coords via Leaflet
      const tl = this._map.containerPointToLatLng([Math.min(startX, endX), Math.min(startY, endY)]);
      const br = this._map.containerPointToLatLng([Math.max(startX, endX), Math.max(startY, endY)]);
      const minX = Math.min(tl.lng, br.lng);
      const maxX = Math.max(tl.lng, br.lng);
      const minY = Math.min(tl.lat, br.lat);
      const maxY = Math.max(tl.lat, br.lat);

      const selected = editState.waypoints
        .map((wp, i) => (wp.x >= minX && wp.x <= maxX && wp.y >= minY && wp.y <= maxY ? i : -1))
        .filter((i) => i >= 0);

      if (selected.length) editState.setSelection(selected);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  // --- editState subscriber ---

  _onEditStateChange(snapshot) {
    if (!snapshot.missionId) {
      this._overlayLayer.clearEditable();
      this._selectionPanel.hide();
      this._bulkActionBar?.hide();
      this._editBanner.hidden = true;
      this._mapEl.classList.remove('is-edit-mode', 'is-locked');
      this._updateElevationProfile();
      return;
    }

    const isLocked = snapshot.status === 'executing';
    this._mapEl.classList.toggle('is-locked', isLocked);
    this._mapEl.classList.toggle('is-edit-mode', snapshot.editMode === 'add');

    this._editBanner.hidden = false;
    const modeLabel = snapshot.editMode === 'vertex' ? ' · vertex edit' : snapshot.editMode === 'add' ? ' · add mode' : '';
    this._editBannerText.textContent =
      `Editing — ${snapshot.status} · rev …${snapshot.missionId.slice(-8)}${modeLabel}${snapshot.busy ? ' (saving…)' : ''}`;

    if (snapshot.selectedIndices.size === 1) {
      const idx = [...snapshot.selectedIndices][0];
      const wp = snapshot.waypoints[idx];
      if (wp) this._selectionPanel.show(wp, idx);
      else this._selectionPanel.hide();
    } else {
      this._selectionPanel.hide();
    }

    this._bulkActionBar?.update(snapshot.selectedIndices, snapshot.waypoints, editState.isEditable());

    const color = this._paletteByMissionId.get(snapshot.missionId) || '#4a90d9';
    this._overlayLayer.renderEditable(snapshot.waypoints, {
      color,
      selectedIndices: snapshot.selectedIndices,
      isLocked,
      callbacks: {
        onDragEnd:         (idx, pt, preDragLL, marker) => this._handleDragEnd(idx, pt, preDragLL, marker),
        onGhostClick:      (afterIndex, pt) => this._handleGhostClick(afterIndex, pt),
        onMarkerClick:     (idx, ev) => this._handleMarkerClick(idx, ev),
        onMarkerRightClick:(idx, ev) => this._handleMarkerRightClick(idx, ev),
        onDragStart:       () => this._hintToasts?.show('Hold Alt to snap to a waypoint'),
      },
    });

    const vehicleKind = this._profilesById[this._activeProfileId]?.kind || 'ground';
    this._elevationPanel?.update(snapshot.waypoints, this._sampleHeight, { color, vehicleKind });

    if (snapshot.selectedIndices.size === 1) {
      const idx = [...snapshot.selectedIndices][0];
      this._elevationPanel?.highlight(idx);
    }
  }

  // --- Keyboard ---

  _handleMapKeydown(e) {
    if (this._isInputFocused(e.target)) return;
    const key = e.key;

    // Always available
    if (key === '?') { e.preventDefault(); this._keyboardHelp.show(); return; }
    if (key === '/') {
      e.preventDefault();
      document.querySelector('#ai-session-search')?.focus();
      return;
    }
    if (key === 'Escape') {
      e.preventDefault();
      if (this._contextMenu.isOpen) { this._contextMenu.close(); return; }
      if (editState.selectedIndices.size) { editState.clearSelection(); return; }
      if (editState.editMode) { editState.setEditMode(null); return; }
      if (editState.missionId) {
        editState.clearEdit();
        this._missionCache.clear();
        this.refresh();
      }
      return;
    }

    if (!editState.missionId) return;

    if (key === 'f' || key === 'F') { e.preventDefault(); this.setFocus(editState.missionId); return; }
    if (key === '[') { e.preventDefault(); editState.stepSelection(-1); return; }
    if (key === ']') { e.preventDefault(); editState.stepSelection(1); return; }

    if (!editState.isEditable()) return;

    if (key === 'v' || key === 'V') { e.preventDefault(); editState.setEditMode('vertex'); return; }
    if (key === 'a' || key === 'A') { e.preventDefault(); editState.setEditMode('add'); return; }
    if (key === 'Delete' || key === 'Backspace') { e.preventDefault(); this._handleDeleteSelected(); return; }
  }

  _isInputFocused(target) {
    if (!target) return false;
    const tag = (target.tagName || '').toLowerCase();
    return ['textarea', 'input', 'select'].includes(tag);
  }

  // --- Confirm modal ---

  _showConfirmModal(missionId) {
    return new Promise((resolve) => {
      this._confirmResolve = resolve;
      const modal = this._confirmModal;
      if (!modal) { resolve(false); return; }
      modal.querySelector('.map-confirm-mission-id').textContent = String(missionId).slice(-8);
      modal.querySelector('.map-confirm-controller-version').textContent =
        this._controllerVersion !== null ? String(this._controllerVersion) : 'unknown';
      modal.hidden = false;
      modal.querySelector('.map-confirm-ok').focus();
    });
  }

  _closeConfirmModal(confirmed) {
    if (this._confirmModal) this._confirmModal.hidden = true;
    if (this._confirmResolve) {
      const resolve = this._confirmResolve;
      this._confirmResolve = null;
      resolve(confirmed);
    }
  }

  // --- Visibility / focus / expand ---

  _executingMissionIds() {
    return this._missions
      .filter((mission) => String(mission.status || '') === 'executing')
      .map((mission) => missionIdOf(mission));
  }

  _syncVisibilityState(missions, { preferredMissionId = '' } = {}) {
    const knownMissionIds = new Set(missions.map((mission) => missionIdOf(mission)));
    this._visibleMissionOrder = this._visibleMissionOrder.filter((missionId) => knownMissionIds.has(missionId));
    this._selectedMissionIds = new Set(
      [...this._selectedMissionIds].filter((missionId) => knownMissionIds.has(missionId)),
    );
    if (this._activeMissionId && !knownMissionIds.has(this._activeMissionId)) {
      this._activeMissionId = '';
    }

    const executingIds = this._executingMissionIds();
    if (!this._visibleMissionOrder.length) {
      const defaults = missions
        .map((mission) => missionIdOf(mission))
        .filter(Boolean);
      this._visibleMissionOrder = enforceVisibilityCap(defaults, Infinity, executingIds);
    } else {
      this._visibleMissionOrder = enforceVisibilityCap(this._visibleMissionOrder, Infinity, executingIds);
    }

    if (preferredMissionId && knownMissionIds.has(preferredMissionId)) {
      this._pinMissionInView(preferredMissionId);
    }
    if (!this._activeMissionId) {
      this._activeMissionId = this._visibleMissionOrder[0] || '';
    }
  }

  async _primeVisibleOverlays() {
    const loads = this._visibleMissionOrder.map(async (missionId) => {
      if (this._missionCache.has(missionId)) return;
      const payload = await getMissionOverlay(missionId);
      if (payload.ok) {
        this._missionCache.set(missionId, payload);
      }
    });
    await Promise.all(loads);

    if (!this._missionCache.size && this._sessionId) {
      const payload = await getCurrentOverlay(this._sessionId);
      const overlayMissionId = String(payload.mission_id || '').trim();
      if (payload.ok && overlayMissionId) {
        this._missionCache.set(overlayMissionId, payload);
      }
    }
  }

  _render({ fit = false } = {}) {
    const editedMissionId = editState.missionId;
    const visibleMissionIds = new Set(this._visibleMissionOrder);
    const paletteByMissionId = assignPaletteColor(this._missions.map((m) => missionIdOf(m)));
    this._paletteByMissionId = paletteByMissionId;

    this._listPanel.render({
      missions: this._missions,
      visibleMissionIds,
      selectedMissionIds: this._selectedMissionIds,
      activeMissionId: this._activeMissionId,
      paletteByMissionId,
      profilesById: this._profilesById,
      activeProfileId: this._activeProfileId,
    });

    // Exclude the actively-edited mission from the read-only overlay so only
    // the editable layer shows it.
    const overlays = this._visibleMissionOrder
      .filter((missionId) => missionId !== editedMissionId)
      .map((missionId) => {
        const payload = this._missionCache.get(missionId);
        if (!payload?.available) return null;
        return {
          missionId: missionId,
          payload,
          color: paletteByMissionId.get(missionId),
          opacity: opacityForMission(missionId, this._activeMissionId),
        };
      })
      .filter(Boolean);

    this._overlayLayer.renderMany(overlays);
    if (fit) {
      const focusedPayload = this._activeMissionId ? this._missionCache.get(this._activeMissionId) : null;
      const unionBounds = boundsUnion(overlays.map((entry) => entry.payload.bounds));
      this._fitBounds(focusedPayload?.bounds || unionBounds);
    }
    this._showEmpty(!this._missions.length);
    this._updateElevationProfile();
  }

  _updateElevationProfile() {
    if (!this._elevationPanel) return;
    // During active edit: show live edit waypoints
    if (editState.missionId && editState.waypoints.length) {
      const color = this._paletteByMissionId.get(editState.missionId) || '#4a90d9';
      const vehicleKind = this._profilesById[this._activeProfileId]?.kind || 'ground';
      this._elevationPanel.update(editState.waypoints, this._sampleHeight, { color, vehicleKind });
      return;
    }
    // Otherwise: show focused mission
    const payload = this._activeMissionId ? this._missionCache.get(this._activeMissionId) : null;
    if (!payload?.available) { this._elevationPanel.clear(); return; }
    const wps = (payload.features || [])
      .filter((f) => f.type === 'waypoint')
      .sort((a, b) => a.index - b.index)
      .map((f) => ({ ...f.point, index: f.index }));
    if (!wps.length) { this._elevationPanel.clear(); return; }
    const color = this._paletteByMissionId.get(this._activeMissionId) || '#4a90d9';
    const vehicleKind = this._profilesById[this._activeProfileId]?.kind || 'ground';
    this._elevationPanel.update(wps, this._sampleHeight, { color, vehicleKind });
  }

  _fitBounds(bounds) {
    if (!bounds) return;
    const sw = [bounds.min_y, bounds.min_x];
    const ne = [bounds.max_y, bounds.max_x];
    if (bounds.min_x === bounds.max_x && bounds.min_y === bounds.max_y) {
      this._map.setView(sw, 3);
    } else {
      this._map.fitBounds([sw, ne], { padding: [28, 28] });
    }
  }

  async _toggleVisibility(missionId) {
    const executingIds = this._executingMissionIds();
    if (this._visibleMissionOrder.includes(missionId)) {
      if (executingIds.includes(missionId)) return;
      this._visibleMissionOrder = this._visibleMissionOrder.filter((id) => id !== missionId);
      if (this._activeMissionId === missionId) {
        this._activeMissionId = '';
      }
      this._render();
      return;
    }
    if (!this._visibleMissionOrder.includes(missionId)) {
      this._visibleMissionOrder.push(missionId);
    }
    this._visibleMissionOrder = enforceVisibilityCap(this._visibleMissionOrder, Infinity, executingIds);
    if (!this._missionCache.has(missionId)) {
      const payload = await getMissionOverlay(missionId);
      if (payload.ok) this._missionCache.set(missionId, payload);
      else this._showError(payload.error || 'Overlay fetch failed');
    }
    if (!this._activeMissionId) this._activeMissionId = missionId;
    this._render();
  }

  _handleMissionActivated(missionId, { shiftKey = false } = {}) {
    if (shiftKey) {
      if (this._selectedMissionIds.has(missionId)) this._selectedMissionIds.delete(missionId);
      else this._selectedMissionIds.add(missionId);
    }
    this.setFocus(missionId);
  }

  _toggleMissionSelection(missionId, { checked = false } = {}) {
    if (!missionId) return;
    if (checked) this._selectedMissionIds.add(missionId);
    else this._selectedMissionIds.delete(missionId);
    this._render();
  }

  async setFocus(missionId, { fit = true } = {}) {
    const nextMissionId = String(missionId || '').trim();
    this._activeMissionId = nextMissionId;
    if (nextMissionId && !this._visibleMissionOrder.includes(nextMissionId)) {
      this._visibleMissionOrder.push(nextMissionId);
      this._visibleMissionOrder = enforceVisibilityCap(this._visibleMissionOrder, Infinity, this._executingMissionIds());
    }
    if (nextMissionId && !this._missionCache.has(nextMissionId)) {
      const payload = await getMissionOverlay(nextMissionId);
      if (payload.ok) this._missionCache.set(nextMissionId, payload);
      else this._showError(payload.error || 'Overlay fetch failed');
    }
    this._render({ fit });
  }

  _pinMissionInView(missionId) {
    const nextMissionId = String(missionId || '').trim();
    if (!nextMissionId) return;
    if (!this._visibleMissionOrder.includes(nextMissionId)) {
      this._visibleMissionOrder.push(nextMissionId);
      this._visibleMissionOrder = enforceVisibilityCap(this._visibleMissionOrder, Infinity, this._executingMissionIds());
    }
    this._activeMissionId = nextMissionId;
  }

  _prepareMissionForEditing(missionId) {
    this._pinMissionInView(missionId);
  }

  async _recoverFromStaleControllerVersion(result, requestedMissionId) {
    const controllerState = result.controller_state || {};
    const latestVersion = controllerState.controller_version ?? null;
    if (latestVersion !== null && latestVersion !== undefined) {
      this._controllerVersion = latestVersion;
    }

    const controllerActiveMissionId = String(controllerState.active_mission_id || '').trim();
    if (controllerActiveMissionId) {
      this._pinMissionInView(controllerActiveMissionId);
    }

    this._missionCache.clear();
    await this.refresh();

    const requestedSuffix = String(requestedMissionId).slice(-6);
    const versionText = latestVersion !== null && latestVersion !== undefined ? String(latestVersion) : 'unknown';
    if (controllerActiveMissionId) {
      this.setFocus(controllerActiveMissionId);
      this._showError(
        `Controller mission version changed to ${versionText}. Refreshed from stale execute on …${requestedSuffix}; review active mission …${controllerActiveMissionId.slice(-6)} and retry.`,
      );
      return;
    }

    this._showError(
      `Controller mission version changed to ${versionText}. Refreshed after stale execute on …${requestedSuffix}; retry when ready.`,
    );
  }

  // --- DOM ---

  _buildDOM() {
    this._container.innerHTML = '';

    const errorBanner = document.createElement('div');
    errorBanner.className = 'map-widget-error-banner';
    errorBanner.setAttribute('role', 'alert');
    errorBanner.hidden = true;
    const errorText = document.createElement('span');
    errorText.className = 'map-widget-error-text';
    const refreshBtn = document.createElement('button');
    refreshBtn.type = 'button';
    refreshBtn.className = 'map-widget-refresh-btn';
    refreshBtn.textContent = 'Refresh';
    refreshBtn.setAttribute('aria-label', 'Refresh mission overlays');
    refreshBtn.addEventListener('click', () => this.refresh());
    errorBanner.append(errorText, refreshBtn);
    this._errorBanner = errorBanner;
    this._errorText = errorText;

    const shell = document.createElement('div');
    shell.className = 'map-widget-shell';
    this._shellEl = shell;

    const listEl = document.createElement('div');
    listEl.className = 'map-widget-list';
    this._listEl = listEl;

    const mapWrap = document.createElement('div');
    mapWrap.className = 'map-widget-wrap';
    this._mapWrapEl = mapWrap;

    const mapEl = document.createElement('div');
    mapEl.className = 'map-widget-map';
    this._mapEl = mapEl;

    const emptyState = document.createElement('div');
    emptyState.className = 'map-widget-empty';
    emptyState.setAttribute('aria-live', 'polite');
    emptyState.hidden = true;
    emptyState.innerHTML = `
      <p class="map-empty-title">No missions yet</p>
      <p class="map-empty-hint">Ask the agent in the chat above to plan a mission.</p>
      <button class="map-empty-cta" type="button">↑ Go to chat</button>
    `;
    emptyState.querySelector('.map-empty-cta').addEventListener('click', () => {
      document.querySelector('.ai-chat-panel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      setTimeout(() => document.getElementById('ai-message-input')?.focus(), 300);
    });
    this._emptyState = emptyState;

    // Edit-mode banner (hidden by default)
    const editBanner = document.createElement('div');
    editBanner.className = 'map-edit-banner';
    editBanner.hidden = true;
    const editBannerText = document.createElement('span');
    editBannerText.className = 'map-edit-banner-text';
    const exitEditBtn = document.createElement('button');
    exitEditBtn.type = 'button';
    exitEditBtn.className = 'map-edit-exit-btn';
    exitEditBtn.textContent = '✕ Exit edit';
    exitEditBtn.setAttribute('aria-label', 'Exit edit mode');
    exitEditBtn.addEventListener('click', () => {
      editState.clearEdit();
      this._missionCache.clear();
      this.refresh();
    });
    editBanner.append(editBannerText, exitEditBtn);
    this._editBanner = editBanner;
    this._editBannerText = editBannerText;

    // Selection panel (floating waypoint inspector)
    const selectionPanelWrap = document.createElement('div');
    selectionPanelWrap.className = 'map-selection-panel-wrap';
    selectionPanelWrap.hidden = true;
    this._selectionPanelWrap = selectionPanelWrap;
    this._selectionPanel = new SelectionPanel(selectionPanelWrap, {
      onClose: () => editState.clearSelection(),
    });

    // Marquee selection rectangle (hidden by default)
    const marqueeEl = document.createElement('div');
    marqueeEl.className = 'map-marquee';
    marqueeEl.hidden = true;
    marqueeEl.setAttribute('aria-hidden', 'true');
    this._marqueeEl = marqueeEl;

    // Hint toasts (floating transient hints, e.g., "Hold Alt to snap")
    this._hintToasts = new HintToasts(mapWrap);

    mapWrap.append(mapEl, emptyState, editBanner, selectionPanelWrap, marqueeEl);

    const layoutResizer = document.createElement('button');
    layoutResizer.type = 'button';
    layoutResizer.className = 'map-widget-layout-resizer';
    layoutResizer.setAttribute('role', 'separator');
    layoutResizer.setAttribute('aria-label', 'Resize mission sidebar');
    layoutResizer.setAttribute('aria-orientation', 'vertical');
    layoutResizer.setAttribute('aria-valuemin', '240');
    layoutResizer.setAttribute('aria-valuemax', '640');
    layoutResizer.setAttribute('aria-valuenow', '340');
    layoutResizer.title = 'Drag to resize mission sidebar';
    this._layoutResizer = layoutResizer;

    const heightResizer = document.createElement('button');
    heightResizer.type = 'button';
    heightResizer.className = 'map-widget-height-resizer';
    heightResizer.setAttribute('role', 'separator');
    heightResizer.setAttribute('aria-label', 'Resize map height');
    heightResizer.setAttribute('aria-orientation', 'horizontal');
    heightResizer.setAttribute('aria-valuemin', '320');
    heightResizer.setAttribute('aria-valuemax', '1100');
    heightResizer.setAttribute('aria-valuenow', '540');
    heightResizer.title = 'Drag to resize map height';
    this._heightResizer = heightResizer;

    shell.append(listEl, layoutResizer, mapWrap, heightResizer);

    // Context menu (absolute-positioned inside container)
    this._contextMenu = new ContextMenu(this._container);

    // Confirm modal
    const confirmModal = document.createElement('div');
    confirmModal.className = 'map-confirm-modal';
    confirmModal.setAttribute('role', 'dialog');
    confirmModal.setAttribute('aria-modal', 'true');
    confirmModal.setAttribute('aria-labelledby', 'map-confirm-title');
    confirmModal.hidden = true;
    confirmModal.innerHTML = `
      <div class="map-confirm-dialog">
        <h3 id="map-confirm-title" class="map-confirm-title">Execute mission on rover?</h3>
        <p class="map-confirm-body">
          This will upload the mission to the rover and start execution.<br>
          Mission: <code class="map-confirm-mission-id"></code> &nbsp;
          Controller version: <code class="map-confirm-controller-version"></code>
        </p>
        <div class="map-confirm-actions">
          <button class="map-confirm-cancel" type="button">Cancel</button>
          <button class="map-confirm-ok" type="button">Execute on rover</button>
        </div>
      </div>
    `;
    confirmModal.querySelector('.map-confirm-cancel').addEventListener('click', () => this._closeConfirmModal(false));
    confirmModal.querySelector('.map-confirm-ok').addEventListener('click', () => this._closeConfirmModal(true));
    confirmModal.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this._closeConfirmModal(false);
    });
    this._confirmModal = confirmModal;

    const elevationEl = document.createElement('div');
    elevationEl.className = 'map-elevation-panel';
    this._elevationEl = elevationEl;

    this._container.append(errorBanner, shell, elevationEl, confirmModal);

    // Keyboard help overlay (<dialog> appended to container by constructor)
    this._keyboardHelp = new KeyboardHelpOverlay(this._container);

    this._setupResizing(shell);
  }

  _setupResizing(shell) {
    const W_KEY = 'gcs-map-widget-sidebar-width';
    const H_KEY = 'gcs-map-widget-shell-height';
    const W_MIN = 240, W_MAX = 640, W_DEFAULT = 340;
    const H_MIN = 320, H_MAX = 1100, H_DEFAULT = 540;
    const MOBILE_QUERY = '(max-width: 1100px)';
    const clampW = (v) => Math.max(W_MIN, Math.min(W_MAX, Number(v) || W_DEFAULT));
    const clampH = (v) => Math.max(H_MIN, Math.min(H_MAX, Number(v) || H_DEFAULT));

    const setWidth = (v, persist = true) => {
      const w = clampW(v);
      shell.style.setProperty('--map-sidebar-w', `${w}px`);
      this._layoutResizer.setAttribute('aria-valuenow', String(w));
      if (persist) {
        try { localStorage.setItem(W_KEY, String(w)); } catch (_) {}
      }
    };
    const setHeight = (v, persist = true) => {
      const h = clampH(v);
      shell.style.setProperty('--map-shell-h', `${h}px`);
      this._heightResizer.setAttribute('aria-valuenow', String(h));
      if (persist) {
        try { localStorage.setItem(H_KEY, String(h)); } catch (_) {}
      }
      window.requestAnimationFrame(() => this.invalidateSize());
    };

    try { setWidth(localStorage.getItem(W_KEY) || W_DEFAULT, false); } catch (_) { setWidth(W_DEFAULT, false); }
    try { setHeight(localStorage.getItem(H_KEY) || H_DEFAULT, false); } catch (_) { setHeight(H_DEFAULT, false); }

    const bindPointerDrag = (handle, dragClass, onPointer) => {
      handle.addEventListener('pointerdown', (event) => {
        if (window.matchMedia(MOBILE_QUERY).matches) return;
        event.preventDefault();
        handle.setPointerCapture(event.pointerId);
        shell.classList.add(dragClass);
        onPointer(event);
      });
      handle.addEventListener('pointermove', (event) => {
        if (!handle.hasPointerCapture(event.pointerId)) return;
        onPointer(event);
      });
      const release = (event) => {
        if (event && handle.hasPointerCapture(event.pointerId)) {
          handle.releasePointerCapture(event.pointerId);
        }
        shell.classList.remove(dragClass);
        window.requestAnimationFrame(() => this.invalidateSize());
      };
      handle.addEventListener('pointerup', release);
      handle.addEventListener('pointercancel', () => shell.classList.remove(dragClass));
      handle.addEventListener('lostpointercapture', () => shell.classList.remove(dragClass));
    };

    bindPointerDrag(this._layoutResizer, 'is-resizing', (event) => {
      const rect = shell.getBoundingClientRect();
      setWidth(event.clientX - rect.left);
    });
    bindPointerDrag(this._heightResizer, 'is-height-resizing', (event) => {
      const rect = shell.getBoundingClientRect();
      setHeight(event.clientY - rect.top);
    });

    this._layoutResizer.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = Number(this._layoutResizer.getAttribute('aria-valuenow')) || W_DEFAULT;
      if (event.key === 'Home') setWidth(W_MIN);
      else if (event.key === 'End') setWidth(W_MAX);
      else setWidth(current + (event.key === 'ArrowRight' ? 24 : -24));
    });
    this._heightResizer.addEventListener('keydown', (event) => {
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = Number(this._heightResizer.getAttribute('aria-valuenow')) || H_DEFAULT;
      if (event.key === 'Home') setHeight(H_MIN);
      else if (event.key === 'End') setHeight(H_MAX);
      else setHeight(current + (event.key === 'ArrowDown' ? 24 : -24));
    });
  }

  _showError(msg) {
    this._errorText.textContent = `Mission overlay unavailable — ${msg}`;
    this._errorBanner.hidden = false;
  }

  _hideError() {
    if (this._errorBanner) this._errorBanner.hidden = true;
  }

  _showEmpty(show) {
    if (this._emptyState) this._emptyState.hidden = !show;
  }

  get isMounted() {
    return this._mounted;
  }
}
