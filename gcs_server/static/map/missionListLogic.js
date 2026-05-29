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

