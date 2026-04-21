// Cytoscape helpers — thin wrapper, no state.
// Converts architecture.json topology nodes+edges to Cytoscape elements.

const NODE_COLOR = {
  process: '#74b9ff',
  external: '#636e72',
  infra: '#00b894',
  module: '#6c5ce7',
  file_md: '#fdcb6e',
  file_dir: '#fdcb6e',
  logfile: '#a29bfe',
  state_json: '#55efc4',
  chromadb: '#fd79a8',
};

const LAYER_HEIGHT = {
  top: 0,
  middle: 400,
  bottom: 900,
};

export function buildElements(nodes, edges, opts = {}) {
  const onlyKinds = opts.onlyKinds; // optional Set
  const onlyIds = opts.onlyIds;     // optional Set
  const dzMap = opts.dzMap || new Map();

  const filteredNodes = nodes.filter(n => {
    if (onlyIds && !onlyIds.has(n.id)) return false;
    if (onlyKinds && !onlyKinds.has(n.kind) && !onlyKinds.has(n.layer)) return false;
    return true;
  });

  const keepIds = new Set(filteredNodes.map(n => n.id));

  const els = [];
  for (const n of filteredNodes) {
    const hasDZ = (n.dark_zone_ids || []).length > 0;
    els.push({
      group: 'nodes',
      data: {
        id: n.id,
        label: n.label,
        kind: n.kind,
        layer: n.layer,
        path: n.path || '',
        loc: n.loc || 0,
        description: n.description || '',
        dark_zones: n.dark_zone_ids || [],
        has_dz: hasDZ,
        color: NODE_COLOR[n.kind] || '#8b8fa3',
      },
      classes: [`layer-${n.layer}`, `kind-${n.kind}`, hasDZ ? 'has-dz' : ''].filter(Boolean).join(' '),
    });
  }

  for (const e of edges) {
    if (!keepIds.has(e.source) || !keepIds.has(e.target)) continue;
    els.push({
      group: 'edges',
      data: {
        id: `${e.source}->${e.target}-${Math.random().toString(36).slice(2,7)}`,
        source: e.source,
        target: e.target,
        label: e.label || '',
        kind: e.kind,
        style: e.style || 'solid',
      },
      classes: `edge-${e.style || 'solid'}`,
    });
  }
  return els;
}

export function defaultStyle() {
  return [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        'label': 'data(label)',
        'color': '#e1e4ed',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': 11,
        'font-weight': 500,
        'text-wrap': 'wrap',
        'text-max-width': 130,
        'width': 140,
        'height': 40,
        'shape': 'rectangle', 'corner-radius': 6,
        'border-width': 1,
        'border-color': '#2a2d3a',
        'text-outline-color': '#0f1117',
        'text-outline-width': 2,
      },
    },
    {
      selector: 'node.kind-external',
      style: {
        'shape': 'diamond',
        'width': 130,
        'height': 70,
      },
    },
    {
      selector: 'node.kind-chromadb',
      style: {
        'shape': 'ellipse',
        'width': 150,
        'height': 42,
      },
    },
    {
      selector: 'node.kind-state_json, node.kind-logfile, node.kind-file_md, node.kind-file_dir',
      style: {
        'shape': 'rectangle', 'corner-radius': 6,
        'width': 130,
        'height': 34,
        'font-size': 10,
      },
    },
    {
      selector: 'node.layer-top',
      style: { 'width': 160, 'height': 48, 'font-size': 12, 'font-weight': 700 },
    },
    {
      selector: 'node.has-dz',
      style: {
        'border-width': 2,
        'border-color': '#a29bfe',
        'border-style': 'solid',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': '#fdcb6e',
        'overlay-color': '#fdcb6e',
        'overlay-opacity': 0.15,
      },
    },
    {
      selector: 'node.dim',
      style: { 'opacity': 0.18 },
    },
    {
      selector: 'node.hit',
      style: {
        'border-width': 3,
        'border-color': '#fdcb6e',
      },
    },

    {
      selector: 'edge',
      style: {
        'width': 1.4,
        'line-color': '#3b3e4e',
        'target-arrow-color': '#3b3e4e',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'arrow-scale': 0.9,
        'font-size': 9,
        'color': '#8b8fa3',
        'text-background-color': '#0f1117',
        'text-background-opacity': 0.85,
        'text-background-padding': 2,
        'label': '',
      },
    },
    {
      selector: 'edge.edge-dashed',
      style: { 'line-style': 'dashed' },
    },
    {
      selector: 'edge.edge-unsafe',
      style: {
        'line-color': '#e17055',
        'target-arrow-color': '#e17055',
        'width': 2,
      },
    },
    {
      selector: 'edge.edge-conditional',
      style: {
        'line-style': 'dashed',
        'line-color': '#fdcb6e',
        'target-arrow-color': '#fdcb6e',
      },
    },
    {
      selector: 'edge.highlighted',
      style: {
        'line-color': '#fdcb6e',
        'target-arrow-color': '#fdcb6e',
        'width': 2.5,
        'label': 'data(label)',
        'z-index': 100,
      },
    },
    {
      selector: 'edge.dim',
      style: { 'opacity': 0.1 },
    },
  ];
}

