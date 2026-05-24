let _cache = null;

export async function fetchSceneMap(gridSize = 128) {
  if (_cache) return _cache;
  try {
    const res = await fetch(`/api/replay/scene-map?grid_size=${gridSize}`);
    if (!res.ok) return null;
    _cache = await res.json();
    return _cache;
  } catch {
    return null;
  }
}

export function makeSampler(sceneMap) {
  if (!sceneMap || !sceneMap.heightmap) return () => 0;
  const { heightmap, height_range, bounds, grid_size } = sceneMap;
  const minH = height_range.min;
  const span = (height_range.max - height_range.min) || 1;
  const gs = grid_size || heightmap.length;
  const minX = bounds.min_x;
  const minY = bounds.min_y;
  const rangeX = bounds.max_x - bounds.min_x || 1;
  const rangeY = bounds.max_y - bounds.min_y || 1;

  return function sampleHeight(x, y) {
    const col = ((x - minX) / rangeX) * (gs - 1);
    const row = ((y - minY) / rangeY) * (gs - 1);
    const c0 = Math.max(0, Math.min(gs - 2, Math.floor(col)));
    const c1 = c0 + 1;
    const r0 = Math.max(0, Math.min(gs - 2, Math.floor(row)));
    const r1 = r0 + 1;
    const tc = col - c0;
    const tr = row - r0;
    const n = heightmap[r0][c0] * (1 - tc) * (1 - tr)
            + heightmap[r0][c1] * tc * (1 - tr)
            + heightmap[r1][c0] * (1 - tc) * tr
            + heightmap[r1][c1] * tc * tr;
    return minH + (n / 255) * span;
  };
}
