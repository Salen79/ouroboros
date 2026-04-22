// Architecture dashboard — orchestrator (Phase 1.9).

import { OverviewView } from './views/overview.js?v=phase1.9';
import { MemoryView } from './views/memory.js?v=phase1.9';
import { DarkZonesView } from './views/darkzones.js?v=phase1.9';
import { ToolsView } from './views/tools.js?v=phase1.9';
import { renderNode, renderTool } from './lib/panel.js?v=phase1.9';
import { t, getLang, setLang } from './lib/i18n.js?v=phase1.9';

const SNAPSHOT_URL = 'architecture.json?v=phase1.9';

async function loadSnapshot() {
  const res = await fetch(SNAPSHOT_URL, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${t('loading')} — ${res.status}`);
  return await res.json();
}

function formatMetaSubline(snap) {
  const meta = snap.meta || {};
  const sum = snap.summary || {};
  const when = meta.generated_at ? meta.generated_at.slice(0, 16).replace('T', ' ') : '';
  const sha = (meta.git && meta.git.sha) ? meta.git.sha.slice(0, 7) : '';
  return `${sum.tools_total} ${t('meta.tools')} · ${sum.dark_zones} ${t('meta.weaknesses')} · ${sum.modules} ${t('meta.modules')} · ${sum.nodes} ${t('meta.nodes')} · ${sum.edges} ${t('meta.edges')} · ${sha} · ${t('meta.snapshot')} ${when}`;
}

function applyStaticI18n() {
  // Title / meta subline / tabs / search placeholder / filter options /
  // tool-tab chips / panel close button.
  document.title = t('title');
  document.documentElement.lang = getLang();

  const brandTitle = document.querySelector('.brand .title');
  if (brandTitle) brandTitle.textContent = t('title');

  const tabMap = {
    overview: 'tab.overview',
    darkzones: 'tab.darkzones',
    memory: 'tab.memory',
    tools: 'tab.tools',
  };
  document.querySelectorAll('.view-btn').forEach(b => {
    const key = tabMap[b.dataset.view];
    if (!key) return;
    // Preserve any <span class="pill"> children; rewrite only the text node
    const pill = b.querySelector('.pill');
    b.innerHTML = t(key) + (pill ? ' ' + pill.outerHTML : '');
  });

  const search = document.getElementById('search');
  if (search) search.placeholder = t('search.placeholder');

  const filter = document.getElementById('filter');
  if (filter) {
    filter.innerHTML = `
      <option value="all">${t('filter.all')}</option>
      <option value="write">${t('filter.write')}</option>
      <option value="memory">${t('filter.memory')}</option>
      <option value="dark">${t('filter.dark')}</option>
      <option value="tools">${t('filter.tools')}</option>
    `;
  }

  const toolChips = {
    all: 'tools.chip.all',
    core: 'tools.chip.core',
    write: 'tools.chip.write',
    destructive: 'tools.chip.destructive',
    consciousness: 'tools.chip.consciousness',
  };
  document.querySelectorAll('.tool-chip').forEach(c => {
    const k = toolChips[c.dataset.toolFilter];
    if (k) c.textContent = t(k);
  });

  const close = document.getElementById('panel-close');
  if (close) close.title = t('close');

  const hint = document.querySelector('#view-darkzones .muted');
  if (hint) hint.textContent = t('dz.select.hint');
}

function mountLangToggle() {
  // Injects RU/EN toggle into the topbar right of the search/filter.
  const right = document.querySelector('.topbar .right');
  if (!right || document.getElementById('lang-toggle')) return;
  const lang = getLang();
  const btn = document.createElement('div');
  btn.id = 'lang-toggle';
  btn.className = 'lang-toggle';
  btn.title = t('lang.toggle.title');
  btn.innerHTML = `
    <button data-lang="ru" class="${lang === 'ru' ? 'active' : ''}">RU</button>
    <button data-lang="en" class="${lang === 'en' ? 'active' : ''}">EN</button>
  `;
  right.appendChild(btn);
  btn.addEventListener('click', e => {
    const b = e.target.closest('[data-lang]');
    if (!b) return;
    if (b.dataset.lang === lang) return;
    setLang(b.dataset.lang);  // reloads the page
  });
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
    document.addEventListener('keydown', e => { if (e.key === 'Escape') this.closePanel(); });

    document.getElementById('meta-sub').textContent = formatMetaSubline(snapshot);
    document.getElementById('dz-count').textContent = snapshot.summary.dark_zones;
    document.getElementById('tool-count').textContent = snapshot.summary.tools_total;

    document.querySelectorAll('.view-btn').forEach(b => {
      b.addEventListener('click', () => this.switchView(b.dataset.view));
    });

    document.getElementById('search').addEventListener('input', e => this._onSearch(e.target.value));
    document.getElementById('filter').addEventListener('change', e => this._onFilter(e.target.value));

    document.querySelectorAll('.tool-chip').forEach(c => {
      c.addEventListener('click', () => {
        document.querySelectorAll('.tool-chip').forEach(x => x.classList.remove('active'));
        c.classList.add('active');
        if (this.tools) this.tools.setFilter(c.dataset.toolFilter);
      });
    });

    document.body.addEventListener('click', e => {
      const chip = e.target.closest('[data-goto-dz]');
      if (chip && chip.dataset.gotoDz) {
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
        } else if (viewName === 'tools') {
          this.switchView('tools');
        } else if (viewName === 'memory') {
          this.switchView('memory');
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
  closePanel() { this.panel.classList.remove('open'); }

  gotoDarkZone(id) {
    this.switchView('darkzones');
    this.dz.select(id);
  }

  _onSearch(q) {
    if (this.activeView === 'overview') this.overview.search(q);
    else if (this.activeView === 'darkzones') this.dz.filter(q);
    else if (this.activeView === 'tools') this.tools.setQuery(q);
  }

  _onFilter(mode) {
    if (this.activeView === 'overview') this.overview.applyFilter(mode);
  }
}

applyStaticI18n();
mountLangToggle();

loadSnapshot()
  .then(snap => {
    const app = new App(snap);
    app.mount();
    window.__arch_app = app;
  })
  .catch(err => {
    document.body.innerHTML = `<div style="padding:40px;color:#e17055;font-family:monospace;">
      <h2>${t('loading')}</h2>
      <pre>${String(err)}</pre>
    </div>`;
    console.error(err);
  });
