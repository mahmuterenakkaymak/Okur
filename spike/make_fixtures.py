"""Generate synthetic Turkish receipt fixtures with known ground truth.

Creates clean + photo-degraded (rotate/blur/noise) variants for OCR benchmarking.
Ground truth JSON is written next to each image. Amounts use Turkish display format
(1.234,56) on the receipt; ground truth stores floats.
"""
import json
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

OUT = os.path.join(os.path.dirname(__file__), '..', 'fixtures')
os.makedirs(OUT, exist_ok=True)

W, MARGIN = 480, 30
LINE_H = 26


def font(size, bold=False):
    path = r'C:\Windows\Fonts\consola%s.ttf' % ('b' if bold else '')
    return ImageFont.truetype(path, size)


def fmt_tr(x):
    """1234.56 -> 1.234,56"""
    s = f'{x:,.2f}'
    return s.replace(',', '#').replace('.', ',').replace('#', '.')


def make_receipt(name, header_lines, items, meta, totals_extra=None, seed=1):
    """items: list of (ad, miktar, birim_fiyat) -> toplam computed. Returns (image, truth)."""
    rnd = random.Random(seed)
    rows = []
    subtotal = 0.0
    for ad, miktar, birim in items:
        toplam = round(miktar * birim, 2)
        subtotal = round(subtotal + toplam, 2)
        rows.append((ad, miktar, birim, toplam))
    iskonto = round(subtotal * (totals_extra or {}).get('iskonto_orani', 0), 2)
    net = round(subtotal - iskonto, 2)
    kdv_orani = (totals_extra or {}).get('kdv_orani', 0.20)
    kdv = round(net * kdv_orani, 2)
    genel = round(net + kdv, 2)

    h = 560 + len(rows) * LINE_H
    img = Image.new('RGB', (W, h), 'white')
    d = ImageDraw.Draw(img)
    y = 18
    d.text((W // 2, y), header_lines[0], font=font(20, True), fill='black', anchor='mt')
    y += 34
    for line in header_lines[1:]:
        d.text((W // 2, y), line, font=font(13), fill='black', anchor='mt')
        y += 20
    y += 6
    d.line([(MARGIN, y), (W - MARGIN, y)], fill='black')
    y += 10
    d.text((MARGIN, y), 'SIRA ADI              MIKTAR    FIYAT      TUTAR', font=font(12, True), fill='black')
    y += 22
    for i, (ad, miktar, birim, toplam) in enumerate(rows, 1):
        d.text((MARGIN, y), f'{i:02d} {ad[:20]:<20}', font=font(13), fill='black')
        d.text((W - MARGIN, y), f'{miktar:g}  {fmt_tr(birim)}  {fmt_tr(toplam)}', font=font(13), fill='black', anchor='ra')
        y += LINE_H
    d.line([(MARGIN, y), (W - MARGIN, y)], fill='black')
    y += 10
    lines = [
        ('ARA TOPLAM', fmt_tr(subtotal)),
        ('ISKONTO', '-' + fmt_tr(iskonto) if iskonto else '0,00'),
        (f'KDV %{int(kdv_orani * 100)}', fmt_tr(kdv)),
        ('GENEL TOPLAM', fmt_tr(genel) + ' TL'),
    ]
    for label, val in lines:
        d.text((MARGIN, y), label, font=font(14, True), fill='black')
        d.text((W - MARGIN, y), val, font=font(14, True), fill='black', anchor='ra')
        y += 24
    y += 8
    d.text((W // 2, y), meta.get('alt_not', 'TESEKKUR EDERIZ / SAYGILARIMIZLA'), font=font(13), fill='black', anchor='mt')
    y += 22
    d.text((W // 2, y), f"{meta['tarih']} {meta['saat']}  SAYA:{meta['saya']}", font=font(12), fill='black', anchor='mt')
    y += 20
    d.text((W // 2, y), f"VKN {meta['vergi_no']}  VD {meta['vergi_dairesi']}", font=font(12), fill='black', anchor='mt')
    y += 20
    d.text((W // 2, y), f"Belge No: {meta['belge_no']}", font=font(12), fill='black', anchor='mt')

    truth = {
        'header': {'isim': header_lines[0], 'vergi_dairesi': meta['vergi_dairesi'], 'vergi_no': meta['vergi_no']},
        'meta': {'tarih': meta['tarih'], 'saat': meta['saat'], 'no': meta['belge_no'], 'tip': meta['tip']},
        'items': [{'ad': ad, 'miktar': miktar, 'birim_fiyat': birim, 'toplam': toplam} for ad, miktar, birim, toplam in rows],
        'totals': {'ara_toplam': subtotal, 'iskonto': iskonto, 'kdv': kdv, 'kdv_orani': kdv_orani, 'toplam': genel},
        'para_birimi': 'TRY',
    }
    return img, truth


def degrade(img, seed, rotate=2.5, blur=0.8, noise=14):
    rnd = random.Random(seed)
    out = img.rotate(rnd.uniform(-rotate, rotate), resample=Image.BICUBIC, expand=True, fillcolor=(240, 238, 230))
    out = out.filter(ImageFilter.GaussianBlur(rnd.uniform(0.3, blur)))
    out = ImageEnhance.Contrast(out).enhance(rnd.uniform(0.75, 0.95))
    out = ImageEnhance.Brightness(out).enhance(rnd.uniform(0.85, 1.05))
    # speckle noise
    px = out.load()
    w, h = out.size
    for _ in range(w * h // noise):
        x, yy = rnd.randrange(w), rnd.randrange(h)
        r, g, b = px[x, yy]
        v = max(0, min(255, r + rnd.randint(-40, 40)))
        px[x, yy] = (v, g, b)
    return out


def save(name, img, truth):
    img.save(os.path.join(OUT, f'{name}.png'))
    with open(os.path.join(OUT, f'{name}.json'), 'w', encoding='utf-8') as f:
        json.dump(truth, f, ensure_ascii=False, indent=1)


# --- Fixture 1: market fisi (indirimli, %20 KDV) ---
img1, t1 = make_receipt(
    'market',
    ['BILGIN MARKETLER ANONIM SIRKETI', 'Ataturk Cad. No:45 Kizilay / ANKARA', 'Tel: 0312 456 78 90'],
    [('Tam buğday ekmeği', 2, 15.00), ('Süt %3,5 yağ 1L', 3, 42.50), ('Zeytinyağı 1L', 1, 285.00),
     ('Yumurta 15li', 1, 95.00), ('Beyaz peynir 600g', 1, 178.90), ('Çay 1kg', 2, 165.00)],
    {'tarih': '28.10.2026', 'saat': '14:32', 'saya': '004512', 'vergi_no': '1234567890',
     'vergi_dairesi': 'KIZILAY', 'belge_no': 'A2-998877', 'tip': 'gider'},
    {'kdv_orani': 0.20, 'iskonto_orani': 0.05}, seed=11)
save('fis_market_clean', img1, t1)
save('fis_market_foto', degrade(img1, 21), t1)

# --- Fixture 2: akaryakit istasyonu (%18 KDV, damga vergisi yok, tek kalem) ---
img2, t2 = make_receipt(
    'benzin',
    ['AKPET AKARYAKIT VE GIDA LTD. STI.', 'E-5 Karayuzu Umraniyesyer Istanbul', 'Tel: 0216 555 44 33'],
    [('Kurşunsuz 95 (litre)', 32.47, 53.19)],
    {'tarih': '30.10.2026', 'saat': '08:15', 'saya': '112233', 'vergi_no': '9876543210',
     'vergi_dairesi': 'UMRANIYE', 'belge_no': 'B5-112233', 'tip': 'gider'},
    {'kdv_orani': 0.20}, seed=22)
save('fis_benzin_clean', img2, t2)
save('fis_benzin_foto', degrade(img2, 31, rotate=4, blur=1.2), t2)

# --- Fixture 3: restoran fisi (%10 KDV gida, bahşiş satırı yok, çok kalem) ---
img3, t3 = make_receipt(
    'restoran',
    ['LEZZET DUNYASI GIDA TURIZM INS. LTD. STI.', 'Kulumbuklu Mah. Gazipaşa Cad. No:12 Antalya', 'Tel: 0242 310 20 10'],
    [('Adana kebir porsiyon', 2, 240.00), ('Ayran 300ml', 2, 35.00), ('İçli köfte (adet)', 6, 45.00),
     ('Künefe', 1, 180.00), ('Su 500ml', 3, 15.00), ('Limonata', 1, 65.00)],
    {'tarih': '25.10.2026', 'saat': '21:47', 'saya': '778899', 'vergi_no': '4567891230',
     'vergi_dairesi': 'MURATPAŞA', 'belge_no': 'C1-445566', 'tip': 'gider'},
    {'kdv_orani': 0.10}, seed=33)
save('fis_restoran_clean', img3, t3)
save('fis_restoran_foto', degrade(img3, 41, rotate=3, blur=1.0, noise=10), t3)

print('fixtures olusturuldu:', sorted(os.listdir(OUT)))
