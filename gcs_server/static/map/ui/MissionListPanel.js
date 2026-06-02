// Flat-Mission row affordances (ADR 0021 §4 "Sidebar-row affordances"):
// edit + execute resolve to the Mission's active revision and are gated by its
// status. executing → locked (no edit/execute); approved|exported|
// cutover_pending → executable. approve/reject stay off the flat row (draft
// plumbing is internal).
const MISSION_ROW_EDITABLE = new Set(['proposed', 'awaiting_approval', 'planning', 'approved', 'exported', 'cutover_pending']);
const MISSION_ROW_EXECUTABLE = new Set(['approved', 'exported', 'cutover_pending']);

const VEHICLE_ICON = { ground: '🚗', multirotor: '🚁', fixed_wing: '✈️' };

// Maps activeRevisionStatus → CSS class applied to the row div for status stripe colouring.
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

// Statuses that don't need a visible label (normal/unremarkable states).
const HIDDEN_STATUS_LABELS = new Set([
  'proposed', 'awaiting_approval', 'planning', 'approved',
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
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
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

function missionRowActionButtons(missionRow, isEditing) {
  const activeRevisionId = String(missionRow.activeRevisionId || '');
  const status = String(missionRow.activeRevisionStatus || '');
  const safeId = escapeHtml(missionRow.id);
  const safeName = escapeHtml(missionRow.name);
  if (!activeRevisionId) {
    return `<button class="mission-row-action-btn is-delete" type="button"
      data-delete-mission-id="${safeId}"
      title="Delete mission"
      aria-label="Delete mission ${safeName}">🗑</button>`;
  }
  if (status === 'executing') {
    return `<span class="mission-row-lock" aria-label="Mission is executing" title="Mission is executing — editing locked">🔒</span>`;
  }
  const parts = [];
  if (MISSION_ROW_EDITABLE.has(status)) {
    if (isEditing) {
      parts.push(`<button class="mission-row-action-btn is-done" type="button"
        data-done-edit-mission-id="${safeId}"
        title="Finish editing"
        aria-label="Finish editing">
        <svg class="mission-row-edit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 12l5 5L20 7"/></svg>
      </button>`);
    } else {
      parts.push(`<button class="mission-row-action-btn is-edit" type="button"
        data-edit-mission-id="${safeId}"
        title="Edit waypoints"
        aria-label="Edit waypoints">
        <svg class="mission-row-edit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>
      </button>`);
    }
  }
  if (MISSION_ROW_EXECUTABLE.has(status)) {
    // Legacy linear-plan upload (ADR 0023): pushes the active revision's
    // waypoints to the controller as a .plan and starts it. This is NOT the
    // behavior-tree session executor — lifecycle BT runs are AI-tool/banner
    // driven (arm_execution/execute_mission + /api/ai/execution/*).
    parts.push(`<button class="mission-row-action-btn is-execute" type="button"
      data-execute-mission-id="${safeId}"
      title="Upload linear plan to controller (legacy direct upload — not behavior-tree execution)"
      aria-label="Upload linear plan to controller">▶</button>`);
  }
  parts.push(`<button class="mission-row-action-btn is-delete" type="button"
    data-delete-mission-id="${safeId}"
    title="Delete mission"
    aria-label="Delete mission ${safeName}">🗑</button>`);
  return parts.join('');
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
    vehicleKind = '',
  } = ctx;
  const id = String(missionRow.id || '');
  const isVisible = visibleMissionIds.has(id);
  const isFocused = focusedMissionId === id;
  const isSelected = selectedMissionIds.has(id);
  const isEditing = editingMissionId === id;
  const status = String(missionRow.activeRevisionStatus || '');
  const statusCls = STATUS_CLASS[status] || '';
  const color = paletteByMissionId.get(id) || 'transparent';
  const indexLabel = missionRow.missionIndex != null ? `#${missionRow.missionIndex}` : '';
  const label = statusLabel(status);
  const dateStr = formatDate(missionRow.createdAt);
  const vehicleIcon = VEHICLE_ICON[vehicleKind] || '';
  const metaParts = [escapeHtml(indexLabel), escapeHtml(label), escapeHtml(dateStr)].filter(Boolean);
  const safeId = escapeHtml(id);
  const safeName = escapeHtml(missionRow.name);
  return `
    <div class="mission-list-row${statusCls ? ' ' + statusCls : ''}${isFocused ? ' is-focused' : ''}${isSelected ? ' is-selected' : ''}${isEditing ? ' is-editing' : ''}" data-mission-id="${safeId}" data-row-mission-id="${safeId}">
      <button class="mission-row-status" type="button" data-color-chip-mission-id="${safeId}" title="Change mission colour" aria-label="Change colour for mission ${safeName}"></button>
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
        <span class="mission-row-color-dot" style="--mission-color:${escapeHtml(color)}"></span>
        <span class="mission-row-main">
          <span class="mission-row-title" data-rename-mission-id="${safeId}" data-current-name="${safeName}" title="Double-click to rename">${safeName}</span>
          <span class="mission-row-meta">${metaParts.join(' · ')}</span>
        </span>
        <span class="mission-row-origin" title="Mission origin">${escapeHtml(missionRow.originBadge)}${vehicleIcon ? `<span class="mission-row-vehicle" title="Vehicle type">${escapeHtml(vehicleIcon)}</span>` : ''}</span>
      </button>
      <span class="mission-row-actions">
        ${missionRowActionButtons(missionRow, isEditing)}
        <span class="mission-row-visibility-text">${isVisible ? 'Visible' : 'Hidden'}</span>
        <button
          class="mission-row-eye"
          type="button"
          data-toggle-mission-id="${safeId}"
          aria-label="${isVisible ? 'Hide mission overlay' : 'Show mission overlay'}"
          title="${isVisible ? 'Hide mission overlay' : 'Show mission overlay'}"
        >${isVisible ? '👁' : '🚫'}</button>
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
    this._onMissionDeleteRequested = opts.onMissionDeleteRequested || (() => {});
    this._onMissionRenameRequested = opts.onMissionRenameRequested || (() => {});
    // Selected state (ADR 0021 §4): batch-operation target set, driven by the
    // per-row checkbox (shift-click extends a range). Distinct from Visible/Active.
    this._onNewMissionRequested = opts.onNewMissionRequested || (() => {});
    this._onMissionSelectionToggled = opts.onMissionSelectionToggled || (() => {});
    this._onSelectedShowRequested = opts.onSelectedShowRequested || (() => {});
    this._onSelectedHideRequested = opts.onSelectedHideRequested || (() => {});
    this._onSelectionCleared = opts.onSelectionCleared || (() => {});
    this._onSelectedDeleteRequested = opts.onSelectedDeleteRequested || (() => {});
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
    vehicleKind = '',
  } = {}) {
    const batchBar = selectedMissionIds.size
      ? `<div class="mission-batch-bar" role="toolbar" aria-label="Batch operations">
            <span class="mission-batch-count">${selectedMissionIds.size} selected</span>
            <button class="mission-batch-btn" type="button" data-batch-action="show">Show</button>
            <button class="mission-batch-btn" type="button" data-batch-action="hide">Hide</button>
            <button class="mission-batch-btn is-clear" type="button" data-batch-action="clear">Clear</button>
            <button class="mission-batch-btn is-delete" type="button" data-batch-action="delete">Delete</button>
          </div>`
      : '';
    const header = `<div class="mission-list-header">
            <span class="mission-list-heading">Missions</span>
            <button class="mission-list-new-btn" type="button" data-new-mission
              title="New mission — place waypoints by clicking the map"
              aria-label="New mission">＋</button>
            <a class="mission-list-settings" href="/settings?tab=mission-lifecycle"
              title="Mission lifecycle settings" aria-label="Mission lifecycle settings">⚙</a>
            <button class="mission-list-overflow-btn" type="button" data-overflow-menu
              title="Mission list options" aria-label="Mission list options">⋯</button>
          </div>`;
    const body = missions.length
      ? batchBar + missions.map((missionRow) => missionRowMarkup(missionRow, {
        visibleMissionIds,
        focusedMissionId,
        selectedMissionIds,
        paletteByMissionId,
        editingMissionId,
        vehicleKind,
      })).join('')
      : `<div class="mission-list-empty">
            <p class="mission-list-empty-title">No missions yet</p>
            <p class="mission-list-empty-hint">Ask the agent in the chat above to plan a mission.</p>
            <button class="mission-list-empty-cta" type="button"
              onclick="document.querySelector('.ai-chat-panel')?.scrollIntoView({behavior:'smooth',block:'nearest'}); setTimeout(()=>document.getElementById('ai-message-input')?.focus(),300)">
              ↑ Go to chat
            </button>
          </div>`;
    this._container.innerHTML = `<div class="mission-list-panel">${header}${body}</div>`;
    this._bindMissions();
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
        if (action === 'show') this._onSelectedShowRequested();
        else if (action === 'hide') this._onSelectedHideRequested();
        else if (action === 'clear') this._onSelectionCleared();
        else if (action === 'delete') this._onSelectedDeleteRequested();
      });
    });
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
