// Memory view — Phase 1.6: reorganized by LIFETIME, not storage type.
//
// Three horizontal bands:
//   Working     — per-task, dropped at task end
//   Short-term  — session / day, ages out
//   Long-term   — persistent, accumulates
//
// Each band lists its storage items. Click → side panel with writers /
// readers / Dark Zones. No more Cytoscape here; pure DOM, matches the
// ecosystem metaphor (three layers of the cell).

const BAND_META = {
  working: {
    title: 'Working memory',
    tagline: 'Per-task — dropped when the task ends',
    hint: 'Loaded at task start, replaced at task end. Nothing here survives a restart untouched.',
    accent: '#74b9ff',
  },
  short_term: {
    title: 'Short-term',
    tagline: 'Session / day — ages out',
    hint: 'Append-only logs and state with TTL. Useful for recent context, cleared regularly.',
    accent: '#fdcb6e',
  },
  long_term: {
    title: 'Long-term',
    tagline: 'Persistent — accumulates across restarts',
    hint: 'Identity, wisdom, skills, historical state. Written rarely, read often.',
    accent: '#a29bfe',
  },
};

// Human-friendly subcategory grouping inside each band (for visual grouping
// only — the lifetime classification is what matters).
const BAND_GROUPS = {
  working: [
    { label: 'File memory', match: n => n.kind === 'file_md' },
  ],
  short_term: [
    { label: 'Logs', match: n => n.kind === 'logfile' },
    { label: 'State (TTL)', match: n => n.kind === 'state_json' },
  ],
  long_term: [
    { label: 'File memory', match: n => n.kind === 'file_md' || n.kind === 'file_dir' },
    { label: 'ChromaDB collections', match: n => n.kind === 'chromadb' },
    { label: 'Persistent state', match: n => n.kind === 'state_json' },
  ],
};

export class MemoryView {
  constructor({ snapshot, containerId, onSelectNode }) {
    this.snap = snapshot;
    this.container = document.getElementById(containerId);
    this.onSelect = onSelectNode;
  }

  mount() {
    const nodes = this.snap.topology.nodes.filter(n => n.organ === 'memory');
    const byLife = { working: [], short_term: [], long_term: [] };
    for (const n of nodes) {
      const life = n.memory_lifetime || 'long_term';
      (byLife[life] || byLife.long_term).push(n);
    }

    const totalDZs = nodes.reduce((acc, n) => acc + (n.dark_zone_ids || []).length, 0);
    const bandsHtml = ['working', 'short_term', 'long_term']
      .map(life => this._renderBand(life, byLife[life]))
      .join('');

    this.container.innerHTML = `
      <div class="mem-root">
        <div class="mem-head">
          <div class="mem-head-title">Memory — classified by lifetime</div>
          <div class="mem-head-sub">
            ${nodes.length} storage locations ·
            <span style="color:#74b9ff">${byLife.working.length} working</span> ·
            <span style="color:#fdcb6e">${byLife.short_term.length} short-term</span> ·
            <span style="color:#a29bfe">${byLife.long_term.length} long-term</span>
          </div>
        </div>
        <div class="mem-bands">
          ${bandsHtml}
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

  _renderBand(lifeKey, nodes) {
    const meta = BAND_META[lifeKey];
    const groups = BAND_GROUPS[lifeKey] || [];

    // Bucket nodes by the first matching group; stragglers go to "Other"
    const buckets = groups.map(g => ({ label: g.label, nodes: [] }));
    const other = [];
    for (const n of nodes) {
      let placed = false;
      for (let i = 0; i < groups.length; i++) {
        if (groups[i].match(n)) { buckets[i].nodes.push(n); placed = true; break; }
      }
      if (!placed) other.push(n);
    }
    if (other.length) buckets.push({ label: 'Other', nodes: other });

    const bucketsHtml = buckets.filter(b => b.nodes.length).map(b => `
      <div class="mem-bucket">
        <div class="mem-bucket-title">${this._esc(b.label)}</div>
        <div class="mem-bucket-grid">
          ${b.nodes.map(n => this._renderNode(n, meta.accent)).join('')}
        </div>
      </div>
    `).join('');

    return `
      <section class="mem-band" data-life="${lifeKey}" style="--band-accent: ${meta.accent}">
        <header class="mem-band-head">
          <div class="mem-band-dot"></div>
          <div>
            <div class="mem-band-title">${this._esc(meta.title)}</div>
            <div class="mem-band-tagline">${this._esc(meta.tagline)}</div>
          </div>
          <div class="mem-band-count">${nodes.length}</div>
        </header>
        <div class="mem-band-body">
          <div class="mem-band-hint">${this._esc(meta.hint)}</div>
          ${bucketsHtml}
        </div>
      </section>
    `;
  }

  _renderNode(n, accent) {
    const dzs = n.dark_zone_ids || [];
    const subline = this._subline(n);
    return `
      <div class="mem-node" data-mem-node="${this._esc(n.id)}" style="--card-accent: ${accent}">
        <div class="mem-node-kind">${this._kindLabel(n.kind)}</div>
        <div class="mem-node-label">${this._esc(n.label)}</div>
        ${subline ? `<div class="mem-node-sub">${this._esc(subline)}</div>` : ''}
        ${dzs.length ? `
          <div class="mem-node-chips">
            ${dzs.map(d => `<span class="chip darkzone" data-goto-dz="${d}">${d}</span>`).join('')}
          </div>
        ` : ''}
      </div>
    `;
  }

  _subline(n) {
    return n.description || '';
  }

  _kindLabel(kind) {
    return {
      file_md:   'FILE',
      file_dir:  'DIR',
      logfile:   'LOG',
      state_json:'JSON',
      chromadb:  'CHROMA',
    }[kind] || kind || '';
  }

  resize() { /* no-op in DOM-only layout */ }

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
}
