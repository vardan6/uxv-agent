export function vehicleIcon(profileId = '', profiles = {}, activeProfileId = 'rover_default') {
  const profile = profiles[profileId] || profiles[activeProfileId] || {};
  switch (profile.kind) {
    case 'multirotor':
      return '🚁';
    case 'fixed_wing':
      return '✈️';
    default:
      return '🚙';
  }
}
