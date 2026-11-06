# -*- coding: utf-8 -*-
import json
from collections import Counter

N = []
E = []


def node(id, type, name, summary, tags, complexity, filePath=None, lineRange=None, languageNotes=None):
    d = {"id": id, "type": type, "name": name, "summary": summary, "tags": tags, "complexity": complexity}
    if filePath:
        d["filePath"] = filePath
    if lineRange:
        d["lineRange"] = lineRange
    if languageNotes:
        d["languageNotes"] = languageNotes
    N.append(d)


def edge(source, target, type, weight):
    assert source != target, source
    E.append({"source": source, "target": target, "type": type, "direction": "forward", "weight": weight})


# -------------------------------------------------------------- file-level nodes
node("config:contract/contract_v1.schema.json", "config", "contract_v1.schema.json",
     "Fiş OCR servisinin iş zarfı (JobEnvelope) sözleşmesini donduran JSON Schema (draft 2020-12): status, job_id, client_ref, meta, result ve validation bloklarını, $defs altındaki Header/Item/JobMeta/Meta/Result/Totals/Validation modelleriyle tanımlar.",
     ["schema-definition", "api-schema", "data-contract", "validation"], "complex",
     filePath="contract/contract_v1.schema.json",
     languageNotes="Pydantic model_json_schema çıktısı: alanlar default taşır (eksik alana tolerans), opsiyonel alanlar anyOf[type, null] ile ifade edilip alt modeller $ref ile yeniden kullanıma açılmış.")

node("file:scripts/tailscale_serve.ps1", "file", "tailscale_serve.ps1",
     "Uygulama portunu (127.0.0.1:8090) yalnız tailnet üzerinden HTTPS'e çıkaran operasyon script'i: tailscale serve ile TLS sonlandırılır, sertifika data\\certs altına dışa aktarılır, -Status ve -Rollback modları sunulur; funnel hiçbir yolda çağrılmaz.",
     ["script", "infrastructure", "deployment", "tls", "operations"], "moderate",
     filePath="scripts/tailscale_serve.ps1",
     languageNotes="PowerShell: Invoke-Tailscale sarmalayıcısı @{code; lines} hashtable'ı döndürür, -AllowFailure ile hata politikası komut bazında belirlenir; $ErrorActionPreference = Stop hattı keser.")

node("file:spike/ask.py", "file", "ask.py",
     "Çalışan bir llama-server OCR endpoint'ine tek görsel gönderip ham çıktıyı spike/last_out.txt'e yazan tek atışlık duman testi; görseli base64 data URL olarak gömer, temperature 0 kullanır ve geçen süreyi raporlar.",
     ["spike", "smoke-test", "ocr", "cli"], "simple", filePath="spike/ask.py")

node("file:spike/bench.py", "file", "bench.py",
     "Sentetik Türkçe fiş fixture'larını (fixtures/) 'Table Recognition:' prompt'uyla modele soran kıyas hattı: ground truth'taki toplam/kalem/vergi no/tarih token'larının kaçının ham çıktının içinde geçtiğini sayar ve spike/bench_<tag>.json üretir.",
     ["spike", "benchmark", "ocr", "evaluation"], "moderate", filePath="spike/bench.py",
     languageNotes="Skorlama birebir metin karşılaştırması değil: tablo işaretçileri (</fcel>, <nl>) silinip yalnız alfanümerik kalan normalize metinde alt dize araması yapılır, böylece 1.046,40 ile 1046.40 eşitlenir.")

node("file:spike/bench_hard.py", "file", "bench_hard.py",
     "El yazısı (anahtar kelime hatırlama) ve ağır bozulmuş fiş (sayısal hatırlama) fixture'larını aynı döngüyle skorlayan zorlaştırılmış kıyas; Türkçe harfleri ASCII'ye çevirerek normalize eder ve spike/hard_<tag>.json yazar.",
     ["spike", "benchmark", "ocr", "evaluation"], "moderate", filePath="spike/bench_hard.py")

