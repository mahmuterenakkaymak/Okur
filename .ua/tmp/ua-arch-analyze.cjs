#!/usr/bin/env node
'use strict';
// Structural analyzer for architecture layer detection.
// Usage: node ua-arch-analyze.js <input.json> <output.json>

const fs = require('fs');

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('usage: node ua-arch-analyze.js <input.json> <output.json>');
  process.exit(1);
}

const raw = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const fileNodes = raw.fileNodes || [];
const importEdges = raw.importEdges || [];
const allEdges = raw.allEdges || [];

const nodeById = new Map(fileNodes.map(n => [n.id, n]));
const FILE_TYPES = new Set(['file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint']);

// ---------- A. Directory grouping ----------
function dirSegments(fp) {
  const parts = fp.split('/');
  return parts.slice(0, -1); // directory segments
}

let commonPrefix = null;
for (const n of fileNodes) {
  const segs = dirSegments(n.filePath);
  if (commonPrefix === null) { commonPrefix = segs; continue; }
  let i = 0;
  while (i < commonPrefix.length && i < segs.length && commonPrefix[i] === segs[i]) i++;
  commonPrefix = commonPrefix.slice(0, i);
}
if (commonPrefix === null) commonPrefix = [];

function groupKey(fp) {
  const segs = dirSegments(fp);
  const rest = segs.slice(commonPrefix.length);
  if (rest.length === 0) return 'root';
  return rest[0];
}

const flatStructure = fileNodes.every(n => dirSegments(n.filePath).length === 0);
const directoryGroups = {};

function flatGroupKey(n) {
  const f = n.filePath.toLowerCase();
  if (/\.(test|spec)\.[^.]+$/.test(f) || /(^|\/)test_[^/]+$/.test(f)) return 'test';
  if (/\.config\./.test(f)) return 'config';
  const ext = (f.match(/\.([a-z0-9]+)$/) || [, 'other'])[1];
  return ext;
}

for (const n of fileNodes) {
  const k = flatStructure ? flatGroupKey(n) : groupKey(n.filePath);
  (directoryGroups[k] = directoryGroups[k] || []).push(n.id);
}

// ---------- B. Node type grouping ----------
const nodeTypeGroups = {};
for (const n of fileNodes) (nodeTypeGroups[n.type] = nodeTypeGroups[n.type] || []).push(n.id);

// ---------- C. Import adjacency, fan-in / fan-out ----------
const fanIn = {}, fanOut = {};
const adj = new Map();
for (const e of importEdges) {
  if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
  fanOut[e.source] = (fanOut[e.source] || 0) + 1;
  fanIn[e.target] = (fanIn[e.target] || 0) + 1;
  if (!adj.has(e.source)) adj.set(e.source, new Set());
  adj.get(e.source).add(e.target);
}

// ---------- D. Cross-category dependency analysis ----------
const crossMap = new Map();
for (const e of allEdges) {
  const s = nodeById.get(e.source), t = nodeById.get(e.target);
  if (!s || !t) continue;
  const key = `${s.type}|${t.type}|${e.type}`;
  crossMap.set(key, (crossMap.get(key) || 0) + 1);
}
const crossCategoryEdges = [...crossMap.entries()].map(([k, count]) => {
  const [fromType, toType, edgeType] = k.split('|');
  return { fromType, toType, edgeType, count };
}).sort((a, b) => b.count - a.count);

// ---------- E. Inter-group import frequency ----------
const idToGroup = new Map();
for (const [g, ids] of Object.entries(directoryGroups)) for (const id of ids) idToGroup.set(id, g);

const interMap = new Map();
for (const e of importEdges) {
  const gs = idToGroup.get(e.source), gt = idToGroup.get(e.target);
  if (gs == null || gt == null || gs === gt) continue;
  const key = `${gs}|${gt}`;
  interMap.set(key, (interMap.get(key) || 0) + 1);
}
const interGroupImports = [...interMap.entries()].map(([k, count]) => {
  const [from, to] = k.split('|');
  return { from, to, count };
}).sort((a, b) => b.count - a.count);

// ---------- F. Intra-group import density ----------
const intraGroupDensity = {};
for (const g of Object.keys(directoryGroups)) {
  let internal = 0, total = 0;
  for (const e of importEdges) {
    const gs = idToGroup.get(e.source), gt = idToGroup.get(e.target);
    if (gs === g && gt === g) { internal++; total++; }
    else if (gs === g || gt === g) total++;
  }
  intraGroupDensity[g] = {
    internalEdges: internal,
    totalEdges: total,
    density: total ? +(internal / total).toFixed(3) : 0
  };
}

