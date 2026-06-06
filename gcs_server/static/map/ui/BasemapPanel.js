// Real 2D WGS84 basemap render mode (Mission Planner Modernization, Phase 4).
//
// The primary map renders the simulator scene in Leaflet `CRS.Simple` (local
// metres). This panel is an additive, read-only second view that plots the
// focused mission on a real geographic basemap (OpenStreetMap tiles, EPSG:3857)
// using the WGS84 lat/lon the overlay payload now carries (ADR 0022). It owns
// its own `L.map`, so it never disturbs the scene map's CRS or edit flow; the
// MapWidget just toggles it visible and feeds it the focused overlay.
//
// The geographic panel still fills its parent map wrap when active, but the
// authoring toolbar is mounted into a MapWidget-owned dock so layout ownership
// stays with the outer widget.

const OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
const DEFAULT_ZOOM = 17;
const BASEMAP_ZOOM_OPTIONS = {
  zoomSnap: 0.25,
  zoomDelta: 0.25,
  wheelPxPerZoomLevel: 160,
};

function setTooltip(node, enabledTitle, disabledTitle, disabled) {
  if (!node) return;
  const title = disabled ? (disabledTitle || '') : (enabledTitle || '');
  if (title) node.title = title;
  else node.removeAttribute('title');
}

function canGenerateFromDrawState(drawMode, drawPoints) {
  if (drawMode === 'survey') return drawPoints.length === 2;
  if (drawMode === 'corridor') return drawPoints.length >= 2;
  return false;
}

export class BasemapPanel {
  // `onGenerate({ pattern, points, params })` is invoked when the operator
  // finishes a sketch and clicks Generate; `points` are drawn WGS84 vertices
  // ({lat, lon}). The panel stays decoupled from the API/refresh — the caller
  // (MapWidget) persists the pattern and reloads the mission list.
  //
  // `onSetGeofence({ polygon, clear })` is invoked when the operator finishes a
  // fence sketch and clicks Save fence (or clicks Clear fence); `polygon` is the
  // drawn WGS84 inclusion polygon ({lat, lon} vertices, >= 3). The caller fences
  // the focused mission (Phase 5) and reloads.
  constructor(parent, { onGenerate = null, onSetGeofence = null, onToggleAddWaypoint = null, toolbarHost = null } = {}) {
    this._el = document.createElement('div');
    this._el.className = 'map-basemap-panel';
    Object.assign(this._el.style, {
      position: 'absolute',
      inset: '0',
      zIndex: '450',
    });
    this._el.hidden = true;
    parent.appendChild(this._el);

    this._map = null;
    this._tileLayer = null;
    this._featureLayer = null;
    this._visible = false;

    // Operator-draw state (Phase 4 authoring + Phase 5 geofence).
    this._onGenerate = onGenerate;
    this._onSetGeofence = onSetGeofence;
    this._onToggleAddWaypoint = onToggleAddWaypoint;
    this._drawMode = null; // null | 'corridor' | 'survey' | 'fence'
    this._drawPoints = []; // L.LatLng[] of the in-progress sketch
    this._drawLayer = null;
    this._toolbar = null;
    this._toolbarHost = toolbarHost || null;
    this._statusEl = null;
    this._clearBtn = null;
    this._toolbarState = {
      addWaypointEnabled: false,
      addWaypointActive: false,
      addWaypointReason: 'Select an editable mission revision to add waypoints.',
      drawToolsEnabled: false,
      drawToolsReason: 'Switch VIEW to Basemap to use corridor and survey tools.',
      geofenceEnabled: false,
      geofenceReason: 'Switch VIEW to Basemap to edit geofences.',
    };
    this._drawTitles = {
      pattern: 'Pattern generator',
      spacing: 'Waypoint / line spacing (m)',
      altitude: 'Altitude (m)',
      passes: 'Passes (corridor)',
      draw: 'Sketch a corridor or survey pattern on the basemap',
      generate: 'Generate a mission from the current sketch',
      clear: 'Clear the current sketch',
      fence: 'Sketch an inclusion geofence on the basemap',
      saveFence: 'Save the current geofence sketch onto the focused mission',
      clearFence: 'Remove the mission geofence',
    };
    this._buildToolbar();
  }

