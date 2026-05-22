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

export async function getControllerState() {
  try {
    const res = await fetch('/api/ai/controller-mission');
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    return { ok: true, ...(await res.json()) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}
