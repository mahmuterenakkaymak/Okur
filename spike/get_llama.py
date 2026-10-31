import urllib.request, zipfile, os
base = 'https://github.com/ggml-org/llama.cpp/releases/download/b12020/'
dst = r'C:\Users\PC\Documents\GitHub\ocr-app\vendor\llama'
os.makedirs(dst, exist_ok=True)
for z in ['llama-b12020-bin-win-cuda-13.4-x64.zip', 'cudart-llama-bin-win-cuda-13.4-x64.zip']:
    p = os.path.join(dst, z)
    print('indiriliyor', z, flush=True)
    urllib.request.urlretrieve(base + z, p)
    with zipfile.ZipFile(p) as f:
        f.extractall(dst)
    os.remove(p)
print('llama.cpp CUDA hazir')
