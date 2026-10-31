"""Benchmark an OCR model against the synthetic Turkish receipt fixtures.

Sends each fixture with the `Table Recognition:` prompt, then scores the raw output
against ground truth by checking how many expected numeric/string tokens appear
(Turkish number format normalized). Writes a per-run JSON + prints a summary.
"""
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.request

ROOT = r'C:\Users\PC\Documents\GitHub\ocr-app'
FIX = os.path.join(ROOT, 'fixtures')
PROMPT = 'Table Recognition:'


def data_url(path):
    with open(path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


def ask(port, image, prompt=PROMPT, max_tokens=1500):
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


def norm(s):
    """Normalize for matching: strip table markup, keep only alphanumerics.
    '1.046,40' and '1046.40' both -> '104640'."""
    s = re.sub(r'</?fcel>|</?lcel>|</?ecel>|<nl>', ' ', s)
    return re.sub(r'[^0-9a-zA-Z\u00e7\u011f\u0131\u00f6\u015f\u00fc]', '', s).lower()


def expected_tokens(truth):
    toks = set()
    t = truth['totals']
    for k in ('ara_toplam', 'iskonto', 'kdv', 'toplam'):
        v = t.get(k)
        if v:
            toks.add(norm(f'{v:.2f}'))
    for it in truth['items']:
        toks.add(norm(f'{it["toplam"]:.2f}'))
    toks.add(norm(truth['header']['vergi_no']))
    toks.add(norm(truth['meta']['tarih']))
    return toks


def score(text, truth):
    n = norm(text)
    exp = expected_tokens(truth)
    hit = {e for e in exp if e in n}
    return len(hit), len(exp), sorted(exp - hit)


def run(port, tag, prompt=PROMPT):
    results = []
    for fx in sorted(glob.glob(os.path.join(FIX, '*.json'))):
        base = fx[:-5]
        truth = json.load(open(fx, encoding='utf-8'))
        txt, dt = ask(port, base + '.png', prompt)
        hit, tot, miss = score(txt, truth)
        results.append({'fixture': os.path.basename(base), 'sec': round(dt, 1),
                        'hit': hit, 'total': tot, 'miss': miss,
                        'chars': len(txt), 'raw': txt})
        print(f'{os.path.basename(base):24s} {hit}/{tot} {dt:5.1f}s miss={miss}', flush=True)
    out = os.path.join(ROOT, 'spike', f'bench_{tag}.json')
    json.dump(results, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    th = sum(r['hit'] for r in results); tt = sum(r['total'] for r in results)
    print(f'\n=== {tag}: {th}/{tt} alan isabeti ({100*th/tt:.0f}%) ===')
    print('avg sec', round(sum(r['sec'] for r in results)/len(results), 1))


if __name__ == '__main__':
    prompt = sys.argv[3] if len(sys.argv) > 3 else PROMPT
    run(int(sys.argv[1]), sys.argv[2], prompt)
