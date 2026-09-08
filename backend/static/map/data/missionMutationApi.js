// Wrappers for the four Phase 1D mutation endpoints plus GET single revision.
// All indices passed to the API are 1-based (server convention).

async function _safeFetch(url, opts) {
  try {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, status: res.status, error: data.detail || data.error || `HTTP ${res.status}`, ...data };
    }
    return { ok: true, ...data };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function getRevision(revisionId) {
  const raw = await _safeFetch(`/api/ai/mission-revisions/${encodeURIComponent(revisionId)}`);
  if (!raw.ok) return raw;
  // Normalize: endpoint may return { revision: {...} } or the revision dict directly.
  const revision = (raw.revision && raw.revision.id) ? raw.revision : raw;
  return { ok: true, ...revision };
}

export async function createClientRevision({ operation_id, waypoints, label = '', from_revision_id = '' }) {
  return _safeFetch('/api/ai/mission-revisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation_id, waypoints, label, from_revision_id }),
  });
}

// waypointIndex is 1-based.
export async function updateWaypoint(revisionId, waypointIndex, { point, expected_version }) {
  return _safeFetch(
    `/api/ai/mission-revisions/${encodeURIComponent(revisionId)}/waypoints/${waypointIndex}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ point, expected_version }),
    },
  );
}

// after_index: -1 = append, 0 = prepend, N = after the N-th waypoint (1-based).
export async function insertWaypoint(revisionId, { point, expected_version, after_index }) {
  return _safeFetch(
    `/api/ai/mission-revisions/${encodeURIComponent(revisionId)}/waypoints`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ point, expected_version, after_index }),
    },
  );
}

// waypointIndex is 1-based.
export async function deleteWaypoint(revisionId, waypointIndex, expected_version) {
  return _safeFetch(
    `/api/ai/mission-revisions/${encodeURIComponent(revisionId)}/waypoints/${waypointIndex}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version }),
    },
  );
}
