# Eren'e Hızlı Başlangıç (Türkçe)

Bu proje ne yapıyor: saha çalışanı telefonu ile fiş çekiyor, PC'deki hat
(okuma → yapılandırma → doğrulama) sözleşme v1 JSON üretiyor — okuma 1–5 saniye,
yapılandırma CPU'da ~30–45 saniye. Hepsi bu makinede; bulut yok. İngilizce tam
doküman: `README.md`, entegrasyon: `CONTRACT.md`, bakım: `OPERATIONS.md`.

## 5 dakikada dene (model indirmeden)

Demo sunucu gerçek uygulamayı sahte model sunucularıyla ayağa kaldırır,
`fixtures/` görselleriyle hazır verili gelir:

```powershell
cd C:\Users\PC\Documents\GitHub\ocr-app
.venv\Scripts\python scripts\serve_demo.py
```

- PWA (çalışan ekranı): http://localhost:8090/app — "Örnek fiş" butonu kameradan bağımsız akışı gösterir
- Admin: http://localhost:8090/admin — giriş için `ADMIN_TOKEN=demo`; demo sunucusu bunu kendi basar, açılış satırında da yazar (`.env` gerekmez)
- API dokümanı: http://localhost:8090/docs

## Gerçek hatla çalıştır

Aşama 2 artık küçük beyinde: `STRUCTURER_BACKEND` varsayılan olarak `small`, yani
fişi Qwen3-VL yapılandırıyor — `127.0.0.1:8100`, tamamen CPU, ekran kartından
bir şey istemiyor. Tek yapman gereken o beyni bir kere kurmak (≈2.1 GB,
`%LOCALAPPDATA%\ocr-small-brain\` içine):

```powershell
.\scripts\install_small_brain.ps1          # eksikleri indirir, kurulana dokunmaz
.\scripts\install_small_brain.ps1 -Check   # ne kurulu, ne eksik — indirmeden sayar
```

Beyin ayakta mı, elle kontrol: `GET http://127.0.0.1:8100/v1/models` — JSON model
listesi geliyorsa aşama 2 canlı; bağlantı reddedilirse sebep
`data\logs\small-brain.log` içinde.

`.env` repo kökünde durur (gitignore'da; her adı `app/config.py` okur):

```env
ADMIN_TOKEN=uzun-ve-tahmin-edilemez-bir-dize
LLAMA_SERVER=vendor/llama/llama-server.exe
OCR_MODEL=models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF.gguf
OCR_MMPROJ=models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF-mmproj.gguf
OCR_CHAT_TEMPLATE=models/paddleocr-vl-1.6/chat_template.jinja
```

`ADMIN_TOKEN` boş kalırsa admin panelinin kapısı hiç açılmaz; bu tek istisna
yukarıdaki demo, kendi anahtarını kendi basar.

Çalışan anahtarı (bir kere gösterilir, kopyala):

```powershell
.venv\Scripts\python -m app.keys_cli add ayse
```

Ve tek komutla hat: OCR + Small brain + Uygulama'yı kendisi kaldırır, üçü de
yeşillenince admin'i açar — başka bir şeyi ayrı başlatman gerekmiyor.

```powershell
.venv\Scripts\python run.py
.venv\Scripts\python run.py --no-browser --app-port 8090 --ocr-port 8081
.venv\Scripts\python run.py --stop     # hepsini kapatır
```

Beyin kurulu değilse aynı yoklamada şunu görürsün ve alt satır neyi koşacağını
söyler — kur, tekrar dene:

```
Small brain ✗ model dosyaları yok
kurulum       scripts\install_small_brain.ps1
dizin         C:\Users\PC\AppData\Local\ocr-small-brain
```

`Small brain ✗ port 8100 dolu` görürsen işgalcinin pid'sini de yazar; önce
`python run.py --stop` dene, launcher'ın kendi çocuğu çıkmanın en kolay yolu.

Aşama 2'nin yerini değiştirmek istersen bu opsiyonel bir yükseltme: `.env` içine
`STRUCTURER_BACKEND=strata` yaz (şu oturum için PowerShell'de
`$env:STRUCTURER_BACKEND="strata"`) ve `python run.py --stop` sonra tekrar
başlat — o zaman hat GPU'daki yapılandırıcıya geçer, `run.py` onu da bekler ama
kendi başlatmaz. Tek satırlık geri dönüş dahil hepsi `OPERATIONS.md` → Small brain.

## Telefona PWA kur

1. Tailscale ayağa kalkmalı (PC'de): `scripts\tailscale_serve.ps1` → `https://<ad>.ts.net`
2. Telefondan `https://<ad>.ts.net/app` aç → Android: menü → *Uygulamayı yükle*; iOS: Paylaş → *Ana Ekrana Ekle*
3. Uygulama "Fiş Çek" olarak açılır; **API anahtarı** alanına çalışanın anahtarını yapıştır
4. Kameraya izin ver → çek → kırp → gönder; aşamalar Türkçe akar, yeşil tik = doğrulandı

Anahtarı kaybeden/çıkan çalışan için: admin → Anahtarlar → iptal (veya `keys_cli revoke <id>`).

## Ne zaman ne çalışır

| Adres | Ne var |
|---|---|
| `/app` | Çalışan PWA'sı (Türkçe, kurulabilir) |
| `/admin` | İnceleme, alan düzeltme, JSON/CSV/XLSX dışa aktarım, anahtarlar, durum |
| `/v1/*` | Entegratör API'si (X-API-Key, sözleşme v1) |
| `/docs` | OpenAPI — deneyerek test edebilirsin |

## Kontrol listesi (küçükten büyüğe)

İlk üçü sahte modelle koşar, hat açık olsun gerektirmez:

```powershell
.venv\Scripts\python -m pytest -q                  # ≈999 test, hepsi sahte modelle
.venv\Scripts\python scripts\acceptance.py --demo  # 7 kabul kontrolü
.venv\Scripts\python scripts\smoke_e2e.py          # uçtan uca duman
```

Gerçek fiş kapıları ikisi — bunlar `run.py` açıkken ve gerçek modellerle ölçer:

```powershell
.venv\Scripts\python scripts\small_brain_gate.py   # 6 fixture, 6/6 şema, 5/6 doğrulayıcı
.venv\Scripts\python scripts\live_ocr_gate.py      # 3 gerçek fiş, kayıtlı baseline'a karşı
```

Hat kapalıyken ikisini `--if-installed` ile koş: SKIP deyip 0 çıkarlar; bayraksız
koşum hata satırlarını saklar.

## Bilinen açıklar (kabul edilmiş, REVIEW.md'de)

- Kalite modunda yeniden koşum, admin düzeltmelerinin üstüne yazar
- Yönetici girişinde hız sınırı yok; CSP `unsafe-inline` içeriyor
- EXIF'siz yüklemeler yeniden kodlanmadan saklanıyor (PNG meta kalabilir)
- Herhangi bir geçerli çalışan anahtarı tüm fişleri okuyabilir (tasarım gereği global)

## Sorun çıkarsa

- `run.py` batarsa: `data\logs\` altındaki log yollarını ve ekranın bastığı komutu gösterir; `--stop` sonra tekrar dene
- `Small brain ✗ model dosyaları yok` → `.\scripts\install_small_brain.ps1` (nereye baktığını da o satır söylüyor: `OCR_SMALL_BRAIN_DIR`)
- `Small brain ✗ port 8100 dolu` → `python run.py --stop`; geçmiyorsan `netstat -ano` ile işgalciyi bul, ya da beyni `SMALL_BRAIN_BASE_URL` ile taşı
- `OCR ✗` görürsen panik yapma: soğuk model açılışı `STARTUP_WAIT_S` varsayılanını aşabiliyor, `.env`'de büyütüp tekrar dene
- GPU modunu elle değiştirme; OCR da küçük beyin de CPU'da çalışacak şekilde ayarlı (`OCR_NGL=0`)
- Fişler ve veritabanı `data\` altında — silme/yedek: `OPERATIONS.md`

> Not: testlerin hepsi sahte modellerle koşuyor; gerçek PaddleOCR-VL + küçük beyin
> hattını yukarıdaki iki kapı ölçüyor. İlk gerçek fişini çektiğinde verdict
> `ok` gelmiyorsa `data\logs\` ve admin → ham JSON bana yeter, gerisini ben bulurum.
