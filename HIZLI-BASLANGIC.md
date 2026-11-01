# Eren'e Hızlı Başlangıç (Türkçe)

Bu proje ne yapıyor: saha çalışanı telefonu ile fiş çekiyor, PC'deki hat
(okuma → yapılandırma → doğrulama) saniyeler içinde sözleşme v1 JSON üretiyor.
Hepsi bu makinede; bulut yok. İngilizce tam doküman: `README.md`,
entegrasyon: `CONTRACT.md`, bakım: `OPERATIONS.md`.

## 5 dakikada dene (model indirmeden)

Demo sunucu gerçek uygulamayı sahte model sunucularıyla ayağa kaldırır,
`fixtures/` görselleriyle hazır verili gelir:

```powershell
cd C:\Users\PC\Documents\GitHub\ocr-app
.venv\Scripts\python scripts\serve_demo.py
```

- PWA (çalışan ekranı): http://localhost:8090/app — "Örnek fiş" butonu kameradan bağımsız akışı gösterir
- Admin: http://localhost:8090/admin — giriş için `.env` içindeki `ADMIN_TOKEN`
- API dokümanı: http://localhost:8090/docs

## Gerçek hatla çalıştır

Ön koşul: Strata ayakta olmalı (GPU modu `agent`; ben kendi üstümde koşuyorum,
yani zaten açık). PaddleOCR-VL ve llama-server yolları `.env` içinde:

```powershell
.venv\Scripts\python run.py            # her şeyi başlatır, hepsi yeşilleyince admin'i açar
.venv\Scripts\python run.py --stop     # hepsini kapatır
```

Çalışan anahtarı (bir kere gösterilir, kopyala):

```powershell
.venv\Scripts\python -m app.keys_cli add ayse
```

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

```powershell
.venv\Scripts\python -m pytest -q                 # 679 test
.venv\Scripts\python scripts\acceptance.py --demo # 7 kabul kontrolü
.venv\Scripts\python scripts\smoke_e2e.py         # uçtan uca duman
```

## Bilinen açıklar (kabul edilmiş, REVIEW.md'de)

- Kalite modunda yeniden koşum, admin düzeltmelerinin üstüne yazar
- Yönetici girişinde hız sınırı yok; CSP `unsafe-inline` içeriyor
- EXIF'siz yüklemeler yeniden kodlanmadan saklanıyor (PNG meta kalabilir)
- Herhangi bir geçerli çalışan anahtarı tüm fişleri okuyabilir (tasarım gereği global)

## Sorun çıkarsa

- `run.py` batarsa: `data\logs\` altındaki log yollarını ve ekranın bastığı komutu gösterir; `--stop` sonra tekrar dene
- GPU modunu elle değiştirme (`switch-mode.ps1`), OCR zaten CPU'da çalışacak şekilde ayarlı (`OCR_NGL=0`)
- Fişler ve veritabanı `data\` altında — silme/yedek: `OPERATIONS.md`

> Not: 679 test sahte modellerle koşuyor; gerçek PaddleOCR-VL + Strata hattı
> ilk canlı denemede birlikte görülecek. İlk gerçek fişini çektiğinde verdict
> `ok` gelmiyorsa `data\logs\` ve admin → ham JSON bana yeter, gerisini ben bulurum.
