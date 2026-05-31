// Real 2D WGS84 basemap render mode (Mission Planner Modernization, Phase 4).
//
// The primary map renders the simulator scene in Leaflet `CRS.Simple` (local
// metres). This panel is an additive, read-only second view that plots the
// focused mission on a real geographic basemap (OpenStreetMap tiles, EPSG:3857)
// using the WGS84 lat/lon the overlay payload now carries (ADR 0022). It owns
// its own `L.map`, so it never disturbs the scene map's CRS or edit flow; the
// MapWidget just toggles it visible and feeds it the focused overlay.
//
// Styling is inline so the panel is self-contained and needs no stylesheet hook;
// it absolutely fills its (position:relative) parent map wrap when active.

const OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
const DEFAULT_ZOOM = 17;

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
  constructor(parent, { onGenerate = null, onSetGeofence = null } = {}) {
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
    this._drawMode = null; // null | 'corridor' | 'survey' | 'fence'
    this._drawPoints = []; // L.LatLng[] of the in-progress sketch
    this._drawLayer = null;
    this._toolbar = null;
    this._statusEl = null;
    this._buildToolbar();
  }

  // ── Draw toolbar (operator-draw, Phase 4) ─────────────────────────────────
  _buildToolbar() {
    const bar = document.createElement('div');
    bar.className = 'map-basemap-drawbar';
    Object.assign(bar.style, {
      position: 'absolute',
      top: '8px',
      left: '8px',
      zIndex: '500',
      display: 'flex',
      flexWrap: 'wrap',
      gap: '6px',
      alignItems: 'center',
      padding: '6px 8px',
      background: 'rgba(255,255,255,0.92)',
      border: '1px solid #b9c4d0',
      borderRadius: '6px',
      font: '12px/1.4 system-ui, sans-serif',
      boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
    });

    const mk = (tag, props = {}, style = {}) => {
      const node = document.createElement(tag);
      Object.assign(node, props);
      Object.assign(node.style, style);
      return node;
    };

    this._patternSel = mk('select');
    for (const [val, label] of [['corridor', 'Corridor'], ['survey', 'Survey']]) {
      this._patternSel.appendChild(mk('option', { value: val, textContent: label }));
    }

    this._spacingInput = mk('input', { type: 'number', value: '5', min: '0.5', step: '0.5', title: 'Waypoint / line spacing (m)' }, { width: '52px' });
    this._altInput = mk('input', { type: 'number', value: '0', step: '0.5', title: 'Altitude (m)' }, { width: '52px' });
    this._passesInput = mk('input', { type: 'number', value: '1', min: '1', step: '1', title: 'Passes (corridor)' }, { width: '44px' });

    this._drawBtn = mk('button', { type: 'button', textContent: '✏️ Draw' });
    this._drawBtn.addEventListener('click', () => this._toggleDraw());
    this._genBtn = mk('button', { type: 'button', textContent: 'Generate', disabled: true });
    this._genBtn.addEventListener('click', () => this._generate());
    const clearBtn = mk('button', { type: 'button', textContent: 'Clear' });
    clearBtn.addEventListener('click', () => this._resetDraw());

    // Geofence draw (Phase 5): independent of the pattern selector — sketch an
    // inclusion polygon (>= 3 vertices) and save it onto the focused mission.
    this._fenceBtn = mk('button', { type: 'button', textContent: '🛡 Fence' });
    this._fenceBtn.addEventListener('click', () => this._toggleFence());
    this._saveFenceBtn = mk('button', { type: 'button', textContent: 'Save fence', disabled: true });
    this._saveFenceBtn.addEventListener('click', () => this._saveFence());
    this._clearFenceBtn = mk('button', { type: 'button', textContent: 'Clear fence', title: 'Remove the mission geofence' });
    this._clearFenceBtn.addEventListener('click', () => this._clearFence());

    this._statusEl = mk('span', { textContent: '' }, { color: '#555' });

    bar.append(
      this._patternSel, mk('span', { textContent: 'sp' }), this._spacingInput,
      mk('span', { textContent: 'alt' }), this._altInput,
      mk('span', { textContent: '×' }), this._passesInput,
      this._drawBtn, this._genBtn, clearBtn,
      mk('span', { textContent: '|' }, { color: '#b9c4d0' }),
      this._fenceBtn, this._saveFenceBtn, this._clearFenceBtn,
      this._statusEl,
    );
    bar.hidden = true;
    this._toolbar = bar;
    this._el.appendChild(bar);
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
    if (this._toolbar) this._toolbar.hidden = false;
    this._ensureMap();
    // Leaflet needs a re-measure once the container becomes visible.
    window.requestAnimationFrame(() => this._map?.invalidateSize(false));
  }

  hide() {
    this._visible = false;
    this._el.hidden = true;
    if (this._toolbar) this._toolbar.hidden = true;
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
    this._el.remove();
  }

  _ensureMap() {
    if (this._map || typeof L === 'undefined') return;
    this._map = L.map(this._el, { zoomSnap: 0.5, worldCopyJump: true });
    this._tileLayer = L.tileLayer(OSM_TILE_URL, {
      maxZoom: 19,
      attribution: OSM_ATTRIBUTION,
    }).addTo(this._map);
    this._featureLayer = L.layerGroup().addTo(this._map);
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

    const features = Array.isArray(payload?.features) ? payload.features : [];
    const latLngs = [];

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
