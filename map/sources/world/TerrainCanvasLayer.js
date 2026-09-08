function colorBlend(a, b, t) {
  const r = Math.max(0, Math.min(1, t));
  return a.map((c, i) => Math.round(c * (1 - r) + b[i] * r));
}

function terrainColor(normalizedByte) {
  const ratio = Math.max(0, Math.min(1, normalizedByte / 255));
  if (ratio < 0.22) return colorBlend([22, 61, 35],   [55, 92, 54],    ratio / 0.22);
  if (ratio < 0.48) return colorBlend([55, 92, 54],   [106, 124, 71],  (ratio - 0.22) / 0.26);
  if (ratio < 0.72) return colorBlend([106, 124, 71], [135, 115, 79],  (ratio - 0.48) / 0.24);
  return               colorBlend([135, 115, 79], [173, 168, 158], (ratio - 0.72) / 0.28);
}

function buildDataUrl(sceneMap) {
  const grid = sceneMap.heightmap || [];
  const size = sceneMap.grid_size || grid.length || 0;
  if (!size || !grid.length) return null;

  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(size, size);

  for (let row = 0; row < size; row++) {
    const srcRow = grid[size - 1 - row] || [];
    for (let col = 0; col < size; col++) {
      const [r, g, b] = terrainColor(srcRow[col] ?? 0);
      const i = (row * size + col) * 4;
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL('image/png');
}

export class TerrainCanvasLayer {
  constructor(sceneMap, { opacity = 0.92, pane = 'terrainPane' } = {}) {
    this._sceneMap = sceneMap;
    this._opacity = opacity;
    this._paneName = pane;
    this._overlay = null;
  }

  addTo(map) {
    if (!window.L || !this._sceneMap) return this;

    if (!map.getPane(this._paneName)) {
      map.createPane(this._paneName);
      const paneEl = map.getPane(this._paneName);
      paneEl.style.zIndex = 180;
      paneEl.style.pointerEvents = 'none';
    }

    const dataUrl = buildDataUrl(this._sceneMap);
    if (!dataUrl) return this;

    const b = this._sceneMap.bounds;
    const bounds = [[b.min_y, b.min_x], [b.max_y, b.max_x]];
    this._overlay = L.imageOverlay(dataUrl, bounds, {
      opacity: this._opacity,
      pane: this._paneName,
      interactive: false,
    }).addTo(map);

    return this;
  }

  remove() {
    this._overlay?.remove();
    this._overlay = null;
  }

  setOpacity(opacity) {
    this._opacity = opacity;
    this._overlay?.setOpacity(opacity);
  }

  setVisible(visible) {
    this._overlay?.setOpacity(visible ? this._opacity : 0);
  }
}
