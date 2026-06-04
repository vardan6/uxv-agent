import { SORT_OPTIONS } from '../state/missionSortPreference.js';

// Header-overflow popover: sort radio list.
// Import/export (JSON) will be wired in Phase D2.

export class MissionListOverflowMenu {
  constructor(container) {
    this._container = container;
    this._popover = null;
    this._dismissHandler = null;
    this._opts = null;
  }

  open(anchorEl, opts = {}) {
    this.close();
    this._opts = opts;
    const currentSort = opts.currentSort || SORT_OPTIONS[0].id;
    const onSortChange = opts.onSortChange || (() => {});
    const onExport = opts.onExport || (() => {});
    const onImport = opts.onImport || (() => {});

    const pop = document.createElement('div');
    pop.className = 'mission-list-overflow-menu';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Mission list options');

    const sortGroup = document.createElement('div');
    sortGroup.className = 'mission-overflow-group';
    sortGroup.innerHTML = `<p class="mission-overflow-group-label">Sort by</p>`;
    const sortList = document.createElement('div');
    sortList.className = 'mission-overflow-sort-list';
    for (const option of SORT_OPTIONS) {
      const id = `mission-sort-${option.id}`;
      const row = document.createElement('label');
      row.className = 'mission-overflow-sort-row';
      row.htmlFor = id;
      row.innerHTML = `
        <input type="radio" id="${id}" name="mission-sort" value="${option.id}" ${option.id === currentSort ? 'checked' : ''}>
        <span>${option.label}</span>
      `;
      row.querySelector('input').addEventListener('change', (e) => {
        if (e.target.checked) {
          onSortChange(option.id);
        }
      });
      sortList.appendChild(row);
    }
    sortGroup.appendChild(sortList);

    const ioGroup = document.createElement('div');
    ioGroup.className = 'mission-overflow-group';
    ioGroup.innerHTML = `<p class="mission-overflow-group-label">File</p>`;
    const exportBtn = document.createElement('button');
    exportBtn.type = 'button';
    exportBtn.className = 'mission-overflow-action-btn';
    exportBtn.textContent = 'Export missions…';
    exportBtn.addEventListener('click', () => { this.close(); onExport(); });
    const importBtn = document.createElement('button');
    importBtn.type = 'button';
    importBtn.className = 'mission-overflow-action-btn';
    importBtn.textContent = 'Import missions…';
    importBtn.addEventListener('click', () => { this.close(); onImport(); });
    ioGroup.append(exportBtn, importBtn);

    pop.append(sortGroup, ioGroup);
    pop.addEventListener('click', (e) => e.stopPropagation());
    this._container.appendChild(pop);
    this._popover = pop;

    this._positionNear(anchorEl);

    this._dismissHandler = (e) => {
      if (e.type === 'keydown' && e.key !== 'Escape') return;
      if (e.type === 'mousedown' && pop.contains(e.target)) return;
      this.close();
    };
    setTimeout(() => {
      document.addEventListener('mousedown', this._dismissHandler);
      document.addEventListener('keydown', this._dismissHandler);
    }, 0);
  }

  _positionNear(anchorEl) {
    if (!anchorEl || !this._popover) return;
    const containerRect = this._container.getBoundingClientRect();
    const anchorRect = anchorEl.getBoundingClientRect();
    const popWidth = 200;
    let left = anchorRect.right - containerRect.left - popWidth;
    let top  = anchorRect.bottom - containerRect.top + 4;
    if (left < 8) left = 8;
    const maxLeft = this._container.clientWidth - popWidth - 8;
    if (left > maxLeft) left = Math.max(8, maxLeft);
    this._popover.style.left = `${left}px`;
    this._popover.style.top = `${top}px`;
  }

  close() {
    if (this._popover) {
      this._popover.remove();
      this._popover = null;
    }
    if (this._dismissHandler) {
      document.removeEventListener('mousedown', this._dismissHandler);
      document.removeEventListener('keydown', this._dismissHandler);
      this._dismissHandler = null;
    }
    this._opts = null;
  }
}
