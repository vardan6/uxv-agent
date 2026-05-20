// Overlay coordinates are local scene metres {x, y, z}.
// Leaflet L.CRS.Simple uses [lat, lng] = [y, x] in Cartesian — pass [point.y, point.x] everywhere.

const STYLE_BY_STATUS = {
  proposed:          { dashed: true,  opacity: 1.0, fillOpacity: 0 },
  awaiting_approval: { dashed: true,  opacity: 1.0, fillOpacity: 0 },
  planning:          { dashed: true,  opacity: 1.0, fillOpacity: 0 },
  approved:          { dashed: false, opacity: 1.0, fillOpacity: 1 },
  exported:          { dashed: false, opacity: 1.0, fillOpacity: 1 },
  cutover_pending:   { dashed: false, opacity: 1.0, fillOpacity: 1 },
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

export class MissionOverlayLayer {
  constructor(map) {
    this._map = map;
    this._group = L.layerGroup().addTo(map);
  }

  render(payload, { color = DEFAULT_COLOR, opacity = null } = {}) {
    this._group.clearLayers();
    if (!payload?.available || !Array.isArray(payload.features)) return;

    const style = styleFor(payload.status);
    const lineOpacity = opacity ?? style.opacity;
    const fillOpacity = payload.status === 'proposed' || payload.status === 'awaiting_approval' || payload.status === 'planning'
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

  clear() {
    this._group.clearLayers();
  }

  remove() {
    this._map.removeLayer(this._group);
  }
}
