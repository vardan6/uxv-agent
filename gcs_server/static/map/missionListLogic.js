const SET2 = [
  '#66c2a5',
  '#fc8d62',
  '#8da0cb',
  '#e78ac3',
  '#a6d854',
  '#ffd92f',
  '#e5c494',
  '#b3b3b3',
];

// Shape flat `missions` rows (GET /api/ai/missions) into display-ready
// descriptors: one row = one Mission (ADR 0021 §2). Pure; no fetching.
// `origin` here is provenance (manual|ai_chat), distinct from ADR 0022's
// coordinate-datum Origin.
const ORIGIN_BADGE = { manual: '👤', ai_chat: '🤖' };

export function mapMissionsForList(missions = []) {
  return (Array.isArray(missions) ? missions : []).map((m) => {
    const id = String(m.id || '');
    const index = Number.isFinite(m.mission_index) ? Number(m.mission_index) : null;
    const name = String(m.name || '').trim();
    const origin = String(m.origin || 'manual');
    return {
      id,
      missionIndex: index,
      name: name || (index != null ? `Mission ${index}` : 'Untitled mission'),
      origin,
      originBadge: ORIGIN_BADGE[origin] || '🤖',
      originChatId: String(m.origin_chat_id || ''),
      clientVersion: Number(m.client_version || 0),
      createdAt: Number(m.created_at || 0),
      updatedAt: Number(m.updated_at || 0),
      // Active-revision resolution from the list endpoint (ADR 0021 §2): the
      // overlay/execute target and the status that gates edit/execute/locked
      // affordances. Empty when the Mission has no bridged active revision yet.
      activeRevisionId: String(m.active_revision_id || ''),
      activeRevisionStatus: String(m.active_revision_status || ''),
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

export function assignPaletteColor(visibleIds) {
  const palette = new Map();
  Array.from(visibleIds || []).forEach((revisionId, index) => {
    palette.set(revisionId, SET2[index % SET2.length]);
  });
  return palette;
}
