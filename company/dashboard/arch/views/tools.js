// Tools view — grid of 64 tool cards with filter chips.

import { renderTool } from '../lib/panel.js?v=phase1.6';

export class ToolsView {
  constructor({ snapshot, gridId, onSelectTool }) {
    this.snapshot = snapshot;
    this.gridEl = document.getElementById(gridId);
    this.onSelect = onSelectTool;
    this.filter = 'all';
    this.query = '';
  }

  mount() {
    this._render();
  }

  _render() {
    const q = this.query.trim().toLowerCase();
    const rows = this.snapshot.tools.filter(t => {
      if (this.filter === 'core' && !t.is_core) return false;
      if (this.filter === 'write' && !t.is_write) return false;
      if (this.filter === 'destructive' && !t.is_destructive) return false;
      if (this.filter === 'consciousness' && !t.is_consciousness) return false;
      if (q) {
        const hay = (
          t.name + ' ' + (t.description || '') + ' ' + t.module + ' ' + (t.dark_zone_ids || []).join(' ')
        ).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    this.gridEl.innerHTML = rows.map(t => `
      <div class="tool-card" data-tool="${this._esc(t.name)}">
        <div class="tool-name">${this._esc(t.name)}</div>
        <div class="tool-desc">${this._esc(t.description || '')}</div>
        <div class="tool-chips">
          ${t.is_core ? '<span class="chip core">CORE</span>' : ''}
          ${t.is_write ? '<span class="chip write">WRITE</span>' : ''}
          ${t.is_destructive ? '<span class="chip dangerous">DESTRUCTIVE</span>' : ''}
          ${t.is_consciousness ? '<span class="chip consciousness">CONS</span>' : ''}
          ${(t.dark_zone_ids || []).map(id => `<span class="chip darkzone" data-goto-dz="${id}">${id}</span>`).join('')}
        </div>
      </div>
    `).join('');

    this.gridEl.querySelectorAll('.tool-card').forEach(card => {
      card.addEventListener('click', e => {
        // Don't trigger panel if the chip was a dark-zone goto chip
        if (e.target.closest('[data-goto-dz]')) return;
        const t = this.snapshot.tools.find(t => t.name === card.dataset.tool);
        if (t) this.onSelect && this.onSelect(t);
      });
    });
  }

  setFilter(filter) {
    this.filter = filter;
    this._render();
  }

  setQuery(q) {
    this.query = q;
    this._render();
  }

  _esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
}
