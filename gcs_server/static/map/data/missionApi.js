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