  // ── Draw toolbar (operator-draw, Phase 4) ─────────────────────────────────
  _buildToolbar() {
    const bar = document.createElement('div');
    bar.className = 'map-authoring-toolbar map-authoring-toolbar--basemap';

    const mk = (tag, props = {}, style = {}) => {
      const node = document.createElement(tag);
      Object.assign(node, props);
      Object.assign(node.style, style);
      return node;
    };

    this._addWaypointBtn = mk('button', { type: 'button', textContent: 'Add waypoint' });
    this._addWaypointBtn.addEventListener('click', () => {
      if (this._addWaypointBtn.disabled || typeof this._onToggleAddWaypoint !== 'function') return;
      this._onToggleAddWaypoint();
    });

    this._patternSel = mk('select', { title: this._drawTitles.pattern });
    for (const [val, label] of [['corridor', 'Corridor'], ['survey', 'Survey']]) {
      this._patternSel.appendChild(mk('option', { value: val, textContent: label }));
    }

    this._spacingInput = mk('input', { type: 'number', value: '5', min: '0.5', step: '0.5', title: this._drawTitles.spacing }, { width: '52px' });
    this._altInput = mk('input', { type: 'number', value: '0', step: '0.5', title: this._drawTitles.altitude }, { width: '52px' });
    this._passesInput = mk('input', { type: 'number', value: '1', min: '1', step: '1', title: this._drawTitles.passes }, { width: '44px' });

    this._drawBtn = mk('button', { type: 'button', textContent: '✏️ Draw', title: this._drawTitles.draw });
    this._drawBtn.addEventListener('click', () => this._toggleDraw());
    this._genBtn = mk('button', { type: 'button', textContent: 'Generate', disabled: true, title: this._drawTitles.generate });
    this._genBtn.addEventListener('click', () => this._generate());
    const clearBtn = mk('button', { type: 'button', textContent: 'Clear', title: this._drawTitles.clear });
    clearBtn.addEventListener('click', () => this._resetDraw());
    this._clearBtn = clearBtn;

    // Geofence draw (Phase 5): independent of the pattern selector — sketch an
    // inclusion polygon (>= 3 vertices) and save it onto the focused mission.
    this._fenceBtn = mk('button', { type: 'button', textContent: '🛡 Fence', title: this._drawTitles.fence });
    this._fenceBtn.addEventListener('click', () => this._toggleFence());
    this._saveFenceBtn = mk('button', { type: 'button', textContent: 'Save fence', disabled: true, title: this._drawTitles.saveFence });
    this._saveFenceBtn.addEventListener('click', () => this._saveFence());
    this._clearFenceBtn = mk('button', { type: 'button', textContent: 'Clear fence', title: this._drawTitles.clearFence });
    this._clearFenceBtn.addEventListener('click', () => this._clearFence());

    this._statusEl = mk('span', { textContent: '' }, { color: '#555' });

    bar.append(
      this._addWaypointBtn,
      mk('span', { textContent: '|' }, { color: '#b9c4d0' }),
      this._patternSel, mk('span', { textContent: 'sp' }), this._spacingInput,
      mk('span', { textContent: 'alt' }), this._altInput,
      mk('span', { textContent: '×' }), this._passesInput,
      this._drawBtn, this._genBtn, clearBtn,
      mk('span', { textContent: '|' }, { color: '#b9c4d0' }),
      this._fenceBtn, this._saveFenceBtn, this._clearFenceBtn,
      this._statusEl,
    );
    bar.hidden = false;
    this._toolbar = bar;
    (this._toolbarHost || this._el).appendChild(bar);
    this.updateToolbarState(this._toolbarState);
  }

  setToolbarHost(host) {
    this._toolbarHost = host || null;
    if (this._toolbar) (this._toolbarHost || this._el).appendChild(this._toolbar);
  }

