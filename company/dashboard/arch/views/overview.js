// Обзор — Phase 1.7 ecosystem composition (block-level, SAFETY organ,
// simplified 2-type edges + filter + legend + static DZ markers, RU UI).

const EDGE_COLORS = {
  control: '#74b9ff',  // Управление (invokes / governs)
  data:    '#55efc4',  // Данные (reads_from / writes_to / observes)
};

const EDGE_LABELS_RU = {
  control: 'Управление',
  data:    'Данные',
};

export class OverviewView {
  constructor({ snapshot, containerId, onSelectLeaf, navigateExternalView }) {
    this.snap = snapshot;
    this.containerId = containerId;
    this.onSelectLeaf = onSelectLeaf;
    this.navigateExternalView = navigateExternalView || (() => {});
    this.container = document.getElementById(containerId);
    this.zoom = 'l0';
    this.filter = 'all'; // all | control | data
    this.animating = false;
    this._suppressHash = false;
  }

  mount() {
    this.container.innerHTML = `
      <div class="ov-root">
        <nav class="ov-crumbs" id="ov-crumbs"></nav>
        <div class="ov-stage">
          ${this._renderSVG()}
          ${this._renderLegend()}
        </div>
      </div>
    `;
    this.crumbsEl = document.getElementById('ov-crumbs');
    this.svg = this.container.querySelector('svg.ecosystem');
    this._installInteractions();
    window.addEventListener('hashchange', () => {
      if (this._suppressHash) return;
      this._restoreFromHash();
    });
    this._restoreFromHash();
  }

  // -------------------------------------------------------------------
  // SVG composition
  // -------------------------------------------------------------------

  _renderSVG() {
    const vb = this.snap.layout.viewbox;
    return `
      <svg class="ecosystem" data-zoom="l0" data-filter="all"
           viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"
           preserveAspectRatio="xMidYMid meet"
           overflow="hidden">
        <defs>
          ${this._defs()}
          <clipPath id="viewBoxClip" clipPathUnits="userSpaceOnUse">
            <rect class="vbclip-rect" x="${vb.x}" y="${vb.y}" width="${vb.w}" height="${vb.h}"/>
          </clipPath>
        </defs>
        <g class="zoom-group" clip-path="url(#viewBoxClip)">
          ${this._renderOrganBodies()}
          ${this._renderMemoryBands()}
          ${this._renderBlocks()}
          ${this._renderEdges()}
          ${this._renderNodes()}
          ${this._renderToolBlockBodies()}
          ${this._renderSafetyBlockBodies()}
          ${this._renderOrganLabels()}
        </g>
      </svg>
    `;
  }

  _defs() {
    const kinds = Object.entries(EDGE_COLORS);
    const markers = kinds.map(([k, c]) => `
      <marker id="arrow-${k}" viewBox="0 0 10 10" refX="9" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="${c}"/>
      </marker>
    `).join('');

    const gradients = `
      <linearGradient id="g-external" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#636e72" stop-opacity="0.10"/>
        <stop offset="1" stop-color="#636e72" stop-opacity="0.02"/>
      </linearGradient>
      <linearGradient id="g-interface" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#74b9ff" stop-opacity="0.12"/>
        <stop offset="1" stop-color="#74b9ff" stop-opacity="0.02"/>
      </linearGradient>
      <radialGradient id="g-brain" cx="0.5" cy="0.5" r="0.7">
        <stop offset="0" stop-color="#6c5ce7" stop-opacity="0.20"/>
        <stop offset="1" stop-color="#6c5ce7" stop-opacity="0.02"/>
      </radialGradient>
      <linearGradient id="g-tools" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#00b894" stop-opacity="0.15"/>
        <stop offset="1" stop-color="#00b894" stop-opacity="0.03"/>
      </linearGradient>
      <linearGradient id="g-memory" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#fdcb6e" stop-opacity="0.04"/>
        <stop offset="1" stop-color="#fdcb6e" stop-opacity="0.18"/>
      </linearGradient>
      <linearGradient id="g-safety" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#e17055" stop-opacity="0.09"/>
        <stop offset="1" stop-color="#e17055" stop-opacity="0.03"/>
      </linearGradient>
    `;
    return markers + gradients;
  }

