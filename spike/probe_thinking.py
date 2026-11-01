import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\PC\Documents\GitHub\ocr-app')
import httpx
from app import config

def try_body(tag, extra):
    body = {'model': config.strata_model(),
            'messages': [{'role': 'user', 'content': 'Sadece JSON dondur: {"a": 1}'}],
            'max_tokens': 200, 'temperature': 0}
    body.update(extra)
    try:
        r = httpx.post(config.strata_base_url() + '/v1/chat/completions', json=body, timeout=120)
        m = r.json()['choices'][0]['message']
        print(tag, '-> content:', repr(m.get('content'))[:90],
              '| reasoning:', bool(m.get('reasoning_content')))
    except Exception as e:
        print(tag, 'HATA', str(e)[:120])

try_body('baz', {})
try_body('chat_template_kwargs.thinking_false', {'chat_template_kwargs': {'thinking': False}})
try_body('thinking_disable', {'thinking': 'disable'})
try_body('template_kwargs.thinking_false', {'template_kwargs': {'thinking': False}})
