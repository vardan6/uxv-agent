function setTooltip(node, enabledTitle, disabledTitle, disabled) {
  if (!node) return;
  const title = disabled ? (disabledTitle || '') : (enabledTitle || '');
  if (title) node.title = title;
  else node.removeAttribute('title');
}

function mk(tag, props = {}) {
  return Object.assign(document.createElement(tag), props);
}

export class MapAuthoringToolbar {
  constructor(parent, {
    onToggleAddWaypoint = null,
    onTogglePatternDraw = null,
    onToggleFenceDraw = null,
    onGeneratePattern = null,
    onSaveFence = null,
    onClearFence = null,
    onClearSketch = null,
    onToggleConstraintDraw = null,
    onSaveConstraint = null,
    onOpenConstraints = null,
    onUndoVertex = null,
    onParamsChange = null,
  } = {}) {
    this._onToggleAddWaypoint = onToggleAddWaypoint;
    this._onTogglePatternDraw = onTogglePatternDraw;
    this._onToggleFenceDraw = onToggleFenceDraw;
    this._onGeneratePattern = onGeneratePattern;
    this._onSaveFence = onSaveFence;
    this._onClearFence = onClearFence;
    this._onClearSketch = onClearSketch;
    this._onToggleConstraintDraw = onToggleConstraintDraw;
    this._onSaveConstraint = onSaveConstraint;
    this._onOpenConstraints = onOpenConstraints;
    this._onUndoVertex = onUndoVertex;
    this._onParamsChange = onParamsChange;

    this._collapsed = false;
    this._prevHasActiveTool = false;

    this._state = {
      addWaypointEnabled: false,
      addWaypointActive: false,
      addWaypointReason: 'Select an editable mission revision to add waypoints.',
      drawToolsEnabled: false,
      drawToolsReason: 'Focus a mission to enable GPS-based drawing on this view.',
      geofenceEnabled: false,
      geofenceReason: 'Focus a mission to enable GPS-based drawing on this view.',
      constraintToolsEnabled: false,
      constraintToolsReason: 'Focus a mission to enable GPS-based drawing on this view.',
      drawMode: null,
      drawPointCount: 0,
      statusText: '',
      constraintKind: null,
      constraintRule: null,
      surveyHeading: 0,
    };

    this._el = document.createElement('div');
    this._el.className = 'map-authoring-toolbar';
    this._el.addEventListener('keydown', (e) => this._handleKeyDown(e));
    parent.appendChild(this._el);
    this._build();
    this.updateState();
  }

  // ── Keyboard contract ─────────────────────────────────────────────────────

  _handleKeyDown(e) {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    const { drawMode, addWaypointActive } = this._state;
    const hasActiveTool = drawMode != null || addWaypointActive;
    if (hasActiveTool) {
      // Cancel the active sketch/tool; calling code will updateState() to idle
      if (addWaypointActive) this._onToggleAddWaypoint?.();
      else this._onClearSketch?.();
    } else if (!this._collapsed) {
      this._setCollapsed(true);
    }
  }

  // ── Section: Collapsed launcher ──────────────────────────────────────────

  _buildLauncher() {
    const el = document.createElement('div');
    el.className = 'mat-section mat-launcher';

    this._launcherBtn = mk('button', { type: 'button', className: 'mat-launcher-btn' });
    this._launcherBtn.setAttribute('aria-label', 'Open map authoring tools');
    this._launcherBtn.setAttribute('aria-expanded', 'false');
    this._launcherBtn.setAttribute('aria-controls', 'mat-expanded-region');
    this._launcherBtn.innerHTML = '✏ Authoring';

    this._draftDotEl = mk('span', { className: 'mat-draft-dot', title: 'Unsaved draft in progress' });
    this._draftDotEl.textContent = ' •';
    this._launcherBtn.append(this._draftDotEl);

    this._launcherBtn.addEventListener('click', () => this._setCollapsed(false));
    el.append(this._launcherBtn);
    return el;
  }

  // ── Section: Expanded idle (tool choices only) ───────────────────────────