node("file:spike/bench_real.py", "file", "bench_real.py",
     "Gerçek dünyadan alınmış üç görsel (iki market fişi, bir el yazısı kırpıntısı) için modeli koşup ham çıktıyı spike/real_<tag>.json'e kaydeden script; makine ground truth'u yoktur, değerlendirme ground_truth_real.md ile elle yapılır.",
     ["spike", "benchmark", "ocr", "manual-review"], "simple", filePath="spike/bench_real.py")

node("file:spike/crop_hand.py", "file", "crop_hand.py",
     "Ekran görüntüsündeki el yazısı panelini kırpan ve LANCZOS ile 2× büyüten tek seferlik yardımcı; fixtures_real/gercek_elyazisi_3_kirp.png üretir, böylece kıyas görüntüsü yalnız belgeyi içerir.",
     ["spike", "image-processing", "fixture"], "simple", filePath="spike/crop_hand.py")

node("file:spike/get_llama.py", "file", "get_llama.py",
     "llama.cpp'nin CUDA ikili paketlerini (b12020 ve cudart) vendor/llama altına indirip açan ve arşivleri silen kurulum script'i; spike/serve.py'nin aradığı llama-server.exe'yi hazırlar.",
     ["spike", "setup", "download", "build-system"], "simple", filePath="spike/get_llama.py")

node("file:spike/live_test.py", "file", "live_test.py",
     "Uçları gerçek olan canlı test: app.keys_cli ile API anahtarı üretir, üç gerçek fixture'ı POST /v1/jobs ile kuyruğa atar, iş done/failed olana kadar yoklar ve contract v1 sonucu ile doğrulama kararını (verdict, mismatch alanları, ocr/total ms) raporlayıp spike/live_real.json'a yazar.",
     ["spike", "integration-test", "api-client", "end-to-end"], "moderate", filePath="spike/live_test.py")

node("file:spike/make_fixtures.py", "file", "make_fixtures.py",
     "PIL ile Türkçe para/KDV biçiminde (1.234,56) sentetik fiş görüntüleri ve yanına birebir ground truth JSON yazan üretici; market, akaryakıt ve restoran senaryolarının temiz artı foto-bozulmuş varyantlarını fixtures/ altına kurar.",
     ["fixture", "image-generation", "synthetic-data", "ground-truth"], "complex", filePath="spike/make_fixtures.py",
     languageNotes="Türkçe sayı biçimi üç aşamalı replace hilesiyle üretilir (binlik ayıracı '#' ile korunur); görüntü ile truth float'ları aynı hesap zincirinden geldiği için kıyas skorlaması güvenilirdir.")

node("file:spike/make_hard.py", "file", "make_hard.py",
     "Model seçiminde beraberalığı bozmak için Windows el yazısı fontlarıyla (Ink Free, Segoe Print) not ve alışveriş listesi, ayrıca düşük çözünürlük + perspektif + blur + gölge uygulanmış kötü bir telefon çekimi üreten zor fixture üreticisi.",
     ["fixture", "image-generation", "synthetic-data", "handwriting"], "moderate", filePath="spike/make_hard.py")

node("file:spike/serve.py", "file", "serve.py",
     "Aday modellerden biri için (PaddleOCR-VL-1.6 :8100 veya Qwen3-VL-8B :8101) llama-server başlatan spike script'i; Strata ile aynı kartı paylaşmak için varsayılan -ngl 0 (CPU) çalışır ve /health 200 verene kadar 120×2 saniye bekler.",
     ["spike", "model-serving", "process-management"], "moderate", filePath="spike/serve.py")

node("file:static/admin/index.html", "file", "index.html",
     "Yönetim panelinin iskeleti: ADMIN_TOKEN ile giriş ekranı, Fişler/Anahtarlar/Durum sekmeleri, arama-durum-tarih filtreli fiş tablosu ve CSV dışa aktarma, anahtar ekleme tablosu, sunucu/VRAM/kuyruk durum ızgarası ve fiş detayını gösteren dialog öğesi.",
     ["component", "ui", "admin", "single-page-app"], "complex", filePath="static/admin/index.html")

node("file:static/admin/style.css", "file", "style.css",
     "Yönetim panelinin tek stil dosyası: koyu tema renk değişkenleri, üst bar/bölüm navigasyonu/kart düzeni, tablo ve durum ızgarası bileşenleri, detay dialog'u, toast ile hata/uyarı durumları ve dar ekran kırılımları.",
     ["stylesheet", "ui", "admin", "design-tokens"], "complex", filePath="static/admin/style.css")

