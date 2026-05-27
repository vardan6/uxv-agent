import { vehicleIcon } from '../vehicleProfiles.js';

const EXECUTABLE = new Set(['proposed', 'awaiting_approval', 'planning', 'approved', 'exported', 'cutover_pending']);
const EDITABLE = new Set(['proposed', 'awaiting_approval', 'planning', 'approved', 'exported', 'cutover_pending']);

const STATUS_CLASS = {
  executing: 'is-executing',
  completed: 'is-completed',
  superseded: 'is-superseded',
  rejected: 'is-superseded',
  validation_failed: 'is-superseded',
};

// Approval-flavored lifecycle states are not surfaced in the row label —
// any mission is manually launchable, so "awaiting approval" / "approved"
// would be noise. Only show statuses the operator can act on.
const HIDDEN_ROW_STATUSES = new Set([
  'proposed',
  'awaiting_approval',
  'planning',
  'approved',
  'exported',
  'cutover_pending',
  'unknown',
  '',
]);

function statusLabel(status) {
  const s = String(status || '');
  if (HIDDEN_ROW_STATUSES.has(s)) return '';
  return s.replaceAll('_', ' ');
}

function formatDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function missionTitle(missionRow) {
  const goal = String(missionRow?.mission?.goal || missionRow?.goal || '').trim();
  return goal || `Mission #${String(missionRow?.id || '').trim() || '?'}`;
}

function computeOriginBadge(missionRow) {
  const prov = missionRow.provenance;
  if (!prov || typeof prov !== 'object') return '🤖';
  const values = Object.values(prov);
  if (!values.length) return '🤖';
  if (values.every(v => v === 'user')) return '👤';
  if (values.some(v => v === 'ai+edited')) return '✏️';
  return '🤖';
}

function renderActionButtons(missionRow, status) {
  const missionId = String(missionRow.id || '');
  const parts = [];

  if (status === 'executing') {
    return `<span class="mission-row-lock" aria-label="Mission is executing" title="Mission is executing — editing locked">🔒</span>`;
  }
  if (EDITABLE.has(status)) {
    parts.push(`<button class="mission-row-action-btn is-edit" type="button"
      data-edit-mission-id="${missionId}"
      title="Edit mission waypoints"
      aria-label="Edit mission waypoints">
      <svg class="mission-row-edit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
      </svg>
    </button>`);
  }
  if (EXECUTABLE.has(status)) {
    parts.push(`<button class="mission-row-action-btn is-execute" type="button"
      data-execute-mission-id="${missionId}"
      title="Execute mission on rover"
      aria-label="Execute mission on rover">▶</button>`);
  }
  if (status !== 'executing' && status !== 'armed' && missionId) {
    parts.push(`<button class="mission-row-action-btn is-delete" type="button"
      data-delete-mission-id="${missionId}"
      title="Delete mission"
      aria-label="Delete mission">🗑</button>`);
  }
  return parts.join('');
}

