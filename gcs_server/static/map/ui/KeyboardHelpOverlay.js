const SHORTCUTS = [
  ['V', 'Toggle vertex-edit mode'],
  ['A', 'Toggle add-waypoint mode'],
  ['F', 'Fit map to selection (falls back to scene)'],
  ['Delete / Backspace', 'Delete selected waypoint(s)'],
  ['[ / ]', 'Step to previous / next waypoint'],
  ['Shift + click', 'Extend selection'],
  ['Ctrl / Cmd + click', 'Toggle selection'],
  ['Drag on empty map', 'Marquee multi-select waypoints'],
  ['Alt (during drag)', 'Snap dragged waypoint to nearby waypoint'],
  ['Esc', 'Close menu → clear selection → exit edit'],
  ['/', 'Focus session search'],
  ['?', 'Show this help'],
];

export class KeyboardHelpOverlay {
  constructor(container) {
    this._dialog = document.createElement('dialog');
    this._dialog.className = 'map-keyboard-help-dialog';
    this._dialog.innerHTML = `
      <h3 class="map-kbhelp-title">Map keyboard shortcuts</h3>
      <table class="map-kbhelp-table">
        <tbody>
          ${SHORTCUTS.map(([key, desc]) => `
            <tr>
              <td><kbd class="map-kbhelp-key">${key}</kbd></td>
              <td>${desc}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <form method="dialog" class="map-kbhelp-footer">
        <button class="map-kbhelp-close" type="submit">Close</button>
      </form>
    `;
    container.appendChild(this._dialog);
  }

  show() {
    if (!this._dialog.open) this._dialog.showModal();
  }

  close() {
    if (this._dialog.open) this._dialog.close();
  }
}
