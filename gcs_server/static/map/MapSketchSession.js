// Renderer-independent sketch state for map authoring (Phase 2 — Decision B).
// Owns active tool, canonical WGS84 draft geometry, vertex-level undo stack,
// and async status text. Contains no Leaflet or DOM references — view adapters
// consume it.

export class MapSketchSession {
  constructor() {
    this._tool = null;           // null | 'corridor' | 'survey' | 'fence' | 'constraint'
    this._vertices = [];         // {lat, lon}[] — canonical WGS84
    this._constraintMeta = null; // {kind, rule} | null
    this._undoStack = [];        // {lat,lon}[][] for vertex-level undo
    this._statusText = '';       // override for async op messages (Saving…/Error…)
    this._listeners = [];        // multiple subscribers allowed (MapWidget + view adapters)
  }

  // ── Accessors ─────────────────────────────────────────────────────────────

  get tool() { return this._tool; }
  get isDirty() { return this._tool !== null; }

  // Defensive copy so callers cannot mutate internal state.
  get vertices() { return this._vertices.slice(); }
  get constraintMeta() { return this._constraintMeta ? { ...this._constraintMeta } : null; }

  // State snapshot consumed by MapAuthoringToolbar.updateState().
  getState() {
    return {
      drawMode: this._tool,
      drawPointCount: this._vertices.length,
      statusText: this._statusText,
      constraintKind: this._constraintMeta?.kind ?? null,
      constraintRule: this._constraintMeta?.rule ?? null,
    };
  }

  // ── Observer ──────────────────────────────────────────────────────────────

  // Registers a listener. Multiple subscribers are allowed (view adapters + MapWidget).
  // Returns an unsubscribe function.
  onChange(fn) {
    this._listeners.push(fn);
    return () => { this._listeners = this._listeners.filter((l) => l !== fn); };
  }

  // ── Commands ──────────────────────────────────────────────────────────────

  startTool(tool, meta = null) {
    this._tool = tool;
    this._constraintMeta = meta ? { ...meta } : null;
    this._vertices = [];
    this._undoStack = [];
    this._statusText = '';
    this._notify();
  }

  // `vertex` accepts {lat, lon} or {lat, lng} (Leaflet LatLng).
  addVertex(vertex) {
    if (!this._tool) return;
    // Survey uses exactly 2 corner points; a third click restarts corner 1.
    if (this._tool === 'survey' && this._vertices.length >= 2) {
      this._pushUndo();
      this._vertices = [];
    }
    this._pushUndo();
    this._vertices.push({ lat: vertex.lat, lon: vertex.lon ?? vertex.lng });
    this._statusText = '';
    this._notify();
  }

  undoVertex() {
    if (!this._tool || this._undoStack.length === 0) return;
    this._vertices = this._undoStack.pop();
    this._statusText = '';
    this._notify();
  }

  // Set async op text (Saving…/Error…/Saved.) without changing draw state.
  setStatus(text) {
    this._statusText = text || '';
    this._notify();
  }

  reset() {
    this._tool = null;
    this._vertices = [];
    this._constraintMeta = null;
    this._undoStack = [];
    this._statusText = '';
    this._notify();
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  _pushUndo() {
    this._undoStack.push(this._vertices.slice());
  }

  _notify() {
    for (const fn of this._listeners) fn();
  }
}
