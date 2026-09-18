import { getCurrentOverlay, getMissionOverlay, listMissions, executeMission, pauseMission, resumeMission, stopMission, getControllerState, getExecutionState, confirmExecution, cancelExecution, createDrawnPattern, previewDrawnPattern, setMissionGeofence, createMission, deleteMission, renameMission, setMissionColor } from './sources/authored/missionApi.js';
import { getRevision, createClientRevision, updateWaypoint, insertWaypoint, deleteWaypoint } from './sources/authored/missionMutationApi.js';
import { getActiveVehicleProfile, listVehicleProfiles } from './sources/authored/vehicleProfileApi.js';
import { fetchSceneMap, makeSampler } from './sources/world/terrainApi.js';
import { MissionOverlayLayer } from './sources/authored/MissionOverlayLayer.js';
import { LiveVehicleLayer } from './sources/authored/LiveVehicleLayer.js';
import { TerrainCanvasLayer } from './sources/world/TerrainCanvasLayer.js';
import { SceneObjectsLayer } from './sources/world/SceneObjectsLayer.js';
import { GridLayer } from './sources/world/GridLayer.js';
import { mapMissionsForList, assignPaletteColor } from './missionListLogic.js';
import { missionColorOverrides } from './state/missionColorOverrides.js';
import { missionSortPreference, sortMissions, SORT_OPTIONS } from './state/missionSortPreference.js';
import { MissionListPanel } from './ui/MissionListPanel.js';
import { MissionColorPicker } from './ui/MissionColorPicker.js';
import { MissionListOverflowMenu } from './ui/MissionListOverflowMenu.js';
import { MissionRowMenu } from './ui/MissionRowMenu.js';
import { SelectionPanel } from './ui/SelectionPanel.js';
import { KeyboardHelpOverlay } from './ui/KeyboardHelpOverlay.js';
import { ContextMenu } from './ui/ContextMenu.js';
import { HintToasts } from './ui/HintToasts.js';
import { ElevationProfilePanel } from './ui/ElevationProfilePanel.js';
import { BulkEditActionBar } from './ui/BulkEditActionBar.js';
import { ConfirmExecutionBanner } from './ui/ConfirmExecutionBanner.js';
import { BasemapPanel } from './ui/BasemapPanel.js';
import { MapAuthoringToolbar } from './ui/MapAuthoringToolbar.js';
import { MapSketchSession } from './MapSketchSession.js';
import { ConstraintsPanel } from './ui/ConstraintsPanel.js';
import { listConstraints, createConstraint, updateConstraint, deleteConstraint } from './sources/authored/constraintsApi.js';
import { editState } from './state/editState.js';

const LOCKED_STATUSES = new Set(['exported', 'cutover_pending', 'executing', 'completed', 'superseded', 'rejected', 'validation_failed']);

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

const MAP_ZOOM_OPTIONS = {
  zoomSnap: 0.25,
  zoomDelta: 0.25,
  wheelPxPerZoomLevel: 160,
};

