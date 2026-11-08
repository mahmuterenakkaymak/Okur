"""Run an OCR model on the 3 REAL receipts/handwriting captured from Google Images.

No machine ground truth; saves raw model output per image for manual comparison
against the human-read ground truth in ground_truth_real.md.
"""
import base64
import json
import os
import sys
import time
import urllib.request

ROOT = r'C:\Users\PC\Documents\GitHub\Okur'
FIX = os.path.join(ROOT, 'fixtures_real')

PROMPTS = {
    'gercek_market_1': 'Table Recognition:',
    'gercek_bim_2': 'Table Recognition:',
    'gercek_elyazisi_3_kirp': 'Transcribe this handwritten Turkish text exactly, line by line. Output only the text.',
}


def data_url(path):
    with open(path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


def ask(port, image, prompt, max_tokens=1500):
    body = {'messages': [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': data_url(image)}},
        {'type': 'text', 'text': prompt}]}],
        'max_tokens': max_tokens, 'temperature': 0}
    req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    return j['choices'][0]['message']['content'], time.time() - t0


def run(port, tag):
    out = {}
    for name in sorted(PROMPTS):
        p = os.path.join(FIX, name + '.png')
        if not os.path.exists(p):
            continue
        txt, dt = ask(port, p, PROMPTS[name])
        out[name] = {'sec': round(dt, 1), 'raw': txt}
        print(f'{name} {dt:.1f}s {len(txt)}ch', flush=True)
    with open(os.path.join(ROOT, 'spike', f'real_{tag}.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('saved real_' + tag + '.json')


if __name__ == '__main__':
    run(int(sys.argv[1]), sys.argv[2])
