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

export function groupRevisionsByOperation(rows = []) {
  const groups = new Map();
  for (const row of rows) {
    const operationId = String(row.operation_id || row.id || '');
    if (!operationId) continue;
    let group = groups.get(operationId);
    if (!group) {
      group = {
        operationId,
        operationStatus: String(row.operation_status || ''),
        activeRevisionId: String(row.active_revision_id || ''),
        revisions: [],
        defaultRevisionId: '',
      };
      groups.set(operationId, group);
    }
    group.revisions.push(row);
  }

  for (const group of groups.values()) {
    const newestRevisionId = String(group.revisions[0]?.id || '');
    group.defaultRevisionId = group.activeRevisionId || newestRevisionId;
  }
  return groups;
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
