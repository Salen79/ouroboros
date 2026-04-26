// Тёмные зоны / Dark Zones — Phase 1.9 with RU/EN group headers + status badges.

import { renderDarkZone } from '../lib/panel.js?v=phase1.10';
import { t, getLang } from '../lib/i18n.js?v=phase1.10';

// Must match SAFETY_DZ_GROUPS in build_architecture_snapshot.py
const TAXONOMY = [
  ['Наблюдаемость',   'Observability',   ['D1', 'D2', 'D5', 'D15', 'D18']],
  ['Согласованность', 'Consistency',     ['D4', 'D19', 'D20', 'D22', 'D23']],
  ['Конфигурация',    'Configuration',   ['D8', 'D11', 'D12', 'D13']],
  ['Атаки',           'Attack Surface',  ['D14', 'D16', 'D17', 'D25', 'D26', 'D27', 'D29']],
  ['Артефакты',       'Artifacts',       ['D3', 'D6', 'D7', 'D10']],
  ['Внешнее',         'External',        ['D9', 'D21', 'D24']],
];

function statusGlyph(status) {
  if (status === 'closed') return '✓';
  if (status === 'catalogued') return '·';
  return '⚠'; // open (default)
}

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

    // Header counter — closed X / total Y across all DZs.
    const sum = this.snap.summary || {};
    const total = sum.dark_zones != null ? sum.dark_zones : this.snap.dark_zones.length;
    const closed = sum.dark_zones_closed != null
      ? sum.dark_zones_closed
      : this.snap.dark_zones.filter(d => d.status === 'closed').length;

    const lang = getLang();
    let html = '';
    html += `<div class="dz-list-header">
      <span class="dz-counter">
        <span class="dz-counter-num">${closed}</span>
        <span class="dz-counter-sep">/</span>
        <span class="dz-counter-total">${total}</span>
        <span class="dz-counter-label">${this._esc(t('dz.counter.closed'))}</span>
      </span>
      <span class="dz-legend">
        <span class="dz-legend-item"><i class="dz-status closed">✓</i>${this._esc(t('dz.status.closed'))}</span>
        <span class="dz-legend-item"><i class="dz-status open">⚠</i>${this._esc(t('dz.status.open'))}</span>
        <span class="dz-legend-item"><i class="dz-status catalogued">·</i>${this._esc(t('dz.status.catalogued'))}</span>
      </span>
    </div>`;

    for (const [groupRu, groupEn, ids] of TAXONOMY) {
      const filtered = ids
        .map(id => dzById[id])
        .filter(d => d && (!q || (d.id + ' ' + d.title + ' ' + d.body_md).toLowerCase().includes(q)));
      if (!filtered.length) continue;
      const groupLabel = lang === 'en' ? groupEn : groupRu;
      const closedInGroup = filtered.filter(d => d.status === 'closed').length;
      html += `<div class="dz-group-head">
        <span>${this._esc(groupLabel)}</span>
        <span class="dz-group-count">${closedInGroup}/${filtered.length}</span>
      </div>`;
      html += filtered.map(d => {
        const status = d.status || 'open';
        return `
        <div class="dz-card status-${status} ${d.id === this.activeId ? 'active' : ''}" data-dz="${d.id}">
          <i class="dz-status ${status}" title="${this._esc(t('dz.status.' + status))}">${statusGlyph(status)}</i>
          <div class="dz-card-text">
            <span class="dz-id">${d.id}</span>
            <span class="dz-title">${this._esc(d.title)}</span>
          </div>
        </div>
      `;
      }).join('');
    }
    if (!html.includes('dz-card')) {
      html += `<div class="dz-empty muted">${this._esc(t('dz.empty'))}</div>`;
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