export function layeredLayout() {
  // Kept for reference but the Overview uses a preset layout (see presetByLayer).
  return {
    name: 'dagre',
    rankDir: 'TB',
    nodeSep: 48,
    rankSep: 110,
    edgeSep: 18,
    ranker: 'longest-path',
    animate: false,
    fit: true,
    padding: 30,
  };
}

/**
 * Build a preset Cytoscape layout that places nodes on three horizontal layers
 * (top/middle/bottom). Within each layer we do a simple column-major grid.
 */
export function presetByLayer(nodes, opts = {}) {
  const layerY = { top: 60, middle: 360, bottom: 720 };
  const layerWidth = opts.layerWidth || 2400;
  const padX = 40;

  // Group by layer
  const byLayer = { top: [], middle: [], bottom: [] };
  for (const n of nodes) {
    (byLayer[n.layer] || byLayer.middle).push(n);
  }

  const positions = {};

  // Custom ordering helpers
  const order = {
    top: ['telegram_api', 'colab_launcher', 'worker_pool', 'consciousness_thread',
          'fs_data', 'docker_chromadb', 'docker_postgres', 'docker_redis', 'openrouter'],
    middle: ['agent', 'context', 'memory', 'loop', 'llm', 'inner_critic',
             'skill_manager', 'experiment_engine', 'pattern_detector',
             'consciousness', 'strategic_planner', 'self_evolution', 'budget',
             'owner_inject', 'registry', 'workers', 'queue', 'events',
             'telegram', 'state', 'git_ops'],
    bottom: [
      'mem_scratchpad', 'mem_identity', 'mem_wisdom', 'mem_knowledge', 'mem_episodic',
      'log_chat', 'log_events', 'log_supervisor', 'log_tools', 'log_progress',
      'file_task_results',
      'state_main', 'state_queue', 'state_budget', 'state_directives',
      'state_commitments', 'state_experiments', 'state_reflected',
      'state_consciousness', 'state_cooldown',
      'chroma_episodes', 'chroma_skills', 'chroma_history',
    ],
  };

  for (const layer of ['top', 'middle', 'bottom']) {
    const wanted = order[layer];
    const present = new Map(byLayer[layer].map(n => [n.id, n]));
    const ordered = [];
    for (const id of wanted) {
      if (present.has(id)) { ordered.push(present.get(id)); present.delete(id); }
    }
    // Append any layer nodes not in the wanted list (e.g. snapshot added new nodes)
    for (const n of present.values()) ordered.push(n);

    const N = ordered.length;
    if (N === 0) continue;
    const spacing = Math.max(160, (layerWidth - 2 * padX) / Math.max(1, N - 1));
    ordered.forEach((n, i) => {
      // Offset alternating rows slightly in bottom layer so labels don't collide
      let y = layerY[layer];
      if (layer === 'bottom' && i % 2 === 1) y += 56;
      positions[n.id] = { x: padX + i * spacing, y };
    });
  }

  return {
    name: 'preset',
    positions: positions,  // keyed by node id
    fit: true,
    padding: 40,
    animate: false,
  };
}
