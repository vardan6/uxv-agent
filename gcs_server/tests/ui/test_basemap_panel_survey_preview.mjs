import test from 'node:test';
import assert from 'node:assert/strict';

import { BasemapPanel } from '../../static/map/ui/BasemapPanel.js';

// _reconcileSurveyPreview (O12) swaps the locally-drawn survey route line for
// the backend's actual generated geometry once `onPreviewPattern` resolves.
// Exercised directly on a bare prototype (no Leaflet/DOM), matching the
// pattern in test_map_widget_info_bar.mjs — the private method under test
// touches only plain objects (`_surveyRouteLineRef.setLatLngs`), never `L`.

function makePanel({ onPreviewPattern, spacing = 10, surveyHeading = 0 } = {}) {
  const panel = Object.create(BasemapPanel.prototype);
  panel._onPreviewPattern = onPreviewPattern;
  panel._sketchParams = { spacing, passes: 1 };
  panel._session = { tool: 'survey', surveyHeading };
  panel._surveyPreviewSeq = 0;
  panel._surveyPreviewAbort = null;
  const calls = [];
  panel._surveyRouteLineRef = { setLatLngs: (pts) => calls.push(pts) };
  return { panel, calls };
}

test('reconcileSurveyPreview replaces the route line with server geometry on success', async () => {
  const serverPoints = [{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }, { lat: 5, lon: 6 }];
  const { panel, calls } = makePanel({
    onPreviewPattern: async () => ({ ok: true, points: serverPoints }),
  });

  panel._reconcileSurveyPreview({ lat: 0, lon: 0 }, { lat: 1, lon: 1 });
  await new Promise((r) => setTimeout(r, 0));

  assert.deepEqual(calls, [[[1, 2], [3, 4], [5, 6]]]);
});

test('reconcileSurveyPreview sends pattern/points/params matching preview_drawn_pattern', async () => {
  let sentPayload = null;
  let sentOpts = null;
  const { panel } = makePanel({
    onPreviewPattern: async (payload, opts) => {
      sentPayload = payload;
      sentOpts = opts;
      return { ok: true, points: [] };
    },
    spacing: 12.5,
    surveyHeading: 90,
  });

  panel._reconcileSurveyPreview({ lat: 10, lon: 20 }, { lat: 30, lon: 40 });
  await new Promise((r) => setTimeout(r, 0));

  assert.deepEqual(sentPayload, {
    pattern: 'survey',
    points: [{ lat: 10, lon: 20 }, { lat: 30, lon: 40 }],
    params: { altitude_m: 0, line_spacing_m: 12.5, heading_deg: 90 },
  });
  assert.ok(sentOpts.signal instanceof AbortSignal);
});

test('reconcileSurveyPreview ignores a stale response superseded by a newer edit', async () => {
  let resolveFirst;
  const first = new Promise((resolve) => { resolveFirst = resolve; });
  const { panel, calls } = makePanel({
    onPreviewPattern: () => first,
  });

  panel._reconcileSurveyPreview({ lat: 0, lon: 0 }, { lat: 1, lon: 1 });
  // A second, newer edit settles before the first request resolves.
  panel._onPreviewPattern = async () => ({ ok: true, points: [{ lat: 9, lon: 9 }, { lat: 8, lon: 8 }] });
  panel._reconcileSurveyPreview({ lat: 2, lon: 2 }, { lat: 3, lon: 3 });
  await new Promise((r) => setTimeout(r, 0));

  resolveFirst({ ok: true, points: [{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }] });
  await new Promise((r) => setTimeout(r, 0));

  // Only the second (newer) response's geometry should ever land.
  assert.deepEqual(calls, [[[9, 9], [8, 8]]]);
});

test('reconcileSurveyPreview leaves the local preview untouched on failure', async () => {
  const { panel, calls } = makePanel({
    onPreviewPattern: async () => ({ ok: false, error: 'boom' }),
  });

  panel._reconcileSurveyPreview({ lat: 0, lon: 0 }, { lat: 1, lon: 1 });
  await new Promise((r) => setTimeout(r, 0));

  assert.deepEqual(calls, []);
});

test('reconcileSurveyPreview is a no-op when no onPreviewPattern is wired', () => {
  const { panel, calls } = makePanel({ onPreviewPattern: null });
  assert.doesNotThrow(() => panel._reconcileSurveyPreview({ lat: 0, lon: 0 }, { lat: 1, lon: 1 }));
  assert.deepEqual(calls, []);
});

test('reconcileSurveyPreview drops a response after the sketch left survey mode', async () => {
  const { panel, calls } = makePanel({
    onPreviewPattern: async () => ({ ok: true, points: [{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }] }),
  });

  panel._reconcileSurveyPreview({ lat: 0, lon: 0 }, { lat: 1, lon: 1 });
  panel._session.tool = 'fence';
  await new Promise((r) => setTimeout(r, 0));

  assert.deepEqual(calls, []);
});
