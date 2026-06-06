// Flat-Mission row affordances (ADR 0021 §4 "Sidebar-row affordances"):
// edit resolves to the Mission's active revision and remains status-gated;
// execute is available for any idle row with an active revision. executing →
// locked (no edit/execute). approve/reject are removed — play gates execution.
const MISSION_ROW_EDITABLE = new Set(['proposed', 'planning', 'exported', 'cutover_pending']);
const VEHICLE_ICON = { ground: '🚗', multirotor: '🚁', fixed_wing: '✈️' };

// Maps activeRevisionStatus → CSS class applied to the row div for status stripe colouring.
const STATUS_CLASS = {
  proposed: 'is-proposed',
  planning: 'is-proposed',
  exported: 'is-approved',
  cutover_pending: 'is-approved',
  executing: 'is-executing',
  completed: 'is-completed',
  superseded: 'is-superseded',
  rejected: 'is-superseded',
  validation_failed: 'is-superseded',
};

// Statuses that don't need a visible label (normal/unremarkable states).
const HIDDEN_STATUS_LABELS = new Set([
  'proposed', 'planning',
  'exported', 'cutover_pending', 'unknown', '',
]);

function statusLabel(status) {
  const s = String(status || '');
  if (HIDDEN_STATUS_LABELS.has(s)) return '';
  return s.replaceAll('_', ' ');
}

function formatDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}

function formatWaypointCount(count) {
  const total = Math.max(0, Number(count || 0));
  return `${total} pt${total === 1 ? '' : 's'}`;
}

function batchActionIcon(action) {
  if (action === 'show-all') {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="3.2"/></svg>';
  }
  if (action === 'hide-all') {
    return '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m3 3 18 18"/><path d="M10.6 6.2A11.6 11.6 0 0 1 12 6c6.2 0 10 6 10 6a17.3 17.3 0 0 1-4.1 4.5"/><path d="M6.2 8.3A17.5 17.5 0 0 0 2 12s3.8 6 10 6c1.7 0 3.3-.4 4.7-1.1"/><path d="M9.9 9.9A3 3 0 0 0 12 15c.5 0 1-.1 1.4-.3"/></svg>';
  }
  return '';
}

function batchActionButton({ action, label, title, disabled = false }) {
  return `<button
    class="mission-batch-icon-btn"
    type="button"
    data-batch-action="${escapeHtml(action)}"
    aria-label="${escapeHtml(label)}"
    title="${escapeHtml(title)}"
    ${disabled ? 'disabled' : ''}
  >${batchActionIcon(action)}</button>`;
}

