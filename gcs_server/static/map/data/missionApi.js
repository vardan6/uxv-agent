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
