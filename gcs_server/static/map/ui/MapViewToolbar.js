// Floating top-right toolbar over the Leaflet map: fit-to-scene,
// fit-to-selection, and a style switcher. Soft-implementation: the style
// list is a config array so options can be added/removed without refactor.

export const MAP_STYLES = [
  { id: 'terrain',     label: 'Terrain',     hint: 'Coloured heightmap (default)' },
  { id: 'scene-image', label: 'Scene image', hint: 'Heightmap rendered as a full-opacity raster' },
  { id: 'plain-grid',  label: 'Plain grid',  hint: 'No terrain — empty grid only' },
];

export class MapViewToolbar {
  constructor(container, opts = {}) {
    this._container = container;
    this._onFitScene = opts.onFitScene || (() => {});
    this._onFitSelection = opts.onFitSelection || (() => {});
    this._onStyleChange = opts.onStyleChange || (() => {});
    this._currentStyle = opts.initialStyle || 'terrain';
    this._el = null;
    this._styleSelect = null;
    this._build();
  }

  _build() {
    const el = document.createElement('div');
    el.className = 'map-view-toolbar';
    el.setAttribute('role', 'toolbar');
    el.setAttribute('aria-label', 'Map view controls');

    const fitSceneBtn = document.createElement('button');
    fitSceneBtn.type = 'button';
    fitSceneBtn.className = 'map-view-tool-btn';
    fitSceneBtn.title = 'Fit map to full scene';
    fitSceneBtn.setAttribute('aria-label', 'Fit map to full scene');
    fitSceneBtn.innerHTML = '⛶';
    fitSceneBtn.addEventListener('click', () => this._onFitScene());

    const fitSelectionBtn = document.createElement('button');
    fitSelectionBtn.type = 'button';
    fitSelectionBtn.className = 'map-view-tool-btn';
    fitSelectionBtn.title = 'Fit to selection (f)';
    fitSelectionBtn.setAttribute('aria-label', 'Fit map to selection');
    fitSelectionBtn.innerHTML = '◎';
    fitSelectionBtn.addEventListener('click', () => this._onFitSelection());

    const styleSelect = document.createElement('select');
    styleSelect.className = 'map-view-style-select';
    styleSelect.setAttribute('aria-label', 'Map background style');
    styleSelect.title = 'Map background style';
    for (const opt of MAP_STYLES) {
      const optionEl = document.createElement('option');
      optionEl.value = opt.id;
      optionEl.textContent = opt.label;
      optionEl.title = opt.hint;
      styleSelect.appendChild(optionEl);
    }
    styleSelect.value = this._currentStyle;
    styleSelect.addEventListener('change', () => {
      this._currentStyle = styleSelect.value;
      this._onStyleChange(this._currentStyle);
    });
    styleSelect.addEventListener('click', (e) => e.stopPropagation());

    el.append(fitSceneBtn, fitSelectionBtn, styleSelect);
    this._container.appendChild(el);
    this._el = el;
    this._styleSelect = styleSelect;
  }

  get currentStyle() {
    return this._currentStyle;
  }

  setStyle(styleId) {
    if (!MAP_STYLES.some((s) => s.id === styleId)) return;
    this._currentStyle = styleId;
    if (this._styleSelect) this._styleSelect.value = styleId;
  }

  destroy() {
    this._el?.remove();
    this._el = null;
  }
}
