// Dark Zones view — list on the left, detail on the right.

import { renderDarkZone } from '../lib/panel.js?v=phase1.6';

export class DarkZonesView {
  constructor({ snapshot, listId, detailId }) {
    this.snapshot = snapshot;
    this.listEl = document.getElementById(listId);
    this.detailEl = document.getElementById(detailId);
    this.activeId = null;
  }

  mount() {
    this._renderList();
    // Select first by default
    if (this.snapshot.dark_zones.length) {
      this.select(this.snapshot.dark_zones[0].id);
    }
  }

  _renderList(filter = '') {
    const q = filter.trim().toLowerCase();
    const dzs = this.snapshot.dark_zones.filter(d => {
      if (!q) return true;
      return (d.id + ' ' + d.title + ' ' + d.body_md).toLowerCase().includes(q);
    });
    this.listEl.innerHTML = dzs.map(d => `
      <div class="dz-card ${d.id === this.activeId ? 'active' : ''}" data-dz="${d.id}">
        <div>
          <span class="dz-id">${d.id}</span>
          <span class="dz-title">${this._esc(d.title)}</span>
        </div>
      </div>
    `).join('');
    this.listEl.querySelectorAll('.dz-card').forEach(card => {
      card.addEventListener('click', () => this.select(card.dataset.dz));
    });
  }

  select(id) {
    const dz = this.snapshot.dark_zones.find(d => d.id === id);
    if (!dz) return;
    this.activeId = id;
    this.listEl.querySelectorAll('.dz-card').forEach(c => {
      c.classList.toggle('active', c.dataset.dz === id);
    });
    this.detailEl.innerHTML = renderDarkZone(dz);
  }

  filter(query) {
    this._renderList(query);
  }

  _esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
}