// Escape untrusted values before interpolating into the row HTML string. Mission
// names and origin badges are AI-/operator-derived, so a name like
// `"><img src=x onerror=...>` would otherwise become executable markup once the
// assembled string is written via innerHTML. Covers both text and double-quoted
// attribute contexts. Kept pure so the row markup stays node-testable.
export function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Up to five button slots per row (B.3): ✏️ ▶/⏸ ⏹ 🗑 👁.
// Edit/play/stop render only when applicable; delete and eye are always present.
// sessionStatus is the in-memory executor state injected by GET /api/ai/missions.
function missionRowUtilityActions(missionRow, isEditing, {
  deleteGuarded = false,
  isExecuting = false,
} = {}) {
  const status = String(missionRow.activeRevisionStatus || '');
  const sessionStatus = String(missionRow.sessionStatus || '');
  const hasActiveRevision = Boolean(String(missionRow.activeRevisionId || '').trim());
  const safeId = escapeHtml(missionRow.id);
  const safeName = escapeHtml(missionRow.name);

  const isSessionRunning = sessionStatus === 'running';
  const isSessionPaused = sessionStatus === 'paused';
  const isActive = isSessionRunning || isSessionPaused || isExecuting;

  // Slot 1 — edit ✏️
  const canEdit = MISSION_ROW_EDITABLE.has(status) && !isActive;
  let editSlot;
  if (canEdit && isEditing) {
    editSlot = `<button class="mission-row-action-btn is-done" type="button"
      data-done-edit-mission-id="${safeId}"
      title="Finish editing" aria-label="Finish editing">
      <svg class="mission-row-edit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 12l5 5L20 7"/></svg>
    </button>`;
  } else if (canEdit) {
    editSlot = `<button class="mission-row-action-btn is-edit" type="button"
      data-edit-mission-id="${safeId}"
      title="Edit waypoints" aria-label="Edit waypoints for mission ${safeName}">
      <svg class="mission-row-edit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>
    </button>`;
  } else {
    editSlot = '';
  }

  // Slot 2 — play ▶ or pause ⏸
  let playPauseSlot;
  if (isSessionRunning) {
    playPauseSlot = `<button class="mission-row-action-btn is-pause" type="button"
      data-pause-mission-id="${safeId}"
      title="Pause mission" aria-label="Pause mission ${safeName}">⏸</button>`;
  } else if (isSessionPaused || (hasActiveRevision && !isActive)) {
    const isResume = isSessionPaused;
    const attr = isResume ? `data-resume-mission-id="${safeId}"` : `data-execute-mission-id="${safeId}"`;
    const title = isResume ? 'Resume mission' : 'Execute mission';
    playPauseSlot = `<button class="mission-row-action-btn is-execute" type="button"
      ${attr}
      title="${title}" aria-label="${title} ${safeName}">▶</button>`;
  } else {
    playPauseSlot = '';
  }

  // Slot 3 — stop ⏹ (only shown when a session is active)
  const stopSlot = (isSessionRunning || isSessionPaused)
    ? `<button class="mission-row-action-btn is-stop" type="button"
        data-stop-mission-id="${safeId}"
        title="Stop mission" aria-label="Stop mission ${safeName}">⏹</button>`
    : '';

  // Slot 4 — delete 🗑
  const deleteDisabled = deleteGuarded || isActive;
  const deleteTitle = deleteDisabled ? 'Delete disabled while mission is active' : 'Delete mission';
  const deleteAttr = deleteDisabled ? ' disabled aria-disabled="true"' : '';
  const deleteSlot = `<button class="mission-row-action-btn is-delete" type="button"
    data-delete-mission-id="${safeId}"
    title="${deleteTitle}" aria-label="Delete mission ${safeName}"${deleteAttr}>🗑</button>`;

  return editSlot + playPauseSlot + stopSlot + deleteSlot;
}

