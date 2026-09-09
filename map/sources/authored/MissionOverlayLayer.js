// Overlay coordinates are local scene metres {x, y, z}.
// Leaflet L.CRS.Simple uses [lat, lng] = [y, x] in Cartesian — pass [point.y, point.x] everywhere.

const ALT_SNAP_PX = 12; // screen-pixel radius for Alt-snap

function findSnapTarget(currentLl, waypoints, excludeIndex, map) {
  const currentPt = map.latLngToContainerPoint(currentLl);
  let bestDist = ALT_SNAP_PX;
  let bestLl = null;
  for (let j = 0; j < waypoints.length; j++) {
    if (j === excludeIndex) continue;
    const wp = waypoints[j];
    const pt = map.latLngToContainerPoint([wp.y, wp.x]);
    const dx = pt.x - currentPt.x;
    const dy = pt.y - currentPt.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < bestDist) {
      bestDist = dist;
      bestLl = L.latLng(wp.y, wp.x);
    }
  }
  return bestLl;
}

const STYLE_BY_STATUS = {
  proposed:        { dashed: true,  opacity: 1.0, fillOpacity: 0 },
  planning:        { dashed: true,  opacity: 1.0, fillOpacity: 0 },
  exported:        { dashed: false, opacity: 1.0, fillOpacity: 1 },
  cutover_pending: { dashed: false, opacity: 1.0, fillOpacity: 1 },
  executing:         { dashed: false, opacity: 1.0, fillOpacity: 1 },
  completed:         { dashed: false, opacity: 0.35, fillOpacity: 0.35 },
  superseded:        { dashed: false, opacity: 0.35, fillOpacity: 0.35 },
  rejected:          { dashed: false, opacity: 0.35, fillOpacity: 0.35 },
  validation_failed: { dashed: false, opacity: 0.35, fillOpacity: 0.35 },
};

const DEFAULT_COLOR = '#4a90d9';

function styleFor(status) {
  return STYLE_BY_STATUS[status] || STYLE_BY_STATUS.proposed;
}

function provenanceSuffix(provenance) {
  if (provenance === 'user') return '<span class="map-wp-prov-user" aria-hidden="true">👤</span>';
  if (provenance === 'ai+edited') return '<span class="map-wp-prov-edited" aria-hidden="true">✏</span>';
  return '';
}

const METRES_PER_DEG = 111320.0;

export class MissionOverlayLayer {
  constructor(map) {
    this._map = map;
    this._group = L.layerGroup().addTo(map);
    // Edit group is separate so renderMany does not clobber it.
    this._editGroup = L.layerGroup().addTo(map);
    // Geofence group is separate so renderMany does not clobber it.
    this._geofenceGroup = L.layerGroup().addTo(map);
  }

