export class HintToasts {
  constructor(container) {
    this._el = document.createElement('div');
    this._el.className = 'map-hint-toast';
    this._el.hidden = true;
    this._el.setAttribute('aria-live', 'polite');
    container.appendChild(this._el);
    this._timer = null;
  }

  show(msg, { duration = 2500 } = {}) {
    clearTimeout(this._timer);
    this._el.textContent = msg;
    this._el.hidden = false;
    this._timer = setTimeout(() => { this._el.hidden = true; }, duration);
  }

  hide() {
    clearTimeout(this._timer);
    this._el.hidden = true;
  }
}
