// Tour topology analyzer: fan-in/out, entry points, BFS, non-code inventory,
// clusters, layers, node summary index.
// Usage: node ua-tour-analyze.js <input.json> <output.json>
const fs = require('fs');

const ENTRY_NAMES = new Set(['index.ts', 'index.js', 'main.ts', 'main.js', 'app.ts', 'app.js',
  'server.ts', 'server.js', 'mod.rs', 'main.go', 'main.py', 'main.rs', 'manage.py', 'app.py',
  'wsgi.py', 'asgi.py', 'run.py', '__main__.py', 'Application.java', 'Main.java', 'Program.cs',
  'config.ru', 'index.php', 'App.swift', 'Application.kt', 'main.cpp', 'main.c']);

function main() {
  const [inPath, outPath] = process.argv.slice(2);
  if (!inPath || !outPath) throw new Error('usage: node ua-tour-analyze.js <in.json> <out.json>');
  const input = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  const nodes = input.nodes || [];
  const edges = input.edges || [];
  const layers = input.layers || [];

  const byId = new Map(nodes.map(n => [n.id, n]));
  // Only count edges whose both endpoints exist in the node set.
  const live = edges.filter(e => byId.has(e.source) && byId.has(e.target));

  // ---------- A. fan-in / B. fan-out ----------
  const fanIn = new Map(nodes.map(n => [n.id, 0]));
  const fanOut = new Map(nodes.map(n => [n.id, 0]));
  for (const e of live) {
    fanIn.set(e.target, fanIn.get(e.target) + 1);
    fanOut.set(e.source, fanOut.get(e.source) + 1);
  }
  const nm = id => ({ name: (byId.get(id) || {}).name, type: (byId.get(id) || {}).type });
  const fanInRanking = [...fanIn.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)
    .map(([id, v]) => ({ id, fanIn: v, ...nm(id) }));
  const fanOutRanking = [...fanOut.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)
    .map(([id, v]) => ({ id, fanOut: v, ...nm(id) }));

  // ---------- C. entry point candidates ----------
  const fanOutVals = [...fanOut.values()].sort((a, b) => a - b);
  const fanInVals = [...fanIn.values()].sort((a, b) => a - b);
  const pct = (arr, p) => arr.length ? arr[Math.min(arr.length - 1, Math.floor(p * (arr.length - 1)))] : 0;
  const fanOutTop10 = pct(fanOutVals, 0.9);
  const fanInBottom25 = pct(fanInVals, 0.25);

  const depthOf = fp => (fp || '').split('/').filter(Boolean).length;
  const scored = nodes.map(n => {
    let score = 0; const why = [];
    const fp = n.filePath || '';
    const base = n.name || '';
    const isDoc = n.type === 'document' || /\.md$/i.test(fp);
    if (isDoc) {
      if (base === 'README.md' && depthOf(fp) === 1) { score += 5; why.push('root README'); }
      else if (/\.md$/i.test(fp) && depthOf(fp) === 1) { score += 2; why.push('root markdown'); }
    } else {
      if (ENTRY_NAMES.has(base)) { score += 3; why.push('entry filename:' + base); }
      if (depthOf(fp) <= 2) { score += 1; why.push('shallow path'); }
      if (fanOut.get(n.id) >= fanOutTop10 && fanOutTop10 > 0) { score += 1; why.push('high fan-out'); }
      if (fanIn.get(n.id) <= fanInBottom25) { score += 1; why.push('low fan-in'); }
    }
    return { id: n.id, score, name: n.name, type: n.type, filePath: n.filePath,
      summary: n.summary || '', signals: why };
  }).filter(x => x.score > 0).sort((a, b) => b.score - a.score || (a.name || '').localeCompare(b.name || ''));

  // ---------- D. BFS from top CODE entry point ----------
  const CODE_TYPES = new Set(['file', 'config', 'schema']);
  const codeCandidates = scored.filter(s => CODE_TYPES.has(s.type) || !/\.md$/i.test(s.filePath || ''));
  const start = codeCandidates.length ? codeCandidates[0].id
    : (nodes.find(n => ENTRY_NAMES.has(n.name)) || {}).id;
  const TRAVEL = new Set(['imports', 'calls']);
  const adj = new Map();
  for (const e of live) {
    if (!TRAVEL.has(e.type)) continue;
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source).push(e.target);
  }
  const order = [], depthMap = {};
  if (start) {
    const seen = new Set([start]); const q = [[start, 0]];
    order.push(start); depthMap[start] = 0;
    while (q.length) {
      const [cur, d] = q.shift();
      for (const nxt of (adj.get(cur) || [])) {
        if (seen.has(nxt)) continue;
        seen.add(nxt); depthMap[nxt] = d + 1; order.push(nxt); q.push([nxt, d + 1]);
      }
    }
  }
  const byDepth = {};
  for (const [id, d] of Object.entries(depthMap)) (byDepth[d] = byDepth[d] || []).push(id);

  // ---------- E. non-code inventory ----------
  const pick = types => nodes.filter(n => types.has(n.type))
    .map(n => ({ id: n.id, name: n.name, type: n.type, filePath: n.filePath, summary: n.summary || '' }));
  const nonCodeFiles = {
    documentation: pick(new Set(['document'])),
    infrastructure: pick(new Set(['service', 'pipeline', 'resource'])),
    data: pick(new Set(['table', 'schema', 'endpoint'])),
    config: pick(new Set(['config'])),
  };

  // ---------- F. tightly coupled clusters ----------
  const pairKey = (a, b) => [a, b].sort().join('||');
  const directed = new Set(live.map(e => e.source + '>' + e.target));
  const relCount = new Map();
  const bidir = new Set();
  for (const e of live) {
    const pk = pairKey(e.source, e.target);
    relCount.set(pk, (relCount.get(pk) || 0) + 1);
    if (directed.has(e.target + '>' + e.source)) bidir.add(pk);
  }
  const seeds = [...bidir].map(pk => pk.split('||'));
  // seed score = edges between the pair (both directions)
  const pairEdgeCount = (a, b) => (directed.has(a + '>' + b) ? 1 : 0) + (directed.has(b + '>' + a) ? 1 : 0);
  seeds.sort((x, y) => pairEdgeCount(y[0], y[1]) - pairEdgeCount(x[0], x[1]));
  const clusters = [];
  const used = new Set();
  for (const seed of seeds) {
    const members = new Set(seed);
    // expand: add nodes connected (either direction, any live edge) to >=2 members
    let grew = true;
    while (grew && members.size < 5) {
      grew = false;
      const cands = new Map();
      for (const e of live) {
        if (members.has(e.source) && !members.has(e.target)) cands.set(e.target, (cands.get(e.target) || 0) + 1);
        if (members.has(e.target) && !members.has(e.source)) cands.set(e.source, (cands.get(e.source) || 0) + 1);
      }
      const best = [...cands.entries()].filter(([, c]) => c >= 2)
        .sort((a, b) => b[1] - a[1])[0];
      if (best && !used.has(best[0])) { members.add(best[0]); grew = true; }
    }
    const arr = [...members];
    if (arr.some(m => used.has(m))) continue;
    let ec = 0;
    for (let i = 0; i < arr.length; i++) for (let j = 0; j < arr.length; j++) {
      if (i !== j && directed.has(arr[i] + '>' + arr[j])) ec++;
    }
    if (ec < 2) continue;
    arr.forEach(m => used.add(m));
    clusters.push({ nodes: arr, edgeCount: ec,
      names: arr.map(id => (byId.get(id) || {}).name).filter(Boolean) });
  }
  clusters.sort((a, b) => b.edgeCount - a.edgeCount);

  // ---------- G. layers ----------
  const layerOut = {
    count: layers.length,
    list: layers.map(l => ({ id: l.id, name: l.name, description: l.description })),
  };
  if (input.layerMembership) {
    layerOut.membership = input.layerMembership;
  }

  // ---------- H. node summary index ----------
  const nodeSummaryIndex = {};
  for (const n of nodes) {
    nodeSummaryIndex[n.id] = { name: n.name, type: n.type, filePath: n.filePath,
      summary: n.summary || '', tags: n.tags || [], fanIn: fanIn.get(n.id), fanOut: fanOut.get(n.id) };
  }

  fs.writeFileSync(outPath, JSON.stringify({
    scriptCompleted: true,
    entryPointCandidates: scored.slice(0, 5),
    entryPointShortlist: scored.slice(0, 12),
    fanInRanking, fanOutRanking,
    bfsTraversal: { startNode: start || null, order, depthMap, byDepth },
    nonCodeFiles,
    clusters: clusters.slice(0, 10),
    bidirectionalPairs: [...bidir].map(pk => pk.split('||')),
    layers: layerOut,
    nodeSummaryIndex,
    totals: { codeFiles: nodes.filter(n => n.type === 'file').length },
    totalNodes: nodes.length,
    totalEdges: edges.length,
    liveEdges: live.length,
  }, null, 2), 'utf8');
  console.log('ok: nodes=' + nodes.length + ' edges=' + edges.length + ' live=' + live.length +
    ' bfsReached=' + order.length + ' clusters=' + Math.min(clusters.length, 10));
}

try { main(); } catch (e) { console.error(e && e.stack || String(e)); process.exit(1); }
