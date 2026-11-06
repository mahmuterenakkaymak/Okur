import fs from 'fs';
import path from 'path';
const R = 'C:/Users/PC/Documents/GitHub/ocr-app';
const scanPath = path.join(R, '.ua/intermediate/scan-result.json');
const s = JSON.parse(fs.readFileSync(scanPath, 'utf8'));
fs.writeFileSync(path.join(R, '.ua/tmp/im-input.json'), JSON.stringify({ projectRoot: R, files: s.files }));
console.log('im-input written with', s.files.length, 'files');
