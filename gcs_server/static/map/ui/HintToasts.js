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
    this._el.classList.remove('has-action');
    this._el.hidden = false;
    this._timer = setTimeout(() => { this._el.hidden = true; }, duration);
  }

  showWithAction(msg, { actionLabel = 'Undo', onAction = null, duration = 8000 } = {}) {
    clearTimeout(this._timer);
    this._el.textContent = '';
    this._el.classList.add('has-action');

    const text = document.createElement('span');
    text.className = 'map-hint-toast-text';
    text.textContent = msg;
    this._el.appendChild(text);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'map-hint-toast-action';
    btn.textContent = actionLabel;
    btn.addEventListener('click', () => {
      this.hide();
      if (typeof onAction === 'function') onAction();
    });
    this._el.appendChild(btn);

    this._el.hidden = false;
    this._timer = setTimeout(() => { this._el.hidden = true; }, duration);
  }

  hide() {
    clearTimeout(this._timer);
    this._el.hidden = true;
  }
}
