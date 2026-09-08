import test from 'node:test';
import assert from 'node:assert/strict';

import { MapWidget } from '../../static/map/MapWidget.js';

test('MapWidget hover info includes terrain ground z', () => {
  const widget = Object.create(MapWidget.prototype);
  widget._infoBarCoords = { textContent: '' };
  widget._infoBarGround = { textContent: '' };
  widget._infoBarGps = { textContent: '' };
  widget._sampleHeight = (x, y) => x - y / 2;
  widget._focusedOrigin = () => null;

  widget._onMapMouseMove({ latlng: { lng: 44, lat: 34 } });

  assert.equal(widget._infoBarCoords.textContent, 'x +44.00 m  y +34.00 m');
  assert.equal(widget._infoBarGround.textContent, 'ground z 27.00 m');
});