  _renderOrganBodies() {
    const parts = [];
    for (const [id, r] of Object.entries(this.snap.layout.organs)) {
      const extraCls = id === 'safety' ? ' organ-safety-outline' : '';
      parts.push(`
        <g class="organ organ-${id}${extraCls}" data-organ="${id}">
          <rect class="organ-bg"
                x="${r.x + 6}" y="${r.y + 6}"
                width="${r.w - 12}" height="${r.h - 12}"
                rx="28" ry="28"
                fill="url(#g-${id})"
                stroke="rgba(255,255,255,${id === 'safety' ? '0.18' : '0.08'})"
                stroke-dasharray="${id === 'safety' ? '6 5' : ''}"
                stroke-width="${id === 'safety' ? '2' : '1.5'}"/>
        </g>
      `);
    }
    return parts.join('');
  }

  _renderOrganLabels() {
    const parts = [];
    for (const [id, r] of Object.entries(this.snap.layout.organs)) {
      parts.push(`
        <text class="organ-label l0-label"
              x="${r.label_x}" y="${r.label_y}"
              text-anchor="middle" dominant-baseline="hanging">${this._esc(r.label)}</text>
      `);
    }
    return parts.join('');
  }

  _renderMemoryBands() {
    const bands = this.snap.layout.memory_bands || {};
    const parts = [];
    for (const [id, b] of Object.entries(bands)) {
      parts.push(`
        <g class="mem-band mem-band-${id}">
          <rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"
                rx="16" ry="16"
                fill="rgba(253,203,110,0.03)"
                stroke="rgba(253,203,110,0.22)"
                stroke-dasharray="6 6" stroke-width="1"/>
          <text x="${b.label_x}" y="${b.label_y}"
                text-anchor="middle"
                class="mem-band-label">${this._esc(b.label)}</text>
        </g>
      `);
    }
    return parts.join('');
  }

  _renderBlocks() {
    // Render lightweight block backgrounds + labels/questions for every
    // block in layout.blocks. Tools/safety have their content rendered
    // separately below; this is the background chrome for all of them.
    const parts = [];
    const blocks = this.snap.layout.blocks || {};
    const blockMeta = this._buildBlockMetaMap();
    for (const [bid, b] of Object.entries(blocks)) {
      const meta = blockMeta[bid] || {};
      const organ = meta.organ || (bid.split('_')[0]);
      parts.push(`
        <g class="block block-${bid}" data-block-id="${this._esc(bid)}" data-block-organ="${organ}">
          <rect class="block-bg"
                x="${b.x + 4}" y="${b.y + 4}"
                width="${b.w - 8}" height="${b.h - 8}"
                rx="12" ry="12"
                fill="rgba(255,255,255,0.015)"
                stroke="rgba(255,255,255,0.06)"
                stroke-width="1"/>
          <text class="block-label" x="${b.label_x}" y="${b.label_y}"
                text-anchor="middle" dominant-baseline="hanging">${this._esc(meta.label || '')}</text>
          ${meta.question ? `
            <text class="block-question" x="${b.label_x}" y="${b.label_y + 22}"
                  text-anchor="middle" dominant-baseline="hanging">${this._esc(meta.question)}</text>
          ` : ''}
        </g>
      `);
    }
    return parts.join('');
  }

  _buildBlockMetaMap() {
    const map = {};
    const blocks = this.snap.blocks || {};
    for (const organKey of Object.keys(blocks)) {
      for (const b of blocks[organKey]) {
        map[b.id] = b;
      }
    }
    return map;
  }

  _renderEdges() {
    const placements = this._blockCenterMap();
    const edges = this.snap.typed_edges || [];
    const parts = [];
    for (const e of edges) {
      const s = placements[e.source];
      const t = placements[e.target];
      if (!s || !t) continue;
      const color = EDGE_COLORS[e.kind] || '#8b8fa3';
      const dash = e.kind === 'data' ? '7 5' : '';
      const path = this._routePath(s, t);
      parts.push(`
        <g class="edge edge-${e.kind} vis-${e.visibility || 'l0'}"
           data-edge="${this._esc(e.source + '->' + e.target)}"
           data-kind="${e.kind}">
          <path d="${path}"
                stroke="${color}"
                stroke-width="2"
                stroke-dasharray="${dash}"
                fill="none"
                marker-end="url(#arrow-${e.kind})"
                opacity="0.82"/>
          <title>${this._esc((EDGE_LABELS_RU[e.kind] || e.kind) + ': ' + (e.label || ''))}</title>
        </g>
      `);
    }
    return parts.join('');
  }

