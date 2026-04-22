// Side panel renderer — given a datum and the full snapshot, builds HTML.

import { t, tField } from './i18n.js?v=phase1.9';

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function dzChips(ids, onClick) {
  if (!ids || !ids.length) return '';
  return `<div class="badges">
    ${ids.map(id => `<span class="chip darkzone" data-goto-dz="${id}">${id}</span>`).join('')}
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
    ${dzChips(node.dark_zones)}
    ${node.description ? `<h3>${esc(t('panel.description'))}</h3><p>${esc(node.description)}</p>` : ''}
    ${moduleRow}
    ${ownership}
    ${dark.length ? `
      <h3>${esc(t('panel.weaknesses'))} (${dark.length})</h3>
      ${dark.map(d => `
        <div style="margin-bottom:10px;">
          <div style="font-weight:600;color:var(--accent-2);">
            <span class="chip darkzone" data-goto-dz="${d.id}">${d.id}</span>
            ${esc(d.title)}
          </div>
          <p style="margin-top:4px;font-size:12.5px;color:var(--muted);">${esc(d.body_md.slice(0, 220))}${d.body_md.length > 220 ? '…' : ''}</p>
        </div>
      `).join('')}
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
    ${dzChips(tool.dark_zone_ids)}
    <h3>${esc(t('panel.description'))}</h3>
    <p>${esc(tool.description) || `<span class="muted">${esc(t('panel.no_description'))}</span>`}</p>
    ${hasParams ? `
      <h3>${esc(t('panel.parameters'))}</h3>
      <pre>${esc(JSON.stringify(params, null, 2))}</pre>
    ` : `<h3>${esc(t('panel.parameters'))}</h3><p class="muted">${esc(t('panel.none'))}</p>`}
  `;
}

export function renderDarkZone(dz) {
  return `
    <h2><span class="dz-id">${dz.id}</span>${esc(dz.title)}</h2>
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