  updateToolbarState(nextState = {}) {
    this._toolbarState = { ...this._toolbarState, ...nextState };
    const state = this._toolbarState;

    if (this._addWaypointBtn) {
      this._addWaypointBtn.disabled = !state.addWaypointEnabled;
      this._addWaypointBtn.classList.toggle('is-active', !!state.addWaypointActive);
      this._addWaypointBtn.setAttribute('aria-pressed', state.addWaypointActive ? 'true' : 'false');
      setTooltip(
        this._addWaypointBtn,
        state.addWaypointActive ? 'Click the map to place waypoints. Click again to leave add mode.' : 'Append waypoints by clicking the map.',
        state.addWaypointReason,
        !state.addWaypointEnabled,
      );
    }

    const drawDisabled = !state.drawToolsEnabled;
    const drawGenerateReady = canGenerateFromDrawState(this._drawMode, this._drawPoints);
    const drawClearReady = this._drawPoints.length > 0;
    this._patternSel.disabled = drawDisabled;
    this._spacingInput.disabled = drawDisabled;
    this._altInput.disabled = drawDisabled;
    this._passesInput.disabled = drawDisabled;
    this._drawBtn.disabled = drawDisabled;
    this._genBtn.disabled = drawDisabled || !drawGenerateReady;
    this._clearBtn.disabled = drawDisabled || !drawClearReady;
    setTooltip(this._patternSel, this._drawTitles.pattern, state.drawToolsReason, drawDisabled);
    setTooltip(this._spacingInput, this._drawTitles.spacing, state.drawToolsReason, drawDisabled);
    setTooltip(this._altInput, this._drawTitles.altitude, state.drawToolsReason, drawDisabled);
    setTooltip(this._passesInput, this._drawTitles.passes, state.drawToolsReason, drawDisabled);
    setTooltip(this._drawBtn, this._drawTitles.draw, state.drawToolsReason, drawDisabled);
    setTooltip(this._genBtn, this._drawTitles.generate, state.drawToolsReason, drawDisabled);
    setTooltip(this._clearBtn, this._drawTitles.clear, state.drawToolsReason, drawDisabled);

    const geofenceDisabled = !state.geofenceEnabled;
    const saveFenceReady = this._drawMode === 'fence' && this._drawPoints.length >= 3;
    this._fenceBtn.disabled = geofenceDisabled;
    this._saveFenceBtn.disabled = geofenceDisabled || !saveFenceReady;
    this._clearFenceBtn.disabled = geofenceDisabled;
    setTooltip(this._fenceBtn, this._drawTitles.fence, state.geofenceReason, geofenceDisabled);
    setTooltip(this._saveFenceBtn, this._drawTitles.saveFence, state.geofenceReason, geofenceDisabled);
    setTooltip(this._clearFenceBtn, this._drawTitles.clearFence, state.geofenceReason, geofenceDisabled);
  }

  _toggleDraw() {
    if (this._drawMode) {
      this._resetDraw();
      return;
    }
    this._drawMode = this._patternSel.value === 'survey' ? 'survey' : 'corridor';
    this._drawPoints = [];
    this._drawBtn.textContent = '■ Stop';
    if (this._map) this._map.getContainer().style.cursor = 'crosshair';
    this._setStatus(this._drawMode === 'survey'
      ? 'Click two opposite corners of the survey area.'
      : 'Click to add corridor vertices.');
    this._refreshDrawLayer();
    this.updateToolbarState();
  }

  _toggleFence() {
    if (this._drawMode) {
      this._resetDraw();
      return;
    }
    this._drawMode = 'fence';
    this._drawPoints = [];
    this._fenceBtn.textContent = '■ Stop';
    if (this._map) this._map.getContainer().style.cursor = 'crosshair';
    this._setStatus('Click to add fence vertices (3+); then Save fence.');
    this._refreshDrawLayer();
    this.updateToolbarState();
  }

  _resetDraw() {
    this._drawMode = null;
    this._drawPoints = [];
    this._drawBtn.textContent = '✏️ Draw';
    this._fenceBtn.textContent = '🛡 Fence';
    this._genBtn.disabled = true;
    this._saveFenceBtn.disabled = true;
    if (this._map) this._map.getContainer().style.cursor = '';
    this._refreshDrawLayer();
    this._setStatus('');
    this.updateToolbarState();
  }

  _onMapClick(latlng) {
    if (!this._drawMode) return;
    if (this._drawMode === 'survey' && this._drawPoints.length >= 2) {
      this._drawPoints = [];
    }
    this._drawPoints.push(latlng);
    if (this._drawMode === 'fence') {
      this._saveFenceBtn.disabled = this._drawPoints.length < 3;
    } else {
      const enough = this._drawMode === 'survey'
        ? this._drawPoints.length === 2
        : this._drawPoints.length >= 2;
      this._genBtn.disabled = !enough;
    }
    this._setStatus(`${this._drawPoints.length} point${this._drawPoints.length === 1 ? '' : 's'}`);
    this._refreshDrawLayer();
    this.updateToolbarState();
  }

