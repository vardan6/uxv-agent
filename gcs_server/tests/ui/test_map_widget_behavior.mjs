import test from 'node:test';
import assert from 'node:assert/strict';

import { MapWidget as PublicMapWidget } from '../../static/map/index.js';
import { MapWidget } from '../../static/map/MapWidget.js';

function mission(id, status = 'proposed', revisionId = `revision-${id}`) {
  return {
    id,
    name: `Mission ${id}`,
    activeRevisionId: revisionId,
    activeRevisionStatus: status,
  };
}

function makeRenderableWidget() {
  const widget = new MapWidget(null);
  const rendered = [];
  const fits = [];
  const emptyStates = [];

  widget._listPanel = { renderMissions() {} };
  widget._overlayLayer = {
    renderMany(overlays) { rendered.push(overlays); },
    renderGeofence() {},
  };
  widget._renderSceneConstraints = () => {};
  widget._fitBounds = (bounds) => fits.push(bounds);
  widget._updateFitButtons = () => {};
  widget._showEmpty = (show) => emptyStates.push(show);
  widget._updateElevationProfile = () => {};
  widget._syncAuthoringToolbarState = () => {};

  return { widget, rendered, fits, emptyStates };
}

test('map package entry point keeps exporting MapWidget', () => {
  assert.equal(PublicMapWidget, MapWidget);
});

test('first mission sync makes every mission visible and focuses the first', () => {
  const widget = new MapWidget(null);
  const missions = [mission('one'), mission('two')];

  widget._syncVisibilityState(missions);

  assert.deepEqual(widget._visibleMissionOrder, ['one', 'two']);
  assert.equal(widget._focusedMissionId, 'one');
  assert.deepEqual(widget._selectedMissionIds, new Set());
});

test('later mission sync prunes removed state and promotes the newest mission', () => {
  const widget = new MapWidget(null);
  widget._visibleMissionOrder = ['removed', 'one'];
  widget._focusedMissionId = 'removed';
  widget._selectedMissionIds = new Set(['removed', 'one']);
  widget._selectionAnchorId = 'removed';
  widget._seenMissionIds = new Set(['removed', 'one']);

  widget._syncVisibilityState([mission('one'), mission('two'), mission('three')]);

  assert.deepEqual(widget._visibleMissionOrder, ['one', 'two', 'three']);
  assert.equal(widget._focusedMissionId, 'three');
  assert.deepEqual(widget._selectedMissionIds, new Set(['one']));
  assert.equal(widget._selectionAnchorId, '');
});

test('executing missions cannot be hidden and survive hide-all', async () => {
  const widget = new MapWidget(null);
  widget._missions = [mission('draft'), mission('running', 'executing')];
  widget._visibleMissionOrder = ['draft', 'running'];
  widget._focusedMissionId = 'draft';
  let renders = 0;
  widget._render = () => { renders += 1; };

  await widget._toggleVisibility('running');
  assert.deepEqual(widget._visibleMissionOrder, ['draft', 'running']);
  assert.equal(renders, 0);

  widget._hideAllMissions();
  assert.deepEqual(widget._visibleMissionOrder, ['running']);
  assert.equal(widget._focusedMissionId, 'running');
  assert.equal(widget._skipAutoFitOnce, true);
  assert.equal(renders, 1);
});

test('delete guards cover armed session states and executing revisions', () => {
  const widget = new MapWidget(null);
  widget._missionsById = new Map([
    ['draft', mission('draft')],
    ['executing', mission('executing', 'executing')],
  ]);

  widget._executionState = { mission_id: 'draft', status: 'awaiting_confirm' };
  assert.deepEqual(widget._deleteGuardedMissionIds(), new Set(['draft']));
  assert.equal(widget._isMissionDeleteBlocked('draft'), true);
  assert.equal(widget._isMissionDeleteBlocked('executing'), true);

  widget._executionState = { mission_id: 'draft', status: 'completed' };
  assert.deepEqual(widget._deleteGuardedMissionIds(), new Set());
  assert.equal(widget._isMissionDeleteBlocked('draft'), false);
  assert.equal(widget._isMissionDeleteBlocked('missing'), false);
});