  _blockCenterMap() {
    // For block-level edges, endpoints are block IDs → use block center.
    const m = {};
    const blocks = this.snap.layout.blocks || {};
    for (const [bid, b] of Object.entries(blocks)) {
      m[bid] = { cx: b.x + b.w / 2, cy: b.y + b.h / 2 };
    }
    // Also include every node center so legacy edges still work.
    for (const [nid, n] of Object.entries(this.snap.layout.nodes || {})) {
      m[nid] = { cx: n.cx, cy: n.cy };
    }
    return m;
  }

  _routePath(s, t) {
    const sx = s.cx, sy = s.cy;
    const tx = t.cx, ty = t.cy;
    const dx = tx - sx, dy = ty - sy;
    const dist = Math.hypot(dx, dy);
    if (dist < 180) return `M ${sx} ${sy} L ${tx} ${ty}`;
    const mx = (sx + tx) / 2;
    const my = (sy + ty) / 2;
    const perpX = -dy / dist;
    const perpY = dx / dist;
    const lift = Math.min(80, dist * 0.12);
    return `M ${sx} ${sy} Q ${mx + perpX * lift} ${my + perpY * lift} ${tx} ${ty}`;
  }

  _renderNodes() {
    // Only render topology nodes that have layout placements AND belong
    // to node-based organs (interface, brain, memory, external).
    // Tools / safety blocks have their own renderers.
    const placements = this.snap.layout.nodes;
    const parts = [];
    for (const n of this.snap.topology.nodes) {
      const p = placements[n.id];
      if (!p) continue;
      if (n.organ === 'tools' && n.id !== 'registry') continue;
      const w = p.w || 130, h = p.h || 40;
      const x = p.cx - w / 2, y = p.cy - h / 2;
      const hasDZ = (n.dark_zone_ids || []).length > 0;
      const organ = n.organ || 'memory';
      const isPaused = !!n.paused;

      const cls = [
        'node',
        `node-${n.id}`,
        `organ-${organ}`,
        hasDZ ? 'has-dz' : '',
        isPaused ? 'paused' : '',
      ].filter(Boolean).join(' ');

      const semantic = n.semantic_label || n.label;
      const tech = n.label || '';
      const showBoth = semantic !== tech && h >= 34;
      // Position semantic text at 38% and tech at 74% of node height when
      // both lines fit; otherwise center the semantic label.
      const semY = showBoth ? h * 0.38 : h / 2;
      const techY = h * 0.74;

      parts.push(`
        <g class="${cls}" data-node-id="${n.id}" transform="translate(${x}, ${y})">
          <rect class="node-rect" x="0" y="0" width="${w}" height="${h}" rx="6" ry="6"/>
          <text class="node-semantic" x="${w/2}" y="${semY}"
                text-anchor="middle" dominant-baseline="central">${this._esc(semantic)}</text>
          ${showBoth ? `
            <text class="node-tech" x="${w/2}" y="${techY}"
                  text-anchor="middle" dominant-baseline="central">${this._esc(tech)}</text>` : ''}
          <title>${this._esc(semantic)}${showBoth ? ' — ' + this._esc(tech) : ''}</title>
          ${hasDZ ? `
            <g class="dz-marker" transform="translate(${w - 10}, 10)">
              <circle class="dz-dot" cx="0" cy="0" r="7" fill="#fdcb6e" stroke="#e17055" stroke-width="1"/>
              <text class="dz-glyph" x="0" y="1" text-anchor="middle" dominant-baseline="central">⚠</text>
              <title>${(n.dark_zone_ids || []).length} известных слабостей: ${(n.dark_zone_ids || []).join(', ')}</title>
            </g>
          ` : ''}
        </g>
      `);
    }
    return parts.join('');
  }

