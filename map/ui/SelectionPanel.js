const PROV_LABEL = {
  ai: 'AI-planned',
  user: 'User-placed',
  'ai+edited': 'AI + edited',
};

export class SelectionPanel {
  constructor(container, { onClose } = {}) {
    this._container = container;
    this._onClose = onClose || (() => {});
    container.hidden = true;
  }

  show(waypoint, index) {
    const prov = waypoint.provenance || 'ai';
    const provLabel = PROV_LABEL[prov] || prov;
    const provClass = `map-prov-${prov.replace('+', '-')}`;
    this._container.hidden = false;
    this._container.innerHTML = `
      <div class="map-selection-panel">
        <div class="map-selection-header">
          <span class="map-selection-title">Waypoint ${index + 1}</span>
          <button class="map-selection-close" type="button" aria-label="Close waypoint inspector">✕</button>
        </div>
        <dl class="map-selection-details">
          <dt>X</dt><dd>${waypoint.x.toFixed(2)} m</dd>
          <dt>Y</dt><dd>${waypoint.y.toFixed(2)} m</dd>
          <dt>Z</dt><dd>${waypoint.z.toFixed(2)} m</dd>
          <dt>Provenance</dt><dd class="${provClass}">${provLabel}</dd>
        </dl>
      </div>
    `;
    this._container.querySelector('.map-selection-close')
      .addEventListener('click', () => this._onClose());
  }

  hide() {
    this._container.hidden = true;
    this._container.innerHTML = '';
  }
}
