// Real 2D WGS84 basemap render mode (Mission Planner Modernization, Phase 4).
//
// The primary map renders the simulator scene in Leaflet `CRS.Simple` (local
// metres). This panel is an additive, read-only second view that plots the
// focused mission on a real geographic basemap (OpenStreetMap tiles, EPSG:3857)
// using the WGS84 lat/lon the overlay payload now carries (ADR 0022). It owns
// its own `L.map`, so it never disturbs the scene map's CRS or edit flow; the
// MapWidget just toggles it visible and feeds it the focused overlay.
//
// The geographic panel still fills its parent map wrap when active, while the
// authoring toolbar lives at the MapWidget layer and drives these sketch APIs.

const OSM_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '© OpenStreetMap contributors';
const DEFAULT_ZOOM = 17;
const BASEMAP_ZOOM_OPTIONS = {
  zoomSnap: 0.25,
  zoomDelta: 0.25,
  wheelPxPerZoomLevel: 160,
};

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
  constructor(parent, { onGenerate = null, onSetGeofence = null, onSketchStateChange = null } = {}) {
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
    this._onSketchStateChange = onSketchStateChange;
    this._drawMode = null; // null | 'corridor' | 'survey' | 'fence'
    this._drawPoints = []; // L.LatLng[] of the in-progress sketch
    this._drawLayer = null;
    this._statusText = '';

    // Live vehicle GPS marker (Phase 4 telemetry simulation).
    this._gpsVehicleMarker = null;
    this._gpsVehicleWs = null;
  }

  _emitSketchState() {
    this._onSketchStateChange?.(this.getSketchState());
  }

  getSketchState() {
    return {
      drawMode: this._drawMode,
      drawPointCount: this._drawPoints.length,
      statusText: this._statusText,
    };
  }

  togglePatternDraw(pattern = 'corridor') {
    if (this._drawMode) {
      this._resetDraw();
      return;
    }
    this._drawMode = pattern === 'survey' ? 'survey' : 'corridor';
    this._drawPoints = [];
    if (this._map) this._map.getContainer().style.cursor = 'crosshair';
    this._setStatus(this._drawMode === 'survey'
      ? 'Click two opposite corners of the survey area.'
      : 'Click to add corridor vertices.');
    this._refreshDrawLayer();
    this._emitSketchState();
  }

  toggleFenceDraw() {
    if (this._drawMode) {
      this._resetDraw();
      return;
    }
    this._drawMode = 'fence';
    this._drawPoints = [];
    if (this._map) this._map.getContainer().style.cursor = 'crosshair';
    this._setStatus('Click to add fence vertices (3+); then Save fence.');
    this._refreshDrawLayer();
    this._emitSketchState();
  }

  clearSketch() {
    this._resetDraw();
  }

  _resetDraw() {
    this._drawMode = null;
    this._drawPoints = [];
    if (this._map) this._map.getContainer().style.cursor = '';
    this._refreshDrawLayer();
    this._setStatus('');
    this._emitSketchState();
  }

  _onMapClick(latlng) {
    if (!this._drawMode) return;
    if (this._drawMode === 'survey' && this._drawPoints.length >= 2) {
      this._drawPoints = [];
    }
    this._drawPoints.push(latlng);
    this._setStatus(`${this._drawPoints.length} point${this._drawPoints.length === 1 ? '' : 's'}`);
    this._refreshDrawLayer();
    this._emitSketchState();
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

  saveFence() {
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

  clearFence() {
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

  generatePattern({ pattern = 'corridor', spacing = 5, altitude = 0, passes = 1 } = {}) {
    if (!this._drawMode || typeof this._onGenerate !== 'function') return;
    const points = this._drawPoints.map((ll) => ({ lat: ll.lat, lon: ll.lng }));
    if (points.length < 2) return;
    const params = {
      altitude_m: Number(altitude) || 0,
    };
    if (pattern === 'corridor') {
      params.spacing_m = spacing;
      params.passes = Math.max(1, parseInt(passes, 10) || 1);
    } else {
      params.line_spacing_m = spacing;
    }
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
    this._statusText = text || '';
    this._emitSketchState();
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
    if (this._gpsVehicleWs) {
      try { this._gpsVehicleWs.close(); } catch {}
      this._gpsVehicleWs = null;
    }
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._tileLayer = null;
    this._featureLayer = null;
    this._drawLayer = null;
    this._gpsVehicleMarker = null;
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
    this._connectGpsVehicle();
  }

  _connectGpsVehicle() {
    if (this._gpsVehicleWs) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    try {
      this._gpsVehicleWs = new WebSocket(
        `${scheme}://${location.host}/ws?client_id=basemap-gps-${Date.now()}`
      );
    } catch { return; }
    this._gpsVehicleWs.addEventListener('message', (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        let telem = null;
        if (msg.type === 'telemetry') telem = msg.data;
        else if (msg.type === 'snapshot') telem = msg.data?.telemetry;
        if (telem) this._updateGpsVehicle(telem);
      } catch {}
    });
    this._gpsVehicleWs.addEventListener('close', () => {
      this._gpsVehicleWs = null;
      if (this._map) setTimeout(() => this._connectGpsVehicle(), 3000);
    });
    this._gpsVehicleWs.addEventListener('error', () => {
      try { this._gpsVehicleWs?.close(); } catch {}
    });
  }

  _updateGpsVehicle(telem) {
    if (!this._map) return;
    const gps = telem?.gps;
    if (typeof gps?.lat !== 'number' || typeof gps?.lon !== 'number') return;
    if (gps.lat === 0 && gps.lon === 0) return;
    const hdg = telem?.orientation?.heading_deg ?? 0;
    const ll = [gps.lat, gps.lon];
    if (!this._gpsVehicleMarker) {
      this._gpsVehicleMarker = L.marker(ll, {
        icon: this._makeGpsVehicleIcon(hdg),
        zIndexOffset: 1000,
        interactive: false,
      }).addTo(this._map);
    } else {
      this._gpsVehicleMarker.setLatLng(ll);
      this._gpsVehicleMarker.setIcon(this._makeGpsVehicleIcon(hdg));
    }
  }

  _makeGpsVehicleIcon(heading) {
    return L.divIcon({
      className: '',
      html: `<div class="map-vehicle-marker" style="transform:rotate(${heading}deg)" aria-hidden="true"></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
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