node("file:static/app/index.html", "file", "index.html",
     "Saha telefonları için PWA iskeleti: API anahtarı girişi, kamera/karalama alanı, kırpma adımı, kuyruk durumu ve ilerleme çubuğu, sonuç ekranı (ürün tablosu, ara toplam/iskonto/KDV/toplam, ham JSON) ile geçmiş listesi; satır içi script çevrimdışı durum çipini çizer ve service worker'ı kaydeder.",
     ["component", "ui", "pwa", "entry-point"], "complex", filePath="static/app/index.html")

node("file:static/app/manifest.webmanifest", "file", "manifest.webmanifest",
     "Fiş Çek PWA'sının kurulum bildirimi: göreli start_url/scope ile /app/ altında kalır, standalone görünüm, tr dili, koyu arka plan/tema rengi ve maskable amaçlı SVG ikonları tanımlar.",
     ["pwa", "config", "manifest", "mobile"], "simple", filePath="static/app/manifest.webmanifest")

node("file:static/app/sw.js", "file", "sw.js",
     "Kabuk service worker: install'da index/manifest/icon'u önbelleğe alır, activate'da eski öbekleri siler, fetch'te /v1, /api ve /demo yollarını bilerek ağa bırakıp diğer aynı-kaynak GET isteklerinde cache-first davranır.",
     ["pwa", "service-worker", "caching", "offline"], "moderate", filePath="static/app/sw.js",
     languageNotes="Kasıtlı olarak API ve demo yolları önbelleğe alınmaz: iş durumu ile kimlikli görünümlerin bayat önbellekten dönmesi istenmez.")

node("file:tests/__init__.py", "file", "__init__.py",
     "tests paketini tanımlayan boş başlatıcı; test modüllerinin paket adı altında import edilmesini ve pytest toplamasının kök dizine dayanmasını sağlar.",
     ["test", "package-init", "barrel"], "simple", filePath="tests/__init__.py")

node("file:tests/js/skeleton.test.js", "file", "skeleton.test.js",
     "node:test altyapısının gerçekten koştuğunu kanıtlayan 1+1=2 iskelet testi; JS testlerini çalıştıran komutun boşuna koşmadığını doğrular.",
     ["test", "smoke-test", "javascript"], "simple", filePath="tests/js/skeleton.test.js")

node("file:tests/test_skeleton.py", "file", "test_skeleton.py",
     "İskelet kontrolleri: app paketinin import edilebilirliği, beklenen klasörlerin varlığı (app, static/app, static/admin, scripts, contract, tests/js) ve temel bağımlılıkların (fastapi, httpx, jsonschema, openpyxl, PIL, pydantic, uvicorn) çözülebilirliği.",
     ["test", "smoke-test", "environment", "validation"], "simple", filePath="tests/test_skeleton.py")


# -------------------------------------------------------------- function nodes
def fn(id, name, filePath, start, end, summary, tags, complexity):
    node(id, "function", name, summary, tags, complexity, filePath=filePath, lineRange=[start, end])


fn("function:scripts/tailscale_serve.ps1:Invoke-Tailscale", "Invoke-Tailscale", "scripts/tailscale_serve.ps1", 32, 42,
   "tailscale komutunu verilen argümanlarla çalıştırır, çıktı satırlarını ekrana basar ve code/lines anahtarlı bir hashtable döndürür; -AllowFailure verilmediyse sıfır olmayan çıkış kodunda script'i sonlandırır.",
   ["powershell", "process-management", "error-handling"], "simple")

fn("function:spike/ask.py:ask", "ask", "spike/ask.py", 18, 36,
   "Görseli base64 data URL olarak mesaj içeriğine gömüp hedef porttaki /v1/chat/completions'a POST eder; metin, geçen süre ve usage bilgilerini döndürür (timeout 600 s, temperature 0).",
   ["http-client", "ocr", "vision"], "simple")

fn("function:spike/bench.py:ask", "ask", "spike/bench.py", 26, 37,
   "Bir fixture görüntüsünü prompt ile modele gönderip ham transkripsiyonu ve geçen süreyi döndürür; sıcaklık 0 ile tekrarlanabilirlik hedeflenir.",
   ["http-client", "ocr", "vision"], "simple")
