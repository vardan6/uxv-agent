import { getCurrentOverlay, getRevisionOverlay, listRevisions } from './data/missionApi.js';
import { getActiveVehicleProfile, listVehicleProfiles } from './data/vehicleProfileApi.js';
import { MissionOverlayLayer } from './layers/MissionOverlayLayer.js';
import { groupRevisionsByOperation, enforceVisibilityCap, assignPaletteColor } from './missionListLogic.js';
import { MissionListPanel } from './ui/MissionListPanel.js';

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

function opacityForRevision(revisionId, focusedRevisionId) {
  if (!focusedRevisionId) return 1;
  return revisionId === focusedRevisionId ? 1 : 0.25;
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
    this._listPanel = null;
    this._mounted = false;
    this._revisionGroups = [];
    this._revisionCache = new Map();
    this._expandedOperationIds = new Set();
    this._visibleRevisionOrder = [];
    this._focusedRevisionId = '';
    this._activeProfileId = 'rover_default';
    this._profilesById = {};
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
    this._listPanel = new MissionListPanel(this._listEl, {
      onFocusRequested: (revisionId) => this.setFocus(revisionId),
      onVisibilityToggled: (revisionId) => this._toggleVisibility(revisionId),
      onExpandToggled: (operationId) => this._toggleExpand(operationId),
    });
    this._mounted = true;
    window.requestAnimationFrame(() => this.invalidateSize());
    this.refresh().catch((error) => this._showError(error?.message || 'Map refresh failed'));
  }

  destroy() {
    this._mounted = false;
    this._revisionCache.clear();
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
      this._revisionCache.clear();
      this._revisionGroups = [];
      this._expandedOperationIds.clear();
      this._visibleRevisionOrder = [];
      this._focusedRevisionId = '';
    }
    this.refresh();
  }

  async refresh() {
    if (!this._map) return;
    this._hideError();
    await this._loadVehicleProfiles();
    const revisionsPayload = await listRevisions({ sessionId: this._sessionId, limit: 100 });
    if (!revisionsPayload.ok) {
      this._showError(revisionsPayload.error || 'fetch failed');
      this._overlayLayer.clear();
      this._listPanel.render();
      this._showEmpty(true);
      return;
    }

    const groups = Array.from(groupRevisionsByOperation(revisionsPayload.revisions || []).values());
    this._revisionGroups = groups;
    this._syncVisibilityState(groups);
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
      console.warn('MapWidget: vehicle profiles unavailable, defaulting to rover_default');
    }
  }

  _syncVisibilityState(groups) {
    for (const group of groups) {
      if (localStorage.getItem(`mapWidget.expand.${group.operationId}`) === '1') {
        this._expandedOperationIds.add(group.operationId);
      }
    }
    const knownRevisionIds = new Set(groups.flatMap((group) => group.revisions.map((revision) => String(revision.id || ''))));
    this._visibleRevisionOrder = this._visibleRevisionOrder.filter((revisionId) => knownRevisionIds.has(revisionId));
    if (this._focusedRevisionId && !knownRevisionIds.has(this._focusedRevisionId)) {
      this._focusedRevisionId = '';
    }

    if (!this._visibleRevisionOrder.length) {
      const defaults = groups
        .map((group) => String(group.defaultRevisionId || ''))
        .filter(Boolean);
      const executingIds = groups
        .flatMap((group) => group.revisions)
        .filter((revision) => String(revision.status || '') === 'executing')
        .map((revision) => String(revision.id || ''));
      this._visibleRevisionOrder = enforceVisibilityCap(defaults, 3, executingIds);
      this._focusedRevisionId = this._visibleRevisionOrder[0] || '';
    }
  }

  async _primeVisibleOverlays() {
    const loads = this._visibleRevisionOrder.map(async (revisionId) => {
      if (this._revisionCache.has(revisionId)) return;
      const payload = await getRevisionOverlay(revisionId);
      if (payload.ok) {
        this._revisionCache.set(revisionId, payload);
      }
    });
    await Promise.all(loads);

    if (!this._revisionCache.size && this._sessionId) {
      const payload = await getCurrentOverlay(this._sessionId);
      if (payload.ok && payload.revision_id) {
        this._revisionCache.set(String(payload.revision_id), payload);
      }
    }
  }

  _render() {
    const visibleRevisionIds = new Set(this._visibleRevisionOrder);
    const paletteByRevisionId = assignPaletteColor(this._visibleRevisionOrder);
    this._listPanel.render({
      groups: this._revisionGroups,
      expandedOperationIds: this._expandedOperationIds,
      visibleRevisionIds,
      focusedRevisionId: this._focusedRevisionId,
      paletteByRevisionId,
      profilesById: this._profilesById,
      activeProfileId: this._activeProfileId,
    });

    const overlays = this._visibleRevisionOrder
      .map((revisionId) => {
        const payload = this._revisionCache.get(revisionId);
        if (!payload?.available) return null;
        return {
          revisionId,
          payload,
          color: paletteByRevisionId.get(revisionId),
          opacity: opacityForRevision(revisionId, this._focusedRevisionId),
        };
      })
      .filter(Boolean);

    this._overlayLayer.renderMany(overlays);
    const focusedPayload = this._focusedRevisionId ? this._revisionCache.get(this._focusedRevisionId) : null;
    const unionBounds = boundsUnion(overlays.map((entry) => entry.payload.bounds));
    this._fitBounds(focusedPayload?.bounds || unionBounds);
    this._showEmpty(!overlays.length);
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

  async _toggleVisibility(revisionId) {
    const executingIds = this._revisionGroups
      .flatMap((group) => group.revisions)
      .filter((revision) => String(revision.status || '') === 'executing')
      .map((revision) => String(revision.id || ''));
    if (this._visibleRevisionOrder.includes(revisionId)) {
      if (executingIds.includes(revisionId)) return;
      this._visibleRevisionOrder = this._visibleRevisionOrder.filter((id) => id !== revisionId);
      if (this._focusedRevisionId === revisionId) {
        this._focusedRevisionId = this._visibleRevisionOrder[0] || '';
      }
      this._render();
      return;
    }
    this._visibleRevisionOrder.push(revisionId);
    this._visibleRevisionOrder = enforceVisibilityCap(this._visibleRevisionOrder, 3, executingIds);
    if (!this._revisionCache.has(revisionId)) {
      const payload = await getRevisionOverlay(revisionId);
      if (payload.ok) this._revisionCache.set(revisionId, payload);
      else this._showError(payload.error || 'Overlay fetch failed');
    }
    if (!this._focusedRevisionId) this._focusedRevisionId = revisionId;
    this._render();
  }

  setFocus(revisionId) {
    this._focusedRevisionId = revisionId || '';
    this._render();
  }

  _toggleExpand(operationId) {
    const key = `mapWidget.expand.${operationId}`;
    if (this._expandedOperationIds.has(operationId)) {
      this._expandedOperationIds.delete(operationId);
      localStorage.setItem(key, '0');
    } else {
      this._expandedOperationIds.add(operationId);
      localStorage.setItem(key, '1');
    }
    this._render();
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
    refreshBtn.setAttribute('aria-label', 'Refresh mission overlays');
    refreshBtn.addEventListener('click', () => this.refresh());
    errorBanner.append(errorText, refreshBtn);
    this._errorBanner = errorBanner;
    this._errorText = errorText;

    const shell = document.createElement('div');
    shell.className = 'map-widget-shell';

    const listEl = document.createElement('div');
    listEl.className = 'map-widget-list';
    this._listEl = listEl;

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
    shell.append(listEl, mapWrap);
    this._container.append(errorBanner, shell);
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
