import fs from 'fs';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const bb = JSON.parse(fs.readFileSync(R + '/.ua-run2/batches.json', 'utf8'));
const byIdx = {};
for (const x of bb.batches) byIdx[x.batchIndex] = new Set(x.files.map(f => f.path));
const shardRe = /^batch-(\d+)(?:-part-(\d+))?\.json$/;
const isMine = (file, json) => {
  const m = file.match(shardRe);
  if (!m) return false;
  const set = byIdx[+m[1]];
  if (!set) return false;
  return (json.nodes || []).every(n => !n.filePath || set.has(n.filePath));
};
const dirs = ['/.ua-run2', '/.ua/tmp/shards', '/.ua/intermediate'];
const chosen = {}; // filename -> srcpath
for (const dir of dirs) {
  if (!fs.existsSync(R + dir)) continue;
  for (const f of fs.readdirSync(R + dir)) {
    if (!shardRe.test(f) || chosen[f]) continue;
    try {
      const j = JSON.parse(fs.readFileSync(R + dir + '/' + f, 'utf8'));
      if (isMine(f, j)) chosen[f] = R + dir + '/' + f;
    } catch {}
  }
}
// drop foreign shards from intermediate
for (const f of fs.readdirSync(R + '/.ua/intermediate')) {
  if (!shardRe.test(f)) continue;
  if (chosen[f]) { fs.copyFileSync(chosen[f], R + '/.ua/intermediate/' + f); }
  else fs.renameSync(R + '/.ua/intermediate/' + f, R + '/.ua/tmp/peer-backup-1793967395/dropped__' + f);
}
const have = new Set();
for (const f of Object.keys(chosen)) have.add(+f.match(shardRe)[1]);
const missing = [];
for (let i = 1; i <= 12; i++) if (!have.has(i)) missing.push(i);
console.log('covered batches:', [...have].sort((a, b) => a - b).join(','));
console.log('MISSING batches:', missing.join(',') || 'none');
console.log('intermediate shards:', fs.readdirSync(R + '/.ua/intermediate').filter(f => shardRe.test(f)).sort().join(' '));
