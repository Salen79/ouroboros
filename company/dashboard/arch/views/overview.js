// Overview view — progressive drill-down (Phase 1.5).
//
// Levels:
//   L0 — 5 aggregate cards (INTERFACE, BRAIN, MEMORY, TOOLS, SAFETY) + inter-aggregate flow
//   L1 — click on an aggregate → show its 3-7 L1 groups (e.g. Memory → Working, Logs, State JSON, ChromaDB…)
//   L2 — click on an L1 group → show its leaf items (nodes/tools/DZs)
//   L3 — click on a leaf → open the existing side panel (phase 1 detail view)
//
// URL hash routing: #/L0 | #/L1/<aggId> | #/L2/<aggId>/<l1Id> | #/L3/<kind>/<id>
// Browser back button Just Works via hashchange.

import { renderNode, renderTool, renderDarkZone } from '../lib/panel.js?v=phase1.5';

export class OverviewView {
  constructor({ snapshot, containerId, onSelectLeaf, navigateExternalView }) {
    this.snapshot = snapshot;
    this.containerId = containerId;
    this.onSelectLeaf = onSelectLeaf;           // opens side panel
    this.navigateExternalView = navigateExternalView || (() => {});

    this.container = document.getElementById(containerId);
    this.state = { level: 0, aggId: null, l1Id: null };
    this._suppressHashEvent = false;
  }

  mount() {
    // Build static scaffold (breadcrumb + stage)
    this.container.innerHTML = `
      <div class="ov-root">
        <nav class="ov-crumbs" id="ov-crumbs"></nav>
        <div class="ov-stage" id="ov-stage"></div>
      </div>
    `;
    this.stageEl = document.getElementById('ov-stage');
    this.crumbsEl = document.getElementById('ov-crumbs');

    window.addEventListener('hashchange', () => {
      if (this._suppressHashEvent) return;
      this._restoreFromHash();
    });

    this._restoreFromHash();
  }

  // ---------------------------------------------------------------
  // Routing
  // ---------------------------------------------------------------

