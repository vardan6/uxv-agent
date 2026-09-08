// Minimum clearance thresholds (metres above terrain) by vehicle kind.
const MIN_CLEARANCE = { multirotor: 3, fixed_wing: 5 };

export class ElevationProfilePanel {
  constructor(container, { onWaypointClick } = {}) {
    this._container = container;
    this._onWaypointClick = onWaypointClick || (() => {});
    this._collapsed = false;
    this._statusChip = null;
    this._chartWrap = null;
    this._toggleBtn = null;
    this._buildDOM();
  }

  _buildDOM() {
    const header = document.createElement('div');
    header.className = 'map-elev-header';

    const title = document.createElement('span');
    title.className = 'map-elev-title';
    title.textContent = 'Elevation Profile';

    this._statusChip = document.createElement('span');
    this._statusChip.className = 'map-elev-chip';
    this._statusChip.hidden = true;

    this._toggleBtn = document.createElement('button');
    this._toggleBtn.type = 'button';
    this._toggleBtn.className = 'map-elev-toggle';
    this._toggleBtn.setAttribute('aria-label', 'Toggle elevation profile');
    this._toggleBtn.textContent = '▾';
    this._toggleBtn.addEventListener('click', () => this._toggle());

    header.append(title, this._statusChip, this._toggleBtn);

    this._chartWrap = document.createElement('div');
    this._chartWrap.className = 'map-elev-chart-wrap';

    this._container.append(header, this._chartWrap);
    this.clear();
  }

  _toggle() {
    this._collapsed = !this._collapsed;
    this._chartWrap.hidden = this._collapsed;
    this._toggleBtn.textContent = this._collapsed ? '▸' : '▾';
  }

  update(waypoints, sampleHeight, { color = '#4e79a7', vehicleKind = 'ground' } = {}) {
    if (!waypoints || waypoints.length < 2) {
      this.clear(waypoints && waypoints.length === 1
        ? 'Need ≥ 2 waypoints to show profile.'
        : 'Select a mission to view elevation profile.');
      return;
    }

    // Cumulative distances along route
    const distances = [0];
    for (let i = 1; i < waypoints.length; i++) {
      const dx = waypoints[i].x - waypoints[i - 1].x;
      const dy = waypoints[i].y - waypoints[i - 1].y;
      distances.push(distances[i - 1] + Math.hypot(dx, dy));
    }
    const totalDist = distances[distances.length - 1];

    const terrainH = waypoints.map((wp) => sampleHeight(wp.x, wp.y));
    const routeH   = waypoints.map((wp) => wp.z);
    const clearances = waypoints.map((_, i) => routeH[i] - terrainH[i]);
    const minClearance = Math.min(...clearances);
    const threshold = MIN_CLEARANCE[vehicleKind] ?? 0;
    const hasBelowTerrain = minClearance < -0.05;
    const hasLowClearance = !hasBelowTerrain && minClearance < threshold;

    if (hasBelowTerrain) {
      this._statusChip.textContent = '⚠ BELOW TERRAIN';
      this._statusChip.className = 'map-elev-chip map-elev-chip-danger';
    } else if (hasLowClearance) {
      this._statusChip.textContent = '⚠ LOW CLEARANCE';
      this._statusChip.className = 'map-elev-chip map-elev-chip-warn';
    } else {
      this._statusChip.textContent = '✓ CLEAR';
      this._statusChip.className = 'map-elev-chip map-elev-chip-ok';
    }
    this._statusChip.hidden = false;

    const allH = [...terrainH, ...routeH];
    const minH = Math.min(...allH) - 0.5;
    const maxH = Math.max(...allH) + 0.5;

    this._renderSVG({ waypoints, distances, terrainH, routeH, clearances,
      totalDist, minH, maxH, color, vehicleKind, threshold });
  }

