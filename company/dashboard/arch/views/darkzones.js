// Тёмные зоны / Dark Zones — Phase 1.9 with RU/EN group headers.

import { renderDarkZone } from '../lib/panel.js?v=phase1.9';
import { t, getLang } from '../lib/i18n.js?v=phase1.9';

// Must match SAFETY_DZ_GROUPS in build_architecture_snapshot.py
const TAXONOMY = [
  ['Наблюдаемость',   'Observability',   ['D1', 'D2', 'D5', 'D15', 'D18']],
  ['Согласованность', 'Consistency',     ['D4', 'D19', 'D20', 'D22', 'D23']],
  ['Конфигурация',    'Configuration',   ['D8', 'D11', 'D12', 'D13']],
  ['Атаки',           'Attack Surface',  ['D14', 'D16', 'D17', 'D25']],
  ['Артефакты',       'Artifacts',       ['D3', 'D6', 'D7', 'D10']],
  ['Внешнее',         'External',        ['D9', 'D21', 'D24']],
];

export class DarkZonesView {
  constructor({ snapshot, listId, detailId }) {
    this.snap = snapshot;
    this.listEl = document.getElementById(listId);
    this.detailEl = document.getElementById(detailId);
    this.activeId = null;
  }

  mount() {
    this._renderList();
    if (this.snap.dark_zones.length) this.select(this.snap.dark_zones[0].id);
  }

  _renderList(filter = '') {
    const q = (filter || '').trim().toLowerCase();
    const dzById = Object.fromEntries(this.snap.dark_zones.map(d => [d.id, d]));

    const lang = getLang();
    let html = '';
    for (const [groupRu, groupEn, ids] of TAXONOMY) {
      const filtered = ids
        .map(id => dzById[id])
        .filter(d => d && (!q || (d.id + ' ' + d.title + ' ' + d.body_md).toLowerCase().includes(q)));
      if (!filtered.length) continue;
      const groupLabel = lang === 'en' ? groupEn : groupRu;
      html += `<div class="dz-group-head">${this._esc(groupLabel)}</div>`;
      html += filtered.map(d => `
        <div class="dz-card ${d.id === this.activeId ? 'active' : ''}" data-dz="${d.id}">
          <div>
            <span class="dz-id">${d.id}</span>
            <span class="dz-title">${this._esc(d.title)}</span>
          </div>
        </div>
      `).join('');
    }
    if (!html) {
      html = `<div class="dz-empty muted">${this._esc(t('dz.empty'))}</div>`;
    }
    this.listEl.innerHTML = html;
    this.listEl.querySelectorAll('.dz-card').forEach(card => {
      card.addEventListener('click', () => this.select(card.dataset.dz));
    });
  }

  select(id) {
    const dz = this.snap.dark_zones.find(d => d.id === id);
    if (!dz) return;
    this.activeId = id;
    this.listEl.querySelectorAll('.dz-card').forEach(c => {
      c.classList.toggle('active', c.dataset.dz === id);
    });
    this.detailEl.innerHTML = renderDarkZone(dz);
  }

  filter(q) { this._renderList(q); }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
