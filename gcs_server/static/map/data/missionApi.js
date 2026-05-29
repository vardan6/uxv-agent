// session_id="" or omitted → server returns an empty list (no global fallback).
// Always pass a real sessionId so results are scoped to the session.

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

export async function listMissions({ sessionId = '', limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  params.set('limit', String(limit));
  try {
    const res = await fetch(`/api/ai/missions?${params.toString()}`);
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, missions: data.missions || [] };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

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

export async function executeMission(missionId, { expectedControllerVersion = null } = {}) {
  try {
    const res = await fetch(`/api/ai/missions/${encodeURIComponent(missionId)}/execute`, {
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

export async function getControllerState() {
  try {
    const res = await fetch('/api/ai/controller-mission');
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}
