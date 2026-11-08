import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\PC\Documents\GitHub\Okur')
import base64
import httpx
from app import config, structurer

img = open(r'C:\Users\PC\Documents\GitHub\Okur\fixtures_real\gercek_market_1.png', 'rb').read()
data_url = 'data:image/jpeg;base64,' + base64.b64encode(img).decode()
ocr_text = "30.01.2022 SAAT 12:31:05 FişNo 0004 BİRŞAH 500G %08 9,90 KRUVASAN 3,50 MILKTEN 15,90 TOPLAM 82,55 KDV 6,11"

def run(tag, extra, maxtok=1500):
    body = {'model': config.strata_model(), 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': structurer.PROMPT + ocr_text},
        {'type': 'image_url', 'image_url': {'url': data_url}}]}],
        'max_tokens': maxtok, 'temperature': 0}
    body.update(extra)
    r = httpx.post(config.strata_base_url() + '/v1/chat/completions', json=body, timeout=300)
    ch = r.json()['choices'][0]
    m = ch['message']
    c = m.get('content')
    print(f'{tag}: finish={ch.get("finish_reason")} content={"NULL" if c is None else str(len(c))+"ch"} reasoning={len(m.get("reasoning_content") or "")}ch')
    if c:
        try:
            d = structurer.extract_json(c)
            print('   extract_json OK:', list(d.keys())[:6])
        except Exception as e:
            print('   extract FAIL:', str(e)[:80])

run('A_1500_yok', {})
run('B_enable_thinking_false', {'chat_template_kwargs': {'enable_thinking': False}})
run('C_thinking_false_top', {'thinking': False})
run('D_4000_yok', {}, maxtok=4000)
