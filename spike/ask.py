"""Quick single-image smoke test against a running llama-server OCR endpoint."""
import base64
import json
import os
import sys
import time
import urllib.request

ROOT = r'C:\Users\PC\Documents\GitHub\ocr-app'


def data_url(path):
    with open(path, 'rb') as f:
        b = base64.b64encode(f.read()).decode()
    return 'data:image/png;base64,' + b


def ask(port, image, prompt, max_tokens=1200):
    body = {
        'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': data_url(image)}},
            {'type': 'text', 'text': prompt},
        ]}],
        'max_tokens': max_tokens,
        'temperature': 0,
    }
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/v1/chat/completions',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    dt = time.time() - t0
    txt = j['choices'][0]['message']['content']
    return txt, dt, j.get('usage', {})


if __name__ == '__main__':
    port = int(sys.argv[1])
    img = sys.argv[2]
    prompt = sys.argv[3] if len(sys.argv) > 3 else 'OCR:'
    txt, dt, usage = ask(port, img, prompt)
    out = os.path.join(ROOT, 'spike', 'last_out.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f'--- {dt:.1f}s usage={usage} ---\n\n' + txt)
    print(f'--- {dt:.1f}s usage={usage} ---')
    print('written to', out, '| chars:', len(txt))
