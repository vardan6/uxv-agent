import test from 'node:test';
import assert from 'node:assert/strict';

import { UNKNOWN_VEHICLE_ICON, vehicleIcon } from '../../../map/vehicleProfiles.js';
import { missionRowMarkup } from '../../../map/ui/MissionListPanel.js';

const PROFILES = {
  rover_default: { id: 'rover_default', kind: 'ground' },
  quad_x500: { id: 'quad_x500', kind: 'multirotor' },
  fixed_wing_default: { id: 'fixed_wing_default', kind: 'fixed_wing' },
};

test('vehicleIcon maps each known kind, with ground explicit', () => {
  assert.equal(vehicleIcon('rover_default', PROFILES), '🚙');
  assert.equal(vehicleIcon('quad_x500', PROFILES), '🚁');
  assert.equal(vehicleIcon('fixed_wing_default', PROFILES), '✈️');
});

test('vehicleIcon renders an unknown or missing profile neutrally, not as a rover', () => {
  assert.equal(vehicleIcon('no_such_profile', PROFILES), UNKNOWN_VEHICLE_ICON);
  assert.equal(vehicleIcon('', PROFILES), UNKNOWN_VEHICLE_ICON);
  assert.equal(vehicleIcon('rover_default', {}), UNKNOWN_VEHICLE_ICON);
  assert.notEqual(UNKNOWN_VEHICLE_ICON, '🚙');
});

test('vehicleIcon does not assume an active profile when none is selected', () => {
  // No third argument: nothing has told the UI which profile is active yet.
  assert.equal(vehicleIcon('', PROFILES), UNKNOWN_VEHICLE_ICON);
  // With one selected, it is the fallback for a row carrying no profile id.
  assert.equal(vehicleIcon('', PROFILES, 'quad_x500'), '🚁');
});

test('vehicleIcon never lends the active profile to an unresolved profile id', () => {
  assert.equal(vehicleIcon('no_such_profile', PROFILES, 'quad_x500'), UNKNOWN_VEHICLE_ICON);
  assert.equal(vehicleIcon('no_such_profile', PROFILES, 'rover_default'), UNKNOWN_VEHICLE_ICON);
});

test('a mission row shows the profile the mission is bound to, not the active one', () => {
  const html = missionRowMarkup(
    {
      id: 'mission-1',
      missionIndex: 1,
      name: 'Test mission',
      waypointCount: 3,
      createdAt: 1,
      activeRevisionId: 'rev-1',
      activeRevisionStatus: 'proposed',
      sessionStatus: '',
      vehicleProfileId: 'quad_x500',
    },
    { profilesById: PROFILES, activeProfileId: 'rover_default' },
  );

  assert.match(html, /mission-row-vehicle[^>]*>🚁</);
});

test('a mission row with an unrecognised profile is labelled unknown', () => {
  const html = missionRowMarkup(
    {
      id: 'mission-1',
      missionIndex: 1,
      name: 'Test mission',
      waypointCount: 3,
      createdAt: 1,
      activeRevisionId: 'rev-1',
      activeRevisionStatus: 'proposed',
      sessionStatus: '',
      vehicleProfileId: 'retired_profile',
    },
    { profilesById: PROFILES, activeProfileId: 'rover_default' },
  );

  assert.match(html, /title="Vehicle type unknown"/);
  assert.doesNotMatch(html, /🚙/);
});
