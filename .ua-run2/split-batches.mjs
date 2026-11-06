import fs from 'fs';
import path from 'path';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const b = JSON.parse(fs.readFileSync(path.join(R, '.ua/intermediate/batches.json'), 'utf8'));
for (const batch of b.batches) {
  const p = path.join(R, `.ua/tmp/batch-input-${batch.batchIndex}.json`);
  fs.writeFileSync(p, JSON.stringify(batch, null, 2));
  console.log(`batch ${batch.batchIndex}: ${batch.files.length} files -> ${path.basename(p)} (${fs.statSync(p).size}B)`);
}