  _renderToolBlockBodies() {
    // For each TOOLS block, render a label + count + 1-2 example tool names.
    const blocks = this.snap.layout.blocks || {};
    const toolsBlocks = (this.snap.blocks || {}).tools || [];
    const parts = [];
    for (const tb of toolsBlocks) {
      const b = blocks[tb.id];
      if (!b) continue;
      const examples = tb.tools.slice(0, 2).join(', ');
      const count = tb.tools.length;
      const dzSet = new Set();
      for (const name of tb.tools) {
        const t = this.snap.tools.find(x => x.name === name);
        if (t) (t.dark_zone_ids || []).forEach(d => dzSet.add(d));
      }
      const dzCount = dzSet.size;
      parts.push(`
        <g class="tool-block-body" data-block-id="${tb.id}" data-block-organ="tools">
          <text class="tool-block-count" x="${b.x + b.w - 14}" y="${b.y + 22}"
                text-anchor="end" dominant-baseline="hanging">${count}</text>
          <text class="tool-block-examples" x="${b.x + 14}" y="${b.y + b.h - 12}"
                text-anchor="start" dominant-baseline="alphabetic">${this._esc(examples)}${count > 2 ? ' …' : ''}</text>
          ${dzCount ? `
            <g class="dz-marker" transform="translate(${b.x + b.w - 14}, ${b.y + b.h - 12})">
              <circle class="dz-dot" cx="0" cy="0" r="6" fill="#fdcb6e" stroke="#e17055" stroke-width="1"/>
              <text class="dz-glyph" x="0" y="1" text-anchor="middle" dominant-baseline="central" style="font-size:8px">⚠</text>
              <title>${dzCount} слабостей в этой категории</title>
            </g>` : ''}
        </g>
      `);
    }
    return parts.join('');
  }

  _renderSafetyBlockBodies() {
    // Each SAFETY block is a stack of labeled items (not topology nodes).
    const blocks = this.snap.layout.blocks || {};
    const safetyBlocks = (this.snap.blocks || {}).safety || [];
    const parts = [];
    for (const sb of safetyBlocks) {
      const b = blocks[sb.id];
      if (!b) continue;
      const items = sb.items || [];
      const innerTop = b.y + 70; // below the label + question
      const rowH = 26;
      const isWeaknesses = sb.id === 'safety_weaknesses';

      const visible = isWeaknesses ? items.slice(0, 8) : items;
      const rows = visible.map((it, i) => {
        const y = innerTop + i * rowH;
        if (isWeaknesses) {
          return `
            <g class="safety-row safety-row-dz" data-goto-dz="${this._esc(it.dz_id || '')}"
               transform="translate(${b.x + 16}, ${y})">
              <circle cx="6" cy="13" r="5" fill="#fdcb6e" stroke="#e17055" stroke-width="1"/>
              <text class="safety-row-text" x="20" y="16" dominant-baseline="alphabetic">${this._esc(it.title)}</text>
            </g>`;
        }
        return `
          <g class="safety-row" transform="translate(${b.x + 16}, ${y})">
            <circle cx="6" cy="13" r="4" fill="#74b9ff" stroke="none"/>
            <text class="safety-row-text" x="20" y="16" dominant-baseline="alphabetic">${this._esc(it.title)}</text>
            ${it.ref ? `<title>${this._esc(it.ref)}</title>` : ''}
          </g>`;
      }).join('');

      const more = (isWeaknesses && items.length > 8)
        ? `<text class="safety-more" x="${b.x + b.w / 2}" y="${innerTop + 8 * rowH + 16}"
              text-anchor="middle">+ ещё ${items.length - 8} — открыть «Тёмные зоны»</text>`
        : '';

      parts.push(`
        <g class="safety-block-body" data-block-id="${sb.id}" data-block-organ="safety">
          ${rows}${more}
        </g>
      `);
    }
    return parts.join('');
  }

  // -------------------------------------------------------------------
  // Legend + filter bar (rendered as HTML siblings of the SVG)
  // -------------------------------------------------------------------

