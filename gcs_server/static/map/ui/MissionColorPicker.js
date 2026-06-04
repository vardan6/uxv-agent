import { MISSION_COLOR_PALETTE } from '../state/missionColorOverrides.js';

// Lightweight popover anchored near a row's colour chip. Renders a swatch
// grid, a "Custom…" hex picker, and a Reset button. Hovering a swatch fires
// onPreview so the caller can re-render the map with the candidate colour;
// onPreview(null) restores the committed colour.

export class MissionColorPicker {
  constructor(container) {
    this._container = container;
    this._popover = null;
    this._dismissHandler = null;
    this._opts = null;
  }

  open(anchorEl, opts = {}) {
    this.close();
    this._opts = opts;
    const onPick = opts.onPick || (() => {});
    const onPreview = opts.onPreview || (() => {});
    const onReset = opts.onReset || (() => {});
    const currentColor = opts.currentColor || '';

    const pop = document.createElement('div');
    pop.className = 'mission-color-picker';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Choose mission colour');

    const grid = document.createElement('div');
    grid.className = 'mission-color-picker-grid';
    for (const swatchColor of MISSION_COLOR_PALETTE) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mission-color-swatch';
      btn.style.background = swatchColor;
      btn.title = swatchColor;
      btn.setAttribute('aria-label', `Pick ${swatchColor}`);
      if (swatchColor.toLowerCase() === currentColor.toLowerCase()) {
        btn.classList.add('is-current');
      }
      btn.addEventListener('mouseenter', () => onPreview(swatchColor));
      btn.addEventListener('mouseleave', () => onPreview(null));
      btn.addEventListener('focus', () => onPreview(swatchColor));
      btn.addEventListener('blur', () => onPreview(null));
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        onPick(swatchColor);
        this.close();
      });
      grid.appendChild(btn);
    }

    const customRow = document.createElement('div');
    customRow.className = 'mission-color-picker-custom';
    const customLabel = document.createElement('label');
    customLabel.textContent = 'Custom… ';
    const customInput = document.createElement('input');
    customInput.type = 'color';
    customInput.value = currentColor || '#66c2a5';
    customInput.addEventListener('input', () => onPreview(customInput.value));
    customInput.addEventListener('change', (e) => {
      e.stopPropagation();
      onPick(customInput.value);
      this.close();
    });
    customLabel.appendChild(customInput);
    customRow.appendChild(customLabel);

    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'mission-color-reset';
    resetBtn.textContent = '↺ Reset';
    resetBtn.title = 'Reset to palette default';
    resetBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      onReset();
      this.close();
    });
    customRow.appendChild(resetBtn);

    pop.append(grid, customRow);
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
    let left = anchorRect.left - containerRect.left;
    let top = anchorRect.bottom - containerRect.top + 4;
    const popRect = { width: 200, height: 120 };
    const maxLeft = this._container.clientWidth - popRect.width - 8;
    if (left > maxLeft) left = Math.max(8, maxLeft);
    if (left < 8) left = 8;
    if (top + popRect.height > this._container.clientHeight) {
      top = Math.max(8, anchorRect.top - containerRect.top - popRect.height - 4);
    }
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
    if (this._opts?.onPreview) this._opts.onPreview(null);
    this._opts = null;
  }
}