fn("function:spike/bench.py:expected_tokens", "expected_tokens", "spike/bench.py", 47, 58,
   "Truth kaydından normalize edilmiş beklenen token kümesini çıkarır: dört toplam alanı, her kalemin tutarı, vergi no ve tarih.",
   ["evaluation", "normalization", "ground-truth"], "simple")
fn("function:spike/bench.py:run", "run", "spike/bench.py", 68, 83,
   "fixtures/ altındaki her truth JSON için modeli koşar, isabet/toplam ve kaçırılan token'ları basar, sonuçları spike/bench_<tag>.json'e yazar, toplam alan isabet yüzdesi ile ortalama süreyi raporlar.",
   ["benchmark", "evaluation", "reporting"], "moderate")

fn("function:spike/bench_hard.py:ask", "ask", "spike/bench_hard.py", 19, 30,
   "Görsel ve prompt çiftini hedef porttaki chat completions endpoint'ine gönderip ham çıktı metnini ve süreyi döndürür.",
   ["http-client", "ocr", "vision"], "simple")
fn("function:spike/bench_hard.py:score", "score", "spike/bench_hard.py", 45, 54,
   "Truth'ta keywords alanı varsa el yazısı, yoksa fiş kabul eder; beklenen token listesini kurup normalize çıktıda geçen ve kaçan token sayılarını döndürür.",
   ["evaluation", "normalization", "ground-truth"], "moderate")
fn("function:spike/bench_hard.py:run", "run", "spike/bench_hard.py", 57, 72,
   "fixtures_hard/ altındaki her fixture için doğru prompt'u (el yazısı mı tablo mu) seçip koşar, skorları spike/hard_<tag>.json'e yazar ve özet yüzde ile ortalama süreyi basar.",
   ["benchmark", "evaluation", "reporting"], "moderate")

fn("function:spike/bench_real.py:ask", "ask", "spike/bench_real.py", 28, 38,
   "Gerçek bir fiş veya el yazısı görüntüsünü prompt ile modele gönderip ham çıktıyı ve geçen süreyi döndürür.",
   ["http-client", "ocr", "vision"], "simple")
fn("function:spike/bench_real.py:run", "run", "spike/bench_real.py", 41, 52,
   "PROMPTS sözlüğündeki adları fixtures_real/ altında arar, bulunan her görüntü için süreyi ve ham metni toplayıp spike/real_<tag>.json olarak kaydeder.",
   ["benchmark", "reporting", "manual-review"], "simple")

fn("function:spike/live_test.py:post_image", "post_image", "spike/live_test.py", 27, 49,
   "multipart/form-data gövdesini elle kurar (boundary, Content-Disposition, Content-Type) ve X-API-Key başlığıyla POST /v1/jobs isteğini http.client ile atar; yanıtta job_id yoksa akışı sonlandırır.",
   ["http-client", "multipart", "api-client"], "moderate")
fn("function:spike/live_test.py:poll", "poll", "spike/live_test.py", 52, 60,
   "İş done veya failed durumuna gelene kadar GET /v1/jobs/{job_id} kaynağını 2 saniyede bir yoklar; timeout aşılırsa TimeoutError fırlatır.",
   ["polling", "api-client", "async-flow"], "simple")

fn("function:spike/make_fixtures.py:make_receipt", "make_receipt", "spike/make_fixtures.py", 30, 91,
   "Kalem listesinden toplamları (ara toplam, iskonto, KDV, genel toplam) deterministik hesaplar ve fişi başlık ile alt bilgi/VKN satırlarını içerecek şekilde görüntüye çizer; hem görüntüyü hem de birebir uyan truth sözlüğünü döndürür.",
   ["image-generation", "ground-truth", "fixture"], "complex")
fn("function:spike/make_fixtures.py:degrade", "degrade", "spike/make_fixtures.py", 94, 108,
   "Görüntüye rastgele döndürme, Gaussian blur, kontrast/parlaklık kaybı ve piksel bazında speckle noise uygulayarak telefonla çekilmiş fiş koşullarını simüle eder.",
   ["image-processing", "synthetic-data", "augmentation"], "moderate")

