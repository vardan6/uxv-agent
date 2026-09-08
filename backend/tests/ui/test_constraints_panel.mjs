import test from 'node:test';
import assert from 'node:assert/strict';

class FakeClassList {
  constructor(owner) {
    this._owner = owner;
    this._set = new Set();
  }

  add(...tokens) {
    tokens.forEach((token) => this._set.add(token));
    this._sync();
  }

  contains(token) {
    return this._set.has(token);
  }

  _sync() {
    this._owner.className = Array.from(this._set).join(' ');
  }
}

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.classList = new FakeClassList(this);
    this.style = {};
    this.hidden = false;
    this.textContent = '';
    this.disabled = false;
    this.type = '';
    this.title = '';
    this.attributes = new Map();
    this._listeners = new Map();
  }

  append(...nodes) {
    nodes.forEach((node) => this.appendChild(node));
  }

  appendChild(node) {
    if (!(node instanceof FakeElement)) {
      const text = new FakeElement('#text', this.ownerDocument);
      text.textContent = String(node);
      node = text;
    }
    node.parentNode = this;
    this.children.push(node);
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [];
    nodes.forEach((node) => this.appendChild(node));
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  addEventListener(type, handler) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(handler);
  }

  click() {
    for (const handler of this._listeners.get('click') || []) {
      handler({ currentTarget: this, target: this, preventDefault() {} });
    }
  }
}

class FakeDocument {
  constructor() {
    this.body = new FakeElement('body', this);
  }

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function allElements(root) {
  const out = [];
  for (const child of root.children) {
    out.push(child, ...allElements(child));
  }
  return out;
}

function findButton(root, text) {
  return allElements(root).find((el) => el.tagName === 'BUTTON' && el.textContent === text) || null;
}

const document = new FakeDocument();
const windowState = { promptValue: null, confirmValue: true, prompts: [], confirms: [] };
globalThis.document = document;
globalThis.window = {
  prompt(message, value) {
    windowState.prompts.push({ message, value });
    return windowState.promptValue;
  },
  confirm(message) {
    windowState.confirms.push(message);
    return windowState.confirmValue;
  },
};

const { ConstraintsPanel } = await import('../../static/map/ui/ConstraintsPanel.js');

function makeConstraint(overrides = {}) {
  return {
    id: 'constraint-1',
    name: 'Lane one',
    kind: 'allowed_corridor',
    rule: 'soft',
    enabled: true,
    version: 3,
    ...overrides,
  };
}

test('ConstraintsPanel renders empty state and close callback', () => {
  let closed = 0;
  const host = document.createElement('div');
  document.body.appendChild(host);
  const panel = new ConstraintsPanel(host, { onClose: () => { closed += 1; } });

  panel.show([]);
  assert.equal(panel.visible, true);
  assert.equal(panel._listEl.children.length, 1);
  assert.equal(panel._listEl.children[0].textContent, 'No constraints yet. Draw one with ▱ Constraint.');

  const closeBtn = findButton(panel._el, '✕');
  assert.ok(closeBtn);
  closeBtn.click();
  assert.equal(panel.visible, false);
  assert.equal(closed, 1);
});

test('ConstraintsPanel rename, rule toggle, enable toggle, and delete callbacks use the expected payloads', async () => {
  const edits = [];
  const toggles = [];
  const deletes = [];
  const host = document.createElement('div');
  document.body.appendChild(host);
  const constraint = makeConstraint({ enabled: false });
  const panel = new ConstraintsPanel(host, {
    onEdit: async (row, patch) => { edits.push({ row, patch }); },
    onToggleEnabled: async (row) => { toggles.push(row); },
    onDelete: async (row) => { deletes.push(row); },
  });

  panel.show([constraint]);

  const row = panel._listEl.children[0];
  assert.equal(row.classList.contains('is-disabled'), true);
  const label = allElements(row).find((el) => el.className === 'map-constraints-panel__label');
  assert.ok(label);
  assert.match(label.textContent, /Lane one · Allowed corridor · soft · disabled/);

  windowState.promptValue = 'Renamed lane';
  findButton(row, 'Rename').click();
  await Promise.resolve();
  assert.deepEqual(edits.shift(), { row: constraint, patch: { name: 'Renamed lane' } });

  findButton(row, 'Make hard').click();
  await Promise.resolve();
  assert.deepEqual(edits.shift(), { row: constraint, patch: { rule: 'hard' } });

  findButton(row, 'Enable').click();
  await Promise.resolve();
  assert.deepEqual(toggles.shift(), constraint);

  windowState.confirmValue = false;
  findButton(row, 'Delete').click();
  await Promise.resolve();
  assert.equal(deletes.length, 0);

  windowState.confirmValue = true;
  findButton(row, 'Delete').click();
  await Promise.resolve();
  assert.deepEqual(deletes.shift(), constraint);
  assert.match(windowState.confirms.at(-1), /Delete constraint "Lane one"\? This cannot be undone\./);
});

test('ConstraintsPanel skips rename when prompt is cancelled, blank, or unchanged', async () => {
  const edits = [];
  const host = document.createElement('div');
  document.body.appendChild(host);
  const constraint = makeConstraint({ name: 'Keep me' });
  const panel = new ConstraintsPanel(host, {
    onEdit: async (row, patch) => { edits.push({ row, patch }); },
  });

  panel.show([constraint]);
  const renameBtn = findButton(panel._listEl.children[0], 'Rename');

  windowState.promptValue = null;
  renameBtn.click();
  windowState.promptValue = '   ';
  renameBtn.click();
  windowState.promptValue = 'Keep me';
  renameBtn.click();
  await Promise.resolve();

  assert.deepEqual(edits, []);
});