function missionRowVisibilityButton(missionId, missionName, { isVisible = false, isExecuting = false } = {}) {
  const safeId = escapeHtml(missionId);
  const safeName = escapeHtml(missionName);
  return `<button
    class="mission-row-eye${isExecuting ? ' is-locked' : ''}"
    type="button"
    data-toggle-mission-id="${safeId}"
    aria-label="${isExecuting ? 'Mission overlay locked while executing' : (isVisible ? 'Hide mission overlay' : 'Show mission overlay')}"
    title="${isExecuting ? 'Mission overlay locked while executing' : (isVisible ? 'Hide mission overlay' : 'Show mission overlay')}"
    aria-disabled="${isExecuting ? 'true' : 'false'}"
    ${isExecuting ? 'disabled' : ''}
  >${isVisible
    ? `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8s2.5-5 6-5 6 5 6 5-2.5 5-6 5-6-5-6-5z"/><circle cx="8" cy="8" r="2" fill="currentColor" stroke="none"/></svg>`
    : `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 2l12 12"/><path d="M6.7 4.2A7.3 7.3 0 018 4c3.5 0 6 4 6 4a11.6 11.6 0 01-1.9 2.5"/><path d="M4.5 5.9A11.6 11.6 0 002 8s2.5 4 6 4c1.2 0 2.3-.4 3.2-1"/></svg>`
  }</button>`;
}

// Pure markup for one flat-Mission row (ADR 0021 §2: one row = one Mission).
// Consumes a descriptor from mapMissionsForList(). Focus/visibility are keyed
// on the Mission id; the revision/operation history is internal detail behind
// an optional expander. Kept pure so it is node-testable without a DOM.
export function missionRowMarkup(missionRow, ctx = {}) {
  const {
    visibleMissionIds = new Set(),
    focusedMissionId = '',
    selectedMissionIds = new Set(),
    paletteByMissionId = new Map(),
    editingMissionId = '',
    profilesById = {},
    activeProfileId = '',
    deleteGuardedMissionIds = new Set(),
  } = ctx;
  const id = String(missionRow.id || '');
  const isVisible = visibleMissionIds.has(id);
  const isFocused = focusedMissionId === id;
  const isSelected = selectedMissionIds.has(id);
  const isEditing = editingMissionId === id;
  const status = String(missionRow.activeRevisionStatus || '');
  const isExecuting = status === 'executing';
  const statusCls = STATUS_CLASS[status] || '';
  const color = paletteByMissionId.get(id) || 'transparent';
  const indexLabel = missionRow.missionIndex != null ? `#${missionRow.missionIndex}` : '';
  const label = statusLabel(status);
  const dateStr = formatDate(missionRow.createdAt);
  const vehicleKind = String(
    profilesById[missionRow.vehicleProfileId]?.kind
    || profilesById[activeProfileId]?.kind
    || 'ground'
  );
  const vehicleIcon = VEHICLE_ICON[vehicleKind] || '';
  const deleteGuarded = deleteGuardedMissionIds.has(id);
  const waypointLabel = formatWaypointCount(missionRow.waypointCount);
  const metaParts = [escapeHtml(indexLabel), escapeHtml(waypointLabel), escapeHtml(label), escapeHtml(dateStr)].filter(Boolean);
  const safeId = escapeHtml(id);
  const safeName = escapeHtml(missionRow.name);
  return `
    <div class="mission-list-row${statusCls ? ' ' + statusCls : ''}${isFocused ? ' is-focused' : ''}${isSelected ? ' is-selected' : ''}${isEditing ? ' is-editing' : ''}" data-mission-id="${safeId}" data-row-mission-id="${safeId}">
      <button class="mission-row-status" type="button" data-color-chip-mission-id="${safeId}" style="--mission-color:${escapeHtml(color)}" title="Change mission colour" aria-label="Change colour for mission ${safeName}"></button>
      <label class="mission-row-select" title="Select for batch operations (shift-click for range)">
        <input
          type="checkbox"
          class="mission-row-select-box"
          data-select-mission-id="${safeId}"
          ${isSelected ? 'checked' : ''}
          aria-label="Select mission ${safeName}"
        />
      </label>
      <button
        class="mission-row-focus"
        type="button"
        data-focus-mission-id="${safeId}"
        aria-pressed="${isFocused ? 'true' : 'false'}"
        title="Focus mission"
      >
        <span class="mission-row-leading">
          ${vehicleIcon ? `<span class="mission-row-vehicle" title="Vehicle type">${escapeHtml(vehicleIcon)}</span>` : ''}
          <span class="mission-row-origin" title="Mission origin">${escapeHtml(missionRow.originBadge)}</span>
        </span>
        <span class="mission-row-main">
          <span class="mission-row-title" data-rename-mission-id="${safeId}" data-current-name="${safeName}" title="Double-click to rename">${safeName}</span>
          <span class="mission-row-meta">${metaParts.join(' · ')}</span>
        </span>
      </button>
      <span class="mission-row-actions">
        ${missionRowUtilityActions(missionRow, isEditing, { deleteGuarded, isExecuting })}
      </span>
      <span class="mission-row-visibility">
        ${missionRowVisibilityButton(id, missionRow.name, { isVisible, isExecuting })}
      </span>
    </div>
  `;
}

export class MissionListPanel {
  constructor(container, opts = {}) {
    this._container = container;
    // Flat-Mission callbacks (ADR 0021 §2: one row = one Mission). Edit/execute
    // resolve to the Mission's active revision inside MapWidget.
    this._onMissionFocusRequested = opts.onMissionFocusRequested || (() => {});
    this._onMissionVisibilityToggled = opts.onMissionVisibilityToggled || (() => {});
    this._onMissionEditRequested = opts.onMissionEditRequested || (() => {});
    this._onMissionExecuteRequested = opts.onMissionExecuteRequested || (() => {});
    this._onMissionPauseRequested = opts.onMissionPauseRequested || (() => {});
    this._onMissionResumeRequested = opts.onMissionResumeRequested || (() => {});
    this._onMissionStopRequested = opts.onMissionStopRequested || (() => {});
    this._onMissionDeleteRequested = opts.onMissionDeleteRequested || (() => {});
    this._onMissionRenameRequested = opts.onMissionRenameRequested || (() => {});
    // Selected state (ADR 0021 §4): batch-operation target set, driven by the
    // per-row checkbox (shift-click extends a range). Distinct from Visible/Active.
    this._onNewMissionRequested = opts.onNewMissionRequested || (() => {});
    this._onMissionSelectionToggled = opts.onMissionSelectionToggled || (() => {});
    this._onAllVisibilityToggled = opts.onAllVisibilityToggled || (() => {});
    this._onAllSelectionToggled = opts.onAllSelectionToggled || (() => {});
    this._onSelectionCleared = opts.onSelectionCleared || (() => {});
    this._onMissionDoneEditRequested = opts.onMissionDoneEditRequested || (() => {});
    this._onColorChipClicked = opts.onColorChipClicked || (() => {});
    this._onOverflowClicked = opts.onOverflowClicked || (() => {});
  }

