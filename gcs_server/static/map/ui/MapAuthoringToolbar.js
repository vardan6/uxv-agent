function setTooltip(node, enabledTitle, disabledTitle, disabled) {
  if (!node) return;
  const title = disabled ? (disabledTitle || '') : (enabledTitle || '');
  if (title) node.title = title;
  else node.removeAttribute('title');
}

function canGenerateFromDrawState(drawMode, drawPointCount) {
  if (drawMode === 'survey') return drawPointCount === 2;
  if (drawMode === 'corridor') return drawPointCount >= 2;
  return false;
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
  } = {}) {
    this._onToggleAddWaypoint = onToggleAddWaypoint;
    this._onTogglePatternDraw = onTogglePatternDraw;
    this._onToggleFenceDraw = onToggleFenceDraw;
    this._onGeneratePattern = onGeneratePattern;
    this._onSaveFence = onSaveFence;
    this._onClearFence = onClearFence;
    this._onClearSketch = onClearSketch;

    this._state = {
      addWaypointEnabled: false,
      addWaypointActive: false,
      addWaypointReason: 'Select an editable mission revision to add waypoints.',
      drawToolsEnabled: false,
      drawToolsReason: 'Scene views do not yet support shared WGS84 sketch capture; use Basemap VIEW for corridor and survey tools.',
      geofenceEnabled: false,
      geofenceReason: 'Scene views do not yet support shared WGS84 sketch capture; use Basemap VIEW to edit geofences.',
      drawMode: null,
      drawPointCount: 0,
      statusText: '',
    };

    this._titles = {
      pattern: 'Pattern generator',
      spacing: 'Waypoint / line spacing (m)',
      altitude: 'Altitude (m)',
      passes: 'Passes (corridor)',
      draw: 'Sketch a corridor or survey pattern on the basemap',
      generate: 'Generate a mission from the current sketch',
      clear: 'Clear the current sketch',
      fence: 'Sketch an inclusion geofence on the basemap',
      saveFence: 'Save the current geofence sketch onto the focused mission',
      clearFence: 'Remove the mission geofence',
    };

    this._el = document.createElement('div');
    this._el.className = 'map-authoring-toolbar map-authoring-toolbar--basemap';
    parent.appendChild(this._el);
    this._build();
    this.updateState();
  }

  _build() {
    const mk = (tag, props = {}, style = {}) => {
      const node = document.createElement(tag);
      Object.assign(node, props);
      Object.assign(node.style, style);
      return node;
    };

    this._addWaypointBtn = mk('button', { type: 'button', textContent: 'Add waypoint' });
    this._addWaypointBtn.addEventListener('click', () => {
      if (this._addWaypointBtn.disabled) return;
      this._onToggleAddWaypoint?.();
    });

    this._patternSel = mk('select', { title: this._titles.pattern });
    for (const [value, label] of [['corridor', 'Corridor'], ['survey', 'Survey']]) {
      this._patternSel.appendChild(mk('option', { value, textContent: label }));
    }

    this._spacingInput = mk('input', { type: 'number', value: '5', min: '0.5', step: '0.5', title: this._titles.spacing }, { width: '52px' });
    this._altInput = mk('input', { type: 'number', value: '0', step: '0.5', title: this._titles.altitude }, { width: '52px' });
    this._passesInput = mk('input', { type: 'number', value: '1', min: '1', step: '1', title: this._titles.passes }, { width: '44px' });

    this._drawBtn = mk('button', { type: 'button', textContent: '✏️ Draw', title: this._titles.draw });
    this._drawBtn.addEventListener('click', () => {
      if (this._drawBtn.disabled) return;
      this._onTogglePatternDraw?.(this._patternSel.value === 'survey' ? 'survey' : 'corridor');
    });
    this._genBtn = mk('button', { type: 'button', textContent: 'Generate', disabled: true, title: this._titles.generate });
    this._genBtn.addEventListener('click', () => {
      if (this._genBtn.disabled) return;
      const activePattern = this._state.drawMode === 'survey' ? 'survey' : 'corridor';
      this._onGeneratePattern?.({
        pattern: activePattern,
        spacing: Number(this._spacingInput.value) || 5,
        altitude: Number(this._altInput.value) || 0,
        passes: Math.max(1, parseInt(this._passesInput.value, 10) || 1),
      });
    });
    this._clearBtn = mk('button', { type: 'button', textContent: 'Clear', title: this._titles.clear });
    this._clearBtn.addEventListener('click', () => {
      if (this._clearBtn.disabled) return;
      this._onClearSketch?.();
    });

    this._fenceBtn = mk('button', { type: 'button', textContent: '🛡 Fence', title: this._titles.fence });
    this._fenceBtn.addEventListener('click', () => {
      if (this._fenceBtn.disabled) return;
      this._onToggleFenceDraw?.();
    });
    this._saveFenceBtn = mk('button', { type: 'button', textContent: 'Save fence', disabled: true, title: this._titles.saveFence });
    this._saveFenceBtn.addEventListener('click', () => {
      if (this._saveFenceBtn.disabled) return;
      this._onSaveFence?.();
    });
    this._clearFenceBtn = mk('button', { type: 'button', textContent: 'Clear fence', title: this._titles.clearFence });
    this._clearFenceBtn.addEventListener('click', () => {
      if (this._clearFenceBtn.disabled) return;
      this._onClearFence?.();
    });

    this._statusEl = mk('span', { textContent: '' }, { color: '#555' });

    this._el.append(
      this._addWaypointBtn,
      mk('span', { textContent: '|' }, { color: '#b9c4d0' }),
      this._patternSel, mk('span', { textContent: 'sp' }), this._spacingInput,
      mk('span', { textContent: 'alt' }), this._altInput,
      mk('span', { textContent: '×' }), this._passesInput,
      this._drawBtn, this._genBtn, this._clearBtn,
      mk('span', { textContent: '|' }, { color: '#b9c4d0' }),
      this._fenceBtn, this._saveFenceBtn, this._clearFenceBtn,
      this._statusEl,
    );
  }

  updateState(nextState = {}) {
    this._state = { ...this._state, ...nextState };
    const state = this._state;

    this._statusEl.textContent = state.statusText || '';

    this._addWaypointBtn.disabled = !state.addWaypointEnabled;
    this._addWaypointBtn.classList.toggle('is-active', !!state.addWaypointActive);
    this._addWaypointBtn.setAttribute('aria-pressed', state.addWaypointActive ? 'true' : 'false');
    setTooltip(
      this._addWaypointBtn,
      state.addWaypointActive ? 'Click the map to place waypoints. Click again to leave add mode.' : 'Append waypoints by clicking the map.',
      state.addWaypointReason,
      !state.addWaypointEnabled,
    );

    const drawDisabled = !state.drawToolsEnabled;
    const drawGenerateReady = canGenerateFromDrawState(state.drawMode, state.drawPointCount);
    const drawClearReady = state.drawPointCount > 0;
    this._patternSel.disabled = drawDisabled;
    this._spacingInput.disabled = drawDisabled;
    this._altInput.disabled = drawDisabled;
    this._passesInput.disabled = drawDisabled;
    this._drawBtn.disabled = drawDisabled;
    this._drawBtn.textContent = state.drawMode === 'corridor' || state.drawMode === 'survey' ? '■ Stop' : '✏️ Draw';
    this._genBtn.disabled = drawDisabled || !drawGenerateReady;
    this._clearBtn.disabled = drawDisabled || !drawClearReady;
    setTooltip(this._patternSel, this._titles.pattern, state.drawToolsReason, drawDisabled);
    setTooltip(this._spacingInput, this._titles.spacing, state.drawToolsReason, drawDisabled);
    setTooltip(this._altInput, this._titles.altitude, state.drawToolsReason, drawDisabled);
    setTooltip(this._passesInput, this._titles.passes, state.drawToolsReason, drawDisabled);
    setTooltip(this._drawBtn, this._titles.draw, state.drawToolsReason, drawDisabled);
    setTooltip(this._genBtn, this._titles.generate, state.drawToolsReason, drawDisabled);
    setTooltip(this._clearBtn, this._titles.clear, state.drawToolsReason, drawDisabled);

    const geofenceDisabled = !state.geofenceEnabled;
    const saveFenceReady = state.drawMode === 'fence' && state.drawPointCount >= 3;
    this._fenceBtn.disabled = geofenceDisabled;
    this._fenceBtn.textContent = state.drawMode === 'fence' ? '■ Stop' : '🛡 Fence';
    this._saveFenceBtn.disabled = geofenceDisabled || !saveFenceReady;
    this._clearFenceBtn.disabled = geofenceDisabled;
    setTooltip(this._fenceBtn, this._titles.fence, state.geofenceReason, geofenceDisabled);
    setTooltip(this._saveFenceBtn, this._titles.saveFence, state.geofenceReason, geofenceDisabled);
    setTooltip(this._clearFenceBtn, this._titles.clearFence, state.geofenceReason, geofenceDisabled);
  }

  destroy() {
    this._el.remove();
  }
}
