"""Crop the handwriting panel out of the lightbox screenshot so the fixture is just the document."""
import os
from PIL import Image

ROOT = r'C:\Users\PC\Documents\GitHub\ocr-app'
src = os.path.join(ROOT, 'fixtures_real', 'gercek_elyazisi_3.png')
img = Image.open(src)
w, h = img.size
print('orig', w, h)
# handwriting panel is the right ~1/3 of the 1280x720 lightbox screenshot
crop = img.crop((int(w * 0.675), int(h * 0.16), int(w * 0.985), int(h * 0.50)))
crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
out = os.path.join(ROOT, 'fixtures_real', 'gercek_elyazisi_3_kirp.png')
crop.save(out)
print('kirpildi ->', out, crop.size)
