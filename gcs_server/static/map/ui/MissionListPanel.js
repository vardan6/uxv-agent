// Flat-Mission row affordances (ADR 0021 §4 "Sidebar-row affordances"):
// edit + execute resolve to the Mission's active revision and are gated by its
// status. executing → locked (no edit/execute); approved|exported|
// cutover_pending → executable. approve/reject stay off the flat row (draft
// plumbing is internal).
const MISSION_ROW_EDITABLE = new Set(['proposed', 'awaiting_approval', 'planning', 'approved', 'exported', 'cutover_pending']);
const MISSION_ROW_EXECUTABLE = new Set(['approved', 'exported', 'cutover_pending']);

function missionRowActionButtons(missionRow) {
  const activeRevisionId = String(missionRow.activeRevisionId || '');
  const status = String(missionRow.activeRevisionStatus || '');
  if (!activeRevisionId) return '';
  if (status === 'executing') {
    return `<span class="mission-row-lock" aria-label="Mission is executing" title="Mission is executing — editing locked">🔒</span>`;
  }
  const parts = [];
  if (MISSION_ROW_EDITABLE.has(status)) {
    parts.push(`<button class="mission-row-action-btn is-edit" type="button"
      data-edit-mission-id="${String(missionRow.id || '')}"
      title="Edit waypoints"
      aria-label="Edit waypoints">✏</button>`);
  }
  if (MISSION_ROW_EXECUTABLE.has(status)) {
    parts.push(`<button class="mission-row-action-btn is-execute" type="button"
      data-execute-mission-id="${String(missionRow.id || '')}"
      title="Execute on rover (uploads and starts mission)"
      aria-label="Execute on rover">▶</button>`);
  }
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
  } = ctx;
  const id = String(missionRow.id || '');
  const isVisible = visibleMissionIds.has(id);
  const isFocused = focusedMissionId === id;
  const isSelected = selectedMissionIds.has(id);
  const color = paletteByMissionId.get(id) || 'transparent';
  const indexLabel = missionRow.missionIndex != null ? `#${missionRow.missionIndex}` : '';
  return `
    <div class="mission-list-row${isFocused ? ' is-focused' : ''}${isSelected ? ' is-selected' : ''}" data-mission-id="${id}">
      <span class="mission-row-status" aria-hidden="true"></span>
      <label class="mission-row-select" title="Select for batch operations (shift-click for range)">
        <input
          type="checkbox"
          class="mission-row-select-box"
          data-select-mission-id="${id}"
          ${isSelected ? 'checked' : ''}
          aria-label="Select mission ${missionRow.name}"
        />
      </label>
      <button
        class="mission-row-focus"
        type="button"
        data-focus-mission-id="${id}"
        aria-pressed="${isFocused ? 'true' : 'false'}"
        title="Focus mission"
      >
        <span class="mission-row-color-dot" style="--mission-color:${color}"></span>
        <span class="mission-row-main">
          <span class="mission-row-title">${missionRow.name}</span>
          <span class="mission-row-meta">${indexLabel}</span>
        </span>
        <span class="mission-row-origin" title="Mission origin">${missionRow.originBadge}</span>
      </button>
      <span class="mission-row-actions">
        ${missionRowActionButtons(missionRow)}
        <span class="mission-row-visibility-text">${isVisible ? 'Visible' : 'Hidden'}</span>
        <button
          class="mission-row-eye"
          type="button"
          data-toggle-mission-id="${id}"
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
    // Selected state (ADR 0021 §4): batch-operation target set, driven by the
    // per-row checkbox (shift-click extends a range). Distinct from Visible/Active.
    this._onMissionSelectionToggled = opts.onMissionSelectionToggled || (() => {});
    this._onSelectedShowRequested = opts.onSelectedShowRequested || (() => {});
    this._onSelectedHideRequested = opts.onSelectedHideRequested || (() => {});
    this._onSelectionCleared = opts.onSelectionCleared || (() => {});
  }

  renderMissions({
    missions = [],
    focusedMissionId = '',
    visibleMissionIds = new Set(),
    selectedMissionIds = new Set(),
    paletteByMissionId = new Map(),
  } = {}) {
    const batchBar = selectedMissionIds.size
      ? `<div class="mission-batch-bar" role="toolbar" aria-label="Batch operations">
            <span class="mission-batch-count">${selectedMissionIds.size} selected</span>
            <button class="mission-batch-btn" type="button" data-batch-action="show">Show</button>
            <button class="mission-batch-btn" type="button" data-batch-action="hide">Hide</button>
            <button class="mission-batch-btn is-clear" type="button" data-batch-action="clear">Clear</button>
          </div>`
      : '';
    const header = `<div class="mission-list-header">
            <span class="mission-list-heading">Missions</span>
            <a class="mission-list-settings" href="/settings?tab=mission-lifecycle"
              title="Mission lifecycle settings" aria-label="Mission lifecycle settings">⚙</a>
          </div>`;
    const body = missions.length
      ? batchBar + missions.map((missionRow) => missionRowMarkup(missionRow, {
        visibleMissionIds,
        focusedMissionId,
        selectedMissionIds,
        paletteByMissionId,
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
    this._container.querySelectorAll('[data-focus-mission-id]').forEach((button) => {
      button.addEventListener('click', () => this._onMissionFocusRequested(button.dataset.focusMissionId || ''));
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
      });
    });
  }
}
