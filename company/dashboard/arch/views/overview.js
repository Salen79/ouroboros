// Overview view — Phase 1.6 ecosystem composition with semantic zoom.
//
// One SVG holds every organ, node and typed edge at fixed coordinates.
// Zoom is achieved by tweening the SVG's viewBox to a target window
// (defined in snapshot.layout.zoom_states). Detail elements fade in/out
// via CSS selectors keyed on data-zoom on the <svg> root.
//
// Levels:
//   L0             → full composition, shows all 5 organs + L0 typed edges
//   L1 <organ>     → viewBox zoomed to one organ, internal edges appear
//   L2 / L3        → opens the side panel for a specific node or tool
//
// Back button + breadcrumb reuse URL hash routing from Phase 1.5.

const EDGE_COLORS = {
  invokes:    '#74b9ff',
  writes_to:  '#fdcb6e',
  reads_from: '#55efc4',
  observes:   '#a29bfe',
  governs:    '#e17055',
};

export class OverviewView {
  constructor({ snapshot, containerId, onSelectLeaf, navigateExternalView }) {
    this.snap = snapshot;
    this.containerId = containerId;
    this.onSelectLeaf = onSelectLeaf;
    this.navigateExternalView = navigateExternalView || (() => {});
    this.container = document.getElementById(containerId);
    this.zoom = 'l0';
    this.animating = false;
    this._suppressHash = false;
  }

  mount() {
    this.container.innerHTML = `
      <div class="ov-root">
        <nav class="ov-crumbs" id="ov-crumbs"></nav>
        <div class="ov-stage">
          ${this._renderSVG()}
        </div>
      </div>
    `;
    this.crumbsEl = document.getElementById('ov-crumbs');
    this.svg = this.container.querySelector('svg.ecosystem');
    this.vbGroup = this.svg.querySelector('.zoom-group');
    this._installInteractions();
    window.addEventListener('hashchange', () => {
      if (this._suppressHash) return;
      this._restoreFromHash();
    });
    this._restoreFromHash();
  }

  // ------------------------------------------------------------------
  // SVG composition
  // ------------------------------------------------------------------

  _renderSVG() {
    const L = this.snap.layout;
    const vb = L.viewbox;
    return `
      <svg class="ecosystem" data-zoom="l0"
           viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"
           preserveAspectRatio="xMidYMid meet"
           overflow="hidden">
        <defs>
          ${this._defs()}
          <clipPath id="viewBoxClip" clipPathUnits="userSpaceOnUse">
            <rect class="vbclip-rect"
                  x="${vb.x}" y="${vb.y}" width="${vb.w}" height="${vb.h}"/>
          </clipPath>
        </defs>
        <g class="zoom-group" clip-path="url(#viewBoxClip)">
          ${this._renderOrganBodies()}
          ${this._renderMemoryBands()}
          ${this._renderEdges()}
          ${this._renderNodes()}
          ${this._renderOrganLabels()}
        </g>
      </svg>
    `;
  }

  _defs() {
    // Per-edge-kind arrowhead markers, pulse keyframe, organ gradient
    const kinds = Object.entries(EDGE_COLORS);
    const markers = kinds.map(([k, c]) => `
      <marker id="arrow-${k}" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="${c}"/>
      </marker>
    `).join('');

    const organGradients = `
      <linearGradient id="g-external" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#636e72" stop-opacity="0.12"/>
        <stop offset="1" stop-color="#636e72" stop-opacity="0.02"/>
      </linearGradient>
      <linearGradient id="g-interface" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#74b9ff" stop-opacity="0.13"/>
        <stop offset="1" stop-color="#74b9ff" stop-opacity="0.03"/>
      </linearGradient>
      <radialGradient id="g-brain" cx="0.5" cy="0.5" r="0.7">
        <stop offset="0" stop-color="#6c5ce7" stop-opacity="0.22"/>
        <stop offset="1" stop-color="#6c5ce7" stop-opacity="0.02"/>
      </radialGradient>
      <linearGradient id="g-tools" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#00b894" stop-opacity="0.16"/>
        <stop offset="1" stop-color="#00b894" stop-opacity="0.04"/>
      </linearGradient>
      <linearGradient id="g-memory" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fdcb6e" stop-opacity="0.04"/>
        <stop offset="1" stop-color="#fdcb6e" stop-opacity="0.18"/>
      </linearGradient>
    `;
    return markers + organGradients;
  }

