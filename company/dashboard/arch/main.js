// Main orchestrator — wires the 4 views to the topbar and side panel.

import { OverviewView } from './views/overview.js?v=phase1.5';
import { MemoryView } from './views/memory.js?v=phase1.5';
import { DarkZonesView } from './views/darkzones.js?v=phase1.5';
import { ToolsView } from './views/tools.js?v=phase1.5';
import { renderNode, renderTool } from './lib/panel.js?v=phase1.5';

const SNAPSHOT_URL = 'architecture.json?v=phase1.5';

async function loadSnapshot() {
  const res = await fetch(SNAPSHOT_URL, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`Failed to load ${SNAPSHOT_URL}: ${res.status}`);
  return await res.json();
}

function formatMetaSubline(snap) {
  const meta = snap.meta || {};
  const sum = snap.summary || {};
  const when = meta.generated_at ? meta.generated_at.slice(0, 16).replace('T', ' ') : '';
  const sha = (meta.git && meta.git.sha) ? meta.git.sha.slice(0, 7) : '';
  return `${sum.tools_total} tools · ${sum.dark_zones} Dark Zones · ${sum.modules} modules · ${sum.nodes} nodes · ${sum.edges} edges · ${sha} · snapshot ${when}`;
}

class App {
  constructor(snapshot) {
    this.snap = snapshot;
    this.activeView = 'overview';
    this.overview = null;
    this.memory = null;
    this.dz = null;
    this.tools = null;

    this.panel = document.getElementById('panel');
    this.panelBody = document.getElementById('panel-body');
    document.getElementById('panel-close').addEventListener('click', () => this.closePanel());
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') this.closePanel();
    });

    // Topbar
    document.getElementById('meta-sub').textContent = formatMetaSubline(snapshot);
    document.getElementById('dz-count').textContent = snapshot.summary.dark_zones;
    document.getElementById('tool-count').textContent = snapshot.summary.tools_total;

    document.querySelectorAll('.view-btn').forEach(b => {
      b.addEventListener('click', () => this.switchView(b.dataset.view));
    });

    // Search + filter (scoped per active view)
    document.getElementById('search').addEventListener('input', e => this._onSearch(e.target.value));
    document.getElementById('filter').addEventListener('change', e => this._onFilter(e.target.value));

    document.querySelectorAll('.tool-chip').forEach(c => {
      c.addEventListener('click', () => {
        document.querySelectorAll('.tool-chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        if (this.tools) this.tools.setFilter(c.dataset.toolFilter);
      });
    });

    // Delegated click for dark-zone chips anywhere in the document
    document.body.addEventListener('click', e => {
      const chip = e.target.closest('[data-goto-dz]');
      if (chip) {
        e.preventDefault();
        e.stopPropagation();
        this.gotoDarkZone(chip.dataset.gotoDz);
      }
    });
  }

  mount() {
    this.overview = new OverviewView({
      snapshot: this.snap,
      containerId: 'cy',
      onSelectLeaf: ({ kind, data }) => {
        if (kind === 'tool') this.showToolPanel(data);
        else this.showNodePanel(data);
      },
      navigateExternalView: (viewName, payload) => {
        if (viewName === 'darkzones') {
          this.switchView('darkzones');
          if (payload) this.dz.select(payload);
        }
      },
    });
    this.overview.mount();

    this.memory = new MemoryView({
      snapshot: this.snap,
      containerId: 'cy-memory',
      onSelectNode: d => this.showNodePanel(d),
    });
    this._memoryMounted = false;

    this.dz = new DarkZonesView({
      snapshot: this.snap,
      listId: 'dz-list',
      detailId: 'dz-detail',
    });
    this.dz.mount();

    this.tools = new ToolsView({
      snapshot: this.snap,
      gridId: 'tool-grid',
      onSelectTool: t => this.showToolPanel(t),
    });
    this.tools.mount();
  }

  switchView(name) {
    this.activeView = name;
    document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === name));
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    this.closePanel();

    if (name === 'memory' && !this._memoryMounted) {
      this.memory.mount();
      this._memoryMounted = true;
    }
    if (name === 'memory') {
      setTimeout(() => this.memory && this.memory.resize(), 50);
    }

    const filterSel = document.getElementById('filter');
    filterSel.style.display = (name === 'overview') ? '' : 'none';
  }

  showNodePanel(data) {
    this.panelBody.innerHTML = renderNode(data, this.snap);
    this.panel.classList.add('open');
  }

  showToolPanel(tool) {
    this.panelBody.innerHTML = renderTool(tool, this.snap);
    this.panel.classList.add('open');
  }

  closePanel() {
    this.panel.classList.remove('open');
  }

  gotoDarkZone(id) {
    this.switchView('darkzones');
    this.dz.select(id);
  }

  _onSearch(q) {
    if (this.activeView === 'overview') {
      this.overview.search(q);
    } else if (this.activeView === 'darkzones') {
      this.dz.filter(q);
    } else if (this.activeView === 'tools') {
      this.tools.setQuery(q);
    }
  }

  _onFilter(mode) {
    if (this.activeView === 'overview') {
      this.overview.applyFilter(mode);
    }
  }
}

loadSnapshot()
  .then(snap => {
    const app = new App(snap);
    app.mount();
    window.__arch_app = app;
  })
  .catch(err => {
    document.body.innerHTML = `<div style="padding:40px;color:#e17055;font-family:monospace;">
      <h2>Failed to load snapshot</h2>
      <pre>${String(err)}</pre>
      <p style="margin-top:12px;color:#8b8fa3">Did you run <code>python3 scripts/build_architecture_snapshot.py</code>?</p>
    </div>`;
    console.error(err);
  });