  _renderSVG({ waypoints, distances, terrainH, routeH, clearances,
               totalDist, minH, maxH, color, vehicleKind, threshold }) {
    const PAD = { top: 14, right: 12, bottom: 22, left: 42 };
    const SVG_H = 130;
    const SVG_W = this._chartWrap.clientWidth || 600;
    const iW = SVG_W - PAD.left - PAD.right;
    const iH = SVG_H - PAD.top - PAD.bottom;
    const botY = PAD.top + iH;

    const xS = (d) => PAD.left + (totalDist > 0 ? (d / totalDist) * iW : 0);
    const yS = (h) => PAD.top + iH - ((h - minH) / Math.max(maxH - minH, 0.001)) * iH;

    const terrainPts = waypoints.map((_, i) => `${xS(distances[i]).toFixed(1)},${yS(terrainH[i]).toFixed(1)}`);
    const routePts   = waypoints.map((_, i) => `${xS(distances[i]).toFixed(1)},${yS(routeH[i]).toFixed(1)}`);

    // Terrain fill polygon: bottom-left → terrain points → bottom-right
    const terrainPolyPts = [
      `${PAD.left},${botY}`,
      ...terrainPts,
      `${PAD.left + iW},${botY}`,
    ].join(' ');

    // Clearance fill polygon: route forward + terrain reversed
    const clearanceFillPts = [...routePts, ...[...terrainPts].reverse()].join(' ');

    // Y-axis ticks
    const hRange = maxH - minH;
    const rawStep = hRange / 4;
    const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(rawStep, 0.01))));
    const tickStep = Math.ceil(rawStep / magnitude) * magnitude || 1;
    const ticks = [];
    for (let h = Math.ceil(minH / tickStep) * tickStep; h <= maxH + tickStep * 0.01; h += tickStep) {
      ticks.push(parseFloat(h.toFixed(6)));
    }

    // Minimum clearance line for aerial vehicles
    let clearanceLineSVG = '';
    if (threshold > 0) {
      const clPts = waypoints.map((_, i) =>
        `${xS(distances[i]).toFixed(1)},${yS(terrainH[i] + threshold).toFixed(1)}`).join(' ');
      clearanceLineSVG = `<polyline points="${clPts}" fill="none" stroke="#f0a030" stroke-width="1" stroke-dasharray="4,3" opacity="0.8"/>`;
    }

    // X-axis distance labels: first, last, and up to 2 mid-points
    const xLabels = [];
    const labelIndices = new Set([0, waypoints.length - 1]);
    if (waypoints.length > 3) labelIndices.add(Math.round(waypoints.length / 2));
    for (const idx of labelIndices) {
      const lx = xS(distances[idx]);
      const anchor = idx === 0 ? 'start' : idx === waypoints.length - 1 ? 'end' : 'middle';
      xLabels.push(`<text x="${lx.toFixed(1)}" y="${botY + 14}" class="map-elev-label" text-anchor="${anchor}">${distances[idx].toFixed(0)}m</text>`);
    }

    const dotsAndLabels = waypoints.map((_, i) => {
      const cx = xS(distances[i]).toFixed(1);
      const cy = yS(routeH[i]).toFixed(1);
      const isBelow = clearances[i] < -0.05;
      const dotColor = isBelow ? '#e05050' : color;
      return `
<circle cx="${cx}" cy="${cy}" r="4.5" fill="${dotColor}" stroke="#fff" stroke-width="1.5" class="map-elev-dot" data-index="${i}" style="cursor:pointer"/>
<text x="${cx}" y="${(yS(routeH[i]) - 7).toFixed(1)}" class="map-elev-label map-elev-wp-num" text-anchor="middle">${i + 1}</text>`;
    }).join('');

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${SVG_W}" height="${SVG_H}" class="map-elev-svg" role="img" aria-label="Elevation profile">
  ${ticks.map((h) => `
  <line x1="${PAD.left}" y1="${yS(h).toFixed(1)}" x2="${PAD.left + iW}" y2="${yS(h).toFixed(1)}" class="map-elev-grid"/>
  <text x="${(PAD.left - 4).toFixed(1)}" y="${(yS(h) + 3.5).toFixed(1)}" class="map-elev-label" text-anchor="end">${h % 1 === 0 ? h : h.toFixed(1)}</text>`).join('')}
  <line x1="${PAD.left}" y1="${PAD.top}" x2="${PAD.left}" y2="${botY}" class="map-elev-axis"/>
  <line x1="${PAD.left}" y1="${botY}" x2="${PAD.left + iW}" y2="${botY}" class="map-elev-axis"/>
  <polygon points="${terrainPolyPts}" class="map-elev-terrain-fill"/>
  <polygon points="${clearanceFillPts}" class="map-elev-clearance-fill"/>
  <polyline points="${terrainPts.join(' ')}" fill="none" class="map-elev-terrain-line"/>
  ${clearanceLineSVG}
  <polyline points="${routePts.join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  ${dotsAndLabels}
  ${xLabels.join('')}
</svg>`;

    this._chartWrap.innerHTML = svg;

    this._chartWrap.querySelectorAll('.map-elev-dot').forEach((dot) => {
      dot.addEventListener('click', (e) => {
        e.stopPropagation();
        this._onWaypointClick(parseInt(dot.dataset.index, 10));
      });
    });
  }

  highlight(index) {
    this._chartWrap.querySelectorAll('.map-elev-dot').forEach((dot) => {
      const i = parseInt(dot.dataset.index, 10);
      dot.setAttribute('r', i === index ? '6' : '4.5');
      dot.setAttribute('stroke-width', i === index ? '2.5' : '1.5');
    });
  }

  clear(msg = 'Select a mission to view elevation profile.') {
    if (this._chartWrap) {
      this._chartWrap.innerHTML = `<p class="map-elev-empty">${msg}</p>`;
    }
    if (this._statusChip) this._statusChip.hidden = true;
  }
}