  _restoreFromHash() {
    const raw = (window.location.hash || '').replace(/^#\/?/, '');
    const parts = raw.split('/').filter(Boolean);
    if (parts[0] !== 'ov' && parts[0] !== 'l0' && parts[0] !== 'l1' && parts[0] !== 'l2') {
      this._renderLevel0({ push: false });
      return;
    }
    if (parts[0] === 'l1' && parts[1]) {
      this._renderLevel1(parts[1], { push: false });
    } else if (parts[0] === 'l2' && parts[1] && parts[2]) {
      this._renderLevel2(parts[1], parts[2], { push: false });
    } else {
      this._renderLevel0({ push: false });
    }
  }

  _setHash(h) {
    this._suppressHashEvent = true;
    // Use replaceState for same-level repaint, pushState for descents
    history.pushState(null, '', h);
    setTimeout(() => { this._suppressHashEvent = false; }, 0);
  }

  _replaceHash(h) {
    this._suppressHashEvent = true;
    history.replaceState(null, '', h);
    setTimeout(() => { this._suppressHashEvent = false; }, 0);
  }

  // ---------------------------------------------------------------
  // Public helpers
  // ---------------------------------------------------------------

  showL0() { this._renderLevel0({ push: true }); }

  // ---------------------------------------------------------------
  // Renderers
  // ---------------------------------------------------------------

  _fade(next) {
    // Fade transition between levels
    const stage = this.stageEl;
    stage.classList.add('fade-out');
    setTimeout(() => {
      next();
      stage.classList.remove('fade-out');
      stage.classList.add('fade-in');
      setTimeout(() => stage.classList.remove('fade-in'), 220);
    }, 140);
  }

  _renderLevel0({ push = true } = {}) {
    this.state = { level: 0, aggId: null, l1Id: null };
    this._renderBreadcrumb();
    if (push) this._setHash('#/l0');

    this._fade(() => {
      const aggs = this.snapshot.hierarchy.aggregates;
      const edges = this.snapshot.hierarchy.l0_edges || [];

      // SVG overlay for connector lines between cards
      const cards = aggs.map(a => this._renderAggregateCard(a)).join('');
      this.stageEl.innerHTML = `
        <div class="l0-wrap">
          <div class="l0-title">Choose a layer to drill into</div>
          <div class="l0-grid">
            ${cards}
          </div>
          <div class="l0-caption">
            Hover a card for counts; click to open. <kbd>Esc</kbd> closes the side panel.
          </div>
        </div>
      `;

      this.stageEl.querySelectorAll('[data-agg-id]').forEach(el => {
        el.addEventListener('click', () => {
          this._renderLevel1(el.dataset.aggId, { push: true });
        });
      });
    });
  }

  _renderAggregateCard(agg) {
    const leafCount = agg.l1.reduce((acc, g) => acc + g.leaves.length, 0);
    const groupCount = agg.l1.length;
    const dzCount = (agg.dark_zone_ids || []).length;
    const tagline = this._esc(agg.tagline || '');
    const cls = `l0-card kind-${agg.id} ${agg.kind === 'overlay' ? 'overlay' : ''}`;
    return `
      <div class="${cls}" data-agg-id="${agg.id}" style="--card-accent: ${agg.color || '#6c5ce7'}">
        <div class="l0-card-head">
          <span class="l0-card-badge" style="background:${agg.color}22;color:${agg.color}">${agg.label}</span>
          ${dzCount ? `<span class="l0-dz-pill" title="${dzCount} Dark Zones overlap here">⚠ ${dzCount}</span>` : ''}
        </div>
        <div class="l0-card-title">${this._esc(agg.label)}</div>
        <div class="l0-card-tagline">${tagline}</div>
        <div class="l0-card-stats">
          <div><span class="num">${groupCount}</span><span class="unit">groups</span></div>
          <div><span class="num">${leafCount}</span><span class="unit">${agg.id === 'tools' ? 'tools' : agg.id === 'safety' ? 'zones' : 'items'}</span></div>
        </div>
      </div>
    `;
  }

  _renderLevel1(aggId, { push = true } = {}) {
    const agg = this.snapshot.hierarchy.aggregates.find(a => a.id === aggId);
    if (!agg) { this._renderLevel0({ push: false }); return; }
    this.state = { level: 1, aggId, l1Id: null };
    this._renderBreadcrumb();
    if (push) this._setHash(`#/l1/${aggId}`);

    this._fade(() => {
      const cards = agg.l1.map(g => this._renderGroupCard(agg, g)).join('');
      this.stageEl.innerHTML = `
        <div class="l1-wrap">
          <div class="l1-head">
            <div class="l1-title" style="color:${agg.color}">${this._esc(agg.label)}</div>
            <div class="l1-sub">${this._esc(agg.tagline || '')}</div>
          </div>
          <div class="l1-grid">${cards}</div>
        </div>
      `;

      this.stageEl.querySelectorAll('[data-group-id]').forEach(el => {
        el.addEventListener('click', () => {
          this._renderLevel2(aggId, el.dataset.groupId, { push: true });
        });
      });
    });
  }

  _renderGroupCard(agg, g) {
    const dzCount = (g.dark_zone_ids || []).length;
    return `
      <div class="l1-card" data-group-id="${g.id}" style="--card-accent: ${agg.color}">
        <div class="l1-card-title">${this._esc(g.label)}</div>
        <div class="l1-card-stats">
          <span class="count"><strong>${g.leaves.length}</strong> ${g.leaf_kind === 'tool' ? 'tools' : g.leaf_kind === 'darkzone' ? 'zones' : 'items'}</span>
          ${dzCount ? `<span class="l1-dz-pill">⚠ ${dzCount}</span>` : ''}
        </div>
        <div class="l1-card-preview">
          ${g.leaves.slice(0, 6).map(l => `<span class="leaf-tag">${this._esc(this._leafLabel(l, g.leaf_kind))}</span>`).join('')}
          ${g.leaves.length > 6 ? `<span class="leaf-more">+${g.leaves.length - 6}</span>` : ''}
        </div>
      </div>
    `;
  }

  _renderLevel2(aggId, l1Id, { push = true } = {}) {
    const agg = this.snapshot.hierarchy.aggregates.find(a => a.id === aggId);
    if (!agg) { this._renderLevel0({ push: false }); return; }
    const g = agg.l1.find(x => x.id === l1Id);
    if (!g) { this._renderLevel1(aggId, { push: false }); return; }
    this.state = { level: 2, aggId, l1Id };
    this._renderBreadcrumb();
    if (push) this._setHash(`#/l2/${aggId}/${l1Id}`);

    this._fade(() => {
      const leaves = g.leaves.map(id => this._renderLeafCard(id, g.leaf_kind, agg)).join('');
      this.stageEl.innerHTML = `
        <div class="l2-wrap">
          <div class="l2-head">
            <div class="l2-title" style="color:${agg.color}">${this._esc(g.label)}</div>
            <div class="l2-sub"><span style="color:${agg.color}">${this._esc(agg.label)}</span> / ${g.leaves.length} ${g.leaf_kind === 'tool' ? 'tools' : g.leaf_kind === 'darkzone' ? 'Dark Zones' : 'items'}</div>
          </div>
          <div class="l2-grid">${leaves}</div>
        </div>
      `;

      this.stageEl.querySelectorAll('[data-leaf-id]').forEach(el => {
        el.addEventListener('click', () => {
          const id = el.dataset.leafId;
          const kind = el.dataset.leafKind;
          this._openLeaf(id, kind);
        });
      });
    });
  }

  _renderLeafCard(id, leafKind, agg) {
    if (leafKind === 'node') {
      const node = this.snapshot.topology.nodes.find(n => n.id === id);
      if (!node) return '';
      const dzs = node.dark_zone_ids || [];
      return `
        <div class="leaf-card" data-leaf-id="${id}" data-leaf-kind="node" style="--card-accent: ${agg.color}">
          <div class="leaf-title">${this._esc(node.label)}</div>
          ${node.path ? `<div class="leaf-sub"><code>${this._esc(node.path)}</code>${node.loc ? ` · ${node.loc} LoC` : ''}</div>` : ''}
          ${node.description ? `<div class="leaf-desc">${this._esc(node.description)}</div>` : ''}
          ${dzs.length ? `<div class="leaf-chips">${dzs.map(d => `<span class="chip darkzone" data-goto-dz="${d}">${d}</span>`).join('')}</div>` : ''}
        </div>
      `;
    }
    if (leafKind === 'tool') {
      const tool = this.snapshot.tools.find(t => t.name === id);
      if (!tool) return '';
      const chips = [];
      if (tool.is_core) chips.push('<span class="chip core">CORE</span>');
      if (tool.is_write) chips.push('<span class="chip write">WRITE</span>');
      if (tool.is_destructive) chips.push('<span class="chip dangerous">DESTRUCTIVE</span>');
      if (tool.is_consciousness) chips.push('<span class="chip consciousness">CONS</span>');
      (tool.dark_zone_ids || []).forEach(d => chips.push(`<span class="chip darkzone" data-goto-dz="${d}">${d}</span>`));
      return `
        <div class="leaf-card" data-leaf-id="${tool.name}" data-leaf-kind="tool" style="--card-accent: ${agg.color}">
          <div class="leaf-title" style="font-family: 'SF Mono', 'Cascadia Code', monospace">${this._esc(tool.name)}</div>
          <div class="leaf-sub"><code>${this._esc(tool.module)}:${tool.line}</code></div>
          ${tool.description ? `<div class="leaf-desc">${this._esc(tool.description)}</div>` : ''}
          ${chips.length ? `<div class="leaf-chips">${chips.join('')}</div>` : ''}
        </div>
      `;
    }
    if (leafKind === 'darkzone') {
      const dz = this.snapshot.dark_zones.find(d => d.id === id);
      if (!dz) return '';
      return `
        <div class="leaf-card" data-leaf-id="${dz.id}" data-leaf-kind="darkzone" style="--card-accent: ${agg.color}">
          <div class="leaf-title"><span class="dz-id">${dz.id}</span> ${this._esc(dz.title)}</div>
          <div class="leaf-desc">${this._esc(dz.body_md.slice(0, 180))}${dz.body_md.length > 180 ? '…' : ''}</div>
        </div>
      `;
    }
    return '';
  }

  _openLeaf(id, kind) {
    // L3 = existing detail panel
    if (kind === 'node') {
      const node = this.snapshot.topology.nodes.find(n => n.id === id);
      if (node) {
        // Normalize shape for renderNode (which expects cy-like data)
        const data = {
          id: node.id,
          label: node.label,
          kind: node.kind,
          layer: node.layer,
          path: node.path || '',
          loc: node.loc || 0,
          description: node.description || '',
          dark_zones: node.dark_zone_ids || [],
        };
        this.onSelectLeaf && this.onSelectLeaf({ kind: 'node', data });
      }
    } else if (kind === 'tool') {
      const tool = this.snapshot.tools.find(t => t.name === id);
      if (tool) this.onSelectLeaf && this.onSelectLeaf({ kind: 'tool', data: tool });
    } else if (kind === 'darkzone') {
      // Jump to the Dark Zones view directly — more useful than a mini panel
      this.navigateExternalView('darkzones', id);
    }
  }

  // ---------------------------------------------------------------
  // Breadcrumb
  // ---------------------------------------------------------------

  _renderBreadcrumb() {
    const crumbs = [{ label: 'Overview', action: () => this.showL0() }];
    if (this.state.level >= 1 && this.state.aggId) {
      const agg = this.snapshot.hierarchy.aggregates.find(a => a.id === this.state.aggId);
      if (agg) crumbs.push({
        label: agg.label,
        color: agg.color,
        action: () => this._renderLevel1(this.state.aggId, { push: true }),
      });
    }
    if (this.state.level >= 2 && this.state.l1Id) {
      const agg = this.snapshot.hierarchy.aggregates.find(a => a.id === this.state.aggId);
      const g = agg && agg.l1.find(x => x.id === this.state.l1Id);
      if (g) crumbs.push({
        label: g.label,
        action: () => this._renderLevel2(this.state.aggId, this.state.l1Id, { push: true }),
      });
    }

    this.crumbsEl.innerHTML = crumbs.map((c, i) => {
      const isLast = i === crumbs.length - 1;
      const style = c.color ? `style="color:${c.color}"` : '';
      return `<span class="crumb ${isLast ? 'current' : ''}" data-crumb="${i}" ${style}>${this._esc(c.label)}</span>` +
             (isLast ? '' : '<span class="crumb-sep">›</span>');
    }).join('');

    this.crumbsEl.querySelectorAll('.crumb').forEach((el, i) => {
      if (i < crumbs.length - 1) {
        el.addEventListener('click', () => crumbs[i].action());
      }
    });
  }

  // ---------------------------------------------------------------
  // Interface required by main.js
  // ---------------------------------------------------------------

  search(query) {
    // Filter the current level's cards by substring match. Empty → show all.
    const q = (query || '').trim().toLowerCase();
    const nodes = this.stageEl.querySelectorAll('[data-agg-id], [data-group-id], [data-leaf-id]');
    let hits = 0;
    nodes.forEach(el => {
      const hay = el.innerText.toLowerCase();
      const match = !q || hay.includes(q);
      el.classList.toggle('dim-card', !match);
      if (match) hits++;
    });
    return hits;
  }

  applyFilter(mode) {
    // On the progressive overview, "filter" maps to a quick-jump shortcut.
    // all   → L0
    // write → TOOLS/write-capable leaves
    // memory → MEMORY/L1
    // dark  → SAFETY/L1
    // tools → TOOLS/L1
    if (mode === 'memory') this._renderLevel1('memory');
    else if (mode === 'dark') this._renderLevel1('safety');
    else if (mode === 'tools') this._renderLevel1('tools');
    else if (mode === 'write') {
      // Drill to tools, then stop — user can further pick a group
      this._renderLevel1('tools');
    } else {
      this._renderLevel0();
    }
  }

  // ---------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------

  _leafLabel(id, kind) {
    if (kind === 'node') {
      const n = this.snapshot.topology.nodes.find(x => x.id === id);
      return n ? n.label : id;
    }
    if (kind === 'tool') return id;
    if (kind === 'darkzone') {
      const d = this.snapshot.dark_zones.find(x => x.id === id);
      return d ? `${d.id} ${d.title}` : id;
    }
    return id;
  }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
