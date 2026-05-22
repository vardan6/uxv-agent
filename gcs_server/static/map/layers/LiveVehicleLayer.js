// Subscribes to /ws telemetry and draws a heading-rotated vehicle marker in scene coordinates.
// position.x / position.y are local scene metres — same CRS as the mission overlays.
// Tolerates missing telemetry silently; call connect() / disconnect() to manage lifecycle.

export class LiveVehicleLayer {
  constructor(map) {
    this._map = map;
    this._marker = null;
    this._ws = null;
    this._active = false;
  }

  connect() {
    this._active = true;
    this._openSocket();
  }

  _openSocket() {
    if (this._ws) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${scheme}://${location.host}/ws?client_id=map-widget-vehicle-${Date.now()}`;
    try {
      this._ws = new WebSocket(url);
    } catch {
      return;
    }
    this._ws.addEventListener('message', (event) => {
      try {
        const msg = JSON.parse(event.data);
        let telemetry = null;
        if (msg.type === 'telemetry') telemetry = msg.data;
        else if (msg.type === 'snapshot') telemetry = msg.data?.telemetry;
        if (telemetry) this._updateMarker(telemetry);
      } catch {}
    });
    this._ws.addEventListener('close', () => {
      this._ws = null;
      if (this._active) setTimeout(() => this._openSocket(), 3000);
    });
    this._ws.addEventListener('error', () => {
      try { this._ws?.close(); } catch {}
    });
  }

  _updateMarker(telemetry) {
    const pos = telemetry?.position;
    if (typeof pos?.x !== 'number' || typeof pos?.y !== 'number') {
      this._hideMarker();
      return;
    }
    const heading = telemetry?.orientation?.heading_deg ?? 0;
    const ll = [pos.y, pos.x];
    if (!this._marker) {
      this._marker = L.marker(ll, {
        icon: this._makeIcon(heading),
        zIndexOffset: 1000,
        interactive: false,
      }).addTo(this._map);
    } else {
      this._marker.setLatLng(ll);
      this._marker.setIcon(this._makeIcon(heading));
    }
  }

  _makeIcon(heading) {
    return L.divIcon({
      className: '',
      html: `<div class="map-vehicle-marker" style="transform:rotate(${heading}deg)" aria-hidden="true"></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
  }

  _hideMarker() {
    if (this._marker) {
      this._marker.remove();
      this._marker = null;
    }
  }

  disconnect() {
    this._active = false;
    if (this._ws) {
      try { this._ws.close(); } catch {}
      this._ws = null;
    }
    this._hideMarker();
  }
}
