// Память — Phase 1.7: 3 уровня по времени жизни + 4 под-блока в Долговременной.

const LEVEL_META = {
  working: {
    title: 'Рабочая',
    tagline: 'per-task — теряется в конце задачи',
    hint: 'Загружается в начале задачи, замещается в конце. Ничего отсюда не переживает рестарт нетронутым.',
    accent: '#74b9ff',
  },
  short: {
    title: 'Оперативная',
    tagline: 'день / сессия — медленно устаревает',
    hint: 'Append-only логи и состояние с TTL. Недавний контекст, регулярно старится.',
    accent: '#fdcb6e',
  },
  long: {
    title: 'Долговременная',
    tagline: 'persistent — накапливается между рестартами',
    hint: 'Идентичность, мудрость, навыки, исторические состояния. Пишется редко, читается часто.',
    accent: '#a29bfe',
  },
  archive: {
    title: 'Архив задач',
    tagline: 'append-only — 645+ файлов',
    hint: 'Один JSON на задачу. Входные данные для pattern_detector и ретроспективной аналитики.',
    accent: '#00b894',
  },
};

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

    this.container.innerHTML = `
      <div class="mem-root">
        <div class="mem-head">
          <div class="mem-head-title">Память — по времени жизни</div>
          <div class="mem-head-sub">
            ${totalNodes} хранилищ ·
            <span style="color:${LEVEL_META.working.accent}">${this._countNodes(byLevel.working)} рабочих</span> ·
            <span style="color:${LEVEL_META.short.accent}">${this._countNodes(byLevel.short)} оперативных</span> ·
            <span style="color:${LEVEL_META.long.accent}">${this._countNodes(byLevel.long)} долговременных</span> ·
            <span style="color:${LEVEL_META.archive.accent}">${this._countNodes(byLevel.archive)} в архиве</span>
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

    return `
      <section class="mem-band" data-level="${levelKey}" style="--band-accent: ${meta.accent}">
        <header class="mem-band-head">
          <div class="mem-band-dot"></div>
          <div>
            <div class="mem-band-title">${this._esc(meta.title)}</div>
            <div class="mem-band-tagline">${this._esc(meta.tagline)}</div>
          </div>
          <div class="mem-band-count">${totalNodes}${blockCount > 1 ? ` · ${blockCount} под-блока` : ''}</div>
        </header>
        <div class="mem-band-body">
          <div class="mem-band-hint">${this._esc(meta.hint)}</div>
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
          <div class="mem-node-kind">ВИРТ</div>
          <div class="mem-node-label">${this._esc(v)}</div>
          <div class="mem-node-sub">in-process, не персистится</div>
        </div>
      `).join('');

    return `
      <div class="mem-bucket">
        <div class="mem-bucket-head">
          <div class="mem-bucket-title">${this._esc(block.label)}</div>
          <div class="mem-bucket-question">${this._esc(block.question || '')}</div>
        </div>
        <div class="mem-bucket-grid">${nodesHtml}${virtualHtml}</div>
      </div>
    `;
  }

  _renderNode(n, accent) {
    const dzs = n.dark_zone_ids || [];
    const semantic = n.semantic_label || n.label;
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
    return {
      file_md:    'ФАЙЛ',
      file_dir:   'ПАПКА',
      logfile:    'ЛОГ',
      state_json: 'JSON',
      chromadb:   'CHROMA',
    }[kind] || (kind || '').toUpperCase();
  }

  resize() { /* no-op */ }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