  _renderOrganBodies() {
    const L = this.snap.layout;
    const parts = [];
    for (const [id, r] of Object.entries(L.organs)) {
      const cls = `organ organ-${id}`;
      parts.push(`
        <g class="${cls}" data-organ="${id}">
          <rect class="organ-bg"
                x="${r.x + 6}" y="${r.y + 6}"
                width="${r.w - 12}" height="${r.h - 12}"
                rx="28" ry="28"
                fill="url(#g-${id})"
                stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/>
        </g>
      `);
    }
    return parts.join('');
  }

  _renderOrganLabels() {
    const L = this.snap.layout;
    const parts = [];
    for (const [id, r] of Object.entries(L.organs)) {
      parts.push(`
        <text class="organ-label l0-label"
              x="${r.label_x}" y="${r.label_y}"
              text-anchor="middle"
              dominant-baseline="hanging">${this._esc(r.label)}</text>
      `);
    }
    return parts.join('');
  }

  _renderMemoryBands() {
    const bands = this.snap.layout.memory_bands;
    const parts = [];
    for (const [id, b] of Object.entries(bands)) {
      parts.push(`
        <g class="mem-band mem-band-${id} detail-only">
          <rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"
                rx="16" ry="16"
                fill="rgba(253,203,110,0.04)"
                stroke="rgba(253,203,110,0.25)" stroke-dasharray="6 6" stroke-width="1"/>
          <text x="${b.label_x}" y="${b.label_y}"
                text-anchor="middle"
                class="mem-band-label">${this._esc(b.label)}</text>
        </g>
      `);
    }
    return parts.join('');
  }

  _renderEdges() {
    const placements = this.snap.layout.nodes;
    const edges = this.snap.typed_edges || [];
    const parts = [];
    for (const e of edges) {
      const s = placements[e.source];
      const t = placements[e.target];
      if (!s || !t) continue;
      const color = EDGE_COLORS[e.kind] || '#8b8fa3';
      const dash = (e.kind === 'reads_from' || e.kind === 'observes') ? '6 5' :
                   (e.kind === 'governs') ? '2 6' : '';
      const path = this._routePath(s, t);
      const cls = `edge edge-${e.kind} vis-${e.visibility}`;
      parts.push(`
        <g class="${cls}" data-edge="${e.source}->${e.target}">
          <path d="${path}"
                stroke="${color}"
                stroke-width="${e.kind === 'governs' ? 2.2 : 1.8}"
                stroke-dasharray="${dash}"
                fill="none"
                marker-end="url(#arrow-${e.kind})"
                opacity="0.82"/>
          <title>${this._esc(e.source + ' → ' + e.target + ': ' + (e.label || e.kind))}</title>
        </g>
      `);
    }
    return parts.join('');
  }

  // Simple orthogonal-ish curve — bezier between endpoints, auto-offset
  // for readability so same-direction edges don't stack.
  _routePath(s, t) {
    const sx = s.cx, sy = s.cy;
    const tx = t.cx, ty = t.cy;
    const dx = tx - sx, dy = ty - sy;
    const dist = Math.hypot(dx, dy);
    // Short edges: straight line; long edges: gentle bezier with midpoint lift
    if (dist < 200) {
      return `M ${sx} ${sy} L ${tx} ${ty}`;
    }
    const mx = (sx + tx) / 2;
    const my = (sy + ty) / 2;
    // Perpendicular offset scaled to distance (small for aesthetic curve)
    const perpX = -dy / dist;
    const perpY = dx / dist;
    const lift = Math.min(80, dist * 0.12);
    const cx = mx + perpX * lift;
    const cy = my + perpY * lift;
    return `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`;
  }

