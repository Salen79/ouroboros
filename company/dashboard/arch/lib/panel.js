// Side panel renderer — given a datum and the full snapshot, builds HTML.

import { t, tField } from './i18n.js?v=phase1.10';

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function dzChips(ids, snapshot) {
  if (!ids || !ids.length) return '';
  const dzById = (snapshot && snapshot.dark_zones)
    ? Object.fromEntries(snapshot.dark_zones.map(d => [d.id, d]))
    : {};
  return `<div class="badges">
    ${ids.map(id => {
      const status = (dzById[id] && dzById[id].status) || 'open';
      return `<span class="chip darkzone status-${status}" data-goto-dz="${id}">${id}</span>`;
    }).join('')}
  </div>`;
}

export function renderNode(node, snapshot) {
  // node: Cytoscape node data
  const dark = (node.dark_zones || []).map(id => snapshot.dark_zones.find(d => d.id === id)).filter(Boolean);
  const isMem = ['file_md', 'file_dir', 'logfile', 'state_json', 'chromadb'].includes(node.kind);

  let ownership = '';
  if (isMem) {
    // Find ownership row
    const matchCandidates = [node.label, node.label.split(':').pop().trim()];
    const own = snapshot.memory_ownership.find(r =>
      matchCandidates.some(c => r.file.includes(c.replace(/^.*\/\*/, '')) || c.includes(r.file)),
    );
    if (own) {
      ownership = `
        <h3>${esc(t('panel.writers'))}</h3>
        <p>${esc(own.writers_md)}</p>
        <h3>${esc(t('panel.readers'))}</h3>
        <p>${esc(own.readers_md)}</p>`;
    }
  }

  // Module-kind nodes: find the module responsibility row
  let moduleRow = '';
  if (node.kind === 'module') {
    const m = snapshot.modules.find(m => node.path && (
      m.file_line.includes(node.path.split('/').pop()) ||
      m.name.replace(/[\s\.]/g, '').includes(node.label.replace(/[\s\.]/g, ''))
    ));
    if (m) {
      moduleRow = `<h3>${esc(t('panel.role'))}</h3><p>${esc(m.role)}</p>`;
    }
  }

  const semantic = tField(node, 'semantic_label') || node.semantic_label || node.label;
  const tech = node.label || '';
  const showTech = semantic !== tech;
  return `
    <h2>${esc(semantic)}</h2>
    <div class="subline">
      ${showTech ? `<code>${esc(tech)}</code> ` : ''}
      ${node.path ? `<code>${esc(node.path)}</code> ` : ''}
      ${node.loc ? `· ${node.loc} ${esc(t('panel.lines'))} ` : ''}
      ${node.layer ? `· ${esc(t('panel.layer'))}: <code>${esc(node.layer)}</code>` : ''}
      ${node.kind ? `· ${esc(t('panel.kind'))}: <code>${esc(node.kind)}</code>` : ''}
    </div>
    ${dzChips(node.dark_zones, snapshot)}
    ${node.description ? `<h3>${esc(t('panel.description'))}</h3><p>${esc(node.description)}</p>` : ''}
    ${moduleRow}
    ${ownership}
    ${dark.length ? `
      <h3>${esc(t('panel.weaknesses'))} (${dark.length})</h3>
      ${dark.map(d => {
        const status = d.status || 'open';
        const glyph = status === 'closed' ? '✓' : status === 'catalogued' ? '·' : '⚠';
        return `
        <div style="margin-bottom:10px;">
          <div style="font-weight:600;color:var(--accent-2);">
            <span class="chip darkzone status-${status}" data-goto-dz="${d.id}">${d.id}</span>
            <span class="dz-status inline ${status}" title="${esc(t('dz.status.' + status))}">${glyph}</span>
            ${esc(d.title)}
          </div>
          <p style="margin-top:4px;font-size:12.5px;color:var(--muted);">${esc(d.body_md.slice(0, 220))}${d.body_md.length > 220 ? '…' : ''}</p>
        </div>
      `;
      }).join('')}
    ` : ''}
  `;
}

export function renderTool(tool, snapshot) {
  const chips = [];
  if (tool.is_core) chips.push('<span class="chip core">CORE</span>');
  if (tool.is_write) chips.push('<span class="chip write">WRITE</span>');
  if (tool.is_destructive) chips.push('<span class="chip dangerous">DESTRUCTIVE</span>');
  if (tool.is_consciousness) chips.push('<span class="chip consciousness">CONSCIOUSNESS</span>');

  const params = tool.parameters || {};
  const hasParams = params.properties && Object.keys(params.properties).length;

  return `
    <h2 style="font-family:'SF Mono',monospace">${esc(tool.name)}</h2>
    <div class="subline">
      <code>${esc(tool.module)}:${tool.line}</code>
      · ${esc(t('panel.timeout'))} ${tool.timeout_sec} ${esc(t('panel.seconds'))}
      ${tool.is_code_tool ? '· code_tool' : ''}
    </div>
    <div class="badges">${chips.join('')}</div>
    ${dzChips(tool.dark_zone_ids, snapshot)}
    <h3>${esc(t('panel.description'))}</h3>
    <p>${esc(tool.description) || `<span class="muted">${esc(t('panel.no_description'))}</span>`}</p>
    ${hasParams ? `
      <h3>${esc(t('panel.parameters'))}</h3>
      <pre>${esc(JSON.stringify(params, null, 2))}</pre>
    ` : `<h3>${esc(t('panel.parameters'))}</h3><p class="muted">${esc(t('panel.none'))}</p>`}
  `;
}

function statusGlyph(status) {
  if (status === 'closed') return '✓';
  if (status === 'catalogued') return '·';
  return '⚠';
}

