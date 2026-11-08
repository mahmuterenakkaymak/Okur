"""Manual stage1+stage2 probe against the live servers; prints raw model output."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import base64  # noqa: E402

sys.path.insert(0, r'C:\Users\PC\Documents\GitHub\Okur')
from app import config, ocr_client, structurer  # noqa: E402

img = open(r'C:\Users\PC\Documents\GitHub\Okur\fixtures_real\gercek_market_1.png', 'rb').read()

ocr = ocr_client.OcrClient()
t = ocr.transcribe(img, quality_mode=False)
print('=== OCR (%d ms, %d char) ===' % (t['ms'], len(t['text'])))
print(t['text'][:600])

# raw leg to Strata, same body as Structurer.structure
import httpx, json  # noqa: E402
data_url = 'data:image/jpeg;base64,' + base64.b64encode(img).decode()
body = {'model': config.strata_model(), 'messages': [{'role': 'user', 'content': [
    {'type': 'text', 'text': structurer.PROMPT + t['text']},
    {'type': 'image_url', 'image_url': {'url': data_url}}]}],
    'max_tokens': 1500, 'temperature': 0}
r = httpx.post(config.strata_base_url() + '/v1/chat/completions', json=body, timeout=300)
print('=== STRATA HTTP', r.status_code, '===')
c = r.json()['choices'][0]['message']['content']
print('--- content ilk 1200 ---')
print(c[:1200])
print('--- content son 400 ---')
print(c[-400:])
try:
    data = structurer.extract_json(c)
    print('extract_json OK, keys:', list(data.keys()))
except Exception as e:
    print('extract_json FAIL:', e)
