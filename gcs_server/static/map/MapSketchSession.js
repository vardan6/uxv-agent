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
    this._surveyHeading = 0;     // CCW from east (backend convention); 0 = lines run east
  }

  // ── Accessors ─────────────────────────────────────────────────────────────

  get tool() { return this._tool; }
  get isDirty() { return this._tool !== null; }

  // Defensive copy so callers cannot mutate internal state.
  get vertices() { return this._vertices.slice(); }
  get constraintMeta() { return this._constraintMeta ? { ...this._constraintMeta } : null; }
  get surveyHeading() { return this._surveyHeading; }

  // State snapshot consumed by MapAuthoringToolbar.updateState().
  getState() {
    return {
      drawMode: this._tool,
      drawPointCount: this._vertices.length,
      statusText: this._statusText,
      constraintKind: this._constraintMeta?.kind ?? null,
      constraintRule: this._constraintMeta?.rule ?? null,
      surveyHeading: this._surveyHeading,
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
    this._surveyHeading = 0;
    this._notify();
  }

  // Load an existing polygon as the initial draft (e.g. constraint shape edit).
  // Vertices must be {lat, lon}[]. Undo stack starts empty so the first undo
  // action returns to the pre-edit state (all vertices removed).
  startToolWithVertices(tool, meta, vertices) {
    this._tool = tool;
    this._constraintMeta = meta ? { ...meta } : null;
    this._vertices = vertices.map((v) => ({ lat: v.lat, lon: v.lon }));
    this._undoStack = [];
    this._statusText = '';
    this._surveyHeading = 0;
    this._notify();
  }

  // `deg` is CCW from east (backend convention). Clamps to [0, 360).
  setSurveyHeading(deg) {
    this._surveyHeading = ((Number(deg) % 360) + 360) % 360;
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

  // Reposition one vertex in-place (vertex drag from the Leaflet view adapter).
  moveVertex(index, { lat, lon }) {
    if (!this._tool || index < 0 || index >= this._vertices.length) return;
    this._pushUndo();
    this._vertices[index] = { lat, lon };
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
    this._surveyHeading = 0;
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
