// Operational constraints client (ADR 0025, V2 contract).
//
// Allowed corridors (stay-inside) and blockages (stay-outside) are deployment-
// wide *planning* data — distinct from the per-mission geofence and the mission
// revision path. `hard` means the planner rejects a violating route; it is not a
// live runtime containment guarantee, so the UI labels this "Planning constraints".
//
// Every call resolves to `{ ok, ... }` and never throws, mirroring missionApi.js.

function _errorOf(data, status) {
  return data.detail || data.error || `HTTP ${status}`;
}

export async function listConstraints() {
  try {
    const res = await fetch('/api/operational-constraints');
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: _errorOf(data, res.status) };
    return { ok: true, constraints: Array.isArray(data.constraints) ? data.constraints : [] };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function createConstraint({ kind, name, polygon = [], rule = 'hard', enabled = true } = {}) {
  try {
    const res = await fetch('/api/operational-constraints', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, name, polygon, rule, enabled }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: _errorOf(data, res.status) };
    return { ok: true, constraint: data.constraint };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

// Patch a constraint under optimistic concurrency. Only supplied fields change;
// a stale `expectedVersion` resolves to `{ ok: false, status: 409 }`.
export async function updateConstraint(id, { expectedVersion, name, polygon, rule, enabled } = {}) {
  try {
    const body = { expected_version: expectedVersion };
    if (name !== undefined) body.name = name;
    if (polygon !== undefined) body.polygon = polygon;
    if (rule !== undefined) body.rule = rule;
    if (enabled !== undefined) body.enabled = enabled;
    const res = await fetch(`/api/operational-constraints/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: _errorOf(data, res.status) };
    return { ok: true, constraint: data.constraint };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function deleteConstraint(id, { expectedVersion } = {}) {
  try {
    const params = new URLSearchParams({ expected_version: String(expectedVersion) });
    const res = await fetch(
      `/api/operational-constraints/${encodeURIComponent(id)}?${params.toString()}`,
      { method: 'DELETE' },
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, status: res.status, error: _errorOf(data, res.status) };
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}
