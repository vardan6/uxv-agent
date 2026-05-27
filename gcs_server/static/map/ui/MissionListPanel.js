import { vehicleIcon } from '../vehicleProfiles.js';

const APPROVABLE = new Set(['proposed', 'awaiting_approval', 'planning']);
const EXECUTABLE = new Set(['approved', 'exported', 'cutover_pending']);
const EDITABLE = new Set(['proposed', 'awaiting_approval', 'planning', 'approved', 'exported', 'cutover_pending']);

const STATUS_CLASS = {
  proposed: 'is-proposed',
  awaiting_approval: 'is-proposed',
  planning: 'is-proposed',
  approved: 'is-approved',
  exported: 'is-approved',
  cutover_pending: 'is-approved',
  armed: 'is-approved',
  executing: 'is-executing',
  completed: 'is-completed',
  superseded: 'is-superseded',
  rejected: 'is-superseded',
  validation_failed: 'is-superseded',
};

function statusLabel(status) {
  return String(status || 'unknown').replaceAll('_', ' ');
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
      aria-label="Edit mission waypoints">✏</button>`);
  }
  if (APPROVABLE.has(status) && missionId) {
    parts.push(`<button class="mission-row-action-btn is-approve" type="button"
      data-approve-draft-id="${missionId}"
      title="Approve mission (does not execute)"
      aria-label="Approve mission (does not execute)">✓</button>`);
    parts.push(`<button class="mission-row-action-btn is-reject" type="button"
      data-reject-draft-id="${missionId}"
      title="Reject mission"
      aria-label="Reject mission">✕</button>`);
  }
  if (EXECUTABLE.has(status)) {
    parts.push(`<button class="mission-row-action-btn is-execute" type="button"
      data-execute-mission-id="${missionId}"
      title="Execute mission on rover"
      aria-label="Execute mission on rover">▶</button>`);
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
  const color = paletteByMissionId.get(missionId) || 'transparent';
  const profileId = String(missionRow?.mission?.vehicle_profile_id || activeProfileId || 'rover_default');
  const profileIcon = vehicleIcon(profileId, profilesById, activeProfileId);
  return `
    <div class="mission-list-row ${STATUS_CLASS[status] || ''}${isActive ? ' is-focused' : ''}${isSelected ? ' is-selected' : ''}">
      <span class="mission-row-status" aria-hidden="true"></span>
      <button
        class="mission-row-focus"
        type="button"
        data-activate-mission-id="${missionId}"
        aria-pressed="${isActive ? 'true' : 'false'}"
        title="Make mission active"
      >
        <span class="mission-row-color-dot" style="--mission-color:${color}"></span>
        <span class="mission-row-vehicle" aria-hidden="true">${profileIcon}</span>
        <span class="mission-row-main">
          <span class="mission-row-title">${missionTitle(missionRow)}</span>
          <span class="mission-row-meta">${statusLabel(status)} · #${missionId}</span>
        </span>
        <span class="mission-row-origin" title="Mission origin">${computeOriginBadge(missionRow)}</span>
        ${isActive ? '<span class="mission-row-active-badge">Active</span>' : ''}
      </button>
      <span class="mission-row-actions">
        <label class="mission-row-select" title="${isSelected ? 'Deselect mission' : 'Select mission'}">
          <input
            type="checkbox"
            data-select-mission-id="${missionId}"
            aria-label="${isSelected ? 'Deselect mission' : 'Select mission'}"
            ${isSelected ? 'checked' : ''}
          >
          <span>Selected</span>
        </label>
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
    this._onApproveRequested = opts.onApproveRequested || (() => {});
    this._onRejectRequested = opts.onRejectRequested || (() => {});
    this._onExecuteRequested = opts.onExecuteRequested || (() => {});
    this._onEditRequested = opts.onEditRequested || (() => {});
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
        <span class="mission-list-header-title">Missions</span>
        <a
          class="mission-list-settings-link"
          href="/settings?tab=mission-lifecycle"
          target="_blank"
          rel="noopener"
          title="Open Mission Lifecycle settings in a new tab"
          aria-label="Open Mission Lifecycle settings in a new tab"
        >⚙</a>
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
    this._container.querySelectorAll('[data-approve-draft-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onApproveRequested(button.dataset.approveDraftId || '');
      });
    });
    this._container.querySelectorAll('[data-reject-draft-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onRejectRequested(button.dataset.rejectDraftId || '');
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
  }
}
