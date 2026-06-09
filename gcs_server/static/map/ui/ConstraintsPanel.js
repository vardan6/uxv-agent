// Operational-constraints list panel (ADR 0025). A small overlay card that
// lists every planning constraint (enabled and disabled), with enable/disable
// and delete. Disabling is the reversible path; delete is guarded by a confirm.
// The panel is presentation only — the caller (MapWidget) owns the API calls
// and re-feeds the refreshed list via `update`.

const KIND_LABEL = { allowed_corridor: 'Allowed corridor', blockage: 'Blockage' };

export class ConstraintsPanel {
  constructor(parent, { onToggleEnabled = null, onDelete = null, onClose = null } = {}) {
    this._onToggleEnabled = onToggleEnabled;
    this._onDelete = onDelete;
    this._onClose = onClose;
    this._list = [];

    this._el = document.createElement('div');
    this._el.className = 'map-constraints-panel';
    this._el.hidden = true;
    this._el.setAttribute('role', 'dialog');
    this._el.setAttribute('aria-label', 'Planning constraints');

    const header = document.createElement('div');
    header.className = 'map-constraints-panel__header';
    const title = document.createElement('strong');
    title.textContent = 'Planning constraints';
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.textContent = '✕';
    closeBtn.title = 'Close';
    closeBtn.addEventListener('click', () => this.hide());
    header.append(title, closeBtn);

    this._note = document.createElement('div');
    this._note.className = 'map-constraints-panel__note';
    this._note.textContent = 'Planning only — hard rules reject violating routes; they are not live containment.';

    this._listEl = document.createElement('div');
    this._listEl.className = 'map-constraints-panel__list';

    this._el.append(header, this._note, this._listEl);
    parent.appendChild(this._el);
  }

  get visible() {
    return !this._el.hidden;
  }

  show(list) {
    if (Array.isArray(list)) this._list = list;
    this._el.hidden = false;
    this._render();
  }

  hide() {
    this._el.hidden = true;
    this._onClose?.();
  }

  update(list) {
    this._list = Array.isArray(list) ? list : [];
    if (!this._el.hidden) this._render();
  }

  _render() {
    this._listEl.replaceChildren();
    if (!this._list.length) {
      const empty = document.createElement('div');
      empty.className = 'map-constraints-panel__empty';
      empty.textContent = 'No constraints yet. Draw one with ▱ Constraint.';
      this._listEl.appendChild(empty);
      return;
    }
    for (const c of this._list) {
      const row = document.createElement('div');
      row.className = 'map-constraints-panel__row';
      if (c.enabled === false) row.classList.add('is-disabled');

      const swatch = document.createElement('span');
      swatch.className = 'map-constraints-panel__swatch';
      swatch.style.background = c.kind === 'blockage' ? '#e67e22' : '#2e8b57';
      if (c.rule === 'soft') swatch.classList.add('is-soft');

      const label = document.createElement('span');
      label.className = 'map-constraints-panel__label';
      const kindLabel = KIND_LABEL[c.kind] || c.kind;
      const ruleLabel = c.rule === 'soft' ? 'soft' : 'hard';
      label.textContent = `${c.name || kindLabel} · ${kindLabel} · ${ruleLabel}${c.enabled === false ? ' · disabled' : ''}`;

      const enableBtn = document.createElement('button');
      enableBtn.type = 'button';
      enableBtn.textContent = c.enabled === false ? 'Enable' : 'Disable';
      enableBtn.title = c.enabled === false ? 'Enable on the map and in planning' : 'Hide from planning (reversible)';
      enableBtn.addEventListener('click', () => {
        enableBtn.disabled = true;
        Promise.resolve(this._onToggleEnabled?.(c)).finally(() => { enableBtn.disabled = false; });
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.textContent = 'Delete';
      deleteBtn.className = 'is-danger';
      deleteBtn.title = 'Permanently remove this constraint';
      deleteBtn.addEventListener('click', () => {
        if (!window.confirm(`Delete constraint "${c.name || kindLabel}"? This cannot be undone.`)) return;
        deleteBtn.disabled = true;
        Promise.resolve(this._onDelete?.(c)).finally(() => { deleteBtn.disabled = false; });
      });

      row.append(swatch, label, enableBtn, deleteBtn);
      this._listEl.appendChild(row);
    }
  }

  destroy() {
    this._el.remove();
  }
}
