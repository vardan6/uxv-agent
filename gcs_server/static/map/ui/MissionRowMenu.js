// Per-row overflow popover (⋯) for secondary Mission actions: rename, delete.
// Colour is intentionally NOT here — recolouring stays on the leading rail so
// there is exactly one path to it (mission-sidebar-toolbar.md → Row Simplification).
// Positioning/dismiss mirror MissionListOverflowMenu so the two menus behave
// identically (scroll/resize reposition, Escape/outside-click close).

export class MissionRowMenu {
  constructor(container) {
    this._container = container;
    this._popover = null;
    this._dismissHandler = null;
    this._repositionHandler = null;
  }

  open(anchorEl, { items = [] } = {}) {
    this.close();
    const pop = document.createElement('div');
    pop.className = 'mission-row-menu';
    pop.setAttribute('role', 'menu');
    pop.setAttribute('aria-label', 'Mission actions');

    for (const item of items) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mission-row-menu-item' + (item.danger ? ' is-danger' : '');
      btn.setAttribute('role', 'menuitem');
      btn.textContent = item.label;
      if (item.disabled) {
        btn.disabled = true;
        if (item.disabledTitle) btn.title = item.disabledTitle;
      } else {
        btn.addEventListener('click', () => { this.close(); item.onClick(); });
      }
      pop.appendChild(btn);
    }

    pop.addEventListener('click', (e) => e.stopPropagation());
    document.body.appendChild(pop);
    this._popover = pop;

    this._positionNear(anchorEl);
    this._repositionHandler = () => this._positionNear(anchorEl);

    this._dismissHandler = (e) => {
      if (e.type === 'keydown' && e.key !== 'Escape') return;
      if (e.type === 'mousedown' && pop.contains(e.target)) return;
      if (e.type === 'mousedown' && anchorEl.contains(e.target)) return;
      this.close();
    };
    setTimeout(() => {
      document.addEventListener('mousedown', this._dismissHandler);
      document.addEventListener('keydown', this._dismissHandler);
      this._container.addEventListener('scroll', this._repositionHandler, { passive: true });
      window.addEventListener('resize', this._repositionHandler);
    }, 0);
  }

  _positionNear(anchorEl) {
    if (!anchorEl || !this._popover) return;
    const anchorRect = anchorEl.getBoundingClientRect();
    const popRect = this._popover.getBoundingClientRect();
    const inset = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = anchorRect.right - popRect.width;
    let top = anchorRect.bottom + 6;
    if (top + popRect.height + inset > vh) {
      top = anchorRect.top - popRect.height - 6;
    }
    left = Math.max(inset, Math.min(left, vw - popRect.width - inset));
    top = Math.max(inset, Math.min(top, vh - popRect.height - inset));
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
    if (this._repositionHandler) {
      this._container.removeEventListener('scroll', this._repositionHandler);
      window.removeEventListener('resize', this._repositionHandler);
      this._repositionHandler = null;
    }
  }
}
