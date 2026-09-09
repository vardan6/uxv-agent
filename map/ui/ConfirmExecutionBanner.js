// Confirm-mode async banner (ADR 0021 §1).
//
// When the AI agent calls arm_execution in Confirm mode, the server arms the run
// and opens a bounded confirm window (status === 'awaiting_confirm') instead of
// starting it. This banner surfaces that window: it shows the armed mission with
// a live countdown and a [Play] the operator must press before the window
// elapses. Chat does not block while it is open; the operator can also dismiss.
//
// The widget is presentational + timing only. The owner (MapWidget) polls
// /api/ai/execution/state and calls show(state)/hide(); the [Play]/[Dismiss]
// callbacks issue confirmExecution/cancelExecution.

export class ConfirmExecutionBanner {
  constructor(parent, { onConfirm, onCancel } = {}) {
    this._onConfirm = onConfirm || (() => {});
    this._onCancel = onCancel || (() => {});
    this._deadline = 0;
    this._tickTimer = null;
    this._busy = false;

    const el = document.createElement('div');
    el.className = 'map-confirm-banner';
    el.setAttribute('role', 'alert');
    el.hidden = true;
    el.innerHTML = `
      <span class="map-confirm-banner-text"></span>
      <span class="map-confirm-banner-countdown" aria-live="polite"></span>
      <button class="map-confirm-banner-play" type="button" aria-label="Confirm and start mission">▶ Play</button>
      <button class="map-confirm-banner-dismiss" type="button" aria-label="Dismiss without starting">✕</button>
    `;
    this._el = el;
    this._textEl = el.querySelector('.map-confirm-banner-text');
    this._countdownEl = el.querySelector('.map-confirm-banner-countdown');
    this._playBtn = el.querySelector('.map-confirm-banner-play');
    this._dismissBtn = el.querySelector('.map-confirm-banner-dismiss');

    this._playBtn.addEventListener('click', () => this._fire(this._onConfirm));
    this._dismissBtn.addEventListener('click', () => this._fire(this._onCancel));

    if (parent) parent.append(el);
  }

  // state is the server execution snapshot. Only 'awaiting_confirm' shows the
  // banner; any other status (running/cancelled/expired/null) hides it.
  show(state) {
    if (!state || state.status !== 'awaiting_confirm') {
      this.hide();
      return;
    }
    const missionId = String(state.mission_id || 'mission');
    this._textEl.textContent = `Armed: ${missionId} — confirm to start`;
    // Prefer an absolute deadline (epoch seconds) so the countdown stays honest
    // across polls; fall back to remaining seconds when only that is given.
    const now = Date.now() / 1000;
    if (Number(state.confirm_deadline) > 0) {
      this._deadline = Number(state.confirm_deadline);
    } else {
      this._deadline = now + (Number(state.confirm_remaining_s) || 0);
    }
    this._busy = false;
    this._playBtn.disabled = false;
    this._dismissBtn.disabled = false;
    this._el.hidden = false;
    this._renderCountdown();
    this._startTick();
  }

  hide() {
    this._stopTick();
    this._deadline = 0;
    this._el.hidden = true;
  }

  destroy() {
    this._stopTick();
    this._el.remove();
  }

  _fire(handler) {
    if (this._busy) return;
    this._busy = true;
    this._playBtn.disabled = true;
    this._dismissBtn.disabled = true;
    this._stopTick();
    Promise.resolve(handler()).finally(() => { this._busy = false; });
  }

  _startTick() {
    this._stopTick();
    this._tickTimer = setInterval(() => this._renderCountdown(), 250);
  }

  _stopTick() {
    if (this._tickTimer !== null) {
      clearInterval(this._tickTimer);
      this._tickTimer = null;
    }
  }

  _renderCountdown() {
    const remaining = Math.max(0, this._deadline - Date.now() / 1000);
    this._countdownEl.textContent = `${Math.ceil(remaining)}s`;
    this._el.classList.toggle('is-urgent', remaining <= 3);
    if (remaining <= 0) {
      // Window elapsed client-side; stop counting and let the server reject a
      // late confirm. The owner's next poll reconciles the status.
      this._stopTick();
      this._playBtn.disabled = true;
    }
  }
}