export class MapWidget {
  constructor(container, opts = {}) {
    this._container = typeof container === 'string' ? document.getElementById(container) : container;
    this._opts = opts || {};
    this._sessionId = opts.sessionId || '';
    this._map = null;
    this._overlayLayer = null;
    this._sessionPillEl = null;
    this._emptyState = null;
    this._mapEl = null;
    this._listEl = null;
    this._listResizerEl = null;
    this._resizeObserver = null;
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
    // Flat-Mission read path (ADR 0021 §2). One row = one Mission; overlay,
    // visibility, focus and palette are all keyed on the Mission id. Each
    // Mission resolves to its active revision (for overlay/edit/execute) via
    // its list descriptor's activeRevisionId.
    this._missions = [];
    this._missionsById = new Map();
    this._overlayCacheByMissionId = new Map();
    this._visibleMissionOrder = [];
    this._focusedMissionId = '';
    // Selected set (ADR 0021 §4): batch-operation target, independent of
    // Visible/Active. `_selectionAnchorId` is the range anchor for shift-click.
    // `_seenMissionIds` tracks which Missions existed at the last sync so a
    // newly-created one can be auto-promoted to Active+Visible (not Selected).
    this._selectedMissionIds = new Set();
    this._selectionAnchorId = '';
    this._seenMissionIds = null;
    // The Mission whose active revision is currently being edited (edit
    // internals below stay revision-keyed via editState).
    this._editingMissionId = '';
    // Empty until /api/vehicle-profile/active answers — the widget does not
    // assume a rover before the backend says which profile is selected.
    this._activeProfileId = '';
    this._profilesById = {};
    this._controllerVersion = null;
    this._executionState = null;
    this._vehicleLayer = null;
    this._pollTimer = null;
    this._confirmModal = null;
    this._confirmResolve = null;
    this._actionBusy = false;
    this._paletteByMissionId = new Map();
    this._colorPicker = null;
    this._overflowMenu = null;
    this._rowMenu = null;
    this._editStateSubscriber = null;
    this._keydownHandler = null;
    this._marqueeEl = null;
    this._marqueeHandler = null;
    this._hintToasts = null;
    this._elevationEl = null;
    this._elevationPanel = null;
    this._sampleHeight = () => 0;
    this._terrainLayer = null;
    this._sceneObjectsLayer = null;
    this._gridLayer = null;
    this._sceneBounds = null;
    // Tracks the last bounds key used for auto-fit so _render() doesn't reset
    // the pan/zoom every poll cycle — only refit when the fit target changes.
    this._lastFitKey = null;
    // Visibility changes should not reframe the operator's current view.
    this._skipAutoFitOnce = false;
    this._bulkActionBar = null;
    // Confirm-mode async banner (ADR 0021 §1): shows the armed run's confirm
    // window and [Play]; polled alongside the overlay refresh.
    this._confirmBanner = null;
    // Real 2D WGS84 basemap render mode (Phase 4): an additive, read-only second
    // view plotting the focused mission on an OSM map by lat/lon. Default off.
    this._sketchSession = null;
    this._sketchSessionUnsub = null;
    this._editingConstraint = null;
    this._sceneSketchLayer = null;
    this._scenePlanningLayer = null;
    this._basemapPanel = null;
    this._authoringToolbarDock = null;
    this._authoringToolbar = null;
    this._layerBar = null;
    this._fitBtns = null;
    this._viewModeSelect = null;
    this._currentViewMode = 'virtual_terrain';
    this._infoBar = null;
    this._infoBarCoords = null;
    this._infoBarGround = null;
    this._infoBarGps = null;
    this._infoBarSel = null;
    this._statusBar = opts.statusBar || null;
    this._replayPathLayer = null;
    this._replayTrackVisible = true;
    this._liveRoverVisible = true;
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
      ...MAP_ZOOM_OPTIONS,
      attributionControl: false,
    });
    this._map.createPane('missionPane');
    this._map.getPane('missionPane').style.zIndex = 470;
    this._map.setView([0, 0], 1);
    this._overlayLayer = new MissionOverlayLayer(this._map);
    this._sceneSketchLayer = L.layerGroup().addTo(this._map);
    this._scenePlanningLayer = L.layerGroup().addTo(this._map);

    // Dismiss context menu on map click; in add mode, append a waypoint at the clicked position
    this._map.on('click', (e) => {
      this._contextMenu.close();
      // Sketch capture on scene views: convert CRS.Simple metres → WGS84 via mission origin.
      if (this._sketchSession?.isDirty && this._currentViewMode !== 'basemap') {
        const origin = this._focusedOrigin();
        if (origin) {
          const METRES_PER_DEG = 111320.0;
          const lat = origin.lat + e.latlng.lat / METRES_PER_DEG;
          const lon = origin.lon + e.latlng.lng / (METRES_PER_DEG * Math.cos(origin.lat * Math.PI / 180));
          this._sketchSession.addVertex({ lat, lon });
          return;
        }
      }
      if (editState.editMode === 'add' && editState.isEditable()) {
        const ll = e.latlng;
        this._handleGhostClick(editState.waypoints.length, { x: ll.lng, y: ll.lat, z: 0 });
      } else if (editState.revisionId) {
        editState.clearSelection();
      }
    });
    this._map.on('mousemove', (e) => this._onMapMouseMove(e));

    this._listPanel = new MissionListPanel(this._listEl, {
      onMissionFocusRequested: (missionId) => this.setFocus(missionId),
      onMissionVisibilityToggled: (missionId) => this._toggleVisibility(missionId),
      onMissionExecuteRequested: (missionId) => this._handleExecuteRequest(missionId),
      onMissionPauseRequested: (missionId) => this._handleMissionPause(missionId),
      onMissionResumeRequested: (missionId) => this._handleMissionResume(missionId),
      onMissionStopRequested: (missionId) => this._handleMissionStop(missionId),
      onMissionEditRequested: (missionId) => this._onEditRequested(missionId),
      onMissionDeleteRequested: (missionId) => this._handleDeleteMission(missionId),
      onMissionRenameRequested: (missionId, name) => this._handleRenameMission(missionId, name),
      onNewMissionRequested: () => this._handleNewMission(),
      onMissionSelectionToggled: (missionId, opts) => this._toggleSelection(missionId, opts),
      onAllVisibilityToggled: (showAll) => (showAll ? this._showAllMissions() : this._hideAllMissions()),
      onAllSelectionToggled: (selectAll) => (selectAll ? this._selectAllMissions() : this._clearSelection()),
      onSelectionCleared: () => this._clearSelection(),
      onMissionDoneEditRequested: () => {
        editState.clearEdit();
        this._overlayCacheByMissionId.clear();
        this.refresh();
      },
      onColorChipClicked: (missionId, anchorEl) => this._openColorPicker(missionId, anchorEl),
      onOverflowClicked: (anchorEl) => this._openOverflowMenu(anchorEl),
      onMissionRowMenuRequested: (missionId, anchorEl) => this._openRowMenu(missionId, anchorEl),
      onMissionDeleteSelectedRequested: () => this._handleDeleteSelectedMissions(),
    });
    this._colorPicker = new MissionColorPicker(this._shellEl, { scrollEl: this._listEl });
    this._overflowMenu = new MissionListOverflowMenu(this._listEl);
    this._rowMenu = new MissionRowMenu(this._listEl);
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
        this._sceneObjectsLayer = new SceneObjectsLayer(sceneMap);
        this._sceneObjectsLayer.addTo(this._map);
        this._gridLayer = new GridLayer(sceneMap);
        this._gridLayer.addTo(this._map);
        this._sceneBounds = sceneMap.bounds || null;
        this._applyViewMode(this._viewModeSelect?.value || 'virtual_terrain');
        this._updateFitButtons();
        // Center on the scene so the 3d-env map renders standalone, even with
        // no mission focused. Only do so while nothing is focused/edited, so we
        // don't yank the view away from a mission the user is already looking at.
        if (this._sceneBounds && !this._focusedMissionId && !editState.revisionId) {
          this._fitBounds(this._sceneBounds);
        }
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
    // Only active when a revision is loaded and not in add mode (add mode uses click-to-append).
    this._marqueeHandler = (e) => {
      if (e.button !== 0) return;
      if (!editState.revisionId || editState.editMode === 'add') return;
      if (e.target.closest('.leaflet-interactive')) return;
      e.stopImmediatePropagation();
      this._startMarquee(e);
    };
    this._mapEl.addEventListener('mousedown', this._marqueeHandler, true);

    this._mounted = true;
    this._bindListResizer();
    window.requestAnimationFrame(() => this.invalidateSize());
    // The map area is user-resizable (CSS `resize: vertical`); re-measure
    // Leaflet whenever the container's box changes so tiles fill the new size.
    if (typeof ResizeObserver !== 'undefined') {
      this._resizeObserver = new ResizeObserver(() => this.invalidateSize());
      this._resizeObserver.observe(this._container);
    }
    this._startPolling();
    this._pollExecutionState().catch(() => {});
    this.refresh().catch((error) => this._pushStatus(error?.message || 'Map refresh failed', 'error'));
  }

  _bindListResizer() {
    const resizer = this._listResizerEl;
    const shell = this._shellEl;
    if (!resizer || !shell) return;
    const MAP_LIST_WIDTH_KEY = 'gcs-map-list-width';
    const MAP_LIST_MIN = 180;
    const MAP_LIST_MAX = 480;
    const clamp = (v) => Math.max(MAP_LIST_MIN, Math.min(MAP_LIST_MAX, Number(v) || 280));
    const setWidth = (w, persist = true) => {
      const next = clamp(w);
      shell.style.setProperty('--map-list-width', `${next}px`);
      resizer.setAttribute('aria-valuenow', String(next));
      if (persist) {
        try { window.localStorage.setItem(MAP_LIST_WIDTH_KEY, String(next)); } catch (_) {}
      }
    };
    try {
      const stored = window.localStorage.getItem(MAP_LIST_WIDTH_KEY);
      if (stored) setWidth(stored, false);
    } catch (_) {}
    resizer.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      resizer.setPointerCapture(e.pointerId);
      shell.classList.add('is-list-resizing');
    });
    resizer.addEventListener('pointermove', (e) => {
      if (!resizer.hasPointerCapture(e.pointerId)) return;
      const rect = shell.getBoundingClientRect();
      setWidth(e.clientX - rect.left);
    });
    resizer.addEventListener('pointerup', (e) => {
      if (resizer.hasPointerCapture(e.pointerId)) resizer.releasePointerCapture(e.pointerId);
      shell.classList.remove('is-list-resizing');
    });
    resizer.addEventListener('pointercancel', () => shell.classList.remove('is-list-resizing'));
    resizer.addEventListener('lostpointercapture', () => shell.classList.remove('is-list-resizing'));
    resizer.addEventListener('keydown', (e) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault();
      const cur = Number(resizer.getAttribute('aria-valuenow')) || 280;
      if (e.key === 'Home') setWidth(MAP_LIST_MIN);
      else if (e.key === 'End') setWidth(MAP_LIST_MAX);
      else setWidth(cur + (e.key === 'ArrowRight' ? 24 : -24));
    });
  }

  destroy() {
    this._mounted = false;
    this._stopPolling();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    this._confirmBanner?.destroy();
    this._confirmBanner = null;
    this._authoringToolbar?.destroy();
    this._authoringToolbar = null;
    this._basemapPanel?.destroy();
    this._basemapPanel = null;
    if (this._sketchSessionUnsub) {
      this._sketchSessionUnsub();
      this._sketchSessionUnsub = null;
    }
    this._sketchSession = null;
    this._sceneSketchLayer?.remove();
    this._sceneSketchLayer = null;
    this._scenePlanningLayer?.remove();
    this._scenePlanningLayer = null;
    this._vehicleLayer?.disconnect();
    this._vehicleLayer = null;
    this._terrainLayer?.remove();
    this._terrainLayer = null;
    this._sceneObjectsLayer?.remove();
    this._sceneObjectsLayer = null;
    this._gridLayer?.remove();
    this._gridLayer = null;
    this._replayPathLayer?.remove();
    this._replayPathLayer = null;
    this._overlayCacheByMissionId.clear();
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
    this._basemapPanel?.invalidateSize();
  }

  getLeafletMap() {
    return this._map;
  }

  setSessionId(sessionId) {
    const nextSessionId = sessionId || '';
    if (nextSessionId !== this._sessionId) {
      this._sessionId = nextSessionId;
      if (this._sessionPillEl) this._sessionPillEl.textContent = this._sessionId || 'No session';
      this._overlayCacheByMissionId.clear();
      this._missions = [];
      this._missionsById = new Map();
      this._visibleMissionOrder = [];
      this._focusedMissionId = '';
      this._selectedMissionIds = new Set();
      this._selectionAnchorId = '';
      this._seenMissionIds = null;
      this._executionState = null;
      // A new session owns a fresh execution; drop any banner from the old one.
      this._confirmBanner?.hide();
    }
    this._pollExecutionState().catch(() => {});
    this.refresh();
  }

  /**
   * Push a static replay track onto this map (R5a).
   * Each point is {@link ReplayPathPoint}-shaped: `position` (scene metres x/y)
   * takes precedence; `gps` is converted via `georefOrigin` when scene coords are
   * absent. Points with neither usable source are skipped (GPS-only sessions
   * without an origin produce an empty track by design).
   *
   * @param {{ position: {x:number,y:number,z:number}|null, gps: {lat:number,lon:number}|null }[]} points
   * @param {{ lat: number, lon: number } | null} georefOrigin
   */
  setReplayPath(points, georefOrigin = null) {
    this.setReplayTracks([{ points, georefOrigin, color: '#3b82f6', visible: true }]);
  }

  /**
   * Render multiple session tracks at once (R8 — multi-session per map). Each
   * track is `{ points, color?, visible?, georefOrigin? }`; points share the
   * `setReplayPath` shape (scene-metres primary, GPS fallback via georefOrigin).
   * Replaces whatever was drawn before. The global `_replayTrackVisible` toggle
   * and the per-track `visible` flag both gate a track.
   */
  setReplayTracks(tracks = []) {
    if (!this._map) return;
    this._clearReplayPathLayer();

    const layer = L.layerGroup();
    let drew = false;
    for (const track of tracks) {
      if (track.visible === false) continue;
      const latlngs = this._replayPointsToLatLngs(track.points || [], track.georefOrigin || null);
      if (!latlngs.length) continue;
      L.polyline(latlngs, {
        color: track.color || '#3b82f6',
        weight: 2.5,
        opacity: 0.85,
      }).addTo(layer);
      drew = true;
    }

    if (!drew) return;
    this._replayPathLayer = layer;
    if (this._replayTrackVisible) layer.addTo(this._map);
  }

  _replayPointsToLatLngs(points, georefOrigin = null) {
    const METRES_PER_DEG = 111320.0;
    const latlngs = [];
    for (const pt of points) {
      if (pt.position) {
        latlngs.push([pt.position.y, pt.position.x]);
      } else if (pt.gps && georefOrigin) {
        const cosLat = Math.cos(georefOrigin.lat * Math.PI / 180);
        const sceneX = (pt.gps.lon - georefOrigin.lon) * METRES_PER_DEG * cosLat;
        const sceneY = (pt.gps.lat - georefOrigin.lat) * METRES_PER_DEG;
        latlngs.push([sceneY, sceneX]);
      }
    }
    return latlngs;
  }

  clearReplayPath() {
    this._clearReplayPathLayer();
  }

  /**
   * Move the current-frame marker to the point at `index` in the path array.
   * Points use the same shape as `setReplayPath` (scene-metres primary, GPS
   * fallback deferred until georef origin is wired).
   */
  setReplayFrame(index, points) {
    if (!this._map || !points?.length) return;
    const safeIndex = Math.max(0, Math.min(index, points.length - 1));
    const pt = points[safeIndex];
    let latlng = null;
    if (pt.position) {
      latlng = [pt.position.y, pt.position.x];
    }
    if (!latlng) {
      this.clearReplayFrame();
      return;
    }
    if (!this._replayFrameMarker) {
      this._replayFrameMarker = L.circleMarker(latlng, {
        radius: 7,
        color: '#ffffff',
        fillColor: '#3b82f6',
        fillOpacity: 1,
        weight: 2,
        className: 'current-frame-icon',
      }).addTo(this._map);
    } else {
      this._replayFrameMarker.setLatLng(latlng);
    }
    this._replayFrameMarker.bringToFront();
  }

  clearReplayFrame() {
    if (this._replayFrameMarker) {
      this._replayFrameMarker.remove();
      this._replayFrameMarker = null;
    }
  }

  setReplayTrackVisible(visible) {
    this._replayTrackVisible = visible;
    if (this._replayPathLayer) {
      if (visible) this._replayPathLayer.addTo(this._map);
      else this._replayPathLayer.remove();
    }
  }

  setLiveRoverVisible(visible) {
    this._liveRoverVisible = visible;
    this._vehicleLayer?.setVisible(visible);
  }

  _clearReplayPathLayer() {
    if (this._replayPathLayer) {
      this._replayPathLayer.remove();
      this._replayPathLayer = null;
    }
    this.clearReplayFrame();
  }

  async refresh() {
    if (!this._map) return;
    await Promise.all([this._loadVehicleProfiles(), this._loadControllerState()]);
    const missionsPayload = await listMissions({ limit: 200 });
    if (!missionsPayload.ok) {
      this._pushStatus(missionsPayload.error || 'fetch failed', 'error');
      this._overlayLayer.clear();
      this._listPanel.renderMissions();
      this._showEmpty(true);
      return;
    }

    // Hydrate persisted per-mission colour overrides from the server before
    // assigning palette colours so a saved colour survives reloads / other clients.
    missionColorOverrides.seedFromServer(missionsPayload.missions || []);
    this._missions = mapMissionsForList(missionsPayload.missions || []);
    this._missionsById = new Map(this._missions.map((m) => [m.id, m]));
    this._syncVisibilityState(this._missions);
    await this._primeVisibleOverlays();
    this._render();
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
      console.warn('MapWidget: vehicle profiles unavailable; rows show an unknown-vehicle glyph');
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
      if (document.visibilityState !== 'hidden') {
        // The confirm banner must keep polling even mid-edit so an armed run's
        // window is never hidden; the overlay refresh still defers to edits.
        this._pollExecutionState().catch(() => {});
        if (!editState.revisionId && !this._colorPicker?.isOpen()) {
          this.refresh().catch(() => {});
        }
      }
      this._pollTimer = setTimeout(tick, 5000);
    };
    this._pollTimer = setTimeout(tick, 5000);
  }

  async _pollExecutionState() {
    if (!this._confirmBanner) return;
    if (!this._sessionId) {
      this._executionState = null;
      this._confirmBanner.hide();
      return;
    }
    const result = await getExecutionState(this._sessionId);
    if (!result.ok) return;
    const nextState = result.execution || null;
    const previousKey = `${this._executionState?.mission_id || ''}:${this._executionState?.status || ''}`;
    const nextKey = `${nextState?.mission_id || ''}:${nextState?.status || ''}`;
    this._executionState = nextState;
    this._confirmBanner.show(nextState);
    if (previousKey !== nextKey && this._missions.length) {
      this._render();
    }
  }

  async _handleConfirmExecution() {
    const result = await confirmExecution(this._sessionId);
    if (!result.ok) this._pushStatus(result.error || 'Could not start mission.', 'error');
    this._confirmBanner.hide();
    this._pollExecutionState().catch(() => {});
  }

  async _handleCancelExecution() {
    await cancelExecution(this._sessionId);
    this._confirmBanner.hide();
    this._pollExecutionState().catch(() => {});
  }

  _stopPolling() {
    if (this._pollTimer !== null) {
      clearTimeout(this._pollTimer);
      this._pollTimer = null;
    }
  }

  _deleteGuardedMissionIds() {
    const missionId = String(this._executionState?.mission_id || '');
    const status = String(this._executionState?.status || '');
    if (!missionId || !new Set(['armed', 'awaiting_confirm', 'running']).has(status)) {
      return new Set();
    }
    return new Set([missionId]);
  }

  _isMissionDeleteBlocked(missionId) {
    const id = String(missionId || '');
    if (!id) return false;
    if (this._deleteGuardedMissionIds().has(id)) return true;
    return String(this._missionsById.get(id)?.activeRevisionStatus || '') === 'executing';
  }

  // Resolve a flat Mission to its active revision id (overlay/edit/execute
  // target). Empty when the Mission has no bridged active revision yet.
  _activeRevisionIdFor(missionId) {
    return String(this._missionsById.get(String(missionId || ''))?.activeRevisionId || '');
  }

  async _handleExecuteRequest(missionId) {
    if (this._actionBusy || !missionId) return;
    const revisionId = this._activeRevisionIdFor(missionId);
    if (!revisionId) { this._pushStatus('Mission has no executable revision yet.', 'error'); return; }
    const confirmed = await this._showConfirmModal(revisionId);
    if (!confirmed) return;
    this._actionBusy = true;
    const missionName = this._missionsById.get(String(missionId))?.name || missionId;
    const result = await executeMission(revisionId, { expectedControllerVersion: this._controllerVersion });
    this._actionBusy = false;
    if (!result.ok) {
      if (result.status === 'stale_revision') {
        await this._recoverFromStaleExecution(result, revisionId);
        return;
      }
      if (result.status === 'stale_controller_version') {
        await this._recoverFromStaleControllerVersion(result, revisionId);
        return;
      }
      this._pushStatus(`Execute failed — ${result.error || 'unknown error'}`, 'error');
      return;
    }
    this._pushStatus(`Mission "${missionName}" executing`);
    this._overlayCacheByMissionId.clear();
    await this.refresh();
  }

  // --- Mission playback controls (B.3) ---

  async _handleMissionPause(missionId) {
    if (!missionId) return;
    const missionName = this._missionsById.get(String(missionId))?.name || missionId;
    const result = await pauseMission(missionId);
    if (!result.ok) {
      this._pushStatus(`Pause failed — ${result.error || 'unknown error'}`, 'error');
      return;
    }
    this._pushStatus(`Mission "${missionName}" paused`);
    await this.refresh();
  }

  async _handleMissionResume(missionId) {
    if (!missionId) return;
    const missionName = this._missionsById.get(String(missionId))?.name || missionId;
    const result = await resumeMission(missionId);
    if (!result.ok) {
      this._pushStatus(`Resume failed — ${result.error || 'unknown error'}`, 'error');
      return;
    }
    this._pushStatus(`Mission "${missionName}" resumed`);
    await this.refresh();
  }

  async _handleMissionStop(missionId) {
    if (!missionId) return;
    const missionName = this._missionsById.get(String(missionId))?.name || missionId;
    const result = await stopMission(missionId);
    if (!result.ok) {
      this._pushStatus(`Stop failed — ${result.error || 'unknown error'}`, 'error');
      return;
    }
    this._pushStatus(`Mission "${missionName}" stopped`);
    await this.refresh();
  }

  _pushStatus(text, level = 'info') {
    this._statusBar?.push(text, level);
  }

  // --- New mission ---

  async _handleNewMission() {
    if (this._actionBusy) return;
    this._actionBusy = true;
    const result = await createMission({ name: 'New mission' });
    this._actionBusy = false;
    if (!result.ok) {
      this._pushStatus(result.error || 'Could not create mission', 'error');
      return;
    }
    const missionId = result.mission_id;
    // Refresh so _syncVisibilityState auto-promotes the new mission to Active+Visible.
    this._overlayCacheByMissionId.clear();
    await this.refresh();
    await this._ensureMissionHasColor(missionId);
    await this._onEditRequested(missionId);
  }

  // --- Mission CRUD ---

  async _handleDeleteMission(missionId, { skipConfirm = false } = {}) {
    if (this._actionBusy) return;
    const id = String(missionId || '').trim();
    if (!id) return;
    if (this._isMissionDeleteBlocked(id)) {
      this._pushStatus('Mission cannot be deleted while armed, awaiting confirmation, or executing.', 'error');
      return;
    }
    if (!skipConfirm) {
      const mission = this._missions?.find((m) => String(m.id || '') === id);
      const label = mission?.name ? `"${mission.name}"` : 'this mission';
      if (!confirm(`Delete ${label}? This cannot be undone.`)) return;
    }
    this._actionBusy = true;
    const result = await deleteMission(id);
    this._actionBusy = false;
    if (!result.ok) {
      this._pushStatus(result.error || 'Could not delete mission', 'error');
      return;
    }
    // Clean up local state for the removed Mission.
    this._overlayCacheByMissionId.delete(id);
    this._visibleMissionOrder = this._visibleMissionOrder.filter((x) => x !== id);
    this._selectedMissionIds.delete(id);
    if (this._focusedMissionId === id) this._focusedMissionId = this._visibleMissionOrder[0] || '';
    if (this._editingMissionId === id) {
      editState.clearEdit();
      this._editingMissionId = '';
    }
    await this.refresh();
  }

  async _handleDeleteSelectedMissions() {
    const ids = [...this._selectedMissionIds];
    if (ids.some((id) => this._isMissionDeleteBlocked(id))) {
      this._pushStatus('Selection includes a mission that is armed, awaiting confirmation, or executing.', 'error');
      return;
    }
    const count = ids.length;
    if (!confirm(`Delete ${count} selected mission${count === 1 ? '' : 's'}? This cannot be undone.`)) return;
    for (const id of ids) {
      await this._handleDeleteMission(id, { skipConfirm: true });
    }
  }

  async _handleRenameMission(missionId, name) {
    const id = String(missionId || '').trim();
    if (!id || !name) return;
    const result = await renameMission(id, name);
    if (!result.ok) {
      this._pushStatus(result.error || 'Could not rename mission', 'error');
      return;
    }
    // Update the in-memory list entry so the sidebar re-renders without a full refresh.
    const mission = this._missionsById.get(id);
    if (mission) mission.name = name;
    this._render();
  }

  // --- Edit flow ---

  // Edit resolves the Mission to its active revision, then edits that revision.
  // The edit internals below stay revision-keyed (editState); _editingMissionId
  // ties the edited revision back to its Mission for overlay/palette/focus.
  async _onEditRequested(missionId) {
    const revisionId = this._activeRevisionIdFor(missionId);
    if (!revisionId) { this._pushStatus('Mission has no editable revision yet.', 'error'); return; }
    this._editingMissionId = String(missionId || '');
    const rawResult = await getRevision(revisionId);
    if (!rawResult.ok) {
      this._pushStatus(rawResult.error || 'Could not load revision for editing', 'error');
      return;
    }
    // rawResult has revision fields spread at the top level (normalized in missionMutationApi).
    let revisionToEdit = rawResult;

    if (LOCKED_STATUSES.has(String(rawResult.status || ''))) {
      // Fork: create a new proposed successor so the original stays intact.
      const waypoints = collectEditableWaypoints(rawResult.mission || {});
      const forkResult = await createClientRevision({
        operation_id: rawResult.operation_id,
        waypoints,
        label: `Edit of …${String(revisionId).slice(-6)}`,
        from_revision_id: revisionId,
      });
      if (!forkResult.ok) {
        this._pushStatus(forkResult.error || 'Could not fork revision for editing', 'error');
        return;
      }
      revisionToEdit = forkResult.revision;
      this._overlayCacheByMissionId.clear();
      await this.refresh();
    }

    this._pinMissionInView(this._editingMissionId);
    editState.beginEdit(revisionToEdit);
    this.setFocus(this._editingMissionId);
    if (editState.waypoints.length <= 1) {
      if (editState.editMode !== 'add') editState.setEditMode('add');
    } else {
      this._hintToasts?.show('Press A to add waypoints · V for vertex edit', { duration: 4000 });
    }
    this._render(); // drop edited mission from renderMany
  }

  async _handleDragEnd(idx, newPoint, preDragLatLng, marker) {
    if (!editState.isEditable()) return;
    editState.setBusy(true);
    const result = await updateWaypoint(editState.revisionId, idx + 1, {
      point: newPoint,
      expected_version: editState.clientVersion,
    });
    if (result.ok) {
      editState.beginEdit(result.revision);
    } else {
      // Snap the marker back to its pre-drag position.
      if (preDragLatLng && marker) marker.setLatLng(preDragLatLng);
      editState.setBusy(false);
      if (result.status === 'version_conflict') {
        this._pushStatus('Edit conflict — refreshing.', 'error');
        const fresh = await getRevision(editState.revisionId);
        if (fresh.ok) editState.beginEdit(fresh);
      } else if (result.status === 'revision_locked') {
        this._pushStatus('This revision is locked. Use the Edit button to create an editable copy.', 'error');
      } else {
        this._pushStatus(result.error || 'Waypoint update failed', 'error');
      }
    }
  }

  // afterIndex is the 1-based API after_index value (0 = prepend, N = insert after N-th waypoint).
  async _handleGhostClick(afterIndex, point) {
    if (!editState.isEditable()) return;
    editState.setBusy(true);
    const result = await insertWaypoint(editState.revisionId, {
      point,
      expected_version: editState.clientVersion,
      after_index: afterIndex,
    });
    if (result.ok) {
      editState.beginEdit(result.revision);
    } else {
      editState.setBusy(false);
      this._pushStatus(result.error || 'Insert failed', 'error');
    }
  }

  async _handleDeleteSelected() {
    if (!editState.isEditable()) return;
    const sortedIndices = [...editState.selectedIndices].sort((a, b) => b - a); // descending
    if (!sortedIndices.length) return;
    editState.setBusy(true);
    let prevRevision = null;
    for (const idx of sortedIndices) {
      const revId = prevRevision ? prevRevision.id : editState.revisionId;
      const version = prevRevision ? prevRevision.client_version : editState.clientVersion;
      const result = await deleteWaypoint(revId, idx + 1, version);
      if (!result.ok) {
        editState.setBusy(false);
        this._pushStatus(result.error || 'Delete failed', 'error');
        if (prevRevision) editState.beginEdit(prevRevision);
        return;
      }
      prevRevision = result.revision;
    }
    if (prevRevision) editState.beginEdit(prevRevision);
  }

  async _handleBulkSetAltitude(z) {
    if (!editState.isEditable()) return;
    const sortedIndices = [...editState.selectedIndices].sort((a, b) => a - b);
    if (!sortedIndices.length) return;
    editState.setBusy(true);
    let prevRevision = null;
    for (const idx of sortedIndices) {
      const revId = prevRevision ? prevRevision.id : editState.revisionId;
      const version = prevRevision ? prevRevision.client_version : editState.clientVersion;
      const wp = editState.waypoints[idx];
      if (!wp) continue;
      const result = await updateWaypoint(revId, idx + 1, {
        point: { x: wp.x, y: wp.y, z },
        expected_version: version,
      });
      if (!result.ok) {
        editState.setBusy(false);
        this._pushStatus(result.error || 'Altitude update failed', 'error');
        if (prevRevision) editState.beginEdit(prevRevision);
        return;
      }
      prevRevision = result.revision;
    }
    if (prevRevision) editState.beginEdit(prevRevision);
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
    if (!snapshot.revisionId) {
      this._editingMissionId = '';
      this._overlayLayer.clearEditable();
      this._selectionPanel.hide();
      this._bulkActionBar?.hide();
      this._editBanner.hidden = true;
      this._mapEl.classList.remove('is-edit-mode', 'is-locked');
      this._updateInfoBarSelection(null);
      this._updateElevationProfile();
      this._syncAuthoringToolbarState();
      return;
    }

    const isLocked = snapshot.status === 'executing';
    this._mapEl.classList.toggle('is-locked', isLocked);
    this._mapEl.classList.toggle('is-edit-mode', snapshot.editMode === 'add');

    this._editBanner.hidden = false;
    const modeLabel = snapshot.editMode === 'vertex' ? ' · vertex edit' : snapshot.editMode === 'add' ? ' · add mode' : ' · A: add  V: vertex';
    this._editBannerText.textContent =
      `Editing — ${snapshot.status} · rev …${snapshot.revisionId.slice(-8)}${modeLabel}${snapshot.busy ? ' (saving…)' : ''}`;

    if (snapshot.selectedIndices.size === 1) {
      const idx = [...snapshot.selectedIndices][0];
      const wp = snapshot.waypoints[idx];
      if (wp) this._selectionPanel.show(wp, idx);
      else this._selectionPanel.hide();
    } else {
      this._selectionPanel.hide();
    }

    this._updateInfoBarSelection(snapshot);
    this._bulkActionBar?.update(snapshot.selectedIndices, snapshot.waypoints, editState.isEditable());

    const color = this._paletteByMissionId.get(this._editingMissionId) || '#4a90d9';
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
    this._syncAuthoringToolbarState();
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
      if (editState.revisionId) {
        editState.clearEdit();
        this._overlayCacheByMissionId.clear();
        this.refresh();
      }
      return;
    }

    if (!editState.revisionId) return;

    if (key === 'f' || key === 'F') { e.preventDefault(); this.setFocus(this._editingMissionId); return; }
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

  _showConfirmModal(revisionId) {
    return new Promise((resolve) => {
      this._confirmResolve = resolve;
      const modal = this._confirmModal;
      if (!modal) { resolve(false); return; }
      modal.querySelector('.map-confirm-revision-id').textContent = String(revisionId).slice(-8);
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

  // --- Visibility / focus ---

  // A Mission is "executing" (locked-visible) when its active revision is.
  _executingMissionIds(missions = this._missions) {
    return missions
      .filter((m) => String(m.activeRevisionStatus || '') === 'executing')
      .map((m) => m.id);
  }

  _syncVisibilityState(missions) {
    const knownMissionIds = new Set(missions.map((m) => m.id));
    this._visibleMissionOrder = this._visibleMissionOrder.filter((id) => knownMissionIds.has(id));
    this._selectedMissionIds = new Set([...this._selectedMissionIds].filter((id) => knownMissionIds.has(id)));
    if (this._selectionAnchorId && !knownMissionIds.has(this._selectionAnchorId)) {
      this._selectionAnchorId = '';
    }
    if (this._focusedMissionId && !knownMissionIds.has(this._focusedMissionId)) {
      this._focusedMissionId = '';
    }

    const executingIds = this._executingMissionIds(missions);

    if (this._seenMissionIds === null) {
      // First sync: default all missions to visible and focus the first.
      if (!this._visibleMissionOrder.length) {
        this._visibleMissionOrder = missions.map((m) => m.id).filter(Boolean);
        this._focusedMissionId = this._visibleMissionOrder[0] || '';
      }
    } else {
      // Smart binding (ADR 0021 §4): a newly-created Mission becomes Active and
      // Visible (but not Selected). Detect ids absent from the previous sync.
      const newIds = missions.map((m) => m.id).filter((id) => id && !this._seenMissionIds.has(id));
      if (newIds.length) {
        const newest = newIds[newIds.length - 1];
        for (const id of newIds) {
          if (!this._visibleMissionOrder.includes(id)) this._visibleMissionOrder.push(id);
        }
        // Ensure executing missions are always visible.
        for (const id of executingIds) {
          if (!this._visibleMissionOrder.includes(id)) this._visibleMissionOrder.push(id);
        }
        this._focusedMissionId = newest;
      }
    }

    // Invariant: the Active Mission must be Visible.
    if (this._focusedMissionId && !this._visibleMissionOrder.includes(this._focusedMissionId)) {
      this._focusedMissionId = this._visibleMissionOrder[0] || '';
    }

    this._seenMissionIds = knownMissionIds;
  }

  async _primeVisibleOverlays() {
    const loads = this._visibleMissionOrder.map(async (missionId) => {
      if (this._overlayCacheByMissionId.has(missionId)) return;
      const payload = await getMissionOverlay(missionId);
      if (payload.ok) {
        this._overlayCacheByMissionId.set(missionId, payload);
      }
    });
    await Promise.all(loads);

    if (!this._overlayCacheByMissionId.size && this._sessionId && this._focusedMissionId) {
      const payload = await getCurrentOverlay(this._sessionId);
      if (payload.ok && payload.available) {
        this._overlayCacheByMissionId.set(this._focusedMissionId, payload);
      }
    }
  }

  _render() {
    const editedMissionId = this._editingMissionId;
    const visibleMissionIds = new Set(this._visibleMissionOrder);
    const deleteGuardedMissionIds = this._deleteGuardedMissionIds();
    const paletteByMissionId = assignPaletteColor(this._missions, missionColorOverrides.getAll());
    this._paletteByMissionId = paletteByMissionId;

    const currentSortId = missionSortPreference.get();
    const sortedMissions = sortMissions(
      this._missions,
      currentSortId,
      { selectedMissionIds: this._selectedMissionIds, visibleMissionIds },
    );
    const sortLabel = currentSortId !== 'updated_desc'
      ? (SORT_OPTIONS.find((o) => o.id === currentSortId)?.label ?? '') : '';

    this._listPanel.renderMissions({
      missions: sortedMissions,
      focusedMissionId: this._focusedMissionId,
      visibleMissionIds,
      selectedMissionIds: this._selectedMissionIds,
      paletteByMissionId,
      editingMissionId: this._editingMissionId,
      profilesById: this._profilesById,
      activeProfileId: this._activeProfileId,
      deleteGuardedMissionIds,
      sortLabel,
    });

    // Exclude the actively-edited Mission from the read-only overlay so only
    // the editable layer shows it.
    const overlays = this._visibleMissionOrder
      .filter((missionId) => missionId !== editedMissionId)
      .map((missionId) => {
        const payload = this._overlayCacheByMissionId.get(missionId);
        if (!payload?.available) return null;
        return {
          revisionId: missionId,
          payload,
          color: paletteByMissionId.get(missionId),
          opacity: opacityForMission(missionId, this._focusedMissionId),
        };
      })
      .filter(Boolean);

    this._overlayLayer.renderMany(overlays);
    const focusedPayload = this._focusedMissionId ? this._overlayCacheByMissionId.get(this._focusedMissionId) : null;
    // Render persisted geofence + constraints on scene views; basemap mode has its own layers.
    if (this._currentViewMode !== 'basemap') {
      this._overlayLayer.renderGeofence(focusedPayload?.geofence ?? null, focusedPayload?.origin ?? null);
      this._renderSceneConstraints();
    } else {
      this._scenePlanningLayer?.clearLayers();
    }
    const unionBounds = boundsUnion(overlays.map((entry) => entry.payload.bounds));
    // Only refit when the logical target changes; skip on every poll tick so the
    // user can freely pan/zoom without the view snapping back every 5 seconds.
    // Derive fitTarget and fitKey from the SAME winning source so they can't
    // diverge: if the focused mission's payload hasn't loaded yet (e.g. it arrives
    // via the 5s poll rather than the awaited setFocus path), we fall through to
    // union/scene for BOTH — otherwise fitKey would lock to the mission id while
    // fitTarget used scene bounds, and the later payload load wouldn't trigger a refit.
    let fitTarget = null;
    let fitKey = null;
    if (focusedPayload?.bounds) {
      fitTarget = focusedPayload.bounds;
      fitKey = this._focusedMissionId;
    } else if (unionBounds) {
      fitTarget = unionBounds;
      fitKey = this._visibleMissionOrder.join(',');
    } else if (this._sceneBounds) {
      fitTarget = this._sceneBounds;
      fitKey = 'scene';
    }
    if (fitKey && fitKey !== this._lastFitKey) {
      this._lastFitKey = fitKey;
      if (!this._skipAutoFitOnce) {
        this._fitBounds(fitTarget);
      }
    }
    this._skipAutoFitOnce = false;
    // The empty state covers the whole canvas, so skip it when the scene is
    // loaded — terrain + objects IS the content even with no missions drawn yet.
    this._updateFitButtons();
    this._showEmpty(!overlays.length && !editedMissionId && !this._sceneBounds);
    this._updateElevationProfile();
    if (this._basemapPanel?.visible) this._basemapPanel.render(focusedPayload);
    this._syncAuthoringToolbarState();
  }

  _onLayerToggle(key, visible) {
    switch (key) {
      case 'terrain': this._terrainLayer?.setVisible(visible); break;
      case 'roads':   this._sceneObjectsLayer?.setRoadsVisible(visible); break;
      case 'objects': this._sceneObjectsLayer?.setObjectsVisible(visible); break;
      case 'grid':    this._gridLayer?.setVisible(visible); break;
    }
  }

  _applyViewMode(mode) {
    this._currentViewMode = mode || 'virtual_terrain';
    const configs = {
      virtual_terrain:  { terrain: true,  roads: true,  objects: true,  grid: true  },
      cad:              { terrain: false, roads: true,  objects: true,  grid: true  },
      heightmap:        { terrain: true,  roads: false, objects: false, grid: false },
      basemap:          { terrain: false, roads: false, objects: false, grid: false },
    };
    const cfg = configs[mode] || configs.virtual_terrain;
    this._terrainLayer?.setVisible(cfg.terrain);
    this._sceneObjectsLayer?.setRoadsVisible(cfg.roads);
    this._sceneObjectsLayer?.setObjectsVisible(cfg.objects);
    this._gridLayer?.setVisible(cfg.grid);
    if (this._layerBar) {
      for (const cb of this._layerBar.querySelectorAll('input[data-layer]')) {
        cb.checked = !!cfg[cb.dataset.layer];
      }
    }
    this._setBasemapVisible(mode === 'basemap');
    this._syncAuthoringToolbarState();
    // Load constraints whenever entering a scene view so the planning layer renders
    // without waiting for the user to open the Constraints panel or the basemap.
    if (mode !== 'basemap') this._refreshConstraints().catch(() => {});
  }

  _handleFitClick(key) {
    let bounds = null;
    if (key === 'scene') {
      bounds = this._sceneBounds;
    } else if (key === 'mission') {
      const payload = this._focusedMissionId
        ? this._overlayCacheByMissionId.get(this._focusedMissionId)
        : null;
      bounds = payload?.bounds || null;
    } else if (key === 'all') {
      const allBounds = [...this._overlayCacheByMissionId.values()].map((p) => p?.bounds).filter(Boolean);
      bounds = boundsUnion([...allBounds, this._sceneBounds]);
    }
    if (!bounds) return;
    this._lastFitKey = null;
    this._fitBounds(bounds);
  }

  _updateFitButtons() {
    if (!this._fitBtns) return;
    const focusedPayload = this._focusedMissionId
      ? this._overlayCacheByMissionId.get(this._focusedMissionId)
      : null;
    this._fitBtns.scene.disabled = !this._sceneBounds;
    this._fitBtns.mission.disabled = !focusedPayload?.bounds;
    this._fitBtns.all.disabled = !this._sceneBounds && !this._overlayCacheByMissionId.size;
  }

  // Real 2D WGS84 basemap render mode (Phase 4): the basemap is a VIEW option,
  // not an independent toggle. Swapping views must not disturb mission focus,
  // visibility, or edit state.
  _setBasemapVisible(visible) {
    if (!this._basemapPanel) return;
    if (visible === this._basemapPanel.visible) {
      if (visible) {
        const focusedPayload = this._focusedMissionId
          ? this._overlayCacheByMissionId.get(this._focusedMissionId)
          : null;
        this._basemapPanel.render(focusedPayload);
      }
      return;
    }
    if (visible) {
      this._basemapPanel.show();
      const focusedPayload = this._focusedMissionId
        ? this._overlayCacheByMissionId.get(this._focusedMissionId)
        : null;
      this._basemapPanel.render(focusedPayload);
      // Operational constraints are deployment-wide; load and render them
      // whenever the basemap (their authoring/render surface) opens.
      this._refreshConstraints().catch(() => {});
      return;
    }
    this._basemapPanel.hide();
    this._constraintsPanel?.hide();
  }

  _syncAuthoringToolbarState() {
    if (!this._authoringToolbar || !this._sketchSession) return;
    const onBasemapView = this._currentViewMode === 'basemap';
    const hasEditableRevision = !!editState.revisionId && editState.isEditable();
    const hasOrigin = !!this._focusedOrigin();
    const canDraw = onBasemapView || hasOrigin;
    const noOriginReason = 'Focus a mission to enable GPS-based drawing on this view.';
    const geofenceReason = canDraw
      ? (this._focusedMissionId ? 'Edit the geofence for the focused mission.' : 'Focus a mission to edit its geofence.')
      : noOriginReason;
    const sketchState = this._sketchSession.getState();
    this._authoringToolbar.updateState({
      addWaypointEnabled: hasEditableRevision,
      addWaypointActive: editState.editMode === 'add',
      addWaypointReason: editState.revisionId
        ? 'The current revision is locked or busy.'
        : 'Open a mission in edit mode to add waypoints.',
      drawToolsEnabled: canDraw,
      drawToolsReason: noOriginReason,
      geofenceEnabled: canDraw && !!this._focusedMissionId,
      geofenceReason,
      constraintToolsEnabled: canDraw,
      constraintToolsReason: noOriginReason,
      ...sketchState,
    });
    if (!onBasemapView) {
      this._map.getContainer().style.cursor = sketchState.drawMode ? 'crosshair' : '';
    }
    this._refreshSceneSketch();
  }

  _refreshSceneSketch() {
    if (!this._sceneSketchLayer) return;
    this._sceneSketchLayer.clearLayers();
    if (this._currentViewMode === 'basemap') return;
    const origin = this._focusedOrigin();
    if (!origin || !this._sketchSession?.isDirty) return;

    const METRES_PER_DEG = 111320.0;
    const cosLat = Math.cos(origin.lat * Math.PI / 180);
    const toScene = ({ lat, lon }) => L.latLng(
      (lat - origin.lat) * METRES_PER_DEG,
      (lon - origin.lon) * METRES_PER_DEG * cosLat,
    );

    const tool = this._sketchSession.tool;
    const vertices = this._sketchSession.vertices;
    if (!tool || vertices.length === 0) return;

    const pts = vertices.map(toScene);
    const isFence = tool === 'fence';
    const isConstraint = tool === 'constraint';
    const stroke = isConstraint
      ? (this._sketchSession.constraintMeta?.kind === 'blockage' ? '#e67e22' : '#2e8b57')
      : (isFence ? '#2e8b57' : '#d9534f');

    if ((isFence || isConstraint) && pts.length >= 2) {
      L.polygon(pts, { color: stroke, weight: 2, dashArray: '6 4', fillOpacity: 0.1 }).addTo(this._sceneSketchLayer);
    } else if (pts.length >= 2) {
      L.polyline(pts, { color: stroke, weight: 3, dashArray: '6 4' }).addTo(this._sceneSketchLayer);
    }

    for (const v of vertices) {
      L.circleMarker(toScene(v), {
        radius: 5, color: stroke, fillColor: stroke, fillOpacity: 0.85, weight: 2, interactive: false,
      }).addTo(this._sceneSketchLayer);
    }
  }

  _toggleAddWaypointMode() {
    if (!editState.isEditable()) return;
    editState.setEditMode('add');
  }

  // Persist an operator-drawn pattern (corridor/survey) sketched on the basemap
  // as a new Mission, then reload the list so it appears in the sidebar (Phase 4).
  async _handleDrawnPattern({ pattern, points, params }) {
    const result = await createDrawnPattern({
      pattern,
      points,
      params,
      sessionId: this._sessionId,
    });
    if (result.ok) {
      await this.refresh().catch(() => {});
      await this._ensureMissionHasColor(result.mission_id);
    }
    return result;
  }

  async _handleSetGeofence({ polygon = [], clear = false } = {}) {
    if (!this._focusedMissionId) {
      return { ok: false, error: 'Focus a mission first (click it in the list).' };
    }
    const result = await setMissionGeofence(this._focusedMissionId, {
      polygon,
      clear,
      sessionId: this._sessionId,
    });
    if (result.ok) {
      await this.refresh().catch(() => {});
    }
    return result;
  }

  // --- Operational constraints (ADR 0025) -------------------------------------

  // Default operator-visible name for a freshly drawn constraint: "<Kind> N",
  // where N makes it unique among existing same-kind constraints. The panel can
  // rename later; the backend only requires a non-empty name.
  _nextConstraintName() {
    const kind = this._sketchSession?.getState().constraintKind || 'allowed_corridor';
    const label = kind === 'blockage' ? 'Blockage' : 'Allowed corridor';
    const count = this._constraints.filter((c) => c.kind === kind).length;
    return `${label} ${count + 1}`;
  }

  async _refreshConstraints() {
    const res = await listConstraints();
    if (res.ok) {
      this._constraints = res.constraints;
      this._basemapPanel?.renderConstraints(this._constraints);
      this._constraintsPanel?.update(this._constraints);
      if (this._currentViewMode !== 'basemap') this._renderSceneConstraints();
    }
    return res;
  }

  _renderSceneConstraints() {
    if (!this._scenePlanningLayer) return;
    this._scenePlanningLayer.clearLayers();
    const constraints = this._constraints || [];
    if (!constraints.length) return;
    // Use focused mission's origin; fall back to any cached overlay origin.
    let origin = this._focusedOrigin();
    if (!origin) {
      for (const payload of this._overlayCacheByMissionId.values()) {
        if (payload?.origin) { origin = payload.origin; break; }
      }
    }
    if (!origin) return;
    const METRES_PER_DEG = 111320.0;
    const cosLat = Math.cos(origin.lat * Math.PI / 180);
    const toScene = ({ lat, lon }) => L.latLng(
      (lat - origin.lat) * METRES_PER_DEG,
      (lon - origin.lon) * METRES_PER_DEG * cosLat,
    );
    for (const c of constraints) {
      const poly = (Array.isArray(c?.polygon) ? c.polygon : [])
        .filter((v) => Number.isFinite(v?.lat) && Number.isFinite(v?.lon));
      if (poly.length < 3) continue;
      const blockage = c.kind === 'blockage';
      const enabled = c.enabled !== false;
      const color = blockage ? '#e67e22' : '#2e8b57';
      const kindLabel = blockage ? 'Blockage' : 'Allowed corridor';
      const ruleLabel = c.rule === 'soft' ? 'soft' : 'hard';
      L.polygon(poly.map(toScene), {
        color,
        weight: 2,
        opacity: enabled ? 0.9 : 0.4,
        fillColor: color,
        fillOpacity: enabled ? (blockage ? 0.14 : 0.08) : 0.04,
        dashArray: c.rule === 'soft' ? '6 4' : null,
        pane: 'missionPane',
      })
        .bindTooltip(
          `${c.name || kindLabel} · ${kindLabel} · ${ruleLabel}${enabled ? '' : ' · disabled'} (planning)`,
          { direction: 'top', sticky: true },
        )
        .addTo(this._scenePlanningLayer);
    }
  }

  async _openConstraintsPanel() {
    await this._refreshConstraints();
    this._constraintsPanel?.show(this._constraints);
  }

  async _handleCreateConstraint({ kind, rule, name, polygon }) {
    const res = await createConstraint({ kind, rule, name, polygon });
    if (res.ok) {
      this._statusBar?.push(`Saved ${kind === 'blockage' ? 'blockage' : 'allowed corridor'} "${res.constraint?.name || name}" (planning).`, 'info');
      await this._refreshConstraints();
    } else {
      this._statusBar?.push(`Constraint save failed: ${res.error}`, 'error');
    }
    return res;
  }

  async _handleToggleConstraint(constraint) {
    const res = await updateConstraint(constraint.id, {
      expectedVersion: constraint.version,
      enabled: !(constraint.enabled !== false),
    });
    if (res.ok) {
      await this._refreshConstraints();
    } else if (res.status === 409) {
      this._statusBar?.push('Constraint changed elsewhere; refreshed.', 'warn');
      await this._refreshConstraints();
    } else {
      this._statusBar?.push(`Constraint update failed: ${res.error}`, 'error');
    }
    return res;
  }

  async _handleEditConstraint(constraint, patch = {}) {
    const res = await updateConstraint(constraint.id, {
      expectedVersion: constraint.version,
      ...patch,
    });
    if (res.ok) {
      const what = patch.name !== undefined ? 'renamed' : `set ${patch.rule}`;
      this._statusBar?.push(`Constraint "${res.constraint?.name || constraint.name || constraint.kind}" ${what}.`, 'info');
      await this._refreshConstraints();
    } else if (res.status === 409) {
      this._statusBar?.push('Constraint changed elsewhere; refreshed.', 'warn');
      await this._refreshConstraints();
    } else {
      this._statusBar?.push(`Constraint update failed: ${res.error}`, 'error');
    }
    return res;
  }

  async _handleDeleteConstraint(constraint) {
    const res = await deleteConstraint(constraint.id, { expectedVersion: constraint.version });
    if (res.ok) {
      this._statusBar?.push(`Deleted constraint "${constraint.name || constraint.kind}".`, 'info');
      await this._refreshConstraints();
    } else if (res.status === 409) {
      this._statusBar?.push('Constraint changed elsewhere; refreshed.', 'warn');
      await this._refreshConstraints();
    } else {
      this._statusBar?.push(`Constraint delete failed: ${res.error}`, 'error');
    }
    return res;
  }

  _startConstraintShapeEdit(constraint) {
    const polygon = Array.isArray(constraint.polygon) ? constraint.polygon : [];
    if (polygon.length < 3) {
      this._statusBar?.push(`Constraint "${constraint.name || constraint.kind}" has no editable polygon.`, 'warn');
      return;
    }
    this._editingConstraint = constraint;
    this._constraintsPanel?.hide();
    this._sketchSession.startToolWithVertices(
      'constraint',
      { kind: constraint.kind, rule: constraint.rule },
      polygon,
    );
  }

  _focusedOrigin() {
    if (!this._focusedMissionId) return null;
    return this._overlayCacheByMissionId.get(this._focusedMissionId)?.origin || null;
  }

  _onMapMouseMove(e) {
    if (!this._infoBarCoords) return;
    const x = e.latlng.lng;
    const y = e.latlng.lat;
    const xSign = x >= 0 ? '+' : '';
    const ySign = y >= 0 ? '+' : '';
    this._infoBarCoords.textContent = `x ${xSign}${x.toFixed(2)} m  y ${ySign}${y.toFixed(2)} m`;
    if (this._infoBarGround) {
      const groundZ = Number(this._sampleHeight?.(x, y));
      this._infoBarGround.textContent = Number.isFinite(groundZ) ? `ground z ${groundZ.toFixed(2)} m` : '';
    }
    if (this._infoBarGps) {
      const origin = this._focusedOrigin();
      if (origin) {
        const METRES_PER_DEG = 111320.0;
        const lat = origin.lat + y / METRES_PER_DEG;
        const lon = origin.lon + x / (METRES_PER_DEG * Math.cos(origin.lat * Math.PI / 180));
        const latDir = lat >= 0 ? 'N' : 'S';
        const lonDir = lon >= 0 ? 'E' : 'W';
        this._infoBarGps.textContent = `${Math.abs(lat).toFixed(6)}°${latDir}  ${Math.abs(lon).toFixed(6)}°${lonDir}`;
      } else {
        this._infoBarGps.textContent = '';
      }
    }
  }

  _updateInfoBarSelection(snapshot) {
    if (!this._infoBarSel) return;
    if (!snapshot || snapshot.selectedIndices.size !== 1) {
      this._infoBarSel.textContent = '';
      return;
    }
    const idx = [...snapshot.selectedIndices][0];
    const wp = snapshot.waypoints[idx];
    if (!wp) { this._infoBarSel.textContent = ''; return; }
    const PROV = { ai: 'AI', user: 'user', 'ai+edited': 'AI+edited' };
    const prov = PROV[wp.provenance] || (wp.provenance || 'AI');
    this._infoBarSel.textContent = `WP ${idx + 1} · ${prov} · z ${wp.z.toFixed(2)} m`;
  }

  _updateElevationProfile() {
    if (!this._elevationPanel) return;
    // During active edit: show live edit waypoints
    if (editState.revisionId && editState.waypoints.length) {
      const color = this._paletteByMissionId.get(this._editingMissionId) || '#4a90d9';
      const vehicleKind = this._profilesById[this._activeProfileId]?.kind || 'ground';
      this._elevationPanel.update(editState.waypoints, this._sampleHeight, { color, vehicleKind });
      return;
    }
    // Otherwise: show focused Mission
    const payload = this._focusedMissionId ? this._overlayCacheByMissionId.get(this._focusedMissionId) : null;
    if (!payload?.available) { this._elevationPanel.clear(); return; }
    const wps = (payload.features || [])
      .filter((f) => f.type === 'waypoint')
      .sort((a, b) => a.index - b.index)
      .map((f) => ({ ...f.point, index: f.index }));
    if (!wps.length) { this._elevationPanel.clear(); return; }
    const color = this._paletteByMissionId.get(this._focusedMissionId) || '#4a90d9';
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
    if (this._visibleMissionOrder.includes(missionId)) {
      if (this._executingMissionIds().includes(missionId)) return;
      this._visibleMissionOrder = this._visibleMissionOrder.filter((id) => id !== missionId);
      if (this._focusedMissionId === missionId) {
        this._focusedMissionId = this._visibleMissionOrder[0] || '';
      }
      this._skipAutoFitOnce = true;
      this._render();
      return;
    }
    this._visibleMissionOrder.push(missionId);
    if (!this._overlayCacheByMissionId.has(missionId)) {
      const payload = await getMissionOverlay(missionId);
      if (payload.ok) this._overlayCacheByMissionId.set(missionId, payload);
      else this._pushStatus(`Mission overlay unavailable — ${payload.error || 'Overlay fetch failed'}`, 'error');
    }
    if (!this._focusedMissionId) this._focusedMissionId = missionId;
    this._skipAutoFitOnce = true;
    this._render();
  }

  // Make a Mission Active. Smart binding (ADR 0021 §4): clicking a row makes it
  // Active and turns Visible on — so focusing also overlays it (and the
  // "Active must be Visible" invariant holds by construction).
  async setFocus(missionId) {
    const id = missionId || '';
    this._focusedMissionId = id;
    // Force a bounds refit for this focus change even if the key would otherwise
    // match (e.g. refocusing the same mission after the user panned away).
    this._lastFitKey = null;
    if (id && !this._visibleMissionOrder.includes(id)) {
      this._visibleMissionOrder.push(id);
      if (!this._overlayCacheByMissionId.has(id)) {
        const payload = await getMissionOverlay(id);
        if (payload.ok) this._overlayCacheByMissionId.set(id, payload);
        else this._pushStatus(`Mission overlay unavailable — ${payload.error || 'Overlay fetch failed'}`, 'error');
      }
    }
    this._render();
  }

  // --- Selected set / batch operations (ADR 0021 §4) ---

  async _toggleSelection(missionId, { shift = false } = {}) {
    const id = String(missionId || '');
    if (!id) return;
    const order = this._missions.map((m) => m.id);
    if (shift && this._selectionAnchorId) {
      const a = order.indexOf(this._selectionAnchorId);
      const b = order.indexOf(id);
      if (a !== -1 && b !== -1) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        const toFetch = [];
        for (let i = lo; i <= hi; i += 1) {
          const rangeId = order[i];
          this._selectedMissionIds.add(rangeId);
          if (!this._visibleMissionOrder.includes(rangeId)) {
            this._visibleMissionOrder.push(rangeId);
            if (!this._overlayCacheByMissionId.has(rangeId)) toFetch.push(rangeId);
          }
        }
        if (toFetch.length) {
          await Promise.all(toFetch.map(async (rid) => {
            const payload = await getMissionOverlay(rid);
            if (payload.ok) this._overlayCacheByMissionId.set(rid, payload);
          }));
        }
        this._render();
        return;
      }
    }
    const wasSelected = this._selectedMissionIds.has(id);
    if (wasSelected) {
      this._selectedMissionIds.delete(id);
    } else {
      this._selectedMissionIds.add(id);
      // Show on map when selected: explicit operator intent should not evict
      // previously-visible missions behind a "soft" auto-layout cap.
      if (!this._visibleMissionOrder.includes(id)) {
        this._visibleMissionOrder.push(id);
        if (!this._overlayCacheByMissionId.has(id)) {
          const payload = await getMissionOverlay(id);
          if (payload.ok) this._overlayCacheByMissionId.set(id, payload);
          else this._pushStatus(`Mission overlay unavailable — ${payload.error || 'Overlay fetch failed'}`, 'error');
        }
      }
    }
    this._selectionAnchorId = id;
    this._render();
  }

  _clearSelection() {
    if (!this._selectedMissionIds.size) return;
    this._selectedMissionIds = new Set();
    this._selectionAnchorId = '';
    this._render();
  }

  async _showSelectedMissions() {
    for (const id of this._selectedMissionIds) {
      if (!this._visibleMissionOrder.includes(id)) this._visibleMissionOrder.push(id);
    }
    await Promise.all(this._visibleMissionOrder.map(async (id) => {
      if (this._overlayCacheByMissionId.has(id)) return;
      const payload = await getMissionOverlay(id);
      if (payload.ok) this._overlayCacheByMissionId.set(id, payload);
    }));
    if (!this._focusedMissionId) this._focusedMissionId = this._visibleMissionOrder[0] || '';
    this._skipAutoFitOnce = true;
    this._render();
  }

  async _showAllMissions() {
    const missionIds = this._missions.map((mission) => String(mission.id || '')).filter(Boolean);
    for (const id of missionIds) {
      if (!this._visibleMissionOrder.includes(id)) this._visibleMissionOrder.push(id);
    }
    await Promise.all(missionIds.map(async (id) => {
      if (this._overlayCacheByMissionId.has(id)) return;
      const payload = await getMissionOverlay(id);
      if (payload.ok) this._overlayCacheByMissionId.set(id, payload);
    }));
    if (!this._focusedMissionId) this._focusedMissionId = this._visibleMissionOrder[0] || '';
    this._skipAutoFitOnce = true;
    this._render();
  }

  _hideSelectedMissions() {
    const executingIds = new Set(this._executingMissionIds());
    this._visibleMissionOrder = this._visibleMissionOrder.filter(
      (id) => !this._selectedMissionIds.has(id) || executingIds.has(id),
    );
    if (this._focusedMissionId && !this._visibleMissionOrder.includes(this._focusedMissionId)) {
      this._focusedMissionId = this._visibleMissionOrder[0] || '';
    }
    this._skipAutoFitOnce = true;
    this._render();
  }

  _hideAllMissions() {
    const executingIds = new Set(this._executingMissionIds());
    this._visibleMissionOrder = this._visibleMissionOrder.filter((id) => executingIds.has(id));
    if (this._focusedMissionId && !this._visibleMissionOrder.includes(this._focusedMissionId)) {
      this._focusedMissionId = this._visibleMissionOrder[0] || '';
    }
    this._skipAutoFitOnce = true;
    this._render();
  }

  async _selectAllMissions() {
    const nextSelection = new Set(this._missions.map((mission) => String(mission.id || '')).filter(Boolean));
    this._selectedMissionIds = nextSelection;
    this._selectionAnchorId = this._missions.length ? String(this._missions[this._missions.length - 1]?.id || '') : '';
    await this._showAllMissions();
  }

  _pinMissionInView(missionId) {
    const nextMissionId = String(missionId || '').trim();
    if (!nextMissionId) return;
    this._visibleMissionOrder = this._visibleMissionOrder.filter((id) => id !== nextMissionId);
    this._visibleMissionOrder.push(nextMissionId);
    this._focusedMissionId = nextMissionId;
  }

  // Resolve a revision id back to the flat Mission whose active revision it is
  // (used by the recovery flows after a refresh reloads the Mission list).
  _missionIdForRevision(revisionId) {
    const target = String(revisionId || '').trim();
    if (!target) return '';
    const match = this._missions.find((m) => String(m.activeRevisionId || '') === target);
    return match ? match.id : '';
  }

  async _recoverFromStaleExecution(result, requestedRevisionId) {
    const activeRevision = result.active_revision || null;
    const activeRevisionId = String(result.active_revision_id || activeRevision?.id || '').trim();

    this._overlayCacheByMissionId.clear();
    await this.refresh();

    const activeMissionId = this._missionIdForRevision(activeRevisionId);
    if (activeMissionId) {
      this._pinMissionInView(activeMissionId);
      this._render();
      this._pushStatus(
        `Revision …${String(requestedRevisionId).slice(-6)} is stale. Focused active revision …${activeRevisionId.slice(-6)} instead.`,
        'error',
      );
      return;
    }

    this._pushStatus(result.error || 'Execute failed', 'error');
  }

  async _recoverFromStaleControllerVersion(result, requestedRevisionId) {
    const controllerState = result.controller_state || {};
    const latestVersion = controllerState.controller_version ?? null;
    if (latestVersion !== null && latestVersion !== undefined) {
      this._controllerVersion = latestVersion;
    }

    const activeRevisionId = String(controllerState.active_revision_id || '').trim();
    const rebasedRevision = result.rebased_revision || {};
    const rebasedRevisionId = String(rebasedRevision.id || result.rebased_revision_id || '').trim();

    this._overlayCacheByMissionId.clear();
    await this.refresh();

    const requestedSuffix = String(requestedRevisionId).slice(-6);
    const versionText = latestVersion !== null && latestVersion !== undefined ? String(latestVersion) : 'unknown';
    const rebasedMissionId = this._missionIdForRevision(rebasedRevisionId);
    const activeMissionId = this._missionIdForRevision(activeRevisionId);
    if (rebasedMissionId) {
      this._pinMissionInView(rebasedMissionId);
      this._render();
      this._pushStatus(
        `Controller mission version changed to ${versionText}. Created rebased revision …${rebasedRevisionId.slice(-6)} from stale execute on …${requestedSuffix}; review and approve it before retrying.`,
        'error',
      );
      return;
    }
    if (activeMissionId) {
      this._pinMissionInView(activeMissionId);
      this._render();
      this._pushStatus(
        `Controller mission version changed to ${versionText}. Refreshed from stale execute on …${requestedSuffix}; review active revision …${activeRevisionId.slice(-6)} and retry.`,
        'error',
      );
      return;
    }

    this._pushStatus(
      `Controller mission version changed to ${versionText}. Refreshed after stale execute on …${requestedSuffix}; retry when ready.`,
      'error',
    );
  }

  // --- Colour picker ---

  _openColorPicker(missionId, anchorEl) {
    let committedColor = this._paletteByMissionId.get(missionId) || '';
    this._colorPicker.open(anchorEl, {
      currentColor: committedColor,
      onPreview: (previewColor) => {
        const effective = previewColor || committedColor;
        this._paletteByMissionId.set(missionId, effective);
        this._refreshOverlayColors();
        const row = this._listEl.querySelector(`[data-row-mission-id="${missionId}"]`);
        const chip = row?.querySelector('.mission-row-status');
        if (chip) chip.style.setProperty('--mission-color', effective);
      },
      onPick: (color) => {
        missionColorOverrides.set(missionId, color);
        this._render();
        committedColor = color;
        // Persist the override server-side (fire-and-forget; local cache already
        // updated for instant feedback).
        setMissionColor(missionId, color).then((res) => {
          if (!res.ok) console.warn('Failed to persist mission colour:', res.error);
        });
      },
      onReset: () => {
        missionColorOverrides.clear(missionId);
        this._render();
        committedColor = this._paletteByMissionId.get(missionId) || '';
        setMissionColor(missionId, '').then((res) => {
          if (!res.ok) console.warn('Failed to clear mission colour:', res.error);
        });
      },
    });
  }

  async _ensureMissionHasColor(missionId) {
    const id = String(missionId || '').trim();
    if (!id) return;
    const existing = String(missionColorOverrides.get(id) || '').trim();
    if (existing) return;
    const assigned = this._paletteByMissionId?.get(id)
      || assignPaletteColor(this._missions, missionColorOverrides.getAll()).get(id)
      || '';
    if (!assigned) return;
    missionColorOverrides.set(id, assigned);
    this._render();
    const res = await setMissionColor(id, assigned);
    if (!res.ok) console.warn('Failed to persist mission colour:', res.error);
  }

  _refreshOverlayColors() {
    const editedMissionId = this._editingMissionId;
    const palette = this._paletteByMissionId;
    const overlays = this._visibleMissionOrder
      .filter((mid) => mid !== editedMissionId)
      .map((mid) => {
        const payload = this._overlayCacheByMissionId.get(mid);
        if (!payload?.available) return null;
        return {
          revisionId: mid,
          payload,
          color: palette.get(mid),
          opacity: opacityForMission(mid, this._focusedMissionId),
        };
      })
      .filter(Boolean);
    this._overlayLayer.renderMany(overlays);
  }

  // --- Overflow / sort menu ---

  _openRowMenu(missionId, anchorEl) {
    const id = String(missionId || '').trim();
    if (!id) return;
    const deleteBlocked = this._isMissionDeleteBlocked(id);
    const editBlocked = !this._missions?.find((m) => {
      const s = String(m.activeRevisionStatus || '');
      return String(m.id || '') === id && ['proposed', 'planning', 'exported', 'cutover_pending'].includes(s);
    });
    const ICON_EDIT    = `<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true"><path d="M8.5 2 11 4.5 5 10.5H2.5V8L8.5 2z"/><line x1="7" y1="3.5" x2="9.5" y2="6"/></svg>`;
    const ICON_RENAME  = `<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" focusable="false" aria-hidden="true"><path d="M8.5 2 11 4.5 5 10.5H2.5V8L8.5 2z"/><line x1="1" y1="12.5" x2="12" y2="12.5"/></svg>`;
    const ICON_TRASH   = `<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" focusable="false" aria-hidden="true"><line x1="1.5" y1="4" x2="11.5" y2="4"/><path d="M4.5 4V3h4v1"/><rect x="3" y="4" width="7" height="7.5" rx="1"/></svg>`;
    this._rowMenu.open(anchorEl, {
      items: [
        {
          label: 'Edit waypoints',
          icon: ICON_EDIT,
          disabled: editBlocked,
          disabledTitle: 'Edit only available for missions in proposed / planning / exported / cutover-pending status',
          onClick: () => this._onEditRequested(id),
        },
        {
          label: 'Rename',
          icon: ICON_RENAME,
          onClick: () => this._listPanel.startRenameById(id),
        },
        {
          label: 'Delete',
          icon: ICON_TRASH,
          danger: true,
          disabled: deleteBlocked,
          disabledTitle: 'Delete disabled while mission is armed, awaiting confirmation, or executing',
          onClick: () => this._handleDeleteMission(id),
        },
      ],
    });
  }

  _openOverflowMenu(anchorEl) {
    this._overflowMenu.open(anchorEl, {
      currentSort: missionSortPreference.get(),
      onSortChange: (sortId) => {
        missionSortPreference.set(sortId);
        this._render();
      },
      onExport: () => this._handleExportMissions(),
      onImport: () => this._handleImportMissions(),
    });
  }

  async _handleExportMissions() {
    const missions = this._missions || [];
    if (!missions.length) return;
    const exportItems = [];
    for (const m of missions) {
      const entry = { name: m.name, origin: m.origin };
      if (m.activeRevisionId) {
        const rev = await getRevision(m.activeRevisionId);
        const wps = rev?.mission?.waypoints;
        if (Array.isArray(wps) && wps.length) {
          entry.waypoints = wps.map((wp) => {
            const w = { id: wp.id };
            if (wp.lat != null) w.lat = wp.lat;
            if (wp.lon != null) w.lon = wp.lon;
            if (wp.alt != null) w.alt = wp.alt;
            if (wp.x != null) w.x = wp.x;
            if (wp.y != null) w.y = wp.y;
            if (wp.z != null) w.z = wp.z;
            return w;
          });
        }
      }
      exportItems.push(entry);
    }
    const blob = new Blob(
      [JSON.stringify({ version: 1, missions: exportItems }, null, 2)],
      { type: 'application/json' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `missions-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  _handleImportMissions() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      let parsed;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        this._pushStatus('Import failed: invalid JSON', 'error');
        return;
      }
      const items = Array.isArray(parsed?.missions) ? parsed.missions : (Array.isArray(parsed) ? parsed : []);
      if (!items.length) {
        this._pushStatus('Import failed: no missions found in file', 'error');
        return;
      }
      const createdMissionIds = [];
      for (const item of items) {
        if (!item || typeof item !== 'object') continue;
        const name = String(item.name || 'Imported mission').trim() || 'Imported mission';
        const waypoints = Array.isArray(item.waypoints) ? item.waypoints : [];
        const result = await createMission({ name, waypoints: waypoints.length ? waypoints : null });
        if (result.ok) createdMissionIds.push(result.mission_id);
      }
      if (createdMissionIds.length) {
        await this.refresh();
        await Promise.all(createdMissionIds.map((missionId) => this._ensureMissionHasColor(missionId)));
      }
    });
    input.click();
  }

  // --- DOM ---

  _buildDOM() {
    this._container.innerHTML = '';

    const head = document.createElement('div');
    head.className = 'map-widget-head';
    const title = document.createElement('h2');
    title.className = 'map-widget-map-title';
    title.textContent = 'Mission Map';
    const sessionPill = document.createElement('span');
    sessionPill.className = 'pill warn map-widget-session-pill';
    sessionPill.textContent = this._sessionId || 'No session';
    this._sessionPillEl = sessionPill;

    const shell = document.createElement('div');
    shell.className = 'map-widget-shell';
    if (this._opts?.missionListPosition === 'right') {
      shell.classList.add('mission-list-right');
    }
    this._shellEl = shell;

    const listEl = document.createElement('div');
    listEl.className = 'map-widget-list';
    this._listEl = listEl;

    const listResizer = document.createElement('button');
    listResizer.type = 'button';
    listResizer.className = 'map-list-resizer';
    listResizer.setAttribute('role', 'separator');
    listResizer.setAttribute('aria-label', 'Resize mission list');
    listResizer.setAttribute('aria-orientation', 'vertical');
    listResizer.setAttribute('aria-valuemin', '180');
    listResizer.setAttribute('aria-valuemax', '480');
    listResizer.setAttribute('aria-valuenow', '280');
    listResizer.title = 'Drag to resize mission list';
    this._listResizerEl = listResizer;

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
      <p class="map-empty-hint">Ask the agent in chat to plan a mission.</p>
      <button class="map-empty-cta" type="button">Go to chat</button>
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
      this._overlayCacheByMissionId.clear();
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

    // Cursor/info bar: scene-metre coordinates, WGS84 when origin known, selection detail
    const infoBar = document.createElement('div');
    infoBar.className = 'map-info-bar--map';
    infoBar.setAttribute('aria-hidden', 'true');
    const infoCoords = document.createElement('span');
    infoCoords.textContent = '—';
    const infoGround = document.createElement('span');
    const infoGps = document.createElement('span');
    const infoSel = document.createElement('span');
    infoBar.append(infoCoords, infoGround, infoGps, infoSel);
    this._infoBar = infoBar;
    this._infoBarCoords = infoCoords;
    this._infoBarGround = infoGround;
    this._infoBarGps = infoGps;
    this._infoBarSel = infoSel;

    // Hint toasts (floating transient hints, e.g., "Hold Alt to snap")
    this._hintToasts = new HintToasts(mapWrap);

    // Confirm-mode execution banner (hidden until a run is awaiting confirm)
    this._confirmBanner = new ConfirmExecutionBanner(mapWrap, {
      onConfirm: () => this._handleConfirmExecution(),
      onCancel: () => this._handleCancelExecution(),
    });

    // Sketch session lives here (Phase 2): shared between BasemapPanel (Leaflet
    // adapter) and the toolbar. Owns canonical WGS84 geometry + undo stack.
    this._sketchSession = new MapSketchSession();
    this._sketchSessionUnsub = this._sketchSession.onChange(() => this._syncAuthoringToolbarState());

    const authoringToolbarDock = document.createElement('div');
    authoringToolbarDock.className = 'map-authoring-toolbar-dock';
    authoringToolbarDock.setAttribute('aria-label', 'Map authoring tools');
    this._authoringToolbarDock = authoringToolbarDock;
    this._authoringToolbar = new MapAuthoringToolbar(authoringToolbarDock, {
      onToggleAddWaypoint: () => this._toggleAddWaypointMode(),
      onTogglePatternDraw: (pattern) => this._basemapPanel?.togglePatternDraw(pattern),
      onToggleFenceDraw: () => this._basemapPanel?.toggleFenceDraw(),
      onGeneratePattern: (params) => this._basemapPanel?.generatePattern(params),
      onSaveFence: () => this._basemapPanel?.saveFence(),
      onClearFence: () => this._basemapPanel?.clearFence(),
      onClearSketch: () => {
        const wasEditingConstraint = !!this._editingConstraint;
        this._editingConstraint = null;
        this._sketchSession.reset();
        this._basemapPanel?.clearSketch();
        if (wasEditingConstraint) {
          this._constraintsPanel?.show(this._constraints);
        }
      },
      onToggleConstraintDraw: (kind, rule) => this._basemapPanel?.toggleConstraintDraw(kind, rule),
      onSaveConstraint: async () => {
        if (this._editingConstraint) {
          const constraint = this._editingConstraint;
          const polygon = this._sketchSession.vertices;
          if (polygon.length < 3) {
            this._statusBar?.push('At least 3 vertices required to save.', 'error');
            return;
          }
          this._sketchSession.setStatus('Saving…');
          const res = await updateConstraint(constraint.id, {
            expectedVersion: constraint.version,
            polygon,
          });
          if (res.ok) {
            this._statusBar?.push(`Constraint "${res.constraint?.name || constraint.name || constraint.kind}" shape updated.`, 'info');
            this._editingConstraint = null;
            this._sketchSession.reset();
            await this._refreshConstraints();
            this._constraintsPanel?.show(this._constraints);
          } else if (res.status === 409) {
            this._sketchSession.setStatus('Conflict — another client changed this constraint. Re-save to apply your shape, or cancel to discard.');
            this._statusBar?.push('Constraint changed elsewhere — draft preserved. Re-save to overwrite, or cancel.', 'warn');
            // Fetch the current server version so the next re-save uses the right expectedVersion.
            const listed = await listConstraints();
            const fresh = listed.ok && listed.constraints.find((c) => c.id === constraint.id);
            if (fresh) this._editingConstraint = { ...this._editingConstraint, version: fresh.version };
          } else {
            this._sketchSession.setStatus(`Save failed: ${res.error || 'unknown error'}`);
            this._statusBar?.push(`Constraint save failed: ${res.error || 'unknown error'}`, 'error');
          }
          return;
        }
        this._basemapPanel?.saveConstraint({ name: this._nextConstraintName() });
      },
      onOpenConstraints: () => this._openConstraintsPanel(),
      onUndoVertex: () => this._basemapPanel?.undoVertex(),
      onParamsChange: (params) => this._basemapPanel?.setSketchParams(params),
    });

    // Real 2D WGS84 basemap render mode (Phase 4). The panel covers the scene
    // map when active; the toggle stays visible above it. The toolbar shell is
    // docked by MapWidget at the bottom of the canvas for layout parity with
    // the rest of the widget chrome.
    this._basemapPanel = new BasemapPanel(mapWrap, {
      onGenerate: (sketch) => this._handleDrawnPattern(sketch),
      onSetGeofence: (fence) => this._handleSetGeofence(fence),
      onCreateConstraint: (constraint) => this._handleCreateConstraint(constraint),
      onPreviewPattern: (sketch, opts) => previewDrawnPattern(sketch, opts),
      session: this._sketchSession,
    });

    // Operational-constraints list panel (ADR 0025): opened from the toolbar's
    // Constraints… button, fed the cached list, and re-fed after each mutation.
    this._constraints = [];
    this._constraintsPanel = new ConstraintsPanel(mapWrap, {
      onToggleEnabled: (c) => this._handleToggleConstraint(c),
      onEdit: (c, patch) => this._handleEditConstraint(c, patch),
      onEditShape: (c) => this._startConstraintShapeEdit(c),
      onDelete: (c) => this._handleDeleteConstraint(c),
    });

    // Top-right overlay column: layer toggles + view mode preset + fit-bounds buttons.
    const ctrlRight = document.createElement('div');
    ctrlRight.className = 'map-ctrl-right';

    const viewModeToolbar = document.createElement('div');
    viewModeToolbar.className = 'map-overlay-card map-overlay-selects map-widget-selects';
    viewModeToolbar.setAttribute('aria-label', 'View mode');
    const viewLabel = document.createElement('label');
    viewLabel.title = 'Choose how the generated terrain is rendered on the mission map.';
    viewLabel.innerHTML = `
      <span class="map-tool-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false"><path d="M4 7.4 9.6 4l5 2.5L20 4v12.6L14.4 20l-5-2.5L4 20V7.4Zm2 1.1v8l3.2-1.9v-8L6 8.5Zm5.2-1.9v8.1l3.2 1.6V8.2l-3.2-1.6Zm5.2 1.4v8l1.6-1V7l-1.6 1Z"/></svg>
      </span>
      <span class="map-tool-label">View</span>
    `;
    const viewModeSelect = document.createElement('select');
    viewModeSelect.className = 'map-view-mode-select';
    viewModeSelect.setAttribute('aria-label', 'Scene view mode');
    viewModeSelect.title = 'Map rendering mode';
    for (const [value, label] of [
      ['virtual_terrain',  'Virtual Terrain'],
      ['cad',              'CAD / Object View'],
      ['heightmap',        'Heightmap'],
      ['basemap',          'Basemap'],
    ]) {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = label;
      viewModeSelect.append(opt);
    }
    viewModeSelect.value = 'virtual_terrain';
    viewModeSelect.addEventListener('change', () => this._applyViewMode(viewModeSelect.value));
    this._viewModeSelect = viewModeSelect;
    viewLabel.append(viewModeSelect);
    viewModeToolbar.append(viewLabel);

    const navLabel = document.createElement('label');
    navLabel.title = 'Navigation behavior is fixed to free pan in mission planning.';
    navLabel.innerHTML = `
      <span class="map-tool-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false"><path d="M12 3 5 21l7-3 7 3-7-18Zm0 5.6 3.4 8.8-3.4-1.5-3.4 1.5L12 8.6Z"/></svg>
      </span>
      <span class="map-tool-label">Nav</span>
    `;
    const navModeSelect = document.createElement('select');
    navModeSelect.className = 'map-nav-mode-select';
    navModeSelect.setAttribute('aria-label', 'Map navigation behavior');
    navModeSelect.title = 'Mission map navigation behavior';
    navModeSelect.disabled = true;
    const freePanOpt = document.createElement('option');
    freePanOpt.value = 'free';
    freePanOpt.textContent = 'Free Pan';
    navModeSelect.append(freePanOpt);
    navLabel.append(navModeSelect);
    viewModeToolbar.append(navLabel);

    const layerBar = document.createElement('div');
    layerBar.className = 'map-layer-bar';
    layerBar.setAttribute('aria-label', 'Map layers');
    for (const { key, label } of [
      { key: 'terrain',  label: 'Terrain' },
      { key: 'roads',    label: 'Roads' },
      { key: 'objects',  label: 'Objects' },
      { key: 'grid',     label: 'Grid' },
    ]) {
      const lbl = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.dataset.layer = key;
      cb.addEventListener('change', () => this._onLayerToggle(key, cb.checked));
      lbl.append(cb, document.createTextNode(' '), Object.assign(document.createElement('span'), { textContent: label }));
      layerBar.append(lbl);
    }
    this._layerBar = layerBar;

    const mapTitleGroup = document.createElement('div');
    mapTitleGroup.className = 'map-widget-map-title-group';
    mapTitleGroup.append(title, sessionPill);

    const mapTopBar = document.createElement('div');
    mapTopBar.className = 'map-widget-map-topbar';
    mapTopBar.append(mapTitleGroup, layerBar);

    const fitToolbar = document.createElement('div');
    fitToolbar.className = 'map-overlay-card map-fit-actions map-fit-toolbar';
    fitToolbar.setAttribute('aria-label', 'Fit view');
    const fitDefs = [
      {
        key: 'scene',
        label: 'terrain',
        title: 'Fit Terrain: Fit the full generated terrain scene in the map view',
        icon: '<path d="M5 5h5v2H7v3H5V5Zm9 0h5v5h-2V7h-3V5ZM5 14h2v3h3v2H5v-5Zm12 0h2v5h-5v-2h3v-3Z"/>',
      },
      {
        key: 'mission',
        label: 'mission',
        title: 'Fit Mission: Fit the focused mission route in the map view',
        icon: '<path d="M6.5 6A2.5 2.5 0 1 0 6.5 11 2.5 2.5 0 0 0 6.5 6Zm0 1.8a.7.7 0 1 1 0 1.4.7.7 0 0 1 0-1.4ZM17.5 13A2.5 2.5 0 1 0 17.5 18 2.5 2.5 0 0 0 17.5 13Zm0 1.8a.7.7 0 1 1 0 1.4.7.7 0 0 1 0-1.4ZM9.1 9.4l1.2-1.5 5.6 4.7-1.2 1.5-5.6-4.7Z"/>',
      },
      {
        key: 'all',
        label: 'all visible missions',
        title: 'Fit All: Fit all visible mission routes in the map view',
        icon: '<path d="M4 4h7v2H7.4l4.1 4.1-1.4 1.4L6 7.4V11H4V4Zm9 0h7v7h-2V7.4l-4.1 4.1-1.4-1.4L16.6 6H13V4ZM4 13h2v3.6l4.1-4.1 1.4 1.4L7.4 18H11v2H4v-7Zm14 0h2v7h-7v-2h3.6l-4.1-4.1 1.4-1.4 4.1 4.1V13Z"/>',
      },
    ];
    const fitBtns = {};
    for (const { key, label, title, icon } of fitDefs) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'map-tool-button map-fit-btn';
      btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${icon}</svg>`;
      btn.disabled = true;
      btn.title = title;
      btn.setAttribute('aria-label', `Fit ${label}`);
      btn.addEventListener('click', () => this._handleFitClick(key));
      fitToolbar.append(btn);
      fitBtns[key] = btn;
    }
    this._fitBtns = fitBtns;

    ctrlRight.append(viewModeToolbar, fitToolbar);

    mapWrap.append(mapEl, emptyState, editBanner, selectionPanelWrap, marqueeEl, ctrlRight, infoBar, authoringToolbarDock);
    const mapCol = document.createElement('div');
    mapCol.className = 'map-widget-map-col';
    mapCol.append(mapTopBar, mapWrap);
    shell.append(listEl, listResizer, mapCol);

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
        <h3 id="map-confirm-title" class="map-confirm-title">Upload linear plan to controller?</h3>
        <p class="map-confirm-body">
          This uploads the active revision's waypoints to the controller as a
          linear plan and starts it (legacy direct upload — not behavior-tree
          execution).<br>
          Revision: <code class="map-confirm-revision-id"></code> &nbsp;
          Controller version: <code class="map-confirm-controller-version"></code>
        </p>
        <div class="map-confirm-actions">
          <button class="map-confirm-cancel" type="button">Cancel</button>
          <button class="map-confirm-ok" type="button">Upload plan</button>
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

    this._container.append(shell, elevationEl, confirmModal);

    // Keyboard help overlay (<dialog> appended to container by constructor)
    this._keyboardHelp = new KeyboardHelpOverlay(this._container);
  }

  _showEmpty(show) {
    if (this._emptyState) this._emptyState.hidden = !show;
  }

  get isMounted() {
    return this._mounted;
  }
}