  _refreshDrawLayer() {
    if (!this._map) return;
    if (!this._drawLayer) this._drawLayer = L.layerGroup().addTo(this._map);
    this._drawLayer.clearLayers();
    const pts = this._drawPoints;
    if (!pts.length) return;
    const fence = this._drawMode === 'fence';
    const stroke = fence ? '#2e8b57' : '#d9534f';
    if (this._drawMode === 'survey' && pts.length === 2) {
      L.rectangle(L.latLngBounds(pts[0], pts[1]), { color: stroke, weight: 2, fillOpacity: 0.1 }).addTo(this._drawLayer);
    } else if (fence && pts.length >= 3) {
      // Closed inclusion polygon (Phase 5 geofence).
      L.polygon(pts, { color: stroke, weight: 2, fillOpacity: 0.1 }).addTo(this._drawLayer);
    } else if (pts.length >= 2) {
      L.polyline(pts, { color: stroke, weight: 3, dashArray: '6 4' }).addTo(this._drawLayer);
    }
    for (const ll of pts) {
      L.circleMarker(ll, { radius: 4, color: stroke, fillColor: '#fff', fillOpacity: 1, weight: 2 }).addTo(this._drawLayer);
    }
  }

  _saveFence() {
    if (this._drawMode !== 'fence' || typeof this._onSetGeofence !== 'function') return;
    const polygon = this._drawPoints.map((ll) => ({ lat: ll.lat, lon: ll.lng }));
    if (polygon.length < 3) return;
    this._setStatus('Saving fence…');
    Promise.resolve(this._onSetGeofence({ polygon }))
      .then((res) => {
        if (res && res.ok === false) {
          this._setStatus(`Error: ${res.error || 'failed'}`);
        } else {
          this._resetDraw();
          this._setStatus('Geofence saved.');
        }
      })
      .catch((err) => this._setStatus(`Error: ${err?.message || 'failed'}`));
  }

  _clearFence() {
    if (typeof this._onSetGeofence !== 'function') return;
    this._resetDraw();
    this._setStatus('Clearing fence…');
    Promise.resolve(this._onSetGeofence({ clear: true }))
      .then((res) => {
        if (res && res.ok === false) this._setStatus(`Error: ${res.error || 'failed'}`);
        else this._setStatus('Geofence cleared.');
      })
      .catch((err) => this._setStatus(`Error: ${err?.message || 'failed'}`));
  }

  _generate() {
    if (!this._drawMode || typeof this._onGenerate !== 'function') return;
    const points = this._drawPoints.map((ll) => ({ lat: ll.lat, lon: ll.lng }));
    if (points.length < 2) return;
    const spacing = Number(this._spacingInput.value) || 5;
    const params = {
      altitude_m: Number(this._altInput.value) || 0,
    };
    if (this._drawMode === 'corridor') {
      params.spacing_m = spacing;
      params.passes = Math.max(1, parseInt(this._passesInput.value, 10) || 1);
    } else {
      params.line_spacing_m = spacing;
    }
    const pattern = this._drawMode;
    this._setStatus('Generating…');
    Promise.resolve(this._onGenerate({ pattern, points, params }))
      .then((res) => {
        if (res && res.ok === false) {
          this._setStatus(`Error: ${res.error || 'failed'}`);
        } else {
          this._resetDraw();
          this._setStatus('Mission created.');
        }
      })
      .catch((err) => this._setStatus(`Error: ${err?.message || 'failed'}`));
  }

  _setStatus(text) {
    if (this._statusEl) this._statusEl.textContent = text;
  }

  get visible() {
    return this._visible;
  }

  toggle() {
    if (this._visible) this.hide();
    else this.show();
    return this._visible;
  }

  show() {
    this._visible = true;
    this._el.hidden = false;
    this._ensureMap();
    // Leaflet needs a re-measure once the container becomes visible.
    window.requestAnimationFrame(() => this._map?.invalidateSize(false));
  }

  invalidateSize() {
    if (this._visible) this._map?.invalidateSize(false);
  }

  hide() {
    this._visible = false;
    this._el.hidden = true;
    this._resetDraw();
  }

