# Canlı hat testi — gerçek PaddleOCR-VL (:8081) + gerçek Strata (:8080)

Tarih: 2026-11-01 ~03:20. 679 birim testi sahte modelle geçiyordu; bu, boru
hattının gerçek modellerle ilk koşusuydu. `run.py` roll-call yeşil (OCR ✓ Strata
✓ Uygulama ✓), sonra `fixtures_real` 3 gerçek örnek POST edildi.

## Sonuç: 1 gerçek entegrasyon hatası bulundu (birim testlerinin göremediği)

| Aşama | Durum |
|---|---|
| OCR (PaddleOCR-VL, CPU) | ✅ 5-7 sn, fişleri doğru okudu (`<fcel>` tablo çıktısı temiz) |
| Yapılandırma (Strata) | ❌ her fişte `verdict=unreadable` |
| Doğrulama | ✅ mantık sağlam ama girdi boş olduğu için sonuçsuz |

## Kök neden (kanıtla)

Strata bir **akıl yürüten model**: yanıtı `reasoning_content` (düşünce) +
`content` olarak ayırıyor. Structurer `max_tokens: 1500` gönderiyor; karmaşık
fişte model 1500 token'ın **tamamını düşünceye** harcıyor ve `content: null`
dönüyor. Structurer `str(None)` → `"None"` görüp JSON yok sayıyor →
`UnreadableError` → `unreadable`.

Kanıt (aynı görsel, ham istek):
```
IMAGE LI: 200  content: null  reasoning_content: "Kullanıcı fişteki firma adını
soruyor. Fişi dikkatlice inceleyeyim. ..."  (100 token'ın hepsi düşünce)
```
Sahte model stub'ları düşünce üretmediği için 679 testin hiçbiri bunu yakalamadı
— tam da canlı testin gerekçesi.

## Doğrulanmış düzeltme

`probe_thinking3.py` — kısa istekte bayrak karşılaştırması:
```
baz                                      reasoning=165ch
chat_template_kwargs.enable_thinking=False   reasoning=  0ch   ✅
chat_template_kwargs.thinking=False          reasoning=165ch   ✗
top.thinking=disable                         reasoning=165ch   ✗
top.enable_thinking=False                    reasoning=165ch   ✗
```
Tek doğru bayrak: istek gövdesine `"chat_template_kwargs": {"enable_thinking": false}`.
Ek güvence: `max_tokens` 1500→2500 (düşünce kapalıyken JSON sığar).

## Pipeline'a kuyruklanan düzeltme görevi

TASKS.md'ye **T68** eklendi (structurer.py + birim testi). Uygulama için:
`python ...hybrid_run.py <repo> --build-only` (resume; T68'i yerelde koşar).

## İkincil bulgular (küçük)

- `run.py` OCR'ı 60 sn'de hazır edemedi (soğuk GGUF yüklemesi ~90 sn);
  `STARTUP_WAIT_S=240` ile geçti. README/OPERATIONS'ta varsayılan yükseltilmeli.
- Testte 8090'da eski bir `serve_demo.py` kalmıştı; `run.py` çakışmayı "port
  meşgul" diye net söylemeli (sessiz başarısız uvicorn).

## Nasıl tekrarlanır
```powershell
cd C:\Users\PC\Documents\GitHub\ocr-app
$env:STARTUP_WAIT_S='240'; .venv\Scripts\python run.py --no-browser   # ayrı terminal
.venv\Scripts\python spike\live_test.py                               # 3 gerçek örnek
```
