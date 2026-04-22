// Инструменты / Tools — Phase 1.9: 6 collapsible functional blocks, RU/EN.

import { renderTool } from '../lib/panel.js?v=phase1.9';
import { t, tField } from '../lib/i18n.js?v=phase1.9';

const BLOCK_ACCENT = {
  tools_read:        '#74b9ff',
  tools_write:       '#fdcb6e',
  tools_selfctl:     '#a29bfe',
  tools_reflection:  '#55efc4',
  tools_danger:      '#e17055',
  tools_meta:        '#8b8fa3',
};

export class ToolsView {
  constructor({ snapshot, gridId, onSelectTool }) {
    this.snap = snapshot;
    this.gridEl = document.getElementById(gridId);
    this.onSelect = onSelectTool;
    this.blocks = (snapshot.blocks && snapshot.blocks.tools) || [];
    this.expanded = new Set(this.blocks.map(b => b.id)); // all open by default
    this.query = '';
    this.filter = 'all';
  }

  mount() {
    this._render();
  }

  _render() {
    const q = this.query.trim().toLowerCase();
    const sections = this.blocks.map(b => this._renderBlock(b, q)).filter(Boolean).join('');

    const filteredBlocks = this.blocks.filter(b => this._toolsInBlock(b, q).length);
    const emptyState = !filteredBlocks.length
      ? `<div class="tools-empty">${this._esc(t('tools.empty', `"${this.query}"`))}</div>`
      : '';

    this.gridEl.innerHTML = `
      <div class="tools-phase17">
        ${sections}
        ${emptyState}
      </div>
    `;

    this.gridEl.querySelectorAll('[data-tool-name]').forEach(card => {
      card.addEventListener('click', e => {
        if (e.target.closest('[data-goto-dz]')) return;
        const t = this.snap.tools.find(x => x.name === card.dataset.toolName);
        if (t) this.onSelect && this.onSelect(t);
      });
    });
    this.gridEl.querySelectorAll('[data-block-toggle]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.blockToggle;
        if (this.expanded.has(id)) this.expanded.delete(id); else this.expanded.add(id);
        this._render();
      });
    });
  }

  _toolsInBlock(b, q) {
    const names = b.tools || [];
    return names
      .map(n => this.snap.tools.find(t => t.name === n))
      .filter(t => t)
      .filter(t => {
        if (this.filter === 'core' && !t.is_core) return false;
        if (this.filter === 'write' && !t.is_write) return false;
        if (this.filter === 'destructive' && !t.is_destructive) return false;
        if (this.filter === 'consciousness' && !t.is_consciousness) return false;
        if (q) {
          const hay = (t.name + ' ' + (t.description || '') + ' ' + t.module + ' ' + (t.dark_zone_ids || []).join(' ')).toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });
  }

  _renderBlock(b, q) {
    const tools = this._toolsInBlock(b, q);
    if (!tools.length) return '';
    const accent = BLOCK_ACCENT[b.id] || '#6c5ce7';
    const expanded = this.expanded.has(b.id);
    const dzSet = new Set();
    tools.forEach(t => (t.dark_zone_ids || []).forEach(d => dzSet.add(d)));
    const dzCount = dzSet.size;

    return `
      <section class="tb-section" style="--block-accent: ${accent}">
        <header class="tb-head" data-block-toggle="${b.id}" tabindex="0" role="button">
          <span class="tb-caret ${expanded ? 'open' : ''}">▸</span>
          <div>
            <div class="tb-title">${this._esc(tField(b, 'label'))}</div>
            <div class="tb-question">${this._esc(tField(b, 'question') || '')}</div>
          </div>
          <span class="tb-count">${tools.length}</span>
          ${dzCount ? `<span class="tb-dz">⚠ ${dzCount}</span>` : ''}
        </header>
        ${expanded ? `
          <div class="tb-grid">
            ${tools.map(tl => this._renderToolCard(tl)).join('')}
          </div>` : ''}
      </section>
    `;
  }

  _renderToolCard(t) {
    const chips = [];
    if (t.is_core) chips.push('<span class="chip core">CORE</span>');
    if (t.is_write) chips.push('<span class="chip write">WRITE</span>');
    if (t.is_destructive) chips.push('<span class="chip dangerous">DESTRUCTIVE</span>');
    if (t.is_consciousness) chips.push('<span class="chip consciousness">CONS</span>');
    (t.dark_zone_ids || []).forEach(d => chips.push(`<span class="chip darkzone" data-goto-dz="${d}">${d}</span>`));
    return `
      <div class="tool-card" data-tool-name="${this._esc(t.name)}">
        <div class="tool-name">${this._esc(t.name)}</div>
        <div class="tool-desc">${this._esc(t.description || '')}</div>
        <div class="tool-chips">${chips.join('')}</div>
      </div>
    `;
  }

  setFilter(mode) { this.filter = mode; this._render(); }
  setQuery(q)     { this.query = q;    this._render(); }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