  render(payload, { color = DEFAULT_COLOR, opacity = null } = {}) {
    this._group.clearLayers();
    if (!payload?.available || !Array.isArray(payload.features)) return;

    const style = styleFor(payload.status);
    const lineOpacity = opacity ?? style.opacity;
    const fillOpacity = payload.status === 'proposed' || payload.status === 'planning'
      ? 0
      : (opacity ?? style.fillOpacity);
    const routeLines = payload.features.filter(f => f.type === 'route_line');
    const waypoints = payload.features.filter(f => f.type === 'waypoint');

    for (const feature of routeLines) {
      if (!Array.isArray(feature.points) || feature.points.length < 2) continue;
      L.polyline(feature.points.map(p => [p.y, p.x]), {
        color,
        weight: 2.5,
        opacity: lineOpacity,
        dashArray: style.dashed ? '6,6' : undefined,
        pane: 'missionPane',
      }).addTo(this._group);
    }

    for (const feature of waypoints) {
      const p = feature.point;
      if (!p) continue;
      L.circleMarker([p.y, p.x], {
        radius: 7,
        color,
        weight: 2,
        opacity: lineOpacity,
        fillColor: color,
        fillOpacity,
        pane: 'missionPane',
      }).addTo(this._group);

      const icon = L.divIcon({
        className: 'map-wp-badge',
        html: `<span style="background:${color}">${feature.index ?? ''}</span>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      });
      L.marker([p.y, p.x], { icon, interactive: false, pane: 'missionPane' }).addTo(this._group);
    }
  }

  renderMany(overlays = []) {
    this._group.clearLayers();
    for (const overlay of overlays) {
      if (!overlay?.payload?.available) continue;
      this._renderOverlay(overlay);
    }
  }

  _renderOverlay(overlay) {
    const nestedGroup = L.layerGroup().addTo(this._group);
    const originalGroup = this._group;
    this._group = nestedGroup;
    this.render(overlay.payload, { color: overlay.color || DEFAULT_COLOR, opacity: overlay.opacity });
    this._group = originalGroup;
  }

  // Renders the draggable edit layer for one revision. Separate from _group.
  renderEditable(waypoints, {
    color = DEFAULT_COLOR,
    selectedIndices = new Set(),
    isLocked = false,
    callbacks = {},
  } = {}) {
    this._editGroup.clearLayers();
    this._map.getContainer().style.cursor = isLocked ? 'not-allowed' : '';

    if (!waypoints || !waypoints.length) return;

    const { onDragEnd, onGhostClick, onMarkerClick, onMarkerRightClick, onDragStart } = callbacks;

    // Route polyline
    if (waypoints.length >= 2) {
      L.polyline(waypoints.map(wp => [wp.y, wp.x]), {
        color,
        weight: 3,
        opacity: 1,
        pane: 'missionPane',
      }).addTo(this._editGroup);
    }

    // Ghost markers (only when editable)
    if (!isLocked) {
      const addGhost = (lat, lng, afterIndex) => {
        const ghost = L.circleMarker([lat, lng], {
          radius: 5,
          color,
          weight: 1.5,
          opacity: 0.5,
          fillColor: color,
          fillOpacity: 0.3,
          interactive: true,
          pane: 'missionPane',
          className: 'map-wp-ghost',
        });
        ghost.on('click', (e) => {
          L.DomEvent.stopPropagation(e);
          if (onGhostClick) onGhostClick(afterIndex, { x: lng, y: lat, z: 0 });
        });
        ghost.addTo(this._editGroup);
      };

      // Midpoint ghosts between consecutive waypoints
      for (let i = 0; i < waypoints.length - 1; i++) {
        const wp1 = waypoints[i];
        const wp2 = waypoints[i + 1];
        // afterIndex is 1-based (API): insert after the (i+1)-th waypoint
        addGhost((wp1.y + wp2.y) / 2, (wp1.x + wp2.x) / 2, i + 1);
      }

      // End-cap ghosts: prepend (afterIndex=0) and append (afterIndex=N)
      if (waypoints.length >= 2) {
        const first = waypoints[0];
        const second = waypoints[1];
        addGhost(first.y - (second.y - first.y) / 2, first.x - (second.x - first.x) / 2, 0);

        const last = waypoints[waypoints.length - 1];
        const prev = waypoints[waypoints.length - 2];
        addGhost(last.y + (last.y - prev.y) / 2, last.x + (last.x - prev.x) / 2, waypoints.length);
      } else if (waypoints.length === 1) {
        // Single waypoint: place ghosts above and below
        addGhost(waypoints[0].y - 1, waypoints[0].x, 0);
        addGhost(waypoints[0].y + 1, waypoints[0].x, 1);
      }
    }

    // Waypoint markers
    for (let i = 0; i < waypoints.length; i++) {
      const wp = waypoints[i];
      const isSelected = selectedIndices.has(i);
      const badgeClass = [
        'map-wp-badge',
        isSelected ? 'map-wp-selected' : '',
        wp.provenance === 'user' ? 'map-wp-user' : '',
        wp.provenance === 'ai+edited' ? 'map-wp-ai-edited' : '',
      ].filter(Boolean).join(' ');

      const icon = L.divIcon({
        className: badgeClass,
        html: `<span style="background:${color}">${i + 1}${provenanceSuffix(wp.provenance)}</span>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      });

      const marker = L.marker([wp.y, wp.x], {
        icon,
        draggable: !isLocked,
        pane: 'missionPane',
      });

      if (!isLocked) {
        let preDragLatLng = null;
        let _snapLl = null;
        marker.on('dragstart', () => {
          preDragLatLng = marker.getLatLng();
          _snapLl = null;
          if (onDragStart) onDragStart(i);
        });
        marker.on('drag', (e) => {
          if (e.originalEvent?.altKey) {
            _snapLl = findSnapTarget(marker.getLatLng(), waypoints, i, this._map);
          } else {
            _snapLl = null;
          }
        });
        marker.on('dragend', () => {
          const ll = _snapLl || marker.getLatLng();
          _snapLl = null;
          if (onDragEnd) onDragEnd(i, { x: ll.lng, y: ll.lat, z: wp.z }, preDragLatLng, marker);
        });
      }

      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        if (onMarkerClick) onMarkerClick(i, e.originalEvent);
      });

      marker.on('contextmenu', (e) => {
        L.DomEvent.stopPropagation(e);
        L.DomEvent.preventDefault(e);
        if (onMarkerRightClick) onMarkerRightClick(i, e.originalEvent);
      });

      marker.addTo(this._editGroup);
    }
  }

  renderGeofence(geofence, origin) {
    this._geofenceGroup.clearLayers();
    const polygon = geofence?.polygon;
    if (!Array.isArray(polygon) || polygon.length < 3 || !origin) return;
    const cosLat = Math.cos(origin.lat * Math.PI / 180);
    const pts = polygon
      .filter((v) => Number.isFinite(v?.lat) && Number.isFinite(v?.lon))
      .map((v) => L.latLng(
        (v.lat - origin.lat) * METRES_PER_DEG,
        (v.lon - origin.lon) * METRES_PER_DEG * cosLat,
      ));
    if (pts.length < 3) return;
    L.polygon(pts, {
      color: '#8e44ad',
      weight: 2,
      fillColor: '#8e44ad',
      fillOpacity: 0.08,
      dashArray: '6 4',
      pane: 'missionPane',
    }).bindTooltip('Inclusion geofence', { direction: 'top', sticky: true })
      .addTo(this._geofenceGroup);
  }

  clearEditable() {
    this._editGroup.clearLayers();
    if (this._map) this._map.getContainer().style.cursor = '';
  }

  clear() {
    this._group.clearLayers();
  }

  remove() {
    this._map.removeLayer(this._group);
    this._map.removeLayer(this._editGroup);
    this._map.removeLayer(this._geofenceGroup);
  }
}
