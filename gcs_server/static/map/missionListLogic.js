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

export function normalizeMissionRows(rows = []) {
  return rows
    .filter((row) => row && row.id !== undefined && row.id !== null)
    .map((row) => ({
      ...row,
      id: String(row.id),
      status: String(row.status || row.approval_status || 'unknown'),
    }));
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
  Array.from(visibleIds || []).forEach((missionId, index) => {
    palette.set(missionId, SET2[index % SET2.length]);
  });
  return palette;
}
