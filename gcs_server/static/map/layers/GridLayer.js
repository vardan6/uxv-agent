// Scene coordinate grid: 50m spacing, ported from the replay page.
// CRS.Simple: [lat=y, lng=x] (X east / Y north).

export class GridLayer {
  constructor(sceneMap) {
    this._sceneMap = sceneMap;
    this._group = null;
  }

  addTo(map) {
    if (!window.L || !this._sceneMap?.bounds) return this;
    const b = this._sceneMap.bounds;
    const group = L.layerGroup();

    const gridMinX = Math.ceil(b.min_x / 50) * 50;
    const gridMaxX = Math.floor(b.max_x / 50) * 50;
    const gridMinY = Math.ceil(b.min_y / 50) * 50;
    const gridMaxY = Math.floor(b.max_y / 50) * 50;

    for (let x = gridMinX; x <= gridMaxX; x += 50) {
      L.polyline(
        [[b.min_y, x], [b.max_y, x]],
        { color: '#f6efe4', weight: x === 0 ? 1.5 : 1, opacity: x === 0 ? 0.46 : 0.24, interactive: false },
      ).addTo(group);
    }
    for (let y = gridMinY; y <= gridMaxY; y += 50) {
      L.polyline(
        [[y, b.min_x], [y, b.max_x]],
        { color: '#f6efe4', weight: y === 0 ? 1.5 : 1, opacity: y === 0 ? 0.46 : 0.24, interactive: false },
      ).addTo(group);
    }

    group.addTo(map);
    this._group = group;
    return this;
  }

  remove() {
    this._group?.remove();
    this._group = null;
  }

  setVisible(visible) {
    if (!this._group) return;
    if (visible) {
      this._group.eachLayer((l) => { const el = l.getElement?.(); if (el) el.style.display = ''; });
    } else {
      this._group.eachLayer((l) => { const el = l.getElement?.(); if (el) el.style.display = 'none'; });
    }
  }
}
