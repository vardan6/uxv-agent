// Read-only static-scene layer for the mission MapWidget: ports the replay
// page's scene render (roads, objects, spawn) from the `/api/replay/scene-map`
// payload so the 3d-env map shows standalone even with no mission focused.
// CRS is L.CRS.Simple with [lat=y, lng=x] (X east / Y north), matching replay.

function sceneObjectStyle(object) {
  const styles = {
    boulder: ['#71685b', 0.36],
    building: ['#8c6b4d', 0.38],
    charger: ['#f2b134', 0.72],
    guard_rail: ['#b8c1c5', 0.45],
    pad: ['#a88b64', 0.26],
    solar_frame: ['#8d969a', 0.22],
    solar_panel: ['#1e4f6d', 0.34],
    stone: ['#777267', 0.34],
    tree: ['#3d7b45', 0.32],
  };
  const [color, fillOpacity] = styles[object.kind] || ['#5b8a57', 0.28];
  return { color, fillOpacity };
}

export class SceneObjectsLayer {
  constructor(sceneMap, { pane = 'scenePane' } = {}) {
    this._sceneMap = sceneMap;
    this._paneName = pane;
    this._roadsGroup = null;
    this._objectsGroup = null;
  }

  addTo(map) {
    if (!window.L || !this._sceneMap) return this;

    if (!map.getPane(this._paneName)) {
      map.createPane(this._paneName);
      const paneEl = map.getPane(this._paneName);
      // Above terrain (180) but below the mission pane (470).
      paneEl.style.zIndex = 300;
    }

    const roadsGroup = L.layerGroup();
    const objectsGroup = L.layerGroup();
    const scene = this._sceneMap;

    for (const road of scene.roads || []) {
      L.polyline(
        [[road.from.y, road.from.x], [road.to.y, road.to.x]],
        {
          color: '#6f6559',
          weight: Math.max(3, Math.min(14, road.width || 9)),
          opacity: 0.42,
          lineCap: 'round',
          pane: this._paneName,
          interactive: false,
        },
      ).addTo(roadsGroup);
    }

    for (const object of scene.objects || []) {
      if (object.metadata?.visible === false) continue;
      const halfWidth = object.pad_half_extents?.x ?? (object.size?.width || 0) / 2;
      const halfHeight = object.pad_half_extents?.y ?? (object.size?.height || 0) / 2;
      const minX = object.center.x - halfWidth;
      const maxX = object.center.x + halfWidth;
      const minY = object.center.y - halfHeight;
      const maxY = object.center.y + halfHeight;
      const { color, fillOpacity } = sceneObjectStyle(object);
      L.rectangle(
        [[minY, minX], [maxY, maxX]],
        {
          color,
          weight: 1.5,
          fillColor: color,
          fillOpacity,
          pane: this._paneName,
        },
      )
        .bindTooltip(`${object.label} • ${object.model_ref}`, { direction: 'top' })
        .addTo(objectsGroup);
    }

    if (scene.spawn) {
      L.circleMarker([scene.spawn.y, scene.spawn.x], {
        radius: 6,
        color: '#ffffff',
        weight: 2,
        fillColor: '#f2b134',
        fillOpacity: 0.95,
        pane: this._paneName,
      })
        .bindTooltip('Spawn', { direction: 'top' })
        .addTo(objectsGroup);
    }

    roadsGroup.addTo(map);
    objectsGroup.addTo(map);
    this._roadsGroup = roadsGroup;
    this._objectsGroup = objectsGroup;
    return this;
  }

  remove() {
    this._roadsGroup?.remove();
    this._objectsGroup?.remove();
    this._roadsGroup = null;
    this._objectsGroup = null;
  }

  setRoadsVisible(visible) {
    if (!this._roadsGroup) return;
    const paneEl = this._roadsGroup._map?.getPane('scenePane');
    if (!paneEl) return;
    // Toggle via group container opacity — roads and objects share the pane,
    // so manipulate each group's layers directly via style on their SVG paths.
    this._roadsGroup.eachLayer((l) => {
      const el = l.getElement?.();
      if (el) el.style.display = visible ? '' : 'none';
    });
  }

  setObjectsVisible(visible) {
    if (!this._objectsGroup) return;
    this._objectsGroup.eachLayer((l) => {
      const el = l.getElement?.();
      if (el) el.style.display = visible ? '' : 'none';
    });
  }
}