  destroy() {
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._tileLayer = null;
    this._featureLayer = null;
    this._drawLayer = null;
    this._toolbar?.remove();
    this._el.remove();
  }

  _ensureMap() {
    if (this._map || typeof L === 'undefined') return;
    this._map = L.map(this._el, { ...BASEMAP_ZOOM_OPTIONS, worldCopyJump: true });
    this._tileLayer = L.tileLayer(OSM_TILE_URL, {
      maxZoom: 19,
      attribution: OSM_ATTRIBUTION,
    }).addTo(this._map);
    this._featureLayer = L.layerGroup().addTo(this._map);
    this._fenceLayer = L.layerGroup().addTo(this._map);
    this._drawLayer = L.layerGroup().addTo(this._map);
    this._map.on('click', (e) => this._onMapClick(e.latlng));
    this._map.setView([0, 0], 2);
  }

  // Render one overlay payload (the focused mission) by its WGS84 coordinates.
  // `payload` is the same overlay shape the scene map consumes; here we read the
  // lat/lon each feature now carries instead of the local x/y.
  render(payload) {
    if (!this._visible) return;
    this._ensureMap();
    if (!this._map || !this._featureLayer) return;
    this._featureLayer.clearLayers();
    this._fenceLayer?.clearLayers();

    const features = Array.isArray(payload?.features) ? payload.features : [];
    const latLngs = [];

    // Stored inclusion geofence (Phase 5): a saved fence rendered on load, kept
    // visually distinct from the in-progress green draw sketch in `_drawLayer`.
    const fence = payload?.geofence;
    const fencePoly = Array.isArray(fence?.polygon)
      ? fence.polygon
          .filter((v) => Number.isFinite(v?.lat) && Number.isFinite(v?.lon))
          .map((v) => [v.lat, v.lon])
      : [];
    if (fencePoly.length >= 3 && this._fenceLayer) {
      L.polygon(fencePoly, {
        color: '#8e44ad',
        weight: 2,
        fillColor: '#8e44ad',
        fillOpacity: 0.08,
        dashArray: '6 4',
      })
        .bindTooltip('Inclusion geofence', { direction: 'top', sticky: true })
        .addTo(this._fenceLayer);
      latLngs.push(...fencePoly);
      for (const rally of fence.rally_points || []) {
        if (!Number.isFinite(rally?.lat) || !Number.isFinite(rally?.lon)) continue;
        L.circleMarker([rally.lat, rally.lon], {
          radius: 4,
          color: '#8e44ad',
          fillColor: '#d2b4de',
          fillOpacity: 0.9,
          weight: 2,
        })
          .bindTooltip('Rally point', { direction: 'top' })
          .addTo(this._fenceLayer);
        latLngs.push([rally.lat, rally.lon]);
      }
    }

    for (const feature of features) {
      if (feature?.type === 'route_line') {
        const line = (feature.points || [])
          .filter((pt) => Number.isFinite(pt?.lat) && Number.isFinite(pt?.lon))
          .map((pt) => [pt.lat, pt.lon]);
        if (line.length >= 2) {
          L.polyline(line, { color: '#4a90d9', weight: 3, opacity: 0.85 }).addTo(this._featureLayer);
          latLngs.push(...line);
        }
      } else if (feature?.type === 'waypoint') {
        const pt = feature.point || {};
        if (!Number.isFinite(pt.lat) || !Number.isFinite(pt.lon)) continue;
        const ll = [pt.lat, pt.lon];
        L.circleMarker(ll, {
          radius: 5,
          color: '#1f5c99',
          fillColor: '#4a90d9',
          fillOpacity: 0.9,
          weight: 2,
        })
          .bindTooltip(String(feature.label || `Waypoint ${feature.index ?? ''}`).trim(), { direction: 'top' })
          .addTo(this._featureLayer);
        latLngs.push(ll);
      }
    }

    if (latLngs.length === 1) {
      this._map.setView(latLngs[0], DEFAULT_ZOOM);
    } else if (latLngs.length > 1) {
      this._map.fitBounds(latLngs, { padding: [28, 28] });
    } else {
      // No waypoints yet — centre on the Mission Origin datum if available.
      const origin = payload?.origin;
      if (origin && Number.isFinite(origin.lat) && Number.isFinite(origin.lon)) {
        this._map.setView([origin.lat, origin.lon], DEFAULT_ZOOM);
      }
    }
  }
}