function renderStatusBlock(dz) {
  const status = dz.status || 'open';
  const label = t('dz.status.' + status);
  const glyph = statusGlyph(status);
  if (status !== 'closed') {
    return `
      <div class="dz-status-block status-${status}">
        <span class="dz-status-icon">${glyph}</span>
        <span class="dz-status-label">${esc(label)}</span>
      </div>
    `;
  }
  // closed — show commit + fix summary if present
  const commit = dz.fix_commit;
  const summary = dz.fix_summary;
  return `
    <div class="dz-status-block status-closed">
      <div class="dz-status-row">
        <span class="dz-status-icon">${glyph}</span>
        <span class="dz-status-label">${esc(label)}</span>
        ${commit ? `<a class="dz-fix-commit" href="https://github.com/Salen79/ouroboros/commit/${esc(commit)}"
                       target="_blank" rel="noopener" title="${esc(t('dz.fix.commit.tooltip'))}"
                       >${esc(commit.slice(0, 7))}</a>` : ''}
      </div>
      ${summary ? `<div class="dz-fix-summary">${esc(summary)}</div>` : ''}
    </div>
  `;
}

export function renderDetector(payload, snapshot) {
  const item = payload.item || {};
  const alerts = payload.alerts || [];
  const totals = ((payload.block || {}).totals) || {};
  const updated = ((payload.block || {}).generated_at) || '';

  const ref = item.ref || '';
  const subline = ref
    ? `<code>${esc(ref)}</code>`
    : '<span class="muted">no source pointer</span>';

  const counters = `
    <div class="badges" style="margin-top:8px;">
      <span class="chip" style="background:rgba(225,112,85,0.18);color:#fab1a0;">
        ${esc(t('detector.today'))}: <b>${item.today | 0}</b>
      </span>
      <span class="chip" style="background:rgba(225,112,85,0.18);color:#fab1a0;">
        ${esc(t('detector.week'))}: <b>${item.week | 0}</b>
      </span>
      <span class="chip" style="background:rgba(225,112,85,0.18);color:#fab1a0;">
        ${esc(t('detector.all'))}: <b>${item.all | 0}</b>
      </span>
    </div>
  `;

  const renderEvidence = ev => {
    if (!ev) return '';
    if (ev.phantom_facts) {
      return ev.phantom_facts.map(p =>
        `<span class="file-tag" title="${esc(p.kind)}">${esc(p.token)}</span>`,
      ).join(' ');
    }
    if (ev.panic_terms) {
      return ev.panic_terms.map(t => `<span class="file-tag">${esc(t)}</span>`).join(' ');
    }
    if (ev.by_term) {
      return Object.entries(ev.by_term).map(
        ([term, n]) => `<span class="file-tag">${esc(term)} ×${n}</span>`,
      ).join(' ');
    }
    return '';
  };

  const renderExcerpt = ev => {
    const x = ev && (ev.report_excerpt || (ev.samples && ev.samples[0])) || '';
    if (!x) return '';
    const trimmed = x.length > 240 ? x.slice(0, 240) + '…' : x;
    return `<p style="margin-top:4px;font-size:12.5px;color:var(--muted);white-space:pre-wrap;">${esc(trimmed)}</p>`;
  };

  const list = alerts.length
    ? alerts.slice(0, 10).map(a => `
      <div style="margin-bottom:10px;padding:8px 10px;border:1px solid rgba(225,112,85,0.25);border-radius:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span class="chip darkzone status-open">${esc(a.type)}</span>
          <span class="muted" style="font-size:11px;">${esc((a.ts || '').slice(0, 16).replace('T', ' '))}</span>
        </div>
        <div style="margin-top:6px;font-size:13px;">${esc(a.summary || '')}</div>
        ${renderEvidence(a.evidence) ? `<div style="margin-top:6px;">${renderEvidence(a.evidence)}</div>` : ''}
        ${renderExcerpt(a.evidence)}
      </div>
    `).join('')
    : `<p class="muted">${esc(t('detector.no_alerts'))}</p>`;

  return `
    <h2><span class="dz-id">${esc(payload.id)}</span> ${esc(item.title || '')}</h2>
    <div class="subline">${subline}</div>
    ${counters}
    <p class="muted" style="margin-top:8px;font-size:12px;">
      ${esc(t('detector.run'))}: ${esc(t('detector.today'))} ${totals.today | 0}
      · ${esc(t('detector.week'))} ${totals.week | 0} · ${esc(t('detector.all'))} ${totals.all | 0}
      ${updated ? ` · ${esc(updated.slice(0, 16).replace('T', ' '))}` : ''}
    </p>
    <h3>${esc(t('detector.recent'))}</h3>
    ${list}
  `;
}

export function renderDarkZone(dz) {
  return `
    <h2><span class="dz-id">${dz.id}</span>${esc(dz.title)}</h2>
    ${renderStatusBlock(dz)}
    <div class="dz-body">${esc(dz.body_md)}</div>
    ${dz.files && dz.files.length ? `
      <h3 style="margin-top:20px;font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)">${esc(t('dz.refs.files'))}</h3>
      <div class="files-list">
        ${dz.files.map(f => `<span class="file-tag">${esc(f)}</span>`).join('')}
      </div>
    ` : ''}
    ${dz.file_lines && dz.file_lines.length ? `
      <h3 style="margin-top:16px;font-size:12px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)">${esc(t('dz.refs.lines'))}</h3>
      <div class="files-list">
        ${dz.file_lines.map(f => `<span class="file-tag">${esc(f)}</span>`).join('')}
      </div>
    ` : ''}
  `;
}
