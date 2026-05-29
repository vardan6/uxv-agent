export class MissionBulkActionBar {
  constructor(container, { onDelete, onHide, onShow, onClearSelection } = {}) {
    this._container = container;
    this._onDelete = onDelete || (() => {});
    this._onHide = onHide || (() => {});
    this._onShow = onShow || (() => {});
    this._onClearSelection = onClearSelection || (() => {});
    this._el = null;
    this._countLabel = null;
    this._deleteBtn = null;
    this._buildDOM();
  }

  _buildDOM() {
    this._el = document.createElement('div');
    this._el.className = 'mission-bulk-bar';
    this._el.hidden = true;
    this._el.setAttribute('role', 'toolbar');
    this._el.setAttribute('aria-label', 'Bulk mission actions');

    this._countLabel = document.createElement('span');
    this._countLabel.className = 'mission-bulk-count';

    const sep = () => {
      const s = document.createElement('span');
      s.className = 'mission-bulk-sep';
      s.setAttribute('aria-hidden', 'true');
      s.textContent = '·';
      return s;
    };

    this._deleteBtn = document.createElement('button');
    this._deleteBtn.type = 'button';
    this._deleteBtn.className = 'mission-bulk-btn mission-bulk-btn-danger';
    this._deleteBtn.setAttribute('aria-label', 'Delete selected missions');
    this._deleteBtn.addEventListener('click', () => this._onDelete());

    const hideBtn = document.createElement('button');
    hideBtn.type = 'button';
    hideBtn.className = 'mission-bulk-btn';
    hideBtn.textContent = 'Hide';
    hideBtn.setAttribute('aria-label', 'Hide selected missions from map');
    hideBtn.addEventListener('click', () => this._onHide());

    const showBtn = document.createElement('button');
    showBtn.type = 'button';
    showBtn.className = 'mission-bulk-btn';
    showBtn.textContent = 'Show';
    showBtn.setAttribute('aria-label', 'Show selected missions on map');
    showBtn.addEventListener('click', () => this._onShow());

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'mission-bulk-clear';
    clearBtn.textContent = '✕';
    clearBtn.setAttribute('aria-label', 'Clear selection');
    clearBtn.addEventListener('click', () => this._onClearSelection());

    this._el.append(this._countLabel, sep(), this._deleteBtn, sep(), hideBtn, showBtn, clearBtn);
    this._container.append(this._el);
  }

  update(count) {
    if (count < 2) {
      this._el.hidden = true;
      return;
    }
    this._el.hidden = false;
    this._countLabel.textContent = `${count} selected`;
    this._deleteBtn.textContent = `Delete ${count}`;
  }

  hide() {
    if (this._el) this._el.hidden = true;
  }
}