  _buildIdle() {
    const el = document.createElement('div');
    el.className = 'mat-section mat-idle';
    el.setAttribute('role', 'toolbar');
    el.setAttribute('aria-label', 'Map authoring tools');
    el.id = 'mat-expanded-region';

    const sep = () => {
      const s = mk('span', { className: 'mat-sep' });
      s.setAttribute('aria-hidden', 'true');
      s.textContent = '|';
      return s;
    };

    this._waypointBtn = mk('button', { type: 'button', textContent: 'Add waypoint' });
    this._waypointBtn.addEventListener('click', () => {
      if (!this._waypointBtn.disabled) this._onToggleAddWaypoint?.();
    });

    this._corridorBtn = mk('button', { type: 'button', textContent: 'Corridor pattern' });
    this._corridorBtn.addEventListener('click', () => {
      if (!this._corridorBtn.disabled) this._onTogglePatternDraw?.('corridor');
    });

    this._surveyBtn = mk('button', { type: 'button', textContent: 'Survey area' });
    this._surveyBtn.addEventListener('click', () => {
      if (!this._surveyBtn.disabled) this._onTogglePatternDraw?.('survey');
    });

    this._geofenceBtn = mk('button', { type: 'button', textContent: 'Mission geofence' });
    this._geofenceBtn.addEventListener('click', () => {
      if (!this._geofenceBtn.disabled) this._onToggleFenceDraw?.();
    });

    this._constraintsMenuBtn = mk('button', {
      type: 'button',
      textContent: 'Constraints ▾',
      title: 'Draw operational planning constraints (allowed corridors and blockages)',
    });

    this._idleCollapseBtn = mk('button', { type: 'button', textContent: '▾' });
    this._idleCollapseBtn.setAttribute('aria-label', 'Collapse authoring toolbar');
    this._idleCollapseBtn.title = 'Collapse authoring toolbar';
    this._idleCollapseBtn.addEventListener('click', () => this._setCollapsed(true));

    el.append(
      this._waypointBtn, sep(),
      this._corridorBtn, this._surveyBtn, sep(),
      this._geofenceBtn, sep(),
      this._constraintsMenuBtn, sep(),
      this._idleCollapseBtn,
    );
    return el;
  }

  // ── Section: Active tool contextual bar ──────────────────────────────────

  _buildActive() {
    const el = document.createElement('div');
    el.className = 'mat-section mat-active';

    this._toolNameEl = mk('span', { className: 'mat-tool-name' });
    this._statusEl = mk('span', { className: 'mat-status-text' });
    this._statusEl.setAttribute('aria-live', 'polite');
    this._statusEl.setAttribute('aria-atomic', 'true');

    // Pattern geometry fields (corridor + survey)
    this._patternFieldsEl = mk('span', { className: 'mat-pattern-fields' });

    this._spacingInput = mk('input', { type: 'number', value: '5', min: '0.5', step: '0.5', title: 'Waypoint / line spacing (m)' });
    this._spacingInput.style.width = '52px';
    this._altInput = mk('input', { type: 'number', value: '0', step: '0.5', title: 'Altitude (m)' });
    this._altInput.style.width = '52px';
    this._passesInput = mk('input', { type: 'number', value: '1', min: '1', step: '1', title: 'Passes (corridor)' });
    this._passesInput.style.width = '44px';

    // Live footprint preview: push Spacing/Passes edits to the adapter while a
    // corridor/survey sketch is open (Phase 3), before commit.
    const emitParams = () => this._emitParamsChange();
    this._spacingInput.addEventListener('input', emitParams);
    this._passesInput.addEventListener('input', emitParams);

    const spacingLbl = mk('label', { title: 'Waypoint / line spacing' });
    spacingLbl.append(document.createTextNode('Spacing '), this._spacingInput, document.createTextNode(' m'));
    this._passesLbl = mk('label', { title: 'Number of parallel passes' });
    this._passesLbl.append(document.createTextNode('Passes '), this._passesInput);
    const altLbl = mk('label', { title: 'Flight altitude above ground' });
    altLbl.append(document.createTextNode('Altitude '), this._altInput, document.createTextNode(' m'));
    this._patternFieldsEl.append(spacingLbl, this._passesLbl, altLbl);

    // Undo last vertex
    this._undoBtn = mk('button', { type: 'button', textContent: '↩ Undo', title: 'Remove last vertex' });
    this._undoBtn.addEventListener('click', () => this._onUndoVertex?.());

    // Primary commit action (label changes per tool)
    this._finishBtn = mk('button', { type: 'button', className: 'mat-finish-btn' });
    this._finishBtn.addEventListener('click', () => this._handleFinish());

    // Discard in-progress draft only — never removes persisted objects
    this._cancelBtn = mk('button', { type: 'button', textContent: 'Cancel sketch', title: 'Discard in-progress sketch' });
    this._cancelBtn.addEventListener('click', () => this._onClearSketch?.());

    // Waypoint mode: "Done" replaces Finish + Cancel
    this._waypointDoneBtn = mk('button', { type: 'button', textContent: 'Done', title: 'Leave add-waypoint mode' });
    this._waypointDoneBtn.addEventListener('click', () => this._onToggleAddWaypoint?.());

    this._activeCollapseBtn = mk('button', { type: 'button', textContent: '▾' });
    this._activeCollapseBtn.setAttribute('aria-label', 'Collapse authoring toolbar');
    this._activeCollapseBtn.title = 'Collapse authoring toolbar (draft is preserved)';
    this._activeCollapseBtn.addEventListener('click', () => this._setCollapsed(true));

    el.append(
      this._toolNameEl, this._statusEl,
      this._patternFieldsEl,
      this._undoBtn, this._finishBtn, this._cancelBtn,
      this._waypointDoneBtn,
      this._activeCollapseBtn,
    );
    return el;
  }

