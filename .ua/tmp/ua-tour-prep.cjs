// Prepares tour-analysis input: file-level nodes only, with function/class edge
// endpoints rolled up to their containing file so fan-in/out is meaningful.
const fs = require('fs');
const path = require('path');

const ROOT = 'C:/Users/PC/Documents/GitHub/ocr-app';
const GRAPH = path.join(ROOT, '.ua/tmp/assembled-graph.merged-backup.json');
const LAYERS = path.join(ROOT, '.ua/intermediate/layers.json');
const OUT = path.join(ROOT, '.ua/tmp/ua-tour-input.json');

const g = JSON.parse(fs.readFileSync(GRAPH, 'utf8'));
const layers = JSON.parse(fs.readFileSync(LAYERS, 'utf8'));

const FILE_TYPES = new Set(['file', 'config', 'document', 'schema']);
const fileNodes = g.nodes.filter(n => FILE_TYPES.has(n.type));
const fileIds = new Set(fileNodes.map(n => n.id));

// Map any node id (function:/class:) to its containing file via the `contains` edges.
const parent = new Map();
for (const e of g.edges) {
  if (e.type === 'contains' && fileIds.has(e.source)) {
    if (!parent.has(e.target)) parent.set(e.target, e.source);
  }
}
// Fallback: id prefix convention "file:app/x.py:Sym" / "function:app/x.py:Sym"
function toFile(id) {
  if (fileIds.has(id)) return id;
  if (parent.has(id)) return parent.get(id);
  const m = /^(?:file|function|class|document|config|schema|service|pipeline|table|resource|endpoint):(.+?)(?::[^:]+)*$/.exec(id);
  if (m) {
    const cand = 'file:' + m[1];
    if (fileIds.has(cand)) return cand;
  }
  return null;
}

const seen = new Set();
const edges = [];
let droppedSelf = 0, droppedDangling = 0;
for (const e of g.edges) {
  if (e.type === 'contains' || e.type === 'exports') continue; // purely intra-file structure
  const s = toFile(e.source), t = toFile(e.target);
  if (!s || !t) { droppedDangling++; continue; }
  if (s === t) { droppedSelf++; continue; }
  const key = s + '|' + t + '|' + e.type;
  if (seen.has(key)) continue;
  seen.add(key);
  edges.push({ source: s, target: t, type: e.type });
}

// layers -> {id,name,description} only (spec), but keep membership separately for our own use
const layerOut = layers.map(l => ({ id: l.id, name: l.name, description: l.description }));
const layerMembership = {};
for (const l of layers) layerMembership[l.id] = l.nodeIds || [];

fs.writeFileSync(OUT, JSON.stringify({
  nodes: fileNodes, edges, layers: layerOut, layerMembership,
  _raw: { graphNodes: g.nodes.length, graphEdges: g.edges.length, fileNodes: fileNodes.length,
          rolledEdges: edges.length, droppedSelf, droppedDangling }
}, null, 2), 'utf8');

console.log('file nodes:', fileNodes.length, '| rolled edges:', edges.length,
  '| dropped self:', droppedSelf, '| dropped dangling:', droppedDangling);
