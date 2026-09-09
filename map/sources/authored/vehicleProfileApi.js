export async function getActiveVehicleProfile() {
  try {
    const res = await fetch('/api/vehicle-profile/active');
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, ...(data.profile ? data : { profile: data }) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}

export async function listVehicleProfiles() {
  try {
    const res = await fetch('/api/vehicle-profiles');
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, ...(data.profiles ? data : { profiles: [] }) };
  } catch (err) {
    return { ok: false, error: err.message || 'Network error' };
  }
}