  _renderNodes() {
    const placements = this.snap.layout.nodes;
    const parts = [];
    for (const n of this.snap.topology.nodes) {
      const p = placements[n.id];
      if (!p) continue;
      const w = p.w || 130, h = p.h || 46;
      const x = p.cx - w / 2, y = p.cy - h / 2;
      const hasDZ = (n.dark_zone_ids || []).length > 0;
      const organ = n.organ || 'memory';
      const role = n.functional_role || '';
      const kind = n.kind || '';
      const isPaused = (n.id === 'strategic_planner');

      const cls = [
        'node',
        `node-${n.id}`,
        `organ-${organ}`,
        role ? `role-${role}` : '',
        hasDZ ? 'has-dz' : '',
        isPaused ? 'paused' : '',
        `kind-${kind}`,
      ].filter(Boolean).join(' ');

      parts.push(`
        <g class="${cls}" data-node-id="${n.id}" transform="translate(${x}, ${y})">
          <rect class="node-rect" x="0" y="0" width="${w}" height="${h}"
                rx="8" ry="8"/>
          <text class="node-label" x="${w/2}" y="${h/2}"
                text-anchor="middle" dominant-baseline="central">${this._esc(n.label)}</text>
          ${hasDZ ? `
            <circle class="dz-pulse" cx="${w - 6}" cy="6" r="5" fill="#e17055"/>
            <title>${this._esc(n.label + ' — Dark Zones: ' + (n.dark_zone_ids || []).join(', '))}</title>
          ` : ''}
        </g>
      `);
    }
    return parts.join('');
  }

  // ------------------------------------------------------------------
  // Interactions
  // ------------------------------------------------------------------

  _installInteractions() {
    // Click on a node → open the detail panel (L2)
    this.svg.addEventListener('click', e => {
      const nodeG = e.target.closest('[data-node-id]');
      if (nodeG) {
        this._selectNode(nodeG.dataset.nodeId);
        return;
      }
      // Click on an organ body or label → zoom into (or out of) that organ
      const organG = e.target.closest('[data-organ]');
      if (organG) {
        const target = `l1-${organG.dataset.organ}`;
        if (this.zoom === target) {
          // second click on an already-zoomed organ → zoom out
          this.zoomTo('l0', { push: true });
        } else {
          this.zoomTo(target, { push: true });
        }
        return;
      }
      // Click on empty svg → zoom out
      if (this.zoom !== 'l0') this.zoomTo('l0', { push: true });
    });

    // Hover: highlight neighborhood
    this.svg.addEventListener('mouseover', e => {
      const nodeG = e.target.closest('[data-node-id]');
      if (nodeG) this._highlightNeighborhood(nodeG.dataset.nodeId);
    });
    this.svg.addEventListener('mouseout', e => {
      const nodeG = e.target.closest('[data-node-id]');
      if (nodeG) this._clearHighlight();
    });
  }

  _highlightNeighborhood(nodeId) {
    this.svg.classList.add('hovering');
    // Tag connected edges and peer nodes
    const edges = this.snap.typed_edges || [];
    const neighbors = new Set([nodeId]);
    for (const e of edges) {
      if (e.source === nodeId) neighbors.add(e.target);
      if (e.target === nodeId) neighbors.add(e.source);
    }
    this.svg.querySelectorAll('[data-node-id]').forEach(el => {
      el.classList.toggle('hl-neighbor', neighbors.has(el.dataset.nodeId));
      el.classList.toggle('hl-dim', !neighbors.has(el.dataset.nodeId));
    });
    this.svg.querySelectorAll('[data-edge]').forEach(el => {
      const [s, t] = el.dataset.edge.split('->');
      const active = (s === nodeId || t === nodeId);
      el.classList.toggle('hl-active', active);
      el.classList.toggle('hl-dim', !active);
    });
  }

  _clearHighlight() {
    this.svg.classList.remove('hovering');
    this.svg.querySelectorAll('.hl-neighbor,.hl-dim,.hl-active').forEach(el => {
      el.classList.remove('hl-neighbor', 'hl-dim', 'hl-active');
    });
  }

  _selectNode(id) {
    const node = this.snap.topology.nodes.find(n => n.id === id);
    if (!node) return;
    // Tools registry: if clicked node is registry, open the Tools view instead
    if (id === 'registry') {
      this.navigateExternalView('tools');
      return;
    }
    const data = {
      id: node.id, label: node.label, kind: node.kind, layer: node.layer,
      path: node.path || '', loc: node.loc || 0,
      description: node.description || '',
      dark_zones: node.dark_zone_ids || [],
      functional_role: node.functional_role,
      organ: node.organ,
    };
    this.onSelectLeaf && this.onSelectLeaf({ kind: 'node', data });
  }

  // ------------------------------------------------------------------
  // Zoom
  // ------------------------------------------------------------------

  zoomTo(state, { push = true } = {}) {
    if (this.animating) return;
    const layout = this.snap.layout;
    const states = layout.zoom_states;
    const target = states[state] || states.l0;
    const current = this._parseViewBox(this.svg.getAttribute('viewBox'));
    this.zoom = state;
    this.svg.setAttribute('data-zoom', state);
    if (push) this._setHash(this._stateToHash(state));
    this._renderBreadcrumb();
    this._animateViewBox(current, target);
  }

