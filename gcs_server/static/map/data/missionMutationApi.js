// Wrappers for flat Mission mutation endpoints plus GET single mission.
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

export async function getMission(missionId) {
  const raw = await _safeFetch(`/api/ai/missions/${encodeURIComponent(missionId)}`);
  if (!raw.ok) return raw;
  const mission = (raw.mission && raw.mission.id) ? raw.mission : raw;
  return { ok: true, ...mission };
}

export async function createMission({ operation_id, waypoints, label = '', from_mission_id = '', session_id = '' }) {
  return _safeFetch('/api/ai/missions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation_id, waypoints, label, from_mission_id, session_id }),
  });
}

// waypointIndex is 1-based.
export async function updateMissionWaypoint(missionId, waypointIndex, { point, expected_version }) {
  return _safeFetch(
    `/api/ai/missions/${encodeURIComponent(missionId)}/waypoints/${waypointIndex}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ point, expected_version }),
    },
  );
}

// after_index: -1 = append, 0 = prepend, N = after the N-th waypoint (1-based).
export async function insertMissionWaypoint(missionId, { point, expected_version, after_index }) {
  return _safeFetch(
    `/api/ai/missions/${encodeURIComponent(missionId)}/waypoints`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ point, expected_version, after_index }),
    },
  );
}

export async function deleteMission(missionId) {
  return _safeFetch(`/api/ai/missions/${encodeURIComponent(missionId)}`, {
    method: 'DELETE',
  });
}

export async function restoreMission(missionId) {
  return _safeFetch(`/api/ai/missions/${encodeURIComponent(missionId)}/restore`, {
    method: 'POST',
  });
}

// waypointIndex is 1-based.
export async function deleteMissionWaypoint(missionId, waypointIndex, expected_version) {
  return _safeFetch(
    `/api/ai/missions/${encodeURIComponent(missionId)}/waypoints/${waypointIndex}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version }),
    },
  );
}
