"""Hard benchmark: handwriting (keyword recall) + degraded receipt (numeric recall)."""
import base64
import json
import os
import re
import sys
import time
import urllib.request

ROOT = r'C:\Users\PC\Documents\GitHub\ocr-app'
FIX = os.path.join(ROOT, 'fixtures_hard')


def data_url(path):
    with open(path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


def ask(port, image, prompt, max_tokens=1200):
    body = {'messages': [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': data_url(image)}},
        {'type': 'text', 'text': prompt}]}],
        'max_tokens': max_tokens, 'temperature': 0}
    req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    return j['choices'][0]['message']['content'], time.time() - t0


_TR = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')


def norm(s):
    s = s.translate(_TR)
    return re.sub(r'[^0-9a-zA-Z]', '', s).lower()


PROMPT_HAND = 'Transcribe this handwritten text exactly, line by line. Output only the text.'
PROMPT_TABLE = 'Table Recognition:'


def score(txt, truth):
    n = norm(txt)
    if 'keywords' in truth:  # handwriting
        exp = [norm(k) for k in truth['keywords']]
    else:  # receipt
        exp = [norm(f'{v:.2f}') for v in truth['totals'].values()]
        exp += [norm(truth['vergi_no']), norm(truth['tarih'])]
        exp += [norm(f'{t:.2f}') for t in truth['items']]
    hit = [e for e in exp if e in n]
    return len(hit), len(exp), [e for e in exp if e not in n]


def run(port, tag):
    res = []
    for fx in sorted(__import__('glob').glob(os.path.join(FIX, '*.json'))):
        base = fx[:-5]
        truth = json.load(open(fx, encoding='utf-8'))
        prompt = PROMPT_HAND if 'keywords' in truth else PROMPT_TABLE
        txt, dt = ask(port, base + '.png', prompt)
        hit, tot, miss = score(txt, truth)
        name = os.path.basename(base)
        res.append({'fixture': name, 'sec': round(dt, 1), 'hit': hit, 'total': tot,
                    'miss': miss, 'raw': txt})
        print(f'{name:20s} {hit}/{tot} {dt:5.1f}s miss={miss}', flush=True)
    json.dump(res, open(os.path.join(ROOT, 'spike', f'hard_{tag}.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    th = sum(r['hit'] for r in res); tt = sum(r['total'] for r in res)
    print(f'\n=== HARD {tag}: {th}/{tt} ({100*th/tt:.0f}%) avg {sum(r["sec"] for r in res)/len(res):.1f}s ===')


if __name__ == '__main__':
    run(int(sys.argv[1]), sys.argv[2])