// ---------- G. Directory pattern matching ----------
const DIR_PATTERNS = {
  routes: 'api', api: 'api', controllers: 'api', endpoints: 'api', handlers: 'api', controller: 'api', routers: 'api', blueprints: 'api', serializers: 'api',
  services: 'service', core: 'service', lib: 'service', domain: 'service', logic: 'service', internal: 'service', composables: 'service', signals: 'service', mailers: 'service', jobs: 'service', channels: 'service',
  models: 'data', db: 'data', data: 'data', persistence: 'data', repository: 'data', entities: 'data', entity: 'data', migrations: 'data', sql: 'data', database: 'data',
  components: 'ui', views: 'ui', pages: 'ui', ui: 'ui', layouts: 'ui', screens: 'ui',
  middleware: 'middleware', plugins: 'middleware', interceptors: 'middleware', guards: 'middleware',
  utils: 'utility', helpers: 'utility', common: 'utility', shared: 'utility', tools: 'utility', pkg: 'utility', templatetags: 'utility',
  config: 'config', constants: 'config', env: 'config', settings: 'config', management: 'config',
  __tests__: 'test', test: 'test', tests: 'test', spec: 'test', specs: 'test',
  types: 'types', interfaces: 'types', schemas: 'types', contracts: 'types', dtos: 'types', dto: 'types', request: 'types', response: 'types', contract: 'types',
  hooks: 'hooks',
  store: 'state', state: 'state', reducers: 'state', actions: 'state', slices: 'state',
  assets: 'assets', static: 'assets', public: 'assets',
  cmd: 'entry', bin: 'entry',
  docs: 'documentation', documentation: 'documentation', wiki: 'documentation',
  deploy: 'infrastructure', deployment: 'infrastructure', infra: 'infrastructure', infrastructure: 'infrastructure', '.github': 'ci-cd', '.gitlab': 'ci-cd', '.circleci': 'ci-cd', k8s: 'infrastructure', kubernetes: 'infrastructure', helm: 'infrastructure', charts: 'infrastructure',
  terraform: 'infrastructure', tf: 'infrastructure', docker: 'infrastructure'
};

function dirPattern(dirName) {
  const d = dirName.toLowerCase();
  if (DIR_PATTERNS[d]) return DIR_PATTERNS[d];
  return 'unknown';
}
const patternMatches = {};
for (const g of Object.keys(directoryGroups)) patternMatches[g] = flatStructure ? 'unknown' : dirPattern(g);

// File-level pattern matches
const filePatterns = {};
for (const n of fileNodes) {
  const f = n.filePath, lf = f.toLowerCase(), base = f.split('/').pop();
  let label = null;
  if (/\.(test|spec)\.[^./]+\./.test('') ) {} // noop
  if (/\.(test|spec)\./.test(lf) || /(^|\/)test_[^/]+\.py$/.test(lf) || /_test\.go$/.test(lf) || /Test\.java$/.test(base) || /_spec\.rb$/.test(base) || /Test\.php$/.test(base) || /Tests\.cs$/.test(base)) label = 'test';
  else if (/\.d\.ts$/.test(lf)) label = 'types';
  else if (/(^|\/)(index\.tsx?|index\.js|__init__\.py)$/.test(lf) && f.split('/').length <= (commonPrefix.length + 2)) label = 'entry';
  else if (base === 'manage.py') label = 'entry';
  else if (/(_restart_app|tailscale_serve)\.ps1$/.test(base) || /(^|\/)(Dockerfile|Makefile)/.test(f) || /docker-compose\./.test(lf) || /(^|\/)Jenkinsfile$/.test(f)) label = 'infrastructure';
  else if (/\.(md|rst)$/.test(lf)) label = 'documentation';
  else if (/\.schema\.json$/.test(lf)) label = 'types';
  else if (/\.(sql)$/.test(lf)) label = 'data';
  else if (/(\.github\/workflows\/)/.test(lf) || lf === '.gitlab-ci.yml') label = 'ci-cd';
  else if (/(^|\/)run\.py$/.test(lf)) label = 'entry';
  else if (/(^|\/)(Cargo\.toml|go\.mod|Gemfile|pom\.xml|build\.gradle|composer\.json)$/.test(f)) label = 'config';
  if (label) filePatterns[n.id] = label;
}