  renderMissions({
    missions = [],
    focusedMissionId = '',
    visibleMissionIds = new Set(),
    selectedMissionIds = new Set(),
    paletteByMissionId = new Map(),
    editingMissionId = '',
    profilesById = {},
    activeProfileId = '',
    deleteGuardedMissionIds = new Set(),
    sortLabel = '',
  } = {}) {
    const hasSelection = selectedMissionIds.size > 0;
    const allVisible = missions.length > 0 && missions.every((missionRow) => visibleMissionIds.has(String(missionRow.id || '')));
    const hideableVisible = missions.some((missionRow) => (
      visibleMissionIds.has(String(missionRow.id || ''))
      && String(missionRow.activeRevisionStatus || '') !== 'executing'
    ));
    const allSelected = missions.length > 0 && missions.every((missionRow) => selectedMissionIds.has(String(missionRow.id || '')));
    const someSelected = selectedMissionIds.size > 0 && !allSelected;
    const visibilityAction = allVisible ? 'hide-all' : 'show-all';
    const batchBar = `<div class="mission-batch-bar" role="toolbar" aria-label="Mission visibility and selection controls">
          <span class="mission-batch-stripe" aria-hidden="true"></span>
          <label class="mission-batch-select" title="${allSelected ? 'Unselect all missions' : 'Select all missions'}">
            <input
              type="checkbox"
              class="mission-batch-select-box"
              data-batch-toggle-select-all
              ${allSelected ? 'checked' : ''}
              ${missions.length ? '' : 'disabled'}
              aria-label="${allSelected ? 'Unselect all missions' : 'Select all missions'}"
            />
          </label>
          <span class="mission-batch-count" aria-live="polite">${hasSelection ? `${selectedMissionIds.size} selected` : 'None selected'}</span>
          <span class="mission-batch-actions" aria-hidden="true"></span>
          <span class="mission-batch-visibility">
            ${batchActionButton({
              action: visibilityAction,
              label: allVisible ? 'Hide all missions' : 'Show all missions',
              title: allVisible
                ? (hideableVisible ? 'Hide all mission overlays except executing missions' : 'No hideable mission overlays are visible')
                : 'Make all mission overlays visible',
              disabled: missions.length === 0 || (allVisible && !hideableVisible),
            })}
          </span>
        </div>`;
    const safeSortLabel = escapeHtml(sortLabel);
    const header = `<div class="mission-list-header">
            <div class="mission-list-header-copy">
              <h2 class="mission-list-header-title">Missions</h2>
              ${safeSortLabel ? `<p class="mission-list-sort-label" title="Active sort order">⇅ ${safeSortLabel}</p>` : ''}
            </div>
            <div class="mission-list-header-actions">
              <button class="mission-list-new-btn" type="button" data-new-mission
                title="New mission — place waypoints by clicking the map"
                aria-label="New mission">+ New</button>
              <a class="mission-list-settings-link" href="/settings?tab=mission-lifecycle"
                title="Mission lifecycle settings" aria-label="Mission lifecycle settings">⚙</a>
              <button class="mission-list-overflow-btn${safeSortLabel ? ' has-active-sort' : ''}" type="button" data-overflow-menu
                title="Mission list options${safeSortLabel ? ` — sorted by ${sortLabel}` : ''}" aria-label="Mission list options">⋯</button>
            </div>
          </div>`;
    const missionRows = missions.length
      ? missions.map((missionRow) => missionRowMarkup(missionRow, {
        visibleMissionIds,
        focusedMissionId,
        selectedMissionIds,
        paletteByMissionId,
        editingMissionId,
        profilesById,
        activeProfileId,
        deleteGuardedMissionIds,
      })).join('')
      : `<div class="mission-list-empty">
            <p class="mission-list-empty-title">No missions yet</p>
            <p class="mission-list-empty-hint">Ask the agent in the chat above to plan a mission.</p>
            <button class="mission-list-empty-cta" type="button"
              onclick="document.querySelector('.ai-chat-panel')?.scrollIntoView({behavior:'smooth',block:'nearest'}); setTimeout(()=>document.getElementById('ai-message-input')?.focus(),300)">
              ↑ Go to chat
            </button>
          </div>`;
    const body = batchBar + missionRows;
    this._container.innerHTML = `<div class="mission-list-panel">${header}${body}</div>`;
    this._bindMissions();
    const selectAllBox = this._container.querySelector('[data-batch-toggle-select-all]');
    if (selectAllBox) {
      selectAllBox.indeterminate = someSelected;
    }
  }

