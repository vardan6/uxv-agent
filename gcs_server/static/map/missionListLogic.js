import { MISSION_COLOR_PALETTE } from './state/missionColorOverrides.js';

// Shape flat `missions` rows (GET /api/ai/missions) into display-ready
// descriptors: one row = one Mission (ADR 0021 §2). Pure; no fetching.
// `origin` here is provenance (manual|ai_chat), distinct from ADR 0022's
// coordinate-datum Origin.

// ✏️ = AI-created then edited in-place (client_version bumped by edit_in_place mode).
// 🤖 = AI-created, unmodified. 👤 = manually created.
function computeOriginBadge(origin, clientVersion) {
  if (origin === 'manual') return '👤';
  if (origin === 'ai_chat') return clientVersion > 1 ? '✏️' : '🤖';
  return '🤖';
}

export function mapMissionsForList(missions = []) {
  return (Array.isArray(missions) ? missions : []).map((m) => {
    const id = String(m.id || '');
    const index = Number.isFinite(m.mission_index) ? Number(m.mission_index) : null;
    const name = String(m.name || '').trim();
    const origin = String(m.origin || 'manual');
    const clientVersion = Number(m.client_version || 0);
    return {
      id,
      missionIndex: index,
      name: name || (index != null ? `Mission ${index}` : 'Untitled mission'),
      vehicleProfileId: String(m.vehicle_profile_id || ''),
      waypointCount: Math.max(0, Number(m.waypoint_count || 0)),
      origin,
      originBadge: computeOriginBadge(origin, clientVersion),
      originChatId: String(m.origin_chat_id || ''),
      clientVersion,
      createdAt: Number(m.created_at || 0),
      updatedAt: Number(m.updated_at || 0),
      // Active-revision resolution from the list endpoint (ADR 0021 §2): the
      // overlay/execute target and the status that gates edit/execute/locked
      // affordances. Empty when the Mission has no bridged active revision yet.
      activeRevisionId: String(m.active_revision_id || ''),
      activeRevisionStatus: String(m.active_revision_status || ''),
      sessionStatus: String(m.session_status || ''),
    };
  });
}

export function enforceVisibilityCap(visibleIds, max = 3, alwaysOn = []) {
  const forced = new Set(alwaysOn.filter(Boolean));
  const ordered = Array.from(visibleIds || []).filter(Boolean);
  while (ordered.length > max) {
    const removableIndex = ordered.findIndex((id) => !forced.has(id));
    if (removableIndex === -1) break;
    ordered.splice(removableIndex, 1);
  }
  for (const id of forced) {
    if (!ordered.includes(id)) ordered.push(id);
  }
  return ordered;
}

function missionPaletteOrder(missions = []) {
  return [...(Array.isArray(missions) ? missions : [])].sort((a, b) => {
    const aIndex = Number.isFinite(a?.missionIndex) ? Number(a.missionIndex) : Number.MAX_SAFE_INTEGER;
    const bIndex = Number.isFinite(b?.missionIndex) ? Number(b.missionIndex) : Number.MAX_SAFE_INTEGER;
    if (aIndex !== bIndex) return aIndex - bIndex;
    const aCreated = Number(a?.createdAt || 0);
    const bCreated = Number(b?.createdAt || 0);
    if (aCreated !== bCreated) return aCreated - bCreated;
    return String(a?.id || '').localeCompare(String(b?.id || ''));
  });
}

// overrides: plain object from missionColorOverrides.getAll(), keyed by mission id string.
// Auto colours are assigned over the full Mission set, not just the visible
// subset, so hidden/newly-created rows still get a stable stripe colour.
export function assignPaletteColor(missions, overrides = {}) {
  const palette = new Map();
  const ordered = missionPaletteOrder(missions);
  const used = new Set();
  const pending = [];

  ordered.forEach((mission) => {
    const missionId = String(mission?.id || '');
    if (!missionId) return;
    const override = String(overrides[missionId] || '').trim();
    if (override) {
      palette.set(missionId, override);
      used.add(override.toLowerCase());
      return;
    }
    pending.push(missionId);
  });

  const available = MISSION_COLOR_PALETTE.filter((color) => !used.has(color.toLowerCase()));
  pending.forEach((missionId, index) => {
    const color = available[index] || MISSION_COLOR_PALETTE[index % MISSION_COLOR_PALETTE.length];
    palette.set(missionId, color);
  });
  return palette;
}
