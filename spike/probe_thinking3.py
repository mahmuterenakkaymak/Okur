import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\PC\Documents\GitHub\Okur')
import httpx
from app import config

def probe(tag, extra):
    body = {'model': config.strata_model(),
            'messages': [{'role': 'user', 'content': 'Sayilarin toplamini hesapla: 2+3. Sadece sonuc ver.'}],
            'max_tokens': 300, 'temperature': 0}
    body.update(extra)
    r = httpx.post(config.strata_base_url() + '/v1/chat/completions', json=body, timeout=120)
    m = r.json()['choices'][0]['message']
    print(f'{tag:40} reasoning={len(m.get("reasoning_content") or ""):4}ch  content={m.get("content")!r:.40}', flush=True)

probe('baz', {})
probe('chat_template_kwargs.enable_thinking=False', {'chat_template_kwargs': {'enable_thinking': False}})
probe('chat_template_kwargs.thinking=False', {'chat_template_kwargs': {'thinking': False}})
probe('top.thinking=disable', {'thinking': 'disable'})
probe('top.enable_thinking=False', {'enable_thinking': False})