  _bindMissions() {
    const newBtn = this._container.querySelector('[data-new-mission]');
    if (newBtn) {
      newBtn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onNewMissionRequested();
      });
    }
    const overflowBtn = this._container.querySelector('[data-overflow-menu]');
    if (overflowBtn) {
      overflowBtn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onOverflowClicked(overflowBtn);
      });
    }
    this._container.querySelectorAll('[data-color-chip-mission-id]').forEach((btn) => {
      btn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onColorChipClicked(btn.dataset.colorChipMissionId || '', btn);
      });
    });
    // Full-row click: plain click focuses; shift/meta/ctrl toggles selection.
    // Inner buttons already stopPropagation so they don't double-fire here.
    this._container.querySelectorAll('[data-row-mission-id]').forEach((row) => {
      row.addEventListener('click', (event) => {
        const missionId = row.dataset.rowMissionId || '';
        if (event.shiftKey || event.metaKey || event.ctrlKey) {
          this._onMissionSelectionToggled(missionId, { shift: event.shiftKey });
        } else {
          this._onMissionFocusRequested(missionId);
        }
      });
    });
    this._container.querySelectorAll('[data-focus-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._onMissionFocusRequested(button.dataset.focusMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-done-edit-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionDoneEditRequested(button.dataset.doneEditMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-toggle-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionVisibilityToggled(button.dataset.toggleMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-edit-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionEditRequested(button.dataset.editMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-execute-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionExecuteRequested(button.dataset.executeMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-pause-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionPauseRequested(button.dataset.pauseMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-resume-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionResumeRequested(button.dataset.resumeMissionId || '');
      });
    });
    this._container.querySelectorAll('[data-stop-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionStopRequested(button.dataset.stopMissionId || '');
      });
    });
    // Selection checkboxes: click carries shiftKey for range extension. Bind on
    // click (not change) so the modifier key is available; preventDefault keeps
    // the checkbox visual in sync with the authoritative Selected set on re-render.
    this._container.querySelectorAll('[data-select-mission-id]').forEach((box) => {
      box.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionSelectionToggled(box.dataset.selectMissionId || '', { shift: event.shiftKey });
      });
    });
    this._container.querySelectorAll('[data-batch-action]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const action = button.dataset.batchAction;
        this._onAllVisibilityToggled(action === 'show-all');
      });
    });
    const selectAllBox = this._container.querySelector('[data-batch-toggle-select-all]');
    if (selectAllBox) {
      selectAllBox.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onAllSelectionToggled(selectAllBox.checked || selectAllBox.indeterminate);
      });
    }
    this._container.querySelectorAll('[data-delete-mission-id]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._onMissionDeleteRequested(button.dataset.deleteMissionId || '');
      });
    });
    // Inline rename: double-click the title span → replace with input, commit on Enter/blur.
    this._container.querySelectorAll('[data-rename-mission-id]').forEach((span) => {
      span.addEventListener('dblclick', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const missionId = span.dataset.renameMissionId || '';
        const currentName = span.dataset.currentName || span.textContent.trim();
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'mission-row-title-input';
        input.value = currentName;
        span.replaceWith(input);
        input.focus();
        input.select();
        const commit = () => {
          const newName = input.value.trim();
          if (newName && newName !== currentName) {
            this._onMissionRenameRequested(missionId, newName);
          } else {
            // Restore the original span without saving
            input.replaceWith(span);
          }
        };
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { e.preventDefault(); input.replaceWith(span); }
        });
        input.addEventListener('blur', commit, { once: true });
      });
    });
  }
}
