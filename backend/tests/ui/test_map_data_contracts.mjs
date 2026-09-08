import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createMission,
  getCurrentOverlay,
  getMissionOverlay,
  listMissions,
  previewDrawnPattern,
  setMissionGeofence,
} from '../../../map/sources/authored/missionApi.js';
import {
  deleteWaypoint,
  getRevision,
  insertWaypoint,
  updateWaypoint,
} from '../../../map/sources/authored/missionMutationApi.js';
import {
  deleteConstraint,
  updateConstraint,
} from '../../../map/sources/authored/constraintsApi.js';

function response(data, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async json() { return data; },
  };
}

async function captureFetch(run, result = {}) {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return response(result);
  };
  try {
    return { value: await run(), calls };
  } finally {
    globalThis.fetch = previousFetch;
  }
}

test('mission list and overlay reads preserve query scoping and normalize wrappers', async () => {
  const listed = await captureFetch(
    () => listMissions({ userId: 'operator/a', limit: 25 }),
    { missions: [{ id: 'one' }] },
  );
  assert.equal(listed.calls[0].url, '/api/ai/missions?user_id=operator%2Fa&limit=25');
  assert.deepEqual(listed.value, { ok: true, missions: [{ id: 'one' }] });

  const current = await captureFetch(
    () => getCurrentOverlay('session/a'),
    { overlay: { available: true, revision_id: 'revision-one' } },
  );
  assert.equal(current.calls[0].url, '/api/ai/mission-overlays/current?session_id=session%2Fa');
  assert.deepEqual(current.value, { ok: true, available: true, revision_id: 'revision-one' });

  const missionOverlay = await captureFetch(
    () => getMissionOverlay('mission/a'),
    { overlay: { available: false } },
  );
  assert.equal(missionOverlay.calls[0].url, '/api/ai/missions/mission%2Fa/overlay');
  assert.deepEqual(missionOverlay.value, { ok: true, available: false });
});

test('mission creation and geofence writes keep their backend payload shapes', async () => {
  const created = await captureFetch(
    () => createMission({ name: 'Survey', userId: 'operator', waypoints: [] }),
    { mission_id: 'mission-one' },
  );
  assert.equal(created.calls[0].url, '/api/ai/missions');
  assert.deepEqual(created.calls[0].options, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'Survey', user_id: 'operator' }),
  });
  assert.deepEqual(created.value, { ok: true, mission_id: 'mission-one' });

  const fenced = await captureFetch(
    () => setMissionGeofence('mission/one', {
      polygon: [{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }, { lat: 5, lon: 6 }],
      sessionId: 'session-one',
    }),
    { revision_id: 'revision-two' },
  );
  assert.equal(fenced.calls[0].url, '/api/ai/missions/mission%2Fone/geofence');
  assert.deepEqual(JSON.parse(fenced.calls[0].options.body), {
    polygon: [{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }, { lat: 5, lon: 6 }],
    session_id: 'session-one',
  });
});

test('draw-pattern preview forwards AbortSignal and classifies cancellation', async () => {
  const controller = new AbortController();
  const sent = await captureFetch(
    () => previewDrawnPattern(
      { pattern: 'corridor', points: [{ lat: 1, lon: 2 }], params: { width_m: 4 } },
      { signal: controller.signal },
    ),
    { points: [{ lat: 1, lon: 2 }] },
  );
  assert.equal(sent.calls[0].url, '/api/ai/missions/draw-pattern/preview');
  assert.equal(sent.calls[0].options.signal, controller.signal);
  assert.deepEqual(JSON.parse(sent.calls[0].options.body), {
    pattern: 'corridor',
    points: [{ lat: 1, lon: 2 }],
    params: { width_m: 4 },
  });

  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new DOMException('cancelled', 'AbortError'); };
  try {
    assert.deepEqual(await previewDrawnPattern(), { ok: false, aborted: true });
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('revision mutations retain encoded ids, 1-based indices, and CAS versions', async () => {
  const updated = await captureFetch(
    () => updateWaypoint('revision/a', 2, {
      point: { lat: 1, lon: 2 },
      expected_version: 7,
    }),
    { client_version: 8 },
  );
  assert.equal(updated.calls[0].url, '/api/ai/mission-revisions/revision%2Fa/waypoints/2');
  assert.equal(updated.calls[0].options.method, 'PATCH');
  assert.deepEqual(JSON.parse(updated.calls[0].options.body), {
    point: { lat: 1, lon: 2 },
    expected_version: 7,
  });

  const inserted = await captureFetch(
    () => insertWaypoint('revision/a', {
      point: { x: 3, y: 4, z: 5 },
      expected_version: 8,
      after_index: 0,
    }),
    {},
  );
  assert.equal(inserted.calls[0].url, '/api/ai/mission-revisions/revision%2Fa/waypoints');
  assert.equal(inserted.calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(inserted.calls[0].options.body), {
    point: { x: 3, y: 4, z: 5 },
    expected_version: 8,
    after_index: 0,
  });

  const deleted = await captureFetch(
    () => deleteWaypoint('revision/a', 3, 9),
    {},
  );
  assert.equal(deleted.calls[0].url, '/api/ai/mission-revisions/revision%2Fa/waypoints/3');
  assert.equal(deleted.calls[0].options.method, 'DELETE');
  assert.deepEqual(JSON.parse(deleted.calls[0].options.body), { expected_version: 9 });
});

test('single-revision read unwraps the server envelope', async () => {
  const result = await captureFetch(
    () => getRevision('revision/one'),
    { revision: { id: 'revision/one', client_version: 4 } },
  );

  assert.equal(result.calls[0].url, '/api/ai/mission-revisions/revision%2Fone');
  assert.deepEqual(result.value, { ok: true, id: 'revision/one', client_version: 4 });
});

test('constraint writes send only supplied fields and carry expected versions', async () => {
  const updated = await captureFetch(
    () => updateConstraint('constraint/a', {
      expectedVersion: 3,
      name: 'New name',
      enabled: false,
    }),
    { constraint: { id: 'constraint/a', version: 4 } },
  );
  assert.equal(updated.calls[0].url, '/api/operational-constraints/constraint%2Fa');
  assert.equal(updated.calls[0].options.method, 'PUT');
  assert.deepEqual(JSON.parse(updated.calls[0].options.body), {
    expected_version: 3,
    name: 'New name',
    enabled: false,
  });

  const deleted = await captureFetch(
    () => deleteConstraint('constraint/a', { expectedVersion: 4 }),
    {},
  );
  assert.equal(deleted.calls[0].url, '/api/operational-constraints/constraint%2Fa?expected_version=4');
  assert.deepEqual(deleted.calls[0].options, { method: 'DELETE' });
});

test('map API adapters return structured failures instead of throwing', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => response({ detail: 'stale version' }, { ok: false, status: 409 });
  try {
    assert.deepEqual(
      await updateWaypoint('revision-one', 1, { point: {}, expected_version: 2 }),
      { ok: false, status: 409, error: 'stale version', detail: 'stale version' },
    );
  } finally {
    globalThis.fetch = previousFetch;
  }

  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    assert.deepEqual(await listMissions(), { ok: false, error: 'offline' });
  } finally {
    globalThis.fetch = previousFetch;
  }
});