fn("function:spike/make_hard.py:base_receipt", "base_receipt", "spike/make_hard.py", 59, 85,
   "Kısa bir market fişini konsol fontlarıyla çizip ara toplam/KDV/genel toplam ile VKN ve tarih bilgisini içeren truth sözlüğünü döndürür; bozma katmanı dışında tutulduğu için insan tarafından da okunabilir kalır.",
   ["image-generation", "ground-truth", "fixture"], "moderate")

fn("function:spike/serve.py:start", "start", "spike/serve.py", 33, 50,
   "llama-server'ı seçili modelin gguf/mmproj yolları, portu, context ve -ngl değerleriyle arka plan süreci olarak başlatır, logu models/server-<ad>.log'a yönlendirir ve /health 200 verene kadar yoklar.",
   ["process-management", "model-serving", "health-check"], "moderate")

# -------------------------------------------------------------- contains + exports
for n in N:
    if n["type"] == "function":
        owner = "file:" + n["filePath"]
        edge(owner, n["id"], "contains", 1.0)
        if not n["id"].endswith("Invoke-Tailscale"):
            edge(owner, n["id"], "exports", 0.8)

# -------------------------------------------------------------- semantic edges
edge("config:contract/contract_v1.schema.json", "file:app/contract.py", "defines_schema", 0.8)
edge("config:contract/contract_v1.schema.json", "file:scripts/gen_contract_doc.py", "related", 0.5)
edge("file:spike/make_fixtures.py", "config:contract/contract_v1.schema.json", "related", 0.5)

edge("file:scripts/tailscale_serve.ps1", "file:run.py", "depends_on", 0.6)
edge("file:scripts/tailscale_serve.ps1", "file:tests/test_tailscale.py", "tested_by", 0.5)

edge("file:static/app/index.html", "file:static/app/manifest.webmanifest", "depends_on", 0.6)
edge("file:static/app/index.html", "file:static/app/sw.js", "depends_on", 0.6)
edge("file:static/app/index.html", "file:static/app/app.js", "depends_on", 0.6)
edge("file:static/admin/index.html", "file:static/admin/style.css", "depends_on", 0.6)
edge("file:static/admin/index.html", "file:static/admin/admin.js", "depends_on", 0.6)

edge("file:static/app/index.html", "file:tests/test_pwa_shell.py", "tested_by", 0.5)
edge("file:static/app/manifest.webmanifest", "file:tests/test_pwa_shell.py", "tested_by", 0.5)
edge("file:static/app/sw.js", "file:tests/test_pwa_shell.py", "tested_by", 0.5)
edge("file:app/__init__.py", "file:tests/test_skeleton.py", "tested_by", 0.5)

edge("file:spike/bench.py", "file:spike/make_fixtures.py", "related", 0.5)
edge("file:spike/bench_hard.py", "file:spike/make_hard.py", "related", 0.5)
edge("file:spike/bench_real.py", "file:spike/crop_hand.py", "related", 0.5)
edge("file:spike/serve.py", "file:spike/get_llama.py", "related", 0.5)
edge("file:spike/ask.py", "file:spike/serve.py", "related", 0.5)
edge("file:spike/bench.py", "file:spike/serve.py", "related", 0.5)
edge("file:spike/live_test.py", "file:app/keys_cli.py", "depends_on", 0.6)

# -------------------------------------------------------------- checks + write
ids = [n["id"] for n in N]
assert len(ids) == len(set(ids)), "duplicate node ids"
file_nodes = {n["filePath"] for n in N if n["type"] in ("file", "config")}
batch = {f["path"] for f in json.load(open(".ua/tmp/dispatch/batch-12-files.json", encoding="utf-8"))}
assert file_nodes == batch, (batch - file_nodes, file_nodes - batch)
imports_edges = sum(1 for e in E if e["type"] == "imports")
assert imports_edges == 0, imports_edges

with open(".ua/intermediate/batch-12.json", "w", encoding="utf-8") as f:
    json.dump({"nodes": N, "edges": E}, f, ensure_ascii=False, indent=1)

print("nodes", len(N), "edges", len(E))
print(Counter(e["type"] for e in E))