  _parseViewBox(v) {
    const [x, y, w, h] = v.split(/\s+/).map(Number);
    return { x, y, w, h };
  }

  _animateViewBox(from, to) {
    this.animating = true;
    const start = performance.now();
    const dur = 520; // ms
    const tween = (a, b, t) => a + (b - a) * t;
    const easeInOut = t => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
    const clipRect = this.svg.querySelector('.vbclip-rect');

    const step = now => {
      const t = Math.min(1, (now - start) / dur);
      const k = easeInOut(t);
      const x = tween(from.x, to.x, k);
      const y = tween(from.y, to.y, k);
      const w = tween(from.w, to.w, k);
      const h = tween(from.h, to.h, k);
      this.svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
      if (clipRect) {
        clipRect.setAttribute('x', x);
        clipRect.setAttribute('y', y);
        clipRect.setAttribute('width', w);
        clipRect.setAttribute('height', h);
      }
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        this.animating = false;
      }
    };
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------------
  // Breadcrumb + URL hash
  // ------------------------------------------------------------------

  _renderBreadcrumb() {
    const L = this.snap.layout;
    const crumbs = [
      { label: 'Overview', state: 'l0' },
    ];
    if (this.zoom && this.zoom !== 'l0') {
      const organId = this.zoom.replace(/^l1-/, '');
      const organ = L.organs[organId];
      if (organ) {
        crumbs.push({ label: organ.label, state: this.zoom });
      }
    }
    this.crumbsEl.innerHTML = crumbs.map((c, i) => {
      const last = i === crumbs.length - 1;
      return `<span class="crumb ${last ? 'current' : ''}" data-state="${c.state}">${this._esc(c.label)}</span>` +
             (last ? '' : '<span class="crumb-sep">›</span>');
    }).join('') + `
      <span class="crumb-spacer"></span>
      <button class="safety-pill" data-safety="open"
              title="${this.snap.summary.dark_zones} Dark Zones — open taxonomy">
        ⚠ ${this.snap.summary.dark_zones} zones
      </button>
      <span class="zoom-hint">${this.zoom === 'l0' ? 'click an organ to zoom' : 'click background or breadcrumb to zoom out'}</span>
    `;

    this.crumbsEl.querySelectorAll('.crumb').forEach(el => {
      if (!el.classList.contains('current')) {
        el.addEventListener('click', () => this.zoomTo(el.dataset.state, { push: true }));
      }
    });
    const safety = this.crumbsEl.querySelector('[data-safety="open"]');
    safety && safety.addEventListener('click', () => {
      this.navigateExternalView('darkzones');
    });
  }

  _setHash(h) {
    this._suppressHash = true;
    history.pushState(null, '', h);
    setTimeout(() => { this._suppressHash = false; }, 0);
  }

  _stateToHash(state) {
    return state === 'l0' ? '#/l0' : `#/${state}`;
  }

  _restoreFromHash() {
    const raw = (window.location.hash || '').replace(/^#\/?/, '');
    if (raw.startsWith('l1-')) {
      this.zoomTo(raw, { push: false });
    } else {
      this.zoomTo('l0', { push: false });
    }
  }

  // Public API called by main.js
  showL0() { this.zoomTo('l0', { push: true }); }

  search(query) {
    const q = (query || '').trim().toLowerCase();
    let hits = 0;
    this.svg.querySelectorAll('[data-node-id]').forEach(el => {
      const id = el.dataset.nodeId;
      const node = this.snap.topology.nodes.find(n => n.id === id);
      if (!node) return;
      const hay = (id + ' ' + (node.label || '') + ' ' + (node.path || '')).toLowerCase();
      const match = !q || hay.includes(q);
      el.classList.toggle('search-hit', match && !!q);
      el.classList.toggle('search-miss', !match && !!q);
      if (match) hits++;
    });
    return hits;
  }

  applyFilter(mode) {
    // "filter" maps to zoom shortcuts.
    if (mode === 'memory') this.zoomTo('l1-memory');
    else if (mode === 'tools') this.zoomTo('l1-tools');
    else if (mode === 'dark') this.navigateExternalView('darkzones');
    else if (mode === 'write') this.zoomTo('l1-brain');
    else this.zoomTo('l0');
  }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
