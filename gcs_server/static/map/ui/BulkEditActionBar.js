export class BulkEditActionBar {
  constructor(container, { onDelete, onSetAltitude, onClearSelection } = {}) {
    this._container = container;
    this._onDelete = onDelete || (() => {});
    this._onSetAltitude = onSetAltitude || (() => {});
    this._onClearSelection = onClearSelection || (() => {});
    this._el = null;
    this._countLabel = null;
    this._deleteBtn = null;
    this._altInput = null;
    this._buildDOM();
  }

  _buildDOM() {
    this._el = document.createElement('div');
    this._el.className = 'map-bulk-bar';
    this._el.hidden = true;
    this._el.setAttribute('role', 'toolbar');
    this._el.setAttribute('aria-label', 'Bulk waypoint actions');

    this._countLabel = document.createElement('span');
    this._countLabel.className = 'map-bulk-count';

    const sep = () => {
      const s = document.createElement('span');
      s.className = 'map-bulk-sep';
      s.setAttribute('aria-hidden', 'true');
      s.textContent = '·';
      return s;
    };

    // Altitude row
    const altLabel = document.createElement('label');
    altLabel.className = 'map-bulk-alt-label';
    altLabel.textContent = 'Alt:';

    this._altInput = document.createElement('input');
    this._altInput.type = 'number';
    this._altInput.className = 'map-bulk-alt-input';
    this._altInput.setAttribute('aria-label', 'Altitude in metres');
    this._altInput.step = '0.1';
    this._altInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        this._applyAltitude();
      }
    });
    altLabel.appendChild(this._altInput);

    const applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'map-bulk-btn';
    applyBtn.textContent = 'Apply';
    applyBtn.setAttribute('aria-label', 'Set altitude for selected waypoints');
    applyBtn.addEventListener('click', () => this._applyAltitude());

    this._deleteBtn = document.createElement('button');
    this._deleteBtn.type = 'button';
    this._deleteBtn.className = 'map-bulk-btn map-bulk-btn-danger';
    this._deleteBtn.setAttribute('aria-label', 'Delete selected waypoints');
    this._deleteBtn.addEventListener('click', () => this._onDelete());

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'map-bulk-clear';
    clearBtn.textContent = '✕';
    clearBtn.setAttribute('aria-label', 'Clear selection');
    clearBtn.addEventListener('click', () => this._onClearSelection());

    this._el.append(
      this._countLabel,
      sep(),
      altLabel, applyBtn,
      sep(),
      this._deleteBtn,
      clearBtn,
    );
    this._container.append(this._el);
  }

  _applyAltitude() {
    const z = parseFloat(this._altInput.value);
    if (!isNaN(z)) this._onSetAltitude(z);
  }

  update(selectedIndices, waypoints, isEditable) {
    const count = selectedIndices.size;
    if (count < 2 || !isEditable) {
      this._el.hidden = true;
      return;
    }
    this._el.hidden = false;
    this._countLabel.textContent = `${count} selected`;
    this._deleteBtn.textContent = `Delete ${count}`;

    // Pre-fill altitude with median z of selected waypoints (don't clobber active input)
    if (document.activeElement !== this._altInput) {
      const zValues = [...selectedIndices]
        .map((i) => waypoints[i]?.z ?? 0)
        .sort((a, b) => a - b);
      const medZ = zValues[Math.floor(zValues.length / 2)];
      this._altInput.value = parseFloat(medZ.toFixed(2));
    }
  }

  hide() {
    if (this._el) this._el.hidden = true;
  }
}