// ---------- H. Deployment topology ----------
const paths = fileNodes.map(n => n.filePath);
const hasDockerfile = paths.some(p => /(^|\/)Dockerfile/.test(p));
const hasCompose = paths.some(p => /docker-compose\./.test(p));
const hasK8s = paths.some(p => /(^|\/)(k8s|kubernetes|helm|charts)(\/|$)/.test(p) || /\.ya?ml$/.test(p) && /k8s|deployment|service\./.test(p));
const hasTerraform = paths.some(p => /\.tf(vars)?$/.test(p));
const hasCI = paths.some(p => /\.github\/workflows\//.test(p) || /\.gitlab-ci\.yml$/.test(p) || /Jenkinsfile$/.test(p));
const infraFiles = paths.filter(p => /Dockerfile|docker-compose|\.tf(vars)?$|\.github\/workflows\/|\.gitlab-ci\.yml|Jenkinsfile|Makefile|\.ps1$/.test(p));
const deploymentTopology = { hasDockerfile, hasCompose, hasK8s, hasTerraform, hasCI, infraFiles };

// ---------- I. Data pipeline detection ----------
const schemaFiles = paths.filter(p => /\.schema\.(json|ya?ml)$|\.graphql$|\.gql$|\.proto$|\.prisma$/.test(p));
const migrationFiles = paths.filter(p => /(^|\/)migrations(\/|$)/.test(p) || /\.sql$/.test(p));
const dataModelFiles = fileNodes.filter(n =>
  /(^|\/)(models|entities|contract|db)(\.py|\/)/.test(n.filePath) ||
  /data-model/.test((n.tags || []).join(','))
).map(n => n.filePath);
const apiHandlerFiles = fileNodes.filter(n =>
  /(^|\/)routes[_\/]/.test(n.filePath) || /(^|\/)(routes|api|controllers)(\/|$)/.test(n.filePath) ||
  /api-handler/.test((n.tags || []).join(','))
).map(n => n.filePath);
const dataPipeline = { schemaFiles, migrationFiles, dataModelFiles, apiHandlerFiles };

// ---------- J. Documentation coverage ----------
const groupsWithDocsSet = new Set();
for (const n of fileNodes) if (n.type === 'document') groupsWithDocsSet.add(idToGroup.get(n.id));
const allGroups = Object.keys(directoryGroups);
const docCoverage = {
  groupsWithDocs: groupsWithDocsSet.size,
  totalGroups: allGroups.length,
  coverageRatio: allGroups.length ? +(groupsWithDocsSet.size / allGroups.length).toFixed(2) : 0,
  undocumentedGroups: allGroups.filter(g => !groupsWithDocsSet.has(g))
};

// ---------- K. Dependency direction ----------
const pairSeen = new Set();
const dependencyDirection = [];
for (const { from, to, count } of interGroupImports) {
  const key = [from, to].sort().join('|');
  if (pairSeen.has(key)) continue;
  pairSeen.add(key);
  const rev = interMap.get(`${to}|${from}`) || 0;
  if (count >= rev) dependencyDirection.push({ dependent: from, dependsOn: to, forward: count, backward: rev });
  else dependencyDirection.push({ dependent: to, dependsOn: from, forward: rev, backward: count });
}

// ---------- Stats & fan ----------
const filesPerGroup = {};
for (const [g, ids] of Object.entries(directoryGroups)) filesPerGroup[g] = ids.length;
const nodeTypeCounts = {};
for (const [t, ids] of Object.entries(nodeTypeGroups)) nodeTypeCounts[t] = ids.length;

const results = {
  scriptCompleted: true,
  commonPrefix: commonPrefix.join('/'),
  flatStructure,
  directoryGroups,
  nodeTypeGroups,
  crossCategoryEdges,
  interGroupImports,
  intraGroupDensity,
  patternMatches,
  filePatterns,
  deploymentTopology,
  dataPipeline,
  docCoverage,
  dependencyDirection,
  fileStats: { totalFileNodes: fileNodes.length, filesPerGroup, nodeTypeCounts },
  fileFanIn: fanIn,
  fileFanOut: fanOut
};

fs.writeFileSync(outPath, JSON.stringify(results, null, 2));
process.exit(0);
