import { vehicleIcon } from '../vehicleProfiles.js';

const APPROVABLE = new Set(['proposed', 'awaiting_approval', 'planning']);
const EXECUTABLE = new Set(['approved', 'exported', 'cutover_pending']);

const STATUS_CLASS = {
  proposed: 'is-proposed',
  awaiting_approval: 'is-proposed',
  planning: 'is-proposed',
  approved: 'is-approved',
  exported: 'is-approved',
  cutover_pending: 'is-approved',
  executing: 'is-executing',
  completed: 'is-completed',
  superseded: 'is-superseded',
  rejected: 'is-superseded',
  validation_failed: 'is-superseded',
};

function statusLabel(status) {
  return String(status || 'unknown').replaceAll('_', ' ');
}

function missionTitle(revision) {
  const goal = String(revision?.mission?.goal || revision?.goal || '').trim();
  return goal || 'Mission revision';
}

function originBadge() {
  return '🤖';
}

function renderActionButtons(revision, status) {
  const revisionId = String(revision.id || '');
  const draftId = String(revision.draft_id || '');

  if (status === 'executing') {
    return `<span class="mission-row-lock" aria-label="Mission is executing" title="Mission is executing — editing locked">🔒</span>`;
  }
  if (APPROVABLE.has(status) && draftId) {
    return `
      <button class="mission-row-action-btn is-approve" type="button"
        data-approve-draft-id="${draftId}"
        title="Approve draft (does not execute)"
        aria-label="Approve draft (does not execute)">✓</button>
      <button class="mission-row-action-btn is-reject" type="button"
        data-reject-draft-id="${draftId}"
        title="Reject draft"
        aria-label="Reject draft">✕</button>
    `;
  }
  if (EXECUTABLE.has(status)) {
    return `
      <button class="mission-row-action-btn is-execute" type="button"
        data-execute-revision-id="${revisionId}"
        title="Execute on rover (uploads and starts mission)"
        aria-label="Execute on rover">▶</button>
    `;
  }
  return '';
}

function renderRow(revision, ctx) {
  const {
    visibleRevisionIds,
    focusedRevisionId,
    paletteByRevisionId,
    profilesById,
    activeProfileId,
    isEarlier,
  } = ctx;
  const revisionId = String(revision.id || '');
  const isVisible = visibleRevisionIds.has(revisionId);
  const isFocused = focusedRevisionId === revisionId;
  const status = String(revision.status || '');
  const color = paletteByRevisionId.get(revisionId) || 'transparent';
  const profileId = String(revision?.mission?.vehicle_profile_id || activeProfileId || 'rover_default');
  const profileIcon = vehicleIcon(profileId, profilesById, activeProfileId);
  return `
    <div class="mission-list-row ${STATUS_CLASS[status] || ''}${isFocused ? ' is-focused' : ''}${isEarlier ? ' is-earlier' : ''}">
      <span class="mission-row-status" aria-hidden="true"></span>
      <button
        class="mission-row-focus"
        type="button"
        data-focus-revision-id="${revisionId}"
        aria-pressed="${isFocused ? 'true' : 'false'}"
        title="Focus mission"
      >
        <span class="mission-row-color-dot" style="--mission-color:${color}"></span>
        <span class="mission-row-vehicle" aria-hidden="true">${profileIcon}</span>
        <span class="mission-row-main">
          <span class="mission-row-title">${missionTitle(revision)}</span>
          <span class="mission-row-meta">${statusLabel(status)} · rev ${String(revisionId).slice(-6)}</span>
        </span>
        <span class="mission-row-origin" title="Agent-created mission">${originBadge()}</span>
      </button>
      <span class="mission-row-actions">
        ${renderActionButtons(revision, status)}
        <span class="mission-row-visibility-text">${isVisible ? 'Visible' : 'Hidden'}</span>
        <button
          class="mission-row-eye${status === 'executing' ? ' is-locked' : ''}"
          type="button"
          data-toggle-revision-id="${revisionId}"
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
    this._onFocusRequested = opts.onFocusRequested || (() => {});
    this._onVisibilityToggled = opts.onVisibilityToggled || (() => {});
    this._onExpandToggled = opts.onExpandToggled || (() => {});
    this._onApproveRequested = opts.onApproveRequested || (() => {});
    this._onRejectRequested = opts.onRejectRequested || (() => {});
    this._onExecuteRequested = opts.onExecuteRequested || (() => {});
  }

  render({
    groups = [],
    expandedOperationIds = new Set(),
    visibleRevisionIds = new Set(),
    focusedRevisionId = '',
    paletteByRevisionId = new Map(),
    profilesById = {},
    activeProfileId = 'rover_default',
  } = {}) {
    const body = groups.length
      ? groups.map((group) => {
        const defaultRevisionId = String(group.defaultRevisionId || '');
        const defaultRevision = group.revisions.find((revision) => String(revision.id || '') === defaultRevisionId)
          || group.revisions[0];
        const earlierRevisions = group.revisions.filter((revision) => revision !== defaultRevision);
        const expanded = expandedOperationIds.has(group.operationId);
        const earlierMarkup = expanded
          ? earlierRevisions.map((revision) => renderRow(revision, {
            visibleRevisionIds,
            focusedRevisionId,
            paletteByRevisionId,
            profilesById,
            activeProfileId,
            isEarlier: true,
          })).join('')
          : '';
        const expander = earlierRevisions.length
          ? `
            <button
              class="mission-group-expander"
              type="button"
              data-toggle-operation-id="${group.operationId}"
              aria-expanded="${expanded ? 'true' : 'false'}"
              title="${expanded ? 'Collapse earlier revisions' : 'Expand earlier revisions'}"
            >${expanded ? '▾' : '▸'} ${earlierRevisions.length} earlier</button>
          `
          : '';
        return `
          <section class="mission-group" data-operation-id="${group.operationId}">
            ${renderRow(defaultRevision, {
              visibleRevisionIds,
              focusedRevisionId,
              paletteByRevisionId,
              profilesById,
              activeProfileId,
              isEarlier: false,
            })}
            ${expander}
            <div class="mission-group-earlier"${expanded ? '' : ' hidden'}>${earlierMarkup}</div>
          </section>
        `;
      }).join('')
      : '<div class="mission-list-empty">No missions yet. Ask the agent.</div>';

    this._container.innerHTML = `<div class="mission-list-panel">${body}</div>`;
    this._bind();
  }

  _bind() {
    this._container.querySelectorAll('[data-focus-revision-id]').forEach((button) => {
      button.addEventListener('click', () => this._onFocusRequested(button.dataset.focusRevisionId || ''));
    });
    this._container.querySelectorAll('[data-toggle-revision-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onVisibilityToggled(button.dataset.toggleRevisionId || '');
      });
    });
    this._container.querySelectorAll('[data-toggle-operation-id]').forEach((button) => {
      button.addEventListener('click', () => {
        this._onExpandToggled(button.dataset.toggleOperationId || '');
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
    this._container.querySelectorAll('[data-execute-revision-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onExecuteRequested(button.dataset.executeRevisionId || '');
      });
    });
  }
}
