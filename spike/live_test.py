"""Live end-to-end: real PaddleOCR-VL (:8081) + real Strata (:8080) through the app (:8090).

Submits the 3 real-world fixtures (fixtures_real/) and prints the contract v1
result + validation verdict for each.
"""
import json
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = r'C:\Users\PC\Documents\GitHub\Okur'
BASE = 'http://127.0.0.1:8090'

# 1) worker key via CLI (plaintext printed once)
out = subprocess.run([sys.executable, '-m', 'app.keys_cli', 'add', 'live-test'],
                     capture_output=True, text=True, cwd=ROOT).stdout
key = next((ln.strip() for ln in out.splitlines() if ln.strip().startswith('ocrk_')), None)
if not key:
    sys.exit('key alinamadi:\n' + out)
print('key alindi')

IMAGES = ['gercek_market_1.png', 'gercek_bim_2.png', 'gercek_elyazisi_3_kirp.png']


def post_image(path):
    import http.client
    import mimetypes
    import os
    boundary = '----live' + uuid.uuid4().hex
    fname = os.path.basename(path)
    with open(path, 'rb') as f:
        data = f.read()
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
        f'filename="{fname}"\r\nContent-Type: image/png\r\n\r\n'
    ).encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    conn = http.client.HTTPConnection('127.0.0.1', 8090, timeout=30)
    conn.request('POST', '/v1/jobs', body=body, headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'X-API-Key': key, 'Content-Length': str(len(body))})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    j = json.loads(raw)
    if 'job_id' not in j:
        sys.exit(f'POST /v1/jobs -> HTTP {resp.status}: {raw[:400]}')
    return j['job_id']


def poll(job_id, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        req = urllib.request.Request(f'{BASE}/v1/jobs/{job_id}', headers={'X-API-Key': key})
        j = json.loads(urllib.request.urlopen(req, timeout=30).read())
        if j['status'] in ('done', 'failed'):
            return j
        time.sleep(2)
    raise TimeoutError(job_id)


report = {}
for name in IMAGES:
    p = ROOT + '\\fixtures_real\\' + name
    jid = post_image(p)
    j = poll(jid)
    report[name] = j
    v = j.get('validation') or {}
    m = j.get('meta') or {}
    print(f"\n=== {name} -> {j['status']} | verdict={v.get('verdict')} "
          f"| ocr={m.get('ocr_ms')}ms total={m.get('total_ms')}ms model={m.get('model')}")
    r = j.get('result') or {}
    if r:
        print('  firma:', (r.get('header') or {}).get('isim'), '| tarih:', (r.get('meta') or {}).get('tarih'))
        for it in (r.get('items') or [])[:12]:
            print(f"    {it['ad'][:38]:38} {it['miktar']:>6} x {it['birim_fiyat']:>8} = {it['toplam']:>8}")
        print('  totals:', json.dumps(r.get('totals'), ensure_ascii=False))
    if v.get('fields'):
        print('  mismatch fields:', v['fields'])
    if j['status'] == 'failed':
        print('  ERROR:', j.get('error'))

with open(ROOT + '\\spike\\live_real.json', 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print('\nsaved spike\\live_real.json')
