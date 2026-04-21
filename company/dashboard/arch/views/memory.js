// Memory view — bottom-layer-focused graph: 7 backends + their writers/readers.

import { buildElements, defaultStyle, layeredLayout } from '../lib/graph.js?v=phase1';

export class MemoryView {
  constructor({ snapshot, containerId, onSelectNode }) {
    this.snapshot = snapshot;
    this.onSelect = onSelectNode;
    this.containerId = containerId;
    this.cy = null;
  }

  mount() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    // Filter topology: keep only middle + bottom layers, and drop external
    // infra-only nodes that aren't connected to a memory backend.
    const { nodes, edges } = this.snapshot.topology;
    const bottomIds = new Set(nodes.filter(n => n.layer === 'bottom').map(n => n.id));

    const edgesTouchingBottom = edges.filter(e => bottomIds.has(e.source) || bottomIds.has(e.target));

    const middleIds = new Set();
    for (const e of edgesTouchingBottom) {
      if (!bottomIds.has(e.source)) middleIds.add(e.source);
      if (!bottomIds.has(e.target)) middleIds.add(e.target);
    }

    const filteredNodes = nodes.filter(n => bottomIds.has(n.id) || middleIds.has(n.id));
    const els = buildElements(filteredNodes, edgesTouchingBottom);

    this.cy = cytoscape({
      container,
      elements: els,
      style: defaultStyle(),
      layout: { ...layeredLayout(), rankDir: 'LR', rankSep: 260, nodeSep: 22, edgeSep: 12 },
      minZoom: 0.2,
      maxZoom: 2.5,
    });

    this.cy.on('tap', 'node', evt => this.onSelect && this.onSelect(evt.target.data()));
    this.cy.on('tap', evt => {
      if (evt.target === this.cy) this.cy.elements().removeClass('dim highlighted');
    });

    // Install the same tooltip as overview (reuse the same #cy-tip element)
    this._installTip();
  }

  _installTip() {
    const tip = document.getElementById('cy-tip') || (() => {
      const el = document.createElement('div'); el.id = 'cy-tip';
      document.body.appendChild(el); return el;
    })();
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    this.cy.on('mouseover', 'node', evt => {
      const d = evt.target.data();
      tip.innerHTML = `
        <div class="tip-title">${esc(d.label)}</div>
        ${d.path ? `<div class="tip-sub">${esc(d.path)}</div>` : ''}
        ${d.description ? `<div style="margin-top:4px;color:var(--muted);font-size:11px">${esc(d.description)}</div>` : ''}
        ${d.dark_zones && d.dark_zones.length ? `<div class="tip-dzs">⚠ ${d.dark_zones.join(', ')}</div>` : ''}
      `;
      tip.classList.add('visible');
    });
    this.cy.on('mouseover', 'edge', evt => {
      const d = evt.target.data();
      if (!d.label) return;
      tip.innerHTML = `<div class="tip-title">${esc(d.label)}</div><div class="tip-sub">${esc(d.source)} → ${esc(d.target)}</div>`;
      tip.classList.add('visible');
    });
    this.cy.on('mouseout', 'node, edge', () => tip.classList.remove('visible'));
    this.cy.container().addEventListener('mousemove', ev => {
      tip.style.left = (ev.clientX + 14) + 'px';
      tip.style.top = (ev.clientY + 14) + 'px';
    });
  }

  resize() {
    if (this.cy) { this.cy.resize(); this.cy.fit(); }
  }
}
