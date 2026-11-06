import fs from 'fs';
import path from 'path';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const UA = path.join(R, '.ua');

// 1. canonical file set from immutable slices
const batches = [];
const canon = new Map();
for (let i = 1; i <= 7; i++) {
  const b = JSON.parse(fs.readFileSync(path.join(UA, `tmp/batch-input-${i}.json`), 'utf8'));
  batches.push(b);
  for (const f of b.files) canon.set(f.path, f);
}

// 2. importMap: filter current 106-entry output down to canonical 62, drop .ua-run2 targets
const im = JSON.parse(fs.readFileSync(path.join(UA, 'tmp/im-output.json'), 'utf8')).importMap;
const importMap = {};
for (const p of canon.keys()) importMap[p] = (im[p] || []).filter((t) => !String(t).startsWith('.ua-run2/') && !String(t).startsWith('.ua/'));

// 3. counts
const byCategory = {};
const byLanguage = {};
for (const f of canon.values()) {
  byCategory[f.fileCategory] = (byCategory[f.fileCategory] || 0) + 1;
  byLanguage[f.language] = (byLanguage[f.language] || 0) + 1;
}

const scan = {
  name: 'ocr-app',
  description:
    'Yerel çalışan (local-first) fiş OCR servisi: sahadaki çalışanın telefonundan yüklediği fiş fotoğrafını üç aşamalı bir kuyruk hattından geçirir — llama.cpp üzerinde PaddleOCR-VL ile metin tanıma, Strata/Unsloth Studio ile sözleşme v1 JSON yapılandırması ve saf Python ile deterministik tutar doğrulaması. FastAPI (:8090) saha PWA, yönetici paneli ve /v1 entegrasyon API\'ini sunar; veriler makineden çıkmaz (KVKK).',
  languages: Object.keys(byLanguage).sort(),
  frameworks: ['FastAPI', 'Uvicorn', 'Pydantic', 'HTTPX', 'pytest', 'jsonschema', 'openpyxl', 'SQLite', 'PWA'],
  files: [...canon.values()],
  totalFiles: canon.size,
  filteredByIgnore: 99,
  estimatedComplexity: 'moderate',
  importMap,
};
if (scan.totalFiles !== 62) throw new Error('expected 62 canonical files, got ' + scan.totalFiles);
const stats = { filesScanned: 62, byCategory, byLanguage };
const batchOut = { totalBatches: 7, totalFiles: 62, stats: { batches: batches.map((b) => b.batchIndex) }, batches };
for (const [name, obj] of [['scan-result.json', scan], ['batches.json', batchOut]]) {
  fs.writeFileSync(path.join(UA, 'intermediate', name), JSON.stringify(obj, null, 2));
  fs.writeFileSync(path.join(UA, 'tmp', 'canonical-' + name), JSON.stringify(obj, null, 2));
}

// 4. verify assembled graph untouched
const g = JSON.parse(fs.readFileSync(path.join(UA, 'intermediate/assembled-graph.json'), 'utf8'));
const fileTypes = new Set(['file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint']);
const fileNodes = g.nodes.filter((n) => fileTypes.has(n.type));
const bad = fileNodes.filter((n) => !canon.has(n.filePath));
console.log('scan restored: 62 files | graph nodes:', g.nodes.length, 'edges:', g.edges.length, '| file-level nodes:', fileNodes.length, '| out-of-scope:', bad.length);
if (g.nodes.length !== 243 || g.edges.length !== 659 || fileNodes.length !== 62 || bad.length) {
  console.log('OUT-OF-SCOPE:', bad.slice(0, 10).map((n) => n.filePath));
  throw new Error('assembled-graph integrity check FAILED — do not proceed');
}
console.log('CANONICAL_OK');