  _renderLegend() {
    return `
      <div class="ov-legend">
        <div class="legend-row">
          <span class="edge-sample control"></span>
          <span class="legend-label">Управление</span>
          <span class="legend-hint">вызов, контроль</span>
        </div>
        <div class="legend-row">
          <span class="edge-sample data"></span>
          <span class="legend-label">Данные</span>
          <span class="legend-hint">чтение, запись, наблюдение</span>
        </div>
        <div class="legend-row legend-marker-row">
          <span class="legend-marker">
            <svg width="14" height="14" viewBox="-8 -8 16 16">
              <circle cx="0" cy="0" r="7" fill="#fdcb6e" stroke="#e17055" stroke-width="1"/>
              <text x="0" y="1" text-anchor="middle" dominant-baseline="central" font-size="9">⚠</text>
            </svg>
          </span>
          <span class="legend-label">Известные слабости</span>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------
  // Interactions
  // -------------------------------------------------------------------

  _installInteractions() {
    this.svg.addEventListener('click', e => {
      // Dark-Zone chip click (inside safety weaknesses)
      const gotoDz = e.target.closest('[data-goto-dz]');
      if (gotoDz && gotoDz.dataset.gotoDz) {
        e.stopPropagation();
        this.navigateExternalView('darkzones', gotoDz.dataset.gotoDz);
        return;
      }
      // Node click → open side panel
      const nodeG = e.target.closest('[data-node-id]');
      if (nodeG) {
        this._selectNode(nodeG.dataset.nodeId);
        return;
      }
      // Tool-block body → open Tools view (preserving phase-1 behavior)
      const toolBody = e.target.closest('.tool-block-body');
      if (toolBody) {
        this.navigateExternalView('tools');
        return;
      }
      // Block background → zoom into its organ
      const blockG = e.target.closest('[data-block-organ]');
      if (blockG) {
        const organ = blockG.dataset.blockOrgan;
        const target = `l1-${organ}`;
        this.zoomTo(this.zoom === target ? 'l0' : target, { push: true });
        return;
      }
      // Organ body → zoom in / out
      const organG = e.target.closest('[data-organ]');
      if (organG) {
        const target = `l1-${organG.dataset.organ}`;
        this.zoomTo(this.zoom === target ? 'l0' : target, { push: true });
        return;
      }
      if (this.zoom !== 'l0') this.zoomTo('l0', { push: true });
    });

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
    const nodeToBlock = {};
    for (const o of ['brain', 'interface', 'memory']) {
      for (const b of (this.snap.blocks[o] || [])) {
        for (const nid of (b.nodes || [])) nodeToBlock[nid] = b.id;
      }
    }
    const myBlock = nodeToBlock[nodeId];
    const edges = this.snap.typed_edges || [];
    const activeEndpoints = new Set([nodeId, myBlock].filter(Boolean));
    for (const e of edges) {
      if (e.source === myBlock) activeEndpoints.add(e.target);
      if (e.target === myBlock) activeEndpoints.add(e.source);
    }

    this.svg.querySelectorAll('[data-node-id]').forEach(el => {
      const isMe = el.dataset.nodeId === nodeId;
      el.classList.toggle('hl-neighbor', isMe);
      el.classList.toggle('hl-dim', !isMe);
    });
    this.svg.querySelectorAll('[data-edge]').forEach(el => {
      const [s, t] = el.dataset.edge.split('->');
      const active = activeEndpoints.has(s) && activeEndpoints.has(t);
      el.classList.toggle('hl-active', active);
      el.classList.toggle('hl-dim', !active);
    });
  }

  _clearHighlight() {
    this.svg.querySelectorAll('.hl-neighbor,.hl-dim,.hl-active').forEach(el => {
      el.classList.remove('hl-neighbor', 'hl-dim', 'hl-active');
    });
  }

  _selectNode(id) {
    const node = this.snap.topology.nodes.find(n => n.id === id);
    if (!node) return;
    if (id === 'registry') { this.navigateExternalView('tools'); return; }
    const data = {
      id: node.id, label: node.label, kind: node.kind, layer: node.layer,
      path: node.path || '', loc: node.loc || 0,
      description: node.description || '',
      dark_zones: node.dark_zone_ids || [],
      functional_role: node.functional_role,
      organ: node.organ,
      semantic_label: node.semantic_label,
    };
    this.onSelectLeaf && this.onSelectLeaf({ kind: 'node', data });
  }

  // -------------------------------------------------------------------
  // Filter
  // -------------------------------------------------------------------

  setFilter(mode) {
    this.filter = mode;
    this.svg.setAttribute('data-filter', mode);
  }

  // -------------------------------------------------------------------
  // Zoom
  // -------------------------------------------------------------------

  zoomTo(state, { push = true } = {}) {
    if (this.animating) return;
    const states = this.snap.layout.zoom_states;
    const target = states[state] || states.l0;
    const current = this._parseVB(this.svg.getAttribute('viewBox'));
    this.zoom = state;
    this.svg.setAttribute('data-zoom', state);
    if (push) this._setHash(state === 'l0' ? '#/l0' : `#/${state}`);
    this._renderBreadcrumb();
    this._tweenVB(current, target);
  }

