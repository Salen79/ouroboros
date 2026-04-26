// Память / Memory — Phase 1.9: 3 lifetime levels + 4 long-term sub-blocks, RU/EN.

import { t, tField, getLang } from '../lib/i18n.js?v=phase1.10';

const LEVEL_META = {
  working: {
    titleRu: 'Рабочая',       titleEn: 'Working',
    taglineRu: 'per-task — теряется в конце задачи',
    taglineEn: 'per-task — discarded at task end',
    hintKey: 'mem.working.hint',
    accent: '#74b9ff',
  },
  short: {
    titleRu: 'Оперативная',   titleEn: 'Short-term',
    taglineRu: 'день / сессия — медленно устаревает',
    taglineEn: 'session / day — ages out',
    hintKey: 'mem.short.hint',
    accent: '#fdcb6e',
  },
  long: {
    titleRu: 'Долговременная', titleEn: 'Long-term',
    taglineRu: 'persistent — накапливается между рестартами',
    taglineEn: 'persistent — accumulates across restarts',
    hintKey: 'mem.long.hint',
    accent: '#a29bfe',
  },
  archive: {
    titleRu: 'Архив задач',    titleEn: 'Task Archive',
    taglineRu: 'append-only — 645+ файлов',
    taglineEn: 'append-only — 645+ files',
    hintKey: 'mem.archive.hint',
    accent: '#00b894',
  },
};

function metaTitle(m)   { return getLang() === 'en' ? m.titleEn   : m.titleRu; }
function metaTagline(m) { return getLang() === 'en' ? m.taglineEn : m.taglineRu; }

export class MemoryView {
  constructor({ snapshot, containerId, onSelectNode }) {
    this.snap = snapshot;
    this.container = document.getElementById(containerId);
    this.onSelect = onSelectNode;
  }

  mount() {
    const memBlocks = (this.snap.blocks && this.snap.blocks.memory) || [];
    const byLevel = { working: [], short: [], long: [], archive: [] };
    for (const b of memBlocks) {
      const lvl = b.level || 'long';
      (byLevel[lvl] || byLevel.long).push(b);
    }

    const totalNodes = memBlocks.reduce((acc, b) => acc + (b.nodes || []).length, 0);

    const locations = t('memory.locations');
    this.container.innerHTML = `
      <div class="mem-root">
        <div class="mem-head">
          <div class="mem-head-title">${this._esc(t('memory.title'))}</div>
          <div class="mem-head-sub">
            ${totalNodes} ${this._esc(locations)} ·
            <span style="color:${LEVEL_META.working.accent}">${this._countNodes(byLevel.working)} ${this._esc(metaTitle(LEVEL_META.working).toLowerCase())}</span> ·
            <span style="color:${LEVEL_META.short.accent}">${this._countNodes(byLevel.short)} ${this._esc(metaTitle(LEVEL_META.short).toLowerCase())}</span> ·
            <span style="color:${LEVEL_META.long.accent}">${this._countNodes(byLevel.long)} ${this._esc(metaTitle(LEVEL_META.long).toLowerCase())}</span> ·
            <span style="color:${LEVEL_META.archive.accent}">${this._countNodes(byLevel.archive)} ${this._esc(metaTitle(LEVEL_META.archive).toLowerCase())}</span>
          </div>
        </div>
        <div class="mem-bands">
          ${this._renderLevel('working', byLevel.working)}
          ${this._renderLevel('short', byLevel.short)}
          ${this._renderLevel('long', byLevel.long)}
          ${this._renderLevel('archive', byLevel.archive)}
        </div>
      </div>
    `;

    this.container.querySelectorAll('[data-mem-node]').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.memNode;
        const node = this.snap.topology.nodes.find(n => n.id === id);
        if (node) this.onSelect && this.onSelect(node);
      });
    });
  }

  _countNodes(blocks) {
    return blocks.reduce((acc, b) => acc + (b.nodes || []).length, 0);
  }

  _renderLevel(levelKey, blocks) {
    const meta = LEVEL_META[levelKey];
    if (!meta || blocks.length === 0) return '';

    const subBlocks = blocks.map(b => this._renderBlock(b, meta.accent)).join('');
    const blockCount = blocks.length;
    const totalNodes = this._countNodes(blocks);
    const subBlockLabel = getLang() === 'en'
      ? (blockCount > 1 ? ` · ${blockCount} ${t('memory.subblocks')}` : '')
      : (blockCount > 1 ? ` · ${blockCount} ${t('memory.subblocks')}` : '');

    return `
      <section class="mem-band" data-level="${levelKey}" style="--band-accent: ${meta.accent}">
        <header class="mem-band-head">
          <div class="mem-band-dot"></div>
          <div>
            <div class="mem-band-title">${this._esc(metaTitle(meta))}</div>
            <div class="mem-band-tagline">${this._esc(metaTagline(meta))}</div>
          </div>
          <div class="mem-band-count">${totalNodes}${subBlockLabel}</div>
        </header>
        <div class="mem-band-body">
          <div class="mem-band-hint">${this._esc(t(meta.hintKey))}</div>
          ${subBlocks}
        </div>
      </section>
    `;
  }

  _renderBlock(block, accent) {
    const nodesHtml = (block.nodes || [])
      .map(id => {
        const node = this.snap.topology.nodes.find(n => n.id === id);
        return node ? this._renderNode(node, accent) : '';
      })
      .filter(Boolean)
      .join('');

    const virtualHtml = (block.virtual_items || [])
      .map(v => `
        <div class="mem-node mem-node-virtual" style="--card-accent: ${accent}">
          <div class="mem-node-kind">${this._esc(t('kind.virtual'))}</div>
          <div class="mem-node-label">${this._esc(v)}</div>
          <div class="mem-node-sub">${this._esc(t('kind.virtual.sub'))}</div>
        </div>
      `).join('');

    return `
      <div class="mem-bucket">
        <div class="mem-bucket-head">
          <div class="mem-bucket-title">${this._esc(tField(block, 'label'))}</div>
          <div class="mem-bucket-question">${this._esc(tField(block, 'question') || '')}</div>
        </div>
        <div class="mem-bucket-grid">${nodesHtml}${virtualHtml}</div>
      </div>
    `;
  }

  _renderNode(n, accent) {
    const dzs = n.dark_zone_ids || [];
    const semantic = tField(n, 'semantic_label') || n.semantic_label || n.label;
    const tech = n.label || '';
    const showTech = semantic !== tech;
    return `
      <div class="mem-node" data-mem-node="${this._esc(n.id)}" style="--card-accent: ${accent}">
        <div class="mem-node-kind">${this._kindLabel(n.kind)}</div>
        <div class="mem-node-label">${this._esc(semantic)}</div>
        ${showTech ? `<div class="mem-node-path"><code>${this._esc(tech)}</code></div>` : ''}
        ${n.description ? `<div class="mem-node-sub">${this._esc(n.description)}</div>` : ''}
        ${dzs.length ? `
          <div class="mem-node-chips">
            ${dzs.map(d => `<span class="chip darkzone" data-goto-dz="${d}">${d}</span>`).join('')}
          </div>
        ` : ''}
      </div>
    `;
  }

  _kindLabel(kind) {
    const k = {
      file_md:    t('kind.file'),
      file_dir:   t('kind.dir'),
      logfile:    t('kind.log'),
      state_json: t('kind.json'),
      chromadb:   t('kind.chroma'),
    }[kind];
    return k || (kind || '').toUpperCase();
  }

  resize() { /* no-op */ }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
