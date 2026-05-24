export class ContextMenu {
  constructor(container) {
    this._el = document.createElement('menu');
    this._el.className = 'map-context-menu';
    this._el.hidden = true;
    this._el.style.position = 'absolute';
    container.appendChild(this._el);
    this._outsideHandler = (e) => {
      if (!this._el.contains(e.target)) this.close();
    };
  }

  open(x, y, items) {
    this._el.innerHTML = '';
    for (const { label, action } of items) {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'map-context-menu-item';
      btn.textContent = label;
      btn.addEventListener('click', () => { this.close(); action(); });
      li.appendChild(btn);
      this._el.appendChild(li);
    }
    this._el.style.left = `${x}px`;
    this._el.style.top = `${y}px`;
    this._el.hidden = false;
    // Defer so this same click event doesn't immediately close the menu.
    setTimeout(() => document.addEventListener('click', this._outsideHandler), 0);
  }

  close() {
    this._el.hidden = true;
    document.removeEventListener('click', this._outsideHandler);
  }

  get isOpen() {
    return !this._el.hidden;
  }
}
