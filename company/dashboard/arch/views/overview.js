// Overview view — 3-layer helicopter graph with interactions.

import { buildElements, defaultStyle, presetByLayer } from '../lib/graph.js?v=phase1';

export class OverviewView {
  constructor({ snapshot, containerId, onSelectNode, onSelectEdge }) {
    this.snapshot = snapshot;
    this.onSelect = onSelectNode;
    this.onSelectEdge = onSelectEdge;
    this.containerId = containerId;
    this.cy = null;
    this.tipEl = null;
  }

  mount() {
    const nodes = this.snapshot.topology.nodes;
    const edges = this.snapshot.topology.edges;

    const elements = buildElements(nodes, edges);

    this.cy = cytoscape({
      container: document.getElementById(this.containerId),
      elements,
      style: defaultStyle(),
      layout: presetByLayer(nodes),
      minZoom: 0.15,
      maxZoom: 2.5,
      boxSelectionEnabled: false,
    });

    this._installTooltip();
    this._installInteractions();
  }

  _ensureTipEl() {
    if (this.tipEl) return this.tipEl;
    const el = document.createElement('div');
    el.id = 'cy-tip';
    document.body.appendChild(el);
    this.tipEl = el;
    return el;
  }

  _installTooltip() {
    const tip = this._ensureTipEl();

    this.cy.on('mouseover', 'node', evt => {
      const d = evt.target.data();
      tip.innerHTML = `
        <div class="tip-title">${this._esc(d.label)}</div>
        ${d.path ? `<div class="tip-sub">${this._esc(d.path)}${d.loc ? ` · ${d.loc} LoC` : ''}</div>` : ''}
        ${d.description ? `<div style="margin-top:4px;color:var(--muted);font-size:11px">${this._esc(d.description.slice(0, 140))}</div>` : ''}
        ${d.dark_zones && d.dark_zones.length ? `<div class="tip-dzs">⚠ ${d.dark_zones.join(', ')}</div>` : ''}
      `;
      tip.classList.add('visible');
    });

    this.cy.on('mouseover', 'edge', evt => {
      const d = evt.target.data();
      if (!d.label) return;
      tip.innerHTML = `
        <div class="tip-title">${this._esc(d.label)}</div>
        <div class="tip-sub">${this._esc(d.source)} → ${this._esc(d.target)}</div>
        ${d.style && d.style !== 'solid' ? `<div class="tip-dzs">style: ${d.style}</div>` : ''}
      `;
      tip.classList.add('visible');
    });

    this.cy.on('mouseout', 'node, edge', () => tip.classList.remove('visible'));

    this.cy.container().addEventListener('mousemove', ev => {
      tip.style.left = (ev.clientX + 14) + 'px';
      tip.style.top = (ev.clientY + 14) + 'px';
    });
  }

  _installInteractions() {
    this.cy.on('tap', 'node', evt => {
      const d = evt.target.data();
      this._highlightNeighborhood(evt.target);
      this.onSelect && this.onSelect(d);
    });
    this.cy.on('tap', 'edge', evt => {
      const d = evt.target.data();
      this.onSelectEdge && this.onSelectEdge(d);
    });
    this.cy.on('tap', evt => {
      if (evt.target === this.cy) {
        this.cy.elements().removeClass('dim highlighted');
      }
    });
  }

  _highlightNeighborhood(node) {
    this.cy.elements().addClass('dim');
    const nbhd = node.closedNeighborhood();
    nbhd.removeClass('dim');
    node.connectedEdges().addClass('highlighted').removeClass('dim');
  }

  applyFilter(mode) {
    const all = this.cy.elements();
    all.removeClass('dim highlighted');

    if (mode === 'all') return;

    const nodes = this.snapshot.topology.nodes;
    let keep = new Set();
    if (mode === 'memory') {
      nodes.filter(n => n.layer === 'bottom').forEach(n => keep.add(n.id));
      // Include writers/readers directly connected
      for (const e of this.snapshot.topology.edges) {
        if (keep.has(e.target) || keep.has(e.source)) {
          keep.add(e.source); keep.add(e.target);
        }
      }
    } else if (mode === 'write') {
      // Highlight unsafe edges and their endpoints
      for (const e of this.snapshot.topology.edges) {
        if (e.style === 'unsafe' || /write|replace|append/.test(e.label || '')) {
          keep.add(e.source); keep.add(e.target);
        }
      }
    } else if (mode === 'dark') {
      nodes.filter(n => (n.dark_zone_ids || []).length).forEach(n => keep.add(n.id));
    } else if (mode === 'tools') {
      // Keep registry + module + tool-adjacent
      ['registry', 'loop', 'agent', 'consciousness'].forEach(id => keep.add(id));
    }
    this.cy.nodes().forEach(n => {
      if (!keep.has(n.id())) n.addClass('dim');
    });
    this.cy.edges().forEach(e => {
      if (!keep.has(e.data('source')) || !keep.has(e.data('target'))) e.addClass('dim');
    });
  }

  search(query) {
    this.cy.elements().removeClass('dim hit highlighted');
    if (!query) return 0;
    const q = query.toLowerCase();
    let hits = 0;
    this.cy.nodes().forEach(n => {
      const d = n.data();
      const hay = (d.label + ' ' + (d.path || '') + ' ' + (d.description || '')).toLowerCase();
      if (hay.includes(q)) {
        n.addClass('hit');
        hits++;
      } else {
        n.addClass('dim');
      }
    });
    // Also dim edges not connected to a hit
    this.cy.edges().forEach(e => {
      const src = this.cy.getElementById(e.data('source'));
      const tgt = this.cy.getElementById(e.data('target'));
      if (!src.hasClass('hit') && !tgt.hasClass('hit')) e.addClass('dim');
    });
    return hits;
  }

  focusNode(id) {
    const n = this.cy.getElementById(id);
    if (!n.length) return false;
    this.cy.animate({ center: { eles: n }, zoom: 1.0 }, { duration: 400 });
    n.select();
    this._highlightNeighborhood(n);
    return true;
  }

  _esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
}
