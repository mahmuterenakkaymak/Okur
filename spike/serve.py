"""Start a llama-server for one of the candidate models (CPU-only to coexist with Strata)."""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = r'C:\Users\PC\Documents\GitHub\Okur'
LLAMA = os.path.join(ROOT, 'vendor', 'llama', 'llama-server.exe')

MODELS = {
    'paddle': {
        'model': os.path.join(ROOT, 'models', 'paddleocr-vl-1.6', 'PaddleOCR-VL-1.6-GGUF.gguf'),
        'mmproj': os.path.join(ROOT, 'models', 'paddleocr-vl-1.6', 'PaddleOCR-VL-1.6-GGUF-mmproj.gguf'),
        'port': 8100,
    },
    'qwen': {
        'model': os.path.join(ROOT, 'models', 'qwen3-vl-8b', 'Qwen3VL-8B-Instruct-Q4_K_M.gguf'),
        'mmproj': os.path.join(ROOT, 'models', 'qwen3-vl-8b', 'mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf'),
        'port': 8101,
    },
}


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def start(which, ngl=0, ctx=4096):
    cfg = MODELS[which]
    args = [LLAMA, '-m', cfg['model'], '--mmproj', cfg['mmproj'],
            '--port', str(cfg['port']), '--host', '127.0.0.1',
            '--temp', '0', '-c', str(ctx), '-ngl', str(ngl),
            '--no-webui']
    if which == 'qwen':
        args += ['--image-min-tokens', '1024']
    logf = open(os.path.join(ROOT, 'models', f'server-{which}.log'), 'w', encoding='utf-8')
    p = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT)
    print('started', which, 'pid', p.pid, 'port', cfg['port'], flush=True)
    for i in range(120):
        if health(cfg['port']):
            print('HEALTHY after', i * 2, 's', flush=True)
            return p
        time.sleep(2)
    print('TIMEOUT waiting for health; see log', flush=True)
    return p


if __name__ == '__main__':
    which = sys.argv[1]
    ngl = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    start(which, ngl)
