// session_id="" or omitted → no session filter (returns ALL revisions globally).
// Always pass a real sessionId when known so results are scoped to the session.

export async function getCurrentOverlay(sessionId) {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  try {
    const res = await fetch(`/api/ai/mission-overlays/current${qs}`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, ...(data.overlay ?? data) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function listRevisions({ sessionId = '', limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  params.set('limit', String(limit));
  try {
    const res = await fetch(`/api/ai/mission-revisions?${params.toString()}`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// Flat Mission list (ADR 0021 §2): one row = one Mission, served by
// GET /api/ai/missions. Distinct from listRevisions, which returns the
// internal revision payload. userId="" matches the single-user default.
export async function listMissions({ userId = '', limit = 200 } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set('user_id', userId);
  params.set('limit', String(limit));
  try {
    const res = await fetch(`/api/ai/missions?${params.toString()}`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// POST /api/ai/missions: create a manual Mission, optionally with initial waypoints.
// Returns { ok, mission_id, operation_id, revision_id }.
export async function createMission({ name = 'New mission', userId = '', waypoints = null } = {}) {
  try {
    const body = { name, user_id: userId };
    if (Array.isArray(waypoints) && waypoints.length) body.waypoints = waypoints;
    const res = await fetch('/api/ai/missions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// POST /api/ai/missions/draw-pattern (Phase 4 authoring): persist an operator-
// drawn corridor/survey pattern as a new manual Mission. `points` are the drawn
// WGS84 vertices ({lat, lon}); the server converts them to the local frame, runs
// the generator, and bridges the result to a flat Mission.
export async function createDrawnPattern({ pattern, points, params = {}, name = '', sessionId = '' } = {}) {
  try {
    const res = await fetch('/api/ai/missions/draw-pattern', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pattern, points, params, name, session_id: sessionId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// Author or clear a Mission's inclusion geofence (Phase 5). `polygon` is the
// drawn WGS84 fence ({lat, lon} vertices, >= 3); pass `clear: true` to remove it.
export async function setMissionGeofence(missionId, { polygon = [], clear = false, sessionId = '' } = {}) {
  try {
    const body = clear ? { clear: true, session_id: sessionId } : { polygon, session_id: sessionId };
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}/geofence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// Mission-level overlay (ADR 0021 §2): keyed on the flat Mission id, served by
// GET /api/ai/missions/{id}/overlay, which resolves Mission -> active operation
// -> active revision server-side. This is the overlay source for the flat-Mission
// render path, replacing getRevisionOverlay's per-revision keying.
export async function getMissionOverlay(missionId) {
  try {
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}/overlay`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, ...(data.overlay ?? data) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function getRevisionOverlay(revisionId) {
  try {
    const res = await fetch(`/api/ai/mission-revisions/${encodeURIComponent(revisionId)}/overlay`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, ...(data.overlay ?? data) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function approveDraft(draftId, { note = '' } = {}) {
  try {
    const res = await fetch(`/api/ai/mission-drafts/${encodeURIComponent(draftId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note, execute_after_approval: false }),
    });
    let errDetail = `HTTP ${res.status}`;
    if (!res.ok) {
      try { errDetail = (await res.json()).detail || errDetail; } catch {}
      return { ok: false, status: res.status, error: errDetail };
    }
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function rejectDraft(draftId, { note = '' } = {}) {
  try {
    const res = await fetch(`/api/ai/mission-drafts/${encodeURIComponent(draftId)}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    });
    let errDetail = `HTTP ${res.status}`;
    if (!res.ok) {
      try { errDetail = (await res.json()).detail || errDetail; } catch {}
      return { ok: false, status: res.status, error: errDetail };
    }
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function executeMission(revisionId, { expectedControllerVersion = null } = {}) {
  try {
    const res = await fetch(`/api/ai/mission-revisions/${encodeURIComponent(revisionId)}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_controller_version: expectedControllerVersion }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return {
        ok: false,
        status: data.status || res.status,
        error: data.error || data.detail || `HTTP ${res.status}`,
        ...data,
      };
    }
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// Confirm-banner support (ADR 0021 §1). getExecutionState polls the in-flight
// run for a session; when status === 'awaiting_confirm' the banner shows a
// countdown (confirm_remaining_s) and a [Play] that calls confirmExecution.
export async function getExecutionState(sessionId) {
  if (!sessionId) return { ok: true, execution: null };
  try {
    const res = await fetch(`/api/ai/execution/state?session_id=${encodeURIComponent(sessionId)}`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function confirmExecution(sessionId) {
  return _postExecution('/api/ai/execution/confirm', sessionId);
}

export async function cancelExecution(sessionId) {
  return _postExecution('/api/ai/execution/cancel', sessionId);
}

async function _postExecution(url, sessionId) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, status: data.status || res.status, error: data.error || data.detail || `HTTP ${res.status}`, ...data };
    }
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function getControllerState() {
  try {
    const res = await fetch('/api/ai/controller-mission');
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// DELETE /api/ai/missions/{id}: remove a flat Mission permanently.
export async function deleteMission(missionId) {
  try {
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.detail || data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// PATCH /api/ai/missions/{id}: rename a flat Mission.
export async function renameMission(missionId, name) {
  try {
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.detail || data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// PATCH /api/ai/missions/{id} with {color}: persist the per-mission colour
// override server-side. Pass '' to clear it (falls back to the auto palette).
export async function setMissionColor(missionId, color) {
  try {
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ color: color || '' }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: data.detail || data.error || `HTTP ${res.status}` };
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}
