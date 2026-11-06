import fs from 'fs';
const g = JSON.parse(fs.readFileSync('.ua/intermediate/batch-6.json', 'utf8'));
const data = JSON.parse(fs.readFileSync('.ua/tmp/dispatch/batch-6-data.json', 'utf8'));
const bid = data.batchImportData;
const nm = data.neighborMap;
const ids = new Set(g.nodes.map((n) => n.id));
console.log('nodes', g.nodes.length, 'edges', g.edges.length);

const seen = new Set();
const dup = [];
for (const n of g.nodes) {
  if (seen.has(n.id)) dup.push(n.id);
  seen.add(n.id);
}
console.log('dupIds', JSON.stringify(dup));

const bad = [];
for (const n of g.nodes) {
  if (!n.id || !n.type || !n.name || !n.summary || !n.tags || !n.complexity) bad.push(n.id + ':missing-field');
  if (n.tags && (n.tags.length < 3 || n.tags.length > 5)) bad.push(n.id + ':tags=' + n.tags.length);
  if (!['simple', 'moderate', 'complex'].includes(n.complexity)) bad.push(n.id + ':complexity');
  if ((n.type === 'function' || n.type === 'class') && !n.lineRange) bad.push(n.id + ':no-lineRange');
  if (!/^(file|function|class|config|document|service|table|endpoint|pipeline|schema|resource):/.test(n.id)) bad.push(n.id + ':bad-prefix');
}
console.log('nodeIssues', JSON.stringify(bad));
console.log('selfEdges', JSON.stringify(g.edges.filter((e) => e.source === e.target).map((e) => e.source)));

const want = Object.values(bid).reduce((a, b) => a + b.length, 0);
const got = g.edges.filter((e) => e.type === 'imports').length;
console.log('imports expected', want, 'got', got);
for (const [f, list] of Object.entries(bid)) {
  const c = g.edges.filter((e) => e.type === 'imports' && e.source === 'file:' + f).length;
  if (c !== list.length) console.log('  MISMATCH', f, c, '!=', list.length);
}

const validTypes = new Set(['contains', 'imports', 'calls', 'inherits', 'implements', 'exports', 'depends_on', 'tested_by', 'configures', 'documents', 'deploys', 'migrates', 'triggers', 'defines_schema', 'serves', 'provisions', 'routes', 'related']);
console.log('badEdgeTypes', JSON.stringify([...new Set(g.edges.filter((e) => !validTypes.has(e.type)).map((e) => e.type))]));
const W = { contains: 1.0, imports: 0.7, calls: 0.8, exports: 0.8, tested_by: 0.5, depends_on: 0.6 };
console.log('badWeights', JSON.stringify(g.edges.filter((e) => W[e.type] !== undefined && e.weight !== W[e.type]).map((e) => e.type + ':' + e.weight)));
console.log('badDirection', g.edges.filter((e) => e.direction !== 'forward').length);

const knownFiles = new Set(Object.keys(bid));
const knownSymbols = new Map();
for (const f of Object.keys(nm)) {
  for (const n of nm[f] || []) {
    knownFiles.add(n.path);
    if (!knownSymbols.has(n.path)) knownSymbols.set(n.path, new Set());
    for (const s of n.symbols || []) knownSymbols.get(n.path).add(s);
  }
}
const dangling = [];
for (const e of g.edges) {
  for (const ref of [e.source, e.target]) {
    if (ids.has(ref)) continue;
    const m = /^(file|function|class):(.+)$/.exec(ref);
    if (!m) { dangling.push(ref + ' (unparsed, edge ' + e.type + ')'); continue; }
    const [, pref, rest] = m;
    if (pref === 'file') {
      if (!knownFiles.has(rest)) dangling.push(ref + ' (file unknown, edge ' + e.type + ')');
    } else {
      const idx = rest.lastIndexOf(':');
      const owner = rest.slice(0, idx);
      const sym = rest.slice(idx + 1);
      if (!knownFiles.has(owner)) dangling.push(ref + ' (owner unknown, edge ' + e.type + ')');
      else if (!(knownSymbols.get(owner) || new Set()).has(sym)) dangling.push(ref + ' (symbol not in neighborMap, edge ' + e.type + ')');
    }
  }
}
console.log('dangling', JSON.stringify([...new Set(dangling)], null, 1));

const byType = {};
for (const e of g.edges) byType[e.type] = (byType[e.type] || 0) + 1;
console.log('edgeTypes', JSON.stringify(byType));
const nt = {};
for (const n of g.nodes) nt[n.type] = (nt[n.type] || 0) + 1;
console.log('nodeTypes', JSON.stringify(nt));
// every batch file has exactly one file node
const fileNodes = g.nodes.filter((n) => n.type === 'file').map((n) => n.filePath).sort();
console.log('fileNodes', JSON.stringify(fileNodes));
// nodes whose filePath not in batch
const batchFiles = new Set(Object.keys(bid));
console.log('orphanNodes', JSON.stringify(g.nodes.filter((n) => n.filePath && !batchFiles.has(n.filePath)).map((n) => n.id)));
