import fs from 'fs';
import path from 'path';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const scanPath = path.join(R, '.ua/intermediate/scan-result.json');
const s = JSON.parse(fs.readFileSync(scanPath, 'utf8'));
const im = JSON.parse(fs.readFileSync(path.join(R, '.ua/tmp/im-output.json'), 'utf8'));

const final = {
  name: 'ocr-app',
  description:
    'Yerel çalışan (local-first) fiş OCR servisi: sahadaki çalışanın telefonundan yüklediği fiş fotoğrafını üç aşamalı bir kuyruk hattından geçirir — llama.cpp üzerinde PaddleOCR-VL ile metin tanıma, Strata/Unsloth Studio ile sözleşme v1 JSON yapılandırması ve saf Python ile deterministik tutar doğrulaması. FastAPI (:8090) saha PWA, yönetici paneli ve /v1 entegrasyon API\'ini sunar; veriler makineden çıkmaz (KVKK).',
  languages: Object.keys(s.stats?.byLanguage ?? {}).sort(),
  frameworks: [
    'FastAPI',
    'Uvicorn',
    'Pydantic',
    'HTTPX',
    'pytest',
    'jsonschema',
    'openpyxl',
    'SQLite',
    'PWA',
  ],
  files: s.files,
  totalFiles: s.totalFiles ?? s.files.length,
  filteredByIgnore: s.filteredByIgnore ?? 0,
  estimatedComplexity: s.estimatedComplexity,
  importMap: im.importMap,
};
if (final.totalFiles !== final.files.length) throw new Error('totalFiles mismatch');
if (Object.keys(final.importMap).length !== final.files.length) console.log('WARN: importMap entries != files');
fs.writeFileSync(scanPath, JSON.stringify(final, null, 2));
console.log('scan-result.json finalized:', final.totalFiles, 'files;', Object.keys(final.importMap).length, 'importMap entries;', final.estimatedComplexity);
console.log('categories:', JSON.stringify(s.stats.byCategory), 'langs:', final.languages.join(','));
