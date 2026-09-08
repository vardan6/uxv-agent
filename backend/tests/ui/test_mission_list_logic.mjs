import test from 'node:test';
import assert from 'node:assert/strict';

import { assignPaletteColor } from '../../static/map/missionListLogic.js';
import { missionRowMarkup, contextBarVerbs } from '../../static/map/ui/MissionListPanel.js';
import { sortMissions } from '../../static/map/state/missionSortPreference.js';

test('assignPaletteColor keeps existing auto colours stable and gives a new mission a new colour', () => {
  const missions = [
    { id: 'mission-3', missionIndex: 3, createdAt: 300 },
    { id: 'mission-2', missionIndex: 2, createdAt: 200 },
    { id: 'mission-1', missionIndex: 1, createdAt: 100 },
  ];

  const initial = assignPaletteColor(missions.slice(1), {});
  const next = assignPaletteColor(missions, {});

  assert.equal(next.get('mission-1'), initial.get('mission-1'));
  assert.equal(next.get('mission-2'), initial.get('mission-2'));
  assert.notEqual(next.get('mission-3'), next.get('mission-1'));
  assert.notEqual(next.get('mission-3'), next.get('mission-2'));
});

test('assignPaletteColor skips overridden colours when auto-assigning the rest', () => {
  const missions = [
    { id: 'mission-1', missionIndex: 1, createdAt: 100 },
    { id: 'mission-2', missionIndex: 2, createdAt: 200 },
    { id: 'mission-3', missionIndex: 3, createdAt: 300 },
  ];

  const palette = assignPaletteColor(missions, { 'mission-2': '#66c2a5' });

  assert.equal(palette.get('mission-2'), '#66c2a5');
  assert.notEqual(palette.get('mission-1'), '#66c2a5');
  assert.notEqual(palette.get('mission-3'), '#66c2a5');
});

test('missionRowMarkup row has no execute button — execute lives in the context bar', () => {
  const html = missionRowMarkup({
    id: 'mission-1',
    missionIndex: 1,
    name: 'Test mission',
    originBadge: '👤',
    waypointCount: 3,
    createdAt: 1,
    activeRevisionId: 'rev-1',
    activeRevisionStatus: 'proposed',
    sessionStatus: '',
  });

  assert.doesNotMatch(html, /data-execute-mission-id/);
  assert.match(html, /#1 · 3 pts/);
});

test('contextBarVerbs renders execute for an idle mission with an active revision', () => {
  const html = contextBarVerbs({
    id: 'mission-1',
    name: 'Test mission',
    activeRevisionId: 'rev-1',
    activeRevisionStatus: 'proposed',
    sessionStatus: '',
  });

  assert.match(html, /data-execute-mission-id="mission-1"/);
});

test('sortMissions orders rows by waypoint count descending', () => {
  const sorted = sortMissions(
    [
      { id: 'mission-1', waypointCount: 3, updatedAt: 10 },
      { id: 'mission-2', waypointCount: 7, updatedAt: 20 },
      { id: 'mission-3', waypointCount: 1, updatedAt: 30 },
    ],
    'waypoints_desc',
  );

  assert.deepEqual(sorted.map((row) => row.id), ['mission-2', 'mission-1', 'mission-3']);
});

test('sortMissions orders rows by waypoint count ascending', () => {
  const sorted = sortMissions(
    [
      { id: 'mission-1', waypointCount: 3, updatedAt: 10 },
      { id: 'mission-2', waypointCount: 7, updatedAt: 20 },
      { id: 'mission-3', waypointCount: 1, updatedAt: 30 },
    ],
    'waypoints_asc',
  );

  assert.deepEqual(sorted.map((row) => row.id), ['mission-3', 'mission-1', 'mission-2']);
});
