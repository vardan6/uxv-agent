// Curated swatch palette for the picker — distinct hues + a few neutrals.
export const MISSION_COLOR_PALETTE = [
  '#d16b5b', '#6f86c7', '#c27aa6', '#d0b24a',
  '#8e98a3', '#3f6f9f', '#b85c5c', '#7b68b2',
  '#4fa3a5', '#d08a6b', '#b96aa0', '#4f6a8a',
  '#8f4f7e', '#c79b5f', '#6e5f9c', '#a56f6f',
  '#667789', '#2f8f83', '#8fbf5a', '#0f9d58',
  '#3aaed8', '#f08c4a', '#a06cd5', '#c06078',
];

export function defaultMissionColor(missionId) {
  const numericId = Number.parseInt(missionId, 10);
  if (!Number.isFinite(numericId)) return MISSION_COLOR_PALETTE[0];
  return MISSION_COLOR_PALETTE[numericId % MISSION_COLOR_PALETTE.length];
}