function renderRow(missionRow, ctx) {
  const {
    visibleMissionIds,
    selectedMissionIds,
    activeMissionId,
    paletteByMissionId,
    profilesById,
    activeProfileId,
  } = ctx;
  const missionId = String(missionRow.id || '');
  const isVisible = visibleMissionIds.has(missionId);
  const isSelected = selectedMissionIds.has(missionId);
  const isActive = activeMissionId === missionId;
  const status = String(missionRow.status || '');
  const color = paletteByMissionId.get(missionId) || '#b8c1c5';
  const profileId = String(missionRow?.mission?.vehicle_profile_id || activeProfileId || 'rover_default');
  const profileIcon = vehicleIcon(profileId, profilesById, activeProfileId);
  return `
    <div class="mission-list-row ${STATUS_CLASS[status] || ''}${isActive ? ' is-focused' : ''}${isSelected ? ' is-selected' : ''}">
      <span class="mission-row-status" aria-hidden="true" style="background:${color}"></span>
      <label class="mission-row-select" title="${isSelected ? 'Deselect mission' : 'Select mission'}">
        <input
          type="checkbox"
          data-select-mission-id="${missionId}"
          aria-label="${isSelected ? 'Deselect mission' : 'Select mission'}"
          ${isSelected ? 'checked' : ''}
        >
        <span class="mission-row-select-text">Selected</span>
      </label>
      <button
        class="mission-row-focus"
        type="button"
        data-activate-mission-id="${missionId}"
        aria-pressed="${isActive ? 'true' : 'false'}"
        title="Make mission active"
      >
        <span class="mission-row-vehicle" aria-hidden="true">${profileIcon}</span>
        <span class="mission-row-origin" title="Mission origin">${computeOriginBadge(missionRow)}</span>
        <span class="mission-row-main">
          <span class="mission-row-title">${missionTitle(missionRow)}</span>
          <span class="mission-row-meta">${[statusLabel(status), `#${missionId}`, missionRow.created_at ? formatDate(missionRow.created_at) : ''].filter(Boolean).join(' · ')}</span>
        </span>
      </button>
      <span class="mission-row-actions">
        ${renderActionButtons(missionRow, status)}
        <span class="mission-row-visibility-text">${isVisible ? 'Visible' : 'Hidden'}</span>
        <button
          class="mission-row-eye${status === 'executing' ? ' is-locked' : ''}"
          type="button"
          data-toggle-mission-id="${missionId}"
          aria-label="${isVisible ? 'Hide mission overlay' : 'Show mission overlay'}"
          title="${isVisible ? 'Hide mission overlay' : 'Show mission overlay'}"
          ${status === 'executing' ? 'disabled aria-disabled="true"' : ''}
        >${isVisible ? '👁' : '🚫'}</button>
      </span>
    </div>
  `;
}

export class MissionListPanel {
  constructor(container, opts = {}) {
    this._container = container;
    this._onActivateRequested = opts.onActivateRequested || (() => {});
    this._onVisibilityToggled = opts.onVisibilityToggled || (() => {});
    this._onSelectionToggled = opts.onSelectionToggled || (() => {});
    this._onExecuteRequested = opts.onExecuteRequested || (() => {});
    this._onEditRequested = opts.onEditRequested || (() => {});
    this._onCreateRequested = opts.onCreateRequested || (() => {});
    this._onDeleteRequested = opts.onDeleteRequested || (() => {});
  }

  render({
    missions = [],
    visibleMissionIds = new Set(),
    selectedMissionIds = new Set(),
    activeMissionId = '',
    paletteByMissionId = new Map(),
    profilesById = {},
    activeProfileId = 'rover_default',
  } = {}) {
    const body = missions.length
      ? missions.map((missionRow) => renderRow(missionRow, {
        visibleMissionIds,
        selectedMissionIds,
        activeMissionId,
        paletteByMissionId,
        profilesById,
        activeProfileId,
      })).join('')
      : `<div class="mission-list-empty">
            <p class="mission-list-empty-title">No missions yet</p>
            <p class="mission-list-empty-hint">Ask the agent in the chat above to plan a mission.</p>
            <button class="mission-list-empty-cta" type="button"
              onclick="document.querySelector('.ai-chat-panel')?.scrollIntoView({behavior:'smooth',block:'nearest'}); setTimeout(()=>document.getElementById('ai-message-input')?.focus(),300)">
              ↑ Go to chat
            </button>
          </div>`;

    const header = `
      <div class="mission-list-header">
        <div>
          <p class="section-kicker">Missions</p>
          <h2 class="mission-list-header-title">Routes</h2>
        </div>
        <div class="mission-list-header-actions">
          <button
            class="mission-list-new-btn"
            type="button"
            data-create-mission="1"
            title="Create a new empty mission"
            aria-label="Create a new empty mission"
          >+ New</button>
          <a
            class="mission-list-settings-link"
            href="/settings?tab=mission-lifecycle"
            target="_blank"
            rel="noopener"
            title="Open Mission Lifecycle settings in a new tab"
            aria-label="Open Mission Lifecycle settings in a new tab"
          >⚙</a>
        </div>
      </div>
    `;
    this._container.innerHTML = `<div class="mission-list-panel">${header}${body}</div>`;
    this._bind();
  }

  _bind() {
    this._container.querySelectorAll('[data-activate-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        this._onActivateRequested(button.dataset.activateMissionId || '', { shiftKey: !!event.shiftKey });
      });
    });
    this._container.querySelectorAll('[data-toggle-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onVisibilityToggled(button.dataset.toggleMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-select-mission-id]').forEach((input) => {
      input.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onSelectionToggled(input.dataset.selectMissionId || '', { checked: !!input.checked });
      });
    });
    this._container.querySelectorAll('[data-execute-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onExecuteRequested(button.dataset.executeMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-edit-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onEditRequested(button.dataset.editMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-delete-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onDeleteRequested(button.dataset.deleteMissionId || '');
      });
    });
    const createBtn = this._container.querySelector('[data-create-mission="1"]');
    if (createBtn) {
      createBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onCreateRequested();
      });
    }
  }
}