  _parseVB(v) {
    const [x, y, w, h] = v.split(/\s+/).map(Number);
    return { x, y, w, h };
  }

  _tweenVB(from, to) {
    this.animating = true;
    const start = performance.now();
    const dur = 520;
    const lerp = (a, b, t) => a + (b - a) * t;
    const ease = t => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
    const clipRect = this.svg.querySelector('.vbclip-rect');
    const step = now => {
      const t = Math.min(1, (now - start) / dur);
      const k = ease(t);
      const x = lerp(from.x, to.x, k);
      const y = lerp(from.y, to.y, k);
      const w = lerp(from.w, to.w, k);
      const h = lerp(from.h, to.h, k);
      this.svg.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
      if (clipRect) {
        clipRect.setAttribute('x', x);
        clipRect.setAttribute('y', y);
        clipRect.setAttribute('width', w);
        clipRect.setAttribute('height', h);
      }
      if (t < 1) requestAnimationFrame(step);
      else this.animating = false;
    };
    requestAnimationFrame(step);
  }

  // -------------------------------------------------------------------
  // Crumbs + hash
  // -------------------------------------------------------------------

  _renderBreadcrumb() {
    const ORGAN_LABELS_RU = {
      external: 'ВНЕШНЕЕ',
      interface: 'ИНТЕРФЕЙС',
      brain: 'МОЗГ',
      tools: 'ИНСТРУМЕНТЫ',
      memory: 'ПАМЯТЬ',
      safety: 'БЕЗОПАСНОСТЬ',
    };
    const crumbs = [{ label: 'Обзор', state: 'l0' }];
    if (this.zoom && this.zoom !== 'l0') {
      const organId = this.zoom.replace(/^l1-/, '');
      const lbl = ORGAN_LABELS_RU[organId] || organId.toUpperCase();
      crumbs.push({ label: lbl, state: this.zoom });
    }
    this.crumbsEl.innerHTML = `
      ${crumbs.map((c, i) => {
        const last = i === crumbs.length - 1;
        return `<span class="crumb ${last ? 'current' : ''}" data-state="${c.state}">${this._esc(c.label)}</span>` +
               (last ? '' : '<span class="crumb-sep">›</span>');
      }).join('')}
      <span class="crumb-spacer"></span>
      <div class="filter-chips" role="group" aria-label="Фильтр связей">
        <button class="fchip ${this.filter === 'all' ? 'active' : ''}" data-filter="all">Все связи</button>
        <button class="fchip ${this.filter === 'control' ? 'active' : ''}" data-filter="control">Только управление</button>
        <button class="fchip ${this.filter === 'data' ? 'active' : ''}" data-filter="data">Только данные</button>
      </div>
      <button class="safety-pill" data-safety="open"
              title="${this.snap.summary.dark_zones} известных слабостей — открыть таксономию">
        ⚠ ${this.snap.summary.dark_zones} слабостей
      </button>
    `;
    this.crumbsEl.querySelectorAll('.crumb').forEach(el => {
      if (!el.classList.contains('current'))
        el.addEventListener('click', () => this.zoomTo(el.dataset.state, { push: true }));
    });
    this.crumbsEl.querySelectorAll('.fchip').forEach(el => {
      el.addEventListener('click', () => {
        this.setFilter(el.dataset.filter);
        this._renderBreadcrumb();
      });
    });
    const safety = this.crumbsEl.querySelector('[data-safety="open"]');
    safety && safety.addEventListener('click', () => this.navigateExternalView('darkzones'));
  }

  _setHash(h) {
    this._suppressHash = true;
    history.pushState(null, '', h);
    setTimeout(() => { this._suppressHash = false; }, 0);
  }

  _restoreFromHash() {
    const raw = (window.location.hash || '').replace(/^#\/?/, '');
    if (raw.startsWith('l1-')) this.zoomTo(raw, { push: false });
    else this.zoomTo('l0', { push: false });
  }

  // -------------------------------------------------------------------
  // API used by main.js
  // -------------------------------------------------------------------

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
    if (mode === 'memory') this.zoomTo('l1-memory');
    else if (mode === 'tools') this.zoomTo('l1-tools');
    else if (mode === 'dark') this.zoomTo('l1-safety');
    else if (mode === 'write') this.zoomTo('l1-brain');
    else this.zoomTo('l0');
  }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
