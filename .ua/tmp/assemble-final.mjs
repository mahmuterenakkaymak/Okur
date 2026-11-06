import fs from 'fs';
import path from 'path';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const UA = path.join(R, '.ua');
const read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));

const g = read(path.join(UA, 'tmp/assembled-graph.merged-backup.json'));
const layers = read(path.join(UA, 'intermediate/layers.json'));
let tour = read(path.join(UA, 'intermediate/tour.json'));
if (!Array.isArray(tour)) tour = tour.steps || tour.tour;
const ids = new Set(g.nodes.map((n) => n.id));
const known = ['file:', 'config:', 'document:', 'service:', 'pipeline:', 'table:', 'schema:', 'resource:', 'endpoint:'];
tour = tour
  .map((s) => {
    const step = { ...s };
    if (step.nodesToInspect && !step.nodeIds) step.nodeIds = step.nodesToInspect;
    if (step.whyItMatters && !step.description) step.description = step.whyItMatters;
    delete step.nodesToInspect; delete step.whyItMatters;
    step.nodeIds = (step.nodeIds || [])
      .map((x) => (typeof x === 'string' ? x : x.id))
      .map((x) => (known.some((p) => x.startsWith(p)) ? x : 'file:' + x))
      .filter((x) => ids.has(x));
    return step;
  })
  .sort((a, b) => a.order - b.order);

const scan = read(path.join(UA, 'tmp/canonical-scan-result.json'));
const graph = {
  version: '1.0.0',
  project: {
    name: scan.name,
    languages: scan.languages,
    frameworks: scan.frameworks,
    description: scan.description,
    analyzedAt: new Date().toISOString(),
    gitCommitHash: 'e6171a36edd2a2ef081d20a8be760a876be025d1',
  },
  nodes: g.nodes,
  edges: g.edges,
  layers,
  tour,
};
const out = JSON.stringify(graph, null, 2);
fs.writeFileSync(path.join(UA, 'intermediate/final-graph.json'), out);
fs.writeFileSync(path.join(UA, 'tmp/final-graph.snapshot.json'), out);
console.log('assembled: nodes', graph.nodes.length, 'edges', graph.edges.length, 'layers', layers.length, 'tour', tour.length, '| tour nodes max order', tour[tour.length - 1]?.order);