  _emitParamsChange() {
    const { drawMode } = this._state;
    if (drawMode !== 'corridor' && drawMode !== 'survey') return;
    this._onParamsChange?.({
      pattern: drawMode,
      spacing: Number(this._spacingInput.value) || 0,
      passes: Math.max(1, parseInt(this._passesInput.value, 10) || 1),
    });
  }

  _handleFinish() {
    const { drawMode } = this._state;
    if (drawMode === 'corridor' || drawMode === 'survey') {
      this._onGeneratePattern?.({
        pattern: drawMode,
        spacing: Number(this._spacingInput.value) || 5,
        altitude: Number(this._altInput.value) || 0,
        passes: Math.max(1, parseInt(this._passesInput.value, 10) || 1),
      });
    } else if (drawMode === 'fence') {
      this._onSaveFence?.();
    } else if (drawMode === 'constraint') {
      this._onSaveConstraint?.();
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  _build() {
    this._launcherEl = this._buildLauncher();
    this._idleEl = this._buildIdle();
    this._activeEl = this._buildActive();
    this._el.append(this._launcherEl, this._idleEl, this._activeEl);
  }

  _setCollapsed(collapsed) {
    this._collapsed = collapsed;
    this.updateState();
    // Move focus: expanding → first idle button; collapsing → launcher
    if (collapsed) {
      this._launcherBtn.focus();
    } else {
      this._focusFirstIdleBtn();
    }
  }

  _focusFirstIdleBtn() {
    const btns = [this._waypointBtn, this._corridorBtn, this._surveyBtn, this._geofenceBtn];
    const target = btns.find(b => !b.disabled && !b.hidden) ?? this._idleCollapseBtn;
    target?.focus();
  }

  // ── State ─────────────────────────────────────────────────────────────────

  updateState(nextState = {}) {
    this._state = { ...this._state, ...nextState };
    const s = this._state;

    const hasActiveTool = s.drawMode != null || s.addWaypointActive;
    const hasDraft = s.drawPointCount > 0;
    const toolTransitioned = hasActiveTool !== this._prevHasActiveTool;
    this._prevHasActiveTool = hasActiveTool;

    // Which section is visible?
    this._launcherEl.hidden = !this._collapsed;
    this._idleEl.hidden = this._collapsed || hasActiveTool;
    this._activeEl.hidden = this._collapsed || !hasActiveTool;

    this._launcherBtn.setAttribute('aria-expanded', this._collapsed ? 'false' : 'true');
    this._draftDotEl.hidden = !hasDraft;

    // Idle section
    if (!this._idleEl.hidden) {
      this._waypointBtn.disabled = !s.addWaypointEnabled;
      setTooltip(this._waypointBtn, 'Append waypoints by clicking the map.', s.addWaypointReason, !s.addWaypointEnabled);

      this._corridorBtn.disabled = !s.drawToolsEnabled;
      setTooltip(this._corridorBtn, 'Draw a corridor pattern on the map.', s.drawToolsReason, !s.drawToolsEnabled);

      this._surveyBtn.disabled = !s.drawToolsEnabled;
      setTooltip(this._surveyBtn, 'Draw a survey area on the map.', s.drawToolsReason, !s.drawToolsEnabled);

      this._geofenceBtn.disabled = !s.geofenceEnabled;
      setTooltip(this._geofenceBtn, 'Draw a mission inclusion geofence on the map.', s.geofenceReason, !s.geofenceEnabled);
    }

    // Active section
    if (!this._activeEl.hidden) {
      const waypoint = s.addWaypointActive;
      const corridor = s.drawMode === 'corridor';
      const survey = s.drawMode === 'survey';
      const fence = s.drawMode === 'fence';
      const constraint = s.drawMode === 'constraint';

      // Tool name
      let toolName = '';
      if (waypoint) {
        toolName = 'Add waypoint';
      } else if (corridor) {
        toolName = 'Corridor pattern';
      } else if (survey) {
        toolName = 'Survey area';
      } else if (fence) {
        toolName = 'Mission geofence';
      } else if (constraint) {
        const kindLabel = s.constraintKind === 'blockage' ? 'Blockage' : 'Allowed corridor';
        const ruleLabel = s.constraintRule === 'soft' ? 'Soft' : 'Hard';
        toolName = `${kindLabel} · ${ruleLabel}`;
      }
      this._toolNameEl.textContent = toolName ? toolName + ' ·' : '';

      // Status text
      if (waypoint) {
        this._statusEl.textContent = 'Click the map to place waypoints.';
      } else if (corridor) {
        const ready = s.drawPointCount >= 2;
        this._statusEl.textContent = s.statusText ||
          (ready ? `${s.drawPointCount} vertices · ready to finish` : `${s.drawPointCount} vertices · need ≥ 2`);
      } else if (survey) {
        if (s.statusText) {
          this._statusEl.textContent = s.statusText;
        } else if (s.drawPointCount >= 2) {
          const hdg = Math.round(s.surveyHeading);
          const hdgText = hdg !== 0 ? ` · ${hdg}°` : '';
          this._statusEl.textContent = `2 corners${hdgText} · drag handle to rotate · ready to finish`;
        } else {
          this._statusEl.textContent = `${s.drawPointCount}/2 corners`;
        }
      } else if (fence) {
        const ready = s.drawPointCount >= 3;
        this._statusEl.textContent = s.statusText ||
          `${s.drawPointCount} vertices${ready ? ' · ready to save' : ' · need ≥ 3'}`;
      } else if (constraint) {
        const ready = s.drawPointCount >= 3;
        this._statusEl.textContent = s.statusText ||
          `${s.drawPointCount} vertices${ready ? ' · ready to save' : ' · need ≥ 3'}`;
      }

      // Pattern fields visibility
      this._patternFieldsEl.hidden = !(corridor || survey);
      this._passesLbl.hidden = !corridor;

      // Finish button label and state
      const isWaypointMode = waypoint;
      let finishLabel = 'Finish';
      let finishEnabled = false;
      if (corridor) { finishLabel = 'Create mission'; finishEnabled = s.drawPointCount >= 2; }
      else if (survey) { finishLabel = 'Create mission'; finishEnabled = s.drawPointCount === 2; }
      else if (fence) { finishLabel = 'Save geofence'; finishEnabled = s.drawPointCount >= 3; }
      else if (constraint) { finishLabel = 'Save constraint'; finishEnabled = s.drawPointCount >= 3; }

      this._finishBtn.textContent = finishLabel;
      this._finishBtn.disabled = !finishEnabled;
      this._finishBtn.hidden = isWaypointMode;
      this._cancelBtn.hidden = isWaypointMode;
      this._undoBtn.hidden = isWaypointMode;
      this._undoBtn.disabled = s.drawPointCount === 0;
      this._waypointDoneBtn.hidden = !isWaypointMode;
    }

    // Focus management on tool activate/deactivate transitions
    if (toolTransitioned && !this._collapsed) {
      if (hasActiveTool) {
        // Tool just activated — move focus into the active bar
        const focusTarget = s.addWaypointActive ? this._waypointDoneBtn : this._cancelBtn;
        focusTarget?.focus();
      } else {
        // Tool just exited — return focus to idle bar
        this._focusFirstIdleBtn();
      }
    }
  }

  destroy() {
    this._el.remove();
  }
}
