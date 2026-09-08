import test from 'node:test';
import assert from 'node:assert/strict';

import { MapSketchSession } from '../../static/map/MapSketchSession.js';
import { makeSampler } from '../../static/map/data/terrainApi.js';

test('MapSketchSession publishes defensive snapshots and supports unsubscribe', () => {
  const session = new MapSketchSession();
  let notifications = 0;
  const unsubscribe = session.onChange(() => { notifications += 1; });

  session.startTool('corridor');
  session.addVertex({ lat: 1, lng: 2 });
  const vertices = session.vertices;
  vertices.push({ lat: 99, lon: 99 });

  assert.equal(notifications, 2);
  assert.deepEqual(session.vertices, [{ lat: 1, lon: 2 }]);
  assert.deepEqual(session.getState(), {
    drawMode: 'corridor',
    drawPointCount: 1,
    statusText: '',
    constraintKind: null,
    constraintRule: null,
    surveyHeading: 0,
  });

  unsubscribe();
  session.addVertex({ lat: 3, lon: 4 });
  assert.equal(notifications, 2);
});

test('MapSketchSession undo restores vertices across add and move operations', () => {
  const session = new MapSketchSession();
  session.startTool('fence');
  session.addVertex({ lat: 1, lon: 2 });
  session.addVertex({ lat: 3, lon: 4 });
  session.moveVertex(0, { lat: 5, lon: 6 });

  assert.deepEqual(session.vertices, [{ lat: 5, lon: 6 }, { lat: 3, lon: 4 }]);
  session.undoVertex();
  assert.deepEqual(session.vertices, [{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }]);
  session.undoVertex();
  assert.deepEqual(session.vertices, [{ lat: 1, lon: 2 }]);
});

test('survey sketch keeps two corners and normalizes heading', () => {
  const session = new MapSketchSession();
  session.startTool('survey');
  session.setSurveyHeading(-90);
  session.addVertex({ lat: 1, lon: 1 });
  session.addVertex({ lat: 2, lon: 2 });

  assert.equal(session.surveyHeading, 270);
  assert.deepEqual(session.vertices, [{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }]);

  session.addVertex({ lat: 3, lon: 3 });
  assert.deepEqual(session.vertices, [{ lat: 3, lon: 3 }]);

  session.undoVertex();
  assert.deepEqual(session.vertices, []);
  session.undoVertex();
  assert.deepEqual(session.vertices, [{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }]);
});

test('constraint edit state copies metadata and vertices before reset', () => {
  const session = new MapSketchSession();
  const metadata = { kind: 'blockage', rule: 'hard' };
  const vertices = [{ lat: 10, lon: 20 }];

  session.startToolWithVertices('constraint', metadata, vertices);
  metadata.rule = 'soft';
  vertices[0].lat = 99;

  assert.deepEqual(session.constraintMeta, { kind: 'blockage', rule: 'hard' });
  assert.deepEqual(session.vertices, [{ lat: 10, lon: 20 }]);
  assert.equal(session.isDirty, true);

  session.setStatus('Saving…');
  session.reset();
  assert.equal(session.isDirty, false);
  assert.deepEqual(session.vertices, []);
  assert.deepEqual(session.getState(), {
    drawMode: null,
    drawPointCount: 0,
    statusText: '',
    constraintKind: null,
    constraintRule: null,
    surveyHeading: 0,
  });
});

test('terrain sampler bilinearly interpolates encoded height values', () => {
  const sample = makeSampler({
    heightmap: [[0, 255], [255, 0]],
    height_range: { min: 10, max: 30 },
    bounds: { min_x: 0, max_x: 10, min_y: 0, max_y: 10 },
    grid_size: 2,
  });

  assert.equal(sample(0, 0), 10);
  assert.equal(sample(10, 0), 30);
  assert.equal(sample(0, 10), 30);
  assert.equal(sample(5, 5), 20);
});

test('terrain sampler safely falls back when no heightmap is available', () => {
  assert.equal(makeSampler(null)(123, 456), 0);
  assert.equal(makeSampler({})(123, 456), 0);
});
