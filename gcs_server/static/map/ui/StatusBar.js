function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const MAX_MESSAGES = 100;

export class StatusBar {
  constructor() {
    this._messages = [];
    this._el = null;
    this._logEl = null;
    this._countEl = null;
    this._collapsed = false;
  }

  mount(container) {
    this._el = container;
    container.innerHTML = `
      <div class="gcs-status-bar">
        <button class="gcs-status-bar-toggle" type="button" aria-expanded="true" title="Toggle status log">
          <span class="gcs-status-bar-label">Status</span>
          <span class="gcs-status-bar-count" aria-label="0 events">0</span>
          <span class="gcs-status-bar-caret" aria-hidden="true">▾</span>
        </button>
        <div class="gcs-status-bar-log" role="log" aria-live="polite" aria-label="GCS status log">
          <div class="gcs-status-bar-empty">No events yet.</div>
        </div>
      </div>
    `;
    this._logEl = container.querySelector('.gcs-status-bar-log');
    this._countEl = container.querySelector('.gcs-status-bar-count');
    const toggle = container.querySelector('.gcs-status-bar-toggle');
    const bar = container.querySelector('.gcs-status-bar');
    toggle.addEventListener('click', () => {
      this._collapsed = !this._collapsed;
      bar.classList.toggle('is-collapsed', this._collapsed);
      toggle.setAttribute('aria-expanded', String(!this._collapsed));
    });
  }

  push(text, level = 'info') {
    const ts = new Date().toLocaleTimeString(undefined, {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    this._messages.push({ text: String(text || ''), level: String(level || 'info'), ts });
    if (this._messages.length > MAX_MESSAGES) this._messages.shift();
    this._update();
  }

  clear() {
    this._messages = [];
    this._update();
  }

  _update() {
    if (!this._logEl) return;
    const count = this._messages.length;
    if (this._countEl) {
      this._countEl.textContent = String(count);
      this._countEl.setAttribute('aria-label', `${count} event${count === 1 ? '' : 's'}`);
    }
    if (!count) {
      this._logEl.innerHTML = '<div class="gcs-status-bar-empty">No events yet.</div>';
      return;
    }
    this._logEl.innerHTML = this._messages.map(({ text, level, ts }) => `<div class="gcs-status-bar-row is-${escapeHtml(level)}"><span class="gcs-status-bar-ts">${escapeHtml(ts)}</span><span class="gcs-status-bar-msg">${escapeHtml(text)}</span></div>`).join('');
    this._logEl.scrollTop = this._logEl.scrollHeight;
  }
}
