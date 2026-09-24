// Vehicle-kind glyphs. `ground` is explicit: an unknown or missing kind is not
// a rover, it is unknown, and showing a rover for it is how the wrong vehicle
// gets read off the sidebar.
export const VEHICLE_KIND_ICON = {
  ground: '🚙',
  multirotor: '🚁',
  fixed_wing: '✈️',
};

export const UNKNOWN_VEHICLE_ICON = '❔';

export function vehicleIcon(profileId = '', profiles = {}, activeProfileId = '') {
  // The active profile stands in only for a row with no profile id at all; an
  // id that resolves to nothing is unknown, not the active vehicle.
  const id = profileId || activeProfileId;
  const profile = (id && profiles[id]) || {};
  return VEHICLE_KIND_ICON[profile.kind] || UNKNOWN_VEHICLE_ICON;
}
