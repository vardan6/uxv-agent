import { getCurrentOverlay } from './data/missionApi.js';
import { MissionOverlayLayer } from './layers/MissionOverlayLayer.js';

export class MapWidget {
  constructor(container, opts = {}) {
    this._container = typeof container === 'string'
      ? document.getElementById(container)
      : container;
    this._sessionId = opts.sessionId || '';
    this._onEvent = opts.onEvent || null;
    this._map = null;
    this._overlayLayer = null;
    this._errorBanner = null;
    this._errorText = null;
    this._emptyState = null;
    this._mapEl = null;
  }

  mount() {
    if (typeof L === 'undefined') {
      console.error('MapWidget: Leaflet (L) is not loaded. Check that leaflet.js loaded before MapWidget.mount() is called.');
      return;
    }
    this._buildDOM();
    this._map = L.map(this._mapEl, {
      crs: L.CRS.Simple,
      zoom: 1,
      minZoom: -6,
      maxZoom: 8,
      zoomSnap: 0.5,
    });
    this._map.setView([0, 0], 1);
    this._overlayLayer = new MissionOverlayLayer(this._map);
    this.refresh();
  }

  destroy() {
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    if (this._container) this._container.innerHTML = '';
  }

  invalidateSize() {
    this._map?.invalidateSize();
  }

  setSessionId(sessionId) {
    this._sessionId = sessionId || '';
    this.refresh();
  }

  async refresh() {
    if (!this._map) return;
    this._hideError();
    const payload = await getCurrentOverlay(this._sessionId);
    if (!payload.ok) {
      this._showError(payload.error || 'fetch failed');
      this._overlayLayer.clear();
      this._showEmpty(true);
      return;
    }
    if (!payload.available) {
      this._overlayLayer.clear();
      this._showEmpty(true);
      return;
    }
    this._showEmpty(false);
    this._overlayLayer.render(payload);
    this._fitBounds(payload.bounds);
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
    refreshBtn.setAttribute('aria-label', 'Refresh mission overlay');
    refreshBtn.addEventListener('click', () => this.refresh());
    errorBanner.append(errorText, refreshBtn);
    this._errorBanner = errorBanner;
    this._errorText = errorText;

    const mapWrap = document.createElement('div');
    mapWrap.className = 'map-widget-wrap';

    const mapEl = document.createElement('div');
    mapEl.className = 'map-widget-map';
    this._mapEl = mapEl;

    const emptyState = document.createElement('div');
    emptyState.className = 'map-widget-empty';
    emptyState.setAttribute('aria-live', 'polite');
    emptyState.hidden = true;
    emptyState.innerHTML = '<p>No mission overlay yet.<br>Ask the agent to plan a mission.</p>';
    this._emptyState = emptyState;

    mapWrap.append(mapEl, emptyState);
    this._container.append(errorBanner, mapWrap);
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
}
