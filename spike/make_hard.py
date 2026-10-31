"""Harder fixtures to break the tie: handwriting fonts + severe photo degradation.

Windows ships cursive/handwriting fonts (Ink Free, Segoe Script, Bradley Hand ITC,
Segoe Print). We render Turkish handwriting notes + a degraded real-world-style
receipt (low-res, perspective warp, heavy blur, shadow) with known ground truth.
"""
import json
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops

OUT = os.path.join(os.path.dirname(__file__), '..', 'fixtures_hard')
os.makedirs(OUT, exist_ok=True)
FONTS = r'C:\Windows\Fonts'


def f(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def save(name, img, truth=None):
    img.save(os.path.join(OUT, f'{name}.png'))
    if truth:
        json.dump(truth, open(os.path.join(OUT, f'{name}.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)


# --- Hand 1: el yazisi not (Ink Free = en kursif) ---
lines = [
    "Sevgili Eren,",
    "Toplanti yarin saat 14:30'da,",
    "lutfen satici raporlarini ve",
    "musteri listesini getir.",
    "Aksama kadar imzalamayi unutma!",
    "Saygilar, - Murat",
]
# ground-truth keywords to check recall
truth_h1 = {'keywords': ['Toplanti', '14:30', 'satici', 'rapor', 'musteri', 'imzalamayi', 'Murat']}
img = Image.new('RGB', (760, 460), (252, 250, 244))
d = ImageDraw.Draw(img)
y = 30
for i, ln in enumerate(lines):
    d.text((40, y), ln, font=f('inkfree.ttf', 40), fill=(20, 24, 60))
    y += 66
save('el_yazisi_not', img, truth_h1)

# --- Hand 2: el yazisi alisveris listesi (Segoe Print) ---
lines2 = ["ALISVERIS LISTESI", "2 kg domates", "1 paket makarna", "3 kutu süt", "500 gr kayisi", "temizlik bezı"]
truth_h2 = {'keywords': ['domates', 'makarna', 's', 'kayisi', 'temizlik']}
img = Image.new('RGB', (620, 420), 'white')
d = ImageDraw.Draw(img)
y = 30
for ln in lines2:
    d.text((40, y), ln, font=f('segoepr.ttf', 38), fill=(15, 15, 15))
    y += 60
save('el_yazisi_liste', img, truth_h2)

# --- Degraded receipt: kotu cekim (dusuk cozunurluk + perspektif + agir blur + golge) ---
def base_receipt():
    W, H = 460, 620
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    def fmt(x): return f'{x:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')
    items = [('Kuru gida', 120.00), ('Temizlik', 85.50), ('Icacak', 64.00)]
    d.text((W//2, 20), 'HER SEY MARKET LTD STI', font=f('consolab.ttf', 19), fill='black', anchor='mt')
    d.text((W//2, 48), 'Cumhuriyet Cad 88/B Kadikoy', font=f('consola.ttf', 13), fill='black', anchor='mt')
    y = 90
    d.line([(25, y), (W-25, y)], fill='black'); y += 14
    sub = 0
    for ad, tut in items:
        sub += tut
        d.text((30, y), ad, font=f('consola.ttf', 15), fill='black')
        d.text((W-30, y), fmt(tut), font=f('consola.ttf', 15), fill='black', anchor='ra')
        y += 30
    sub = round(sub, 2); kdv = round(sub*0.2, 2); gen = round(sub+kdv, 2)
    d.line([(25, y), (W-25, y)], fill='black'); y += 12
    for lbl, val in [('ARA TOPLAM', sub), ('KDV %20', kdv), ('GENEL TOPLAM', gen)]:
        d.text((30, y), lbl, font=f('consolab.ttf', 16), fill='black')
        d.text((W-30, y), fmt(val), font=f('consolab.ttf', 16), fill='black', anchor='ra')
        y += 28
    d.text((W//2, y+10), '02.11.2026 19:05  VKN 5556667778', font=f('consola.ttf', 13), fill='black', anchor='mt')
    truth = {'totals': {'ara_toplam': sub, 'kdv': kdv, 'toplam': gen},
             'vergi_no': '5556667778', 'tarih': '02.11.2026',
             'items': [t for _, t in items]}
    return img, truth

img0, truth0 = base_receipt()
# simulate a realistic bad phone photo: slight rotate, mild downscale, light blur,
# mild contrast loss, gentle left-side shadow. Must stay human-readable.
w, h = img0.size
imgp = img0.rotate(4.0, resample=Image.BICUBIC, expand=True, fillcolor=(245, 243, 238))
w, h = imgp.size
small = imgp.resize((int(w*0.55), int(h*0.55)), Image.BILINEAR)
imgp = small.resize((w, h), Image.BILINEAR)
imgp = imgp.filter(ImageFilter.GaussianBlur(0.7))
imgp = ImageEnhance.Contrast(imgp).enhance(0.8)
# gentle left-side shadow (paper in uneven light), not blowing highlights
grad = Image.new('L', (w, h))
gd = ImageDraw.Draw(grad)
for x in range(w):
    v = int(200 + 55 * (x / w))  # 200 (left, darker) -> 255 (right)
    gd.line([(x, 0), (x, h)], fill=v)
shadow = Image.merge('RGB', [grad, grad, grad])
imgp = ImageChops.multiply(imgp, shadow)
save('fis_kotu_cekim', imgp, truth0)

print('zor fixtures:', sorted(os.listdir(OUT)))