test('mission identity helpers preserve the Mission-to-active-revision seam', () => {
  const widget = new MapWidget(null);
  widget._missions = [mission('one'), mission('two', 'proposed', 'revision-special')];
  widget._missionsById = new Map(widget._missions.map((row) => [row.id, row]));

  assert.equal(widget._activeRevisionIdFor('two'), 'revision-special');
  assert.equal(widget._activeRevisionIdFor('missing'), '');
  assert.equal(widget._missionIdForRevision('revision-special'), 'two');
  assert.equal(widget._missionIdForRevision('missing'), '');
});

test('render auto-fits once per logical target and treats a loaded scene as content', () => {
  const { widget, rendered, fits, emptyStates } = makeRenderableWidget();
  const sceneBounds = { min_x: -5, max_x: 5, min_y: -10, max_y: 10 };
  widget._sceneBounds = sceneBounds;

  widget._render();
  widget._render();

  assert.equal(rendered.length, 2);
  assert.deepEqual(fits, [sceneBounds]);
  assert.deepEqual(emptyStates, [false, false]);
  assert.equal(widget._lastFitKey, 'scene');

  const focusedBounds = { min_x: 1, max_x: 3, min_y: 2, max_y: 4 };
  widget._missions = [mission('focused')];
  widget._focusedMissionId = 'focused';
  widget._visibleMissionOrder = ['focused'];
  widget._overlayCacheByMissionId.set('focused', { available: true, bounds: focusedBounds });

  widget._render();
  widget._render();

  assert.deepEqual(fits, [sceneBounds, focusedBounds]);
  assert.equal(widget._lastFitKey, 'focused');
});

test('fit bounds uses a stable point zoom and padded bounds for an area', () => {
  const widget = new MapWidget(null);
  const calls = [];
  widget._map = {
    setView(point, zoom) { calls.push({ kind: 'point', point, zoom }); },
    fitBounds(bounds, options) { calls.push({ kind: 'area', bounds, options }); },
  };

  widget._fitBounds({ min_x: 7, max_x: 7, min_y: 8, max_y: 8 });
  widget._fitBounds({ min_x: -2, max_x: 4, min_y: -3, max_y: 5 });

  assert.deepEqual(calls, [
    { kind: 'point', point: [8, 7], zoom: 3 },
    {
      kind: 'area',
      bounds: [[-3, -2], [5, 4]],
      options: { padding: [28, 28] },
    },
  ]);
});

test('keyboard shortcuts ignore text-entry controls and open help elsewhere', () => {
  const widget = new MapWidget(null);
  let helpShown = 0;
  let prevented = 0;
  widget._keyboardHelp = { show() { helpShown += 1; } };

  widget._handleMapKeydown({
    key: '?',
    target: { tagName: 'TEXTAREA' },
    preventDefault() { prevented += 1; },
  });
  assert.equal(helpShown, 0);
  assert.equal(prevented, 0);

  widget._handleMapKeydown({
    key: '?',
    target: { tagName: 'DIV' },
    preventDefault() { prevented += 1; },
  });
  assert.equal(helpShown, 1);
  assert.equal(prevented, 1);
});

test('info bar derives WGS84 from the focused mission origin', () => {
  const widget = new MapWidget(null);
  widget._infoBarCoords = { textContent: '' };
  widget._infoBarGround = { textContent: '' };
  widget._infoBarGps = { textContent: '' };
  widget._sampleHeight = () => Number.NaN;
  widget._focusedMissionId = 'one';
  widget._overlayCacheByMissionId.set('one', {
    origin: { lat: 0, lon: 0, alt: 0 },
  });

  widget._onMapMouseMove({ latlng: { lng: -111320, lat: 111320 } });

  assert.equal(widget._infoBarCoords.textContent, 'x -111320.00 m  y +111320.00 m');
  assert.equal(widget._infoBarGround.textContent, '');
  assert.equal(widget._infoBarGps.textContent, '1.000000°N  1.000000°W');
});

test('selection info shows one waypoint only and keeps provenance visible', () => {
  const widget = new MapWidget(null);
  widget._infoBarSel = { textContent: '' };

  widget._updateInfoBarSelection({
    selectedIndices: new Set([1]),
    waypoints: [
      { z: 1, provenance: 'ai' },
      { z: 12.5, provenance: 'ai+edited' },
    ],
  });
  assert.equal(widget._infoBarSel.textContent, 'WP 2 · AI+edited · z 12.50 m');

  widget._updateInfoBarSelection({
    selectedIndices: new Set([0, 1]),
    waypoints: [],
  });
  assert.equal(widget._infoBarSel.textContent, '');
});
