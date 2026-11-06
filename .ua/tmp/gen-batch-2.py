"""Generate batch-2 graph fragments from the extraction results."""
import json
import math
import pathlib

ROOT = pathlib.Path(r"C:/Users/PC/Documents/GitHub/ocr-app")
UA = ROOT / ".ua"
res = json.loads((UA / "tmp/ua-file-extract-results-2.json").read_text(encoding="utf-8"))
inp = json.loads((UA / "tmp/batch-input-2.json").read_text(encoding="utf-8"))
IMPORTS = inp["batchImportData"]
BY_PATH = {r["path"]: r for r in res["results"]}


def rng(path, name, kind="fn"):
    r = BY_PATH[path]
    items = r.get("functions", []) if kind == "fn" else r.get("classes", [])
    for it in items:
        if it["name"] == name:
            return [it["startLine"], it["endLine"]]
    raise SystemExit(f"missing {kind} {path}:{name}")


nodes = []
edges = []


def node(id, type, name, summary, tags, complexity, filePath=None, lineRange=None,
         languageNotes=None):
    n = {"id": id, "type": type, "name": name, "summary": summary, "tags": tags,
         "complexity": complexity}
    if filePath:
        n["filePath"] = filePath
    if lineRange:
        n["lineRange"] = lineRange
    if languageNotes:
        n["languageNotes"] = languageNotes
    nodes.append(n)


def edge(source, target, type, weight):
    assert source != target, source
    edges.append({"source": source, "target": target, "type": type,
                  "direction": "forward", "weight": weight})


def f(path, summary, tags, complexity, notes=None):
    node(f"file:{path}", "file", path.rsplit("/", 1)[-1], summary, tags, complexity,
         filePath=path, languageNotes=notes)


def klass(path, name, summary, tags, complexity, exported=True):
    cid = f"class:{path}:{name}"
    node(cid, "class", name, summary, tags, complexity, filePath=path,
         lineRange=rng(path, name, "cls"))
    edge(f"file:{path}", cid, "contains", 1.0)
    if exported:
        edge(f"file:{path}", cid, "exports", 0.8)
    return cid


def func(path, name, summary, tags, complexity, exported=True):
    fid = f"function:{path}:{name}"
    node(fid, "function", name, summary, tags, complexity, filePath=path,
         lineRange=rng(path, name, "fn"))
    edge(f"file:{path}", fid, "contains", 1.0)
    if exported:
        edge(f"file:{path}", fid, "exports", 0.8)
    return fid


# ---------------------------------------------------------------- app/config.py
f("app/config.py",
  "Tüm ayarların tek merkezi: her ortam değişkenini tipli bir değere (str/int/float/Path) çevirir ve "
  "PLAN.md'deki güvenli varsayılanıyla döndürür; sırlar (ADMIN_TOKEN) boş olmayan varsayana sahip değildir.",
  ["yapılandırma", "environment", "utility", "tek-merkez"], "moderate",
  "os.environ'ı okuyan tek modül: her ayar küçük bir erişim fonksiyonu olarak tembel okunur, böylece "
  "testler monkeypatch ile ortamı değiştirdiğinde değer anında yeniden çözülür. Göreceli yollar proje "
  "köküne göre çözümlenir.")

# -------------------------------------------------------------- app/contract.py
f("app/contract.py",
  "Contract v1'in Pydantic şekilleri: fiş sonucu (Result), doğrulama bloğu (Validation) ve iş zarfı "
  "(JobEnvelope). Her alan bir ev varsayılanıyla geldiği için kısmi model çıktısı da eksiksiz bir nesneye dönüşür.",
  ["data-model", "schema-definition", "contract", "validasyon"], "moderate",
  "Annotated + BeforeValidator ile alan tipleri (Text/Amount/Rate) fişin bastığı biçimleri tek ortak "
  "parserdan (app.numbers) geçirir; _null_is_missing ile null, alan yok demek sayılır.")
CM = "class:app/contract.py:_Model"
node(CM, "class", "_Model",
     "Tüm contract modellerinin tabanı: null değerleri 'yok sayılır' süzgecinden geçirir ve kısmi veriden "
     "tam nesne üreten parse() sınıf metodunu sağlar.",
     ["data-model", "base-class", "pydantic"], "simple", filePath="app/contract.py",
     lineRange=rng("app/contract.py", "_Model", "cls"))
edge("file:app/contract.py", CM, "contains", 1.0)
C = {}
C["Header"] = klass("app/contract.py", "Header",
                    "Fiş başlığı: firma adı, vergi dairesi ve vergi numarası; vergi_no sayı olarak gelse de metne döner.",
                    ["data-model", "contract", "seri-devresi"], "simple")
C["ReceiptMeta"] = klass("app/contract.py", "ReceiptMeta",
                         "Fişin üst bilgisi: tarih, saat, fiş no ve tip alanları.",
                         ["data-model", "contract", "meta"], "simple")
C["Item"] = klass("app/contract.py", "Item",
                  "Tek kalem satırı: ad, miktar, birim fiyat ve satır toplamı; tutarlar fişin bastığı biçimden normalize edilir.",
                  ["data-model", "contract", "para-birimi"], "simple")
C["Totals"] = klass("app/contract.py", "Totals",
                    "Fişin toplam bloğu: ara toplam, iskonto, KDV, KDV oranı ve genel toplam.",
                    ["data-model", "contract", "para-birimi"], "simple")
C["Result"] = klass("app/contract.py", "Result",
                    "Aşama 2'nin ürettiği sözleşme sonucu: başlık, meta, kalemler, toplamlar, para birimi ve "
                    "okunamayan listesi. Validator'ın girdisi ve iş kaydının result bloğu budur.",
                    ["data-model", "contract", "dogrulama"], "moderate")
C["TotalsBlock"] = klass("app/contract.py", "TotalsBlock",
                         "Validator'ın kalemlerden yeniden hesapladığı dört tutar; beklenen ve gerçek taraflar aynı bloğu kullanır.",
                         ["data-model", "contract", "dogrulama"], "simple")
C["Validation"] = klass("app/contract.py", "Validation",
                        "Doğrulama sonucu: verdict (ok/mismatch/unreadable), beklenen ve gerçek tutar blokları ile uyuşmayan alan adları. "
                        "Verdict yoksa varsayılan unreadable'dır, asla ima edilen ok değildir.",
                        ["data-model", "contract", "dogrulama"], "simple")
C["JobMeta"] = klass("app/contract.py", "JobMeta",
                     "İşin çalışma meta verisi: çalışan adı, çekim/alım zamanları, OCR ve toplam süreler, kullanılan model ve kalite modu.",
                     ["data-model", "contract", "meta"], "simple")
C["JobEnvelope"] = klass("app/contract.py", "JobEnvelope",
                         "API'lerin dışa verdiği iş zarfı: job_id, durum, client_ref, sonuç, doğrulama ve meta. "
                         "JSON Şema bu modelden üretilir.",
                         ["data-model", "contract", "api-schema"], "simple")
for name in ("Header", "ReceiptMeta", "Item", "Totals", "Result", "TotalsBlock",
             "Validation", "JobMeta", "JobEnvelope"):
    edge(C[name], CM, "inherits", 0.9)
func("app/contract.py", "schema_text",
     "İş zarfını kök alan JSON Schema (draft 2020-12) metnini bayt-deterministik üretir; sort_keys sayesinde "
     "yeniden üretim aynı baytları verir.",
     ["schema-definition", "serializasyon", "contract"], "simple")
for fn in ("_lowered", "_to_text", "_to_amount", "_to_rate"):
    func("app/contract.py", fn,
         "Alan tipi dönüştürücü: " + {
             "_lowered": "durum ve verdict değerlerini küçük harfe indirir.",
             "_to_text": "None'ı boş metne, sayısal vergi no'yu metne çevirir.",
             "_to_amount": "fişin bastığı tutarı (1.046,40 / 149,00-) float'a çevirir; okunamayansa 0.0.",
             "_to_rate": "KDV oranını kesre çevirir (%20 -> 0.2); okunamayansa 0.0.",
         }[fn],
         ["parser", "donusum", "contract"], "simple", exported=False)

# ------------------------------------------------------------ app/ocr_client.py
f("app/ocr_client.py",
  "Aşama 1: görüntüyü llama-server'ın OpenAI uyumlu /v1/chat/completions ucunda PaddleOCR-VL'ye gönderir ve "
  "ham masa metnini süreyle birlikte döndürür.",
  ["api-client", "ocr", "stage-1", "servis"], "simple",
  "Dış sınırı tek bir httpx.Client; testler transport enjekte ederek model çıktılarını HTTP katmanında yeniden oynatır.")
OE = klass("app/ocr_client.py", "OcrError",
           "OCR sunucusu arızası: zaman aşımı, bağlantı hatası, 2xx dışı yanıt veya bozuk gövde. Aşama 1'i failed iş yapar.",
           ["exception", "hata-yonetimi", "ocr"], "simple")
OC = klass("app/ocr_client.py", "OcrClient",
           "PaddleOCR-VL HTTP istemcisi: görüntüyü base64 data URL yapıp 'Table Recognition:' istemiyle gönderir, "
           "metni ve geçen süreyi döner.",
           ["api-client", "ocr", "stage-1", "servis"], "moderate")

# ---------------------------------------------------------------- app/pipeline.py
f("app/pipeline.py",
  "Aşama 1 → 2 → 3 orkestrasyonu: bir görüntü girer, sözleşmeye uygun {result, validation, meta, error} demeti çıkar. "
  "Raporlanan her tutarı validator kalemlerden yeniden hesaplar; modelin kendi toplamları yalnızca 'gerçek' tarafı olur.",
  ["orchestration", "pipeline", "entry-point", "dogrulama"], "moderate",
  "Kötü foto veya çökmüş model sunucusu için asla istisna fırlatmaz — her yol bir demet döner, böylece hiçbir iş "
  "görüşlerin beklediği nesnenin olduğu yerde boşluk taşımaz.")
run = func("app/pipeline.py", "run",
           "Üç aşamayı tek görüntü üzerinde çalıştırır: OCR metnini yapılandırıcıya verir, çıkan sözlüğü contract.Result "
           "ile süzer, sonra validator ile demeti kurar. UnreadableError işi done+unreadable yapar; diğer aşama 2 arızaları failed.",
           ["orchestration", "pipeline", "hata-yonetimi"], "complex")
bundle = func("app/pipeline.py", "_bundle",
              "Demeti kurar: sonucu (yoksa boş Result) validator'dan geçirir, JobMeta'ya model/süre/kalite modunu yazar ve "
              "hata satırını taşır.",
              ["factory", "pipeline", "dogrulama"], "moderate", exported=False)
_default = func("app/pipeline.py", "_default_structurer",
                "Kalite moduna göre gerçek Structurer'ı tembel içe aktarımla kurar; enjekte edilen istemciler bu modüle bağımlı kalmaz.",
                ["factory", "pipeline", "lazy-import"], "simple", exported=False)
_reason = func("app/pipeline.py", "_reason",
               "Modelin şikâyetini PWA ve yönetici panelinin taşıyabileceği tek satıra indirir (REASON_MAX_CHARS).",
               ["utility", "metin", "pipeline"], "simple", exported=False)
_ms = func("app/pipeline.py", "_ms",
           "OCR'ın bildirdiği süreyi güvenli pozitif tam sayıya çevirir; bozuk değer 0 olur.",
           ["utility", "donusum", "pipeline"], "simple", exported=False)
VAL = "function:app/validator.py:validate"
edge(bundle, VAL, "calls", 0.8)
edge(run, "class:app/structurer.py:Structurer", "calls", 0.8)
edge(run, "class:app/ocr_client.py:OcrClient", "calls", 0.8)
edge(_default, "class:app/structurer.py:Structurer", "calls", 0.8)

# ----------------------------------------------------------- app/queue_worker.py
f("app/queue_worker.py",
  "SQLite kuyruğunu tüketen tek iş parçacığı: queued → running → done/failed. Kuyruk jobs tablosunun kendisidir; "
  "crash sonrası recover() çalışan işleri ya kuyruğa geri koyar ya da bayat sayıp failed yapar.",
  ["worker", "queue", "concurrency", "servis"], "complex",
  "sqlite bağlantısı iş parçacıkları arasında paylaşılamadığı için bağlantı threading.local'de tutulur; "
  "runner tek dikiş yeri olduğundan testler pipeline yerine sahte çalıştırıcı enjekte eder.")
recover = func("app/queue_worker.py", "recover",
               "Yeniden başlama temizliği: running işlerin sahibi artık yok. Yaşı az olanlar kuyruğa döner, "
               "stale_job_minutes'i aşanlar aynı çökmeye sonsuz kez girmesin diye failed işaretlenir.",
               ["hata-kurtarma", "queue", "restart"], "moderate")
QW = klass("app/queue_worker.py", "QueueWorker",
           "Kuyruğu boşaltan daemon iş parçacığı: start() önce recover() çalıştırır, run_once() en eski sıradaki işi "
           "kapıp işler, stop() uçtaki işi bitirir. Demette hata varsa iş failed; okunamayan fiş hatasız geldiği için done kalır.",
           ["worker", "queue", "concurrency"], "complex")
edge(recover, "function:app/db.py:list_jobs", "calls", 0.8)
edge(recover, "function:app/db.py:set_status", "calls", 0.8)
edge(QW, run, "calls", 0.8)
for fn in ("_cutoff",):
    func("app/queue_worker.py", fn,
         "stale kesim zamanını job zaman damgarının biçiminde (Z sonekli ISO) üretir.",
         ["utility", "tarih", "queue"], "simple", exported=False)

# ------------------------------------------------------------- app/structurer.py
f("app/structurer.py",
  "Aşama 2: OCR metni ve fiş görüntüsünü Strata'ya (:8080, kalite modunda Unsloth Studio :8888) gönderip "
  "contract v1 sonucu üretir. Burada hiçbir tutar hesaplanmaz; model fişin yazdığını aktarır, aritmetiği validator sahibi çıkar.",
  ["stage-2", "api-client", "llm", "parser"], "complex",
  "Reasoning modeli olan Strata'ya enable_thinking=False gönderilir: bayrak olmadan bütçenin tamamı "
  "reasoning_content'e gidiyor ve content=null döndüğü için her gerçek fiş okunamayan sayılıyordu (T68). "
  "Model geveziliği (think bloğu, ```json çiti, fazladan virgül) savunmacı JSON çıkarmayla temizlenir.")
SE = klass("app/structurer.py", "StructurerError",
           "Yapılandırma sunucusu arızası: zaman aşımı, bağlantı hatası, 2xx dışı yanıt veya bozuk gövde.",
           ["exception", "hata-yonetimi", "stage-2"], "simple")
UE = klass("app/structurer.py", "UnreadableError",
           "Model çıktısı sözleşmeye uygun bir sonuç olamıyor: bu bir iş kararı (unreadable verdict), altyapı arızası değil.",
           ["exception", "hata-yonetimi", "verdict"], "simple")
ST = klass("app/structurer.py", "Structurer",
           "Aşama 2 istemcisi: kalite moduna göre sunucu/modeli seçer, OCR metniyle görüntüyü tek mesajda gönderir, "
           "çıkan JSON'u contract'tan geçirerek sonuç olup olmadığına karar verir.",
           ["api-client", "stage-2", "llm", "routing"], "complex")
edge(UE, SE, "inherits", 0.9)
ej = func("app/structurer.py", "extract_json",
          "Model yanıtının içindeki sözleşme nesnesini çıkarır: think/reasoning etiketlerini siler, ```json çitinin "
          "sondakini tercih eder, hiçbir nesne yoksa UnreadableError fırlatır.",
          ["parser", "json", "dayaniklilik"], "moderate")
fo = func("app/structurer.py", "_first_object",
          "Gürültülü bir metindeki ilk çözülebilir JSON nesnesini bulur: her '{' kendi denemesini açar ve sondaki "
          "fazladan virgüller onarılarak ikinci bir tur denenir.",
          ["parser", "json", "onarma"], "moderate", exported=False)
edge(ST, ej, "calls", 0.8)

# --------------------------------------------------------- scripts/fake_models.py
f("scripts/fake_models.py",
  "İki model rolü için OpenAI uyumlu sahte sunucular: OCR rolü fixture ground truth'tan türetilmiş Paddle tarzı "
  "tablo metnini, yapılandırma rolü fixture JSON'unun kendisini gerçek soket üzerinden geri verir.",
  ["test-altyapisi", "mock", "http-server", "demo"], "complex",
  "Uygulama kodu bu modülü asla içe aktarmaz; sadece smoke ve demo gerçek HTTP, gerçek kuyruk ve gerçek pipeline "
  "üzerinden koşsun diye vardır. Görüntü sha256 ile, metin de son OCR eşiyle eşleştirilir.")
render = func("scripts/fake_models.py", "render_ocr_text",
              "Ground truth sonucunu PaddleOCR-VL'ın 'Table Recognition' çıktısına benzer metne çevirir "
              "(<fcel>/<nl> ayraçları, Türkçe tutar biçimi 1.046,40).",
              ["fixture", "metin-uretimi", "ocr"], "moderate")
Fixture = klass("scripts/fake_models.py", "Fixture",
                "Tek fixture'ın üç yüzü: adı, ground truth sonucu, ondan türetilmiş OCR metni ve görüntüsünün sha256 özeti.",
                ["data-model", "fixture", "veri-yapisi"], "simple")
FB = klass("scripts/fake_models.py", "FixtureBook",
           "Tüm fixture ground truth'larını hem görüntü baytlarına hem OCR metnine göre bulunur kılar; metin "
           "eşleşmezse OCR rolünün son servis ettiği fixture'a düşer.",
           ["fixture", "arama", "test-altyapisi"], "moderate")
_completion = func("scripts/fake_models.py", "_completion",
                  "OpenAI chat.completion gövdesi biçiminde sabit bir yanıt kurar.",
                  ["fixture", "http", "seri-devresi"], "simple", exported=False)
_last_message = func("scripts/fake_models.py", "_last_message",
                     "İstek gövdesindeki son mesajın (görüntü data URL, birleştirilmiş metin) ikilisini çıkarır; "
                     "metin içerikli veya çok parçalı içeriklerin ikisini de idare eder.",
                     ["parser", "http", "test-altyapisi"], "moderate", exported=False)
_H = klass("scripts/fake_models.py", "_Handler",
           "Sahte sunucunun HTTP tutucusu: /v1/chat/completions isteğinin rolüne bakıp OCR metni ya da fixture JSON'u "
           "döner, /v1/models ile yalnızca beklenen model kimliğini bildirir.",
           ["http-handler", "mock", "test-altyapisi"], "moderate", exported=False)
FMS = klass("scripts/fake_models.py", "FakeModelServer",
            "Tek rolü gerçek bir sokette (port 0 geçici port) ThreadingHTTPServer ile dinleyen sahte model sunucusu.",
            ["http-server", "mock", "test-altyapisi"], "moderate")
FM = klass("scripts/fake_models.py", "FakeModels",
           "OCR ve yapılandırma sahti çiftini birlikte açıp kapatmak için ince sarmalayıcı.",
           ["test-altyapisi", "factory", "mock"], "simple")
sfm = func("scripts/fake_models.py", "start_fake_models",
           "Fixture kitabını yükleyip iki rolün sahte sunucusunu açar ve çift olarak döner.",
           ["factory", "test-altyapisi", "giris-noktasi"], "simple")
edge(FMS, "class:scripts/fake_models.py:_Handler", "depends_on", 0.6)
edge(sfm, FB, "calls", 0.8)
edge(FB, render, "calls", 0.8)

# ---------------------------------------------------------- scripts/serve_demo.py
f("scripts/serve_demo.py",
  "Demo sunucusu: gerçek uygulamayı (auth, SQLite kuyruğu, worker, pipeline, validator) sahte model "
  "çıkartılarıyla :8090'da kaldırır ve her fixture'ı farklı kuyruk durumu/verdict ile tohumlar; böylece kameraya ve "
  "model sunucusuna gerek kalmadan her ekran veri görür.",
  ["demo", "entry-point", "gelistirme", "tohumlama"], "complex",
  "--check modu geçici portta kaldırıp /app, /admin, /api/me/jobs yoklayıp 0 döner; bu sayede kapı, 8090'da bir demo "
  "zaten koşarken çalışabilir.")
DemoError = klass("scripts/serve_demo.py", "DemoError",
                  "Ters giden ilk şey; mesajı raporun tamamıdır.",
                  ["exception", "hata-yonetimi", "demo"], "simple")
rf = func("scripts/serve_demo.py", "_result_for",
          "Fixture ground truth'unu contract.Result'a çevirir; fixtures_hard şekilleri sözleşmeye uymazsa boş Result "
          "döner (okunamayan yolunu göstermek için), bozuk tutarlı fixture'da toplam 5 TL kaydırılır.",
          ["fixture", "tohumlama", "demo"], "moderate", exported=False)
seed = func("scripts/serve_demo.py", "seed_jobs",
            "Her işlenmiş fixture için bir iş satırı açar: temizler done/ok, karıştırılmış olan uyuşmazlık panelini, "
            "zorlar unreadable, biri failed, ikisi kuyrukta/çalışan olarak canlı görünümleri besler.",
            ["tohumlama", "demo", "queue"], "moderate")
DW = klass("scripts/serve_demo.py", "DemoWorker",
           "Gerçek worker'ın demo hâli: tohumlanan canlı işleri sahiplenmez ve recover() onların durumunu bozduktan "
           "sonra geri geri yazar; 'Örnek fiş' yüklemeleri ise aynı kuyruktan geçmeye devam eder.",
           ["worker", "demo", "subclass"], "moderate")
mr = func("scripts/serve_demo.py", "_model_runner",
          "Gerçek pipeline'ı sahte sunuculara bakacak şekilde tek bir çalıştırıcıda birleştirir; kuyruk worker'ı ile "
          "yönetici kalite-yeniden-koşturma yolu bu tek çalıştırıcıyı paylaşır.",
          ["factory", "pipeline", "demo"], "moderate", exported=False)
adr = func("scripts/serve_demo.py", "_add_demo_routes",
           "PWA'nın demo el sıkışması için /demo/config.json ve /demo/samples/{name} rotalarını ekler; /v1 ve /api "
           "dışındadır çünkü PWA anahtarı almadan yapılandırmayı okumak zorundadır.",
           ["api-handler", "demo", "rota"], "moderate", exported=False)
serve = func("scripts/serve_demo.py", "_serve",
             "Uygulamayı ayrı iş parçacığında uvicorn ile kaldırır ve 30 saniyelik bir bütçeyle hazır olmasını bekler.",
             ["server", "uvicorn", "demo"], "moderate", exported=False)
boot = func("scripts/serve_demo.py", "_boot",
            "Her şeyi yukarı kaldırır: geçici veri dizini, tohumlanmış veritabanı ve anahtar, sahte sunucular, "
            "uygulama ve worker; sunucu/worker/modeller/api_key döndürür.",
            ["bootstrap", "demo", "giris-noktasi"], "moderate", exported=False)
chk = func("scripts/serve_demo.py", "_check",
           "Demo'nun ayağa kalktığını /app, /admin ve /api/me/jobs yoklayarak doğrular; tohumlanmış anahtar iş "
           "görmüyorsa hatalı sayar.",
           ["saglik-kontrolu", "demo", "dogrulama"], "moderate", exported=False)
smain = func("scripts/serve_demo.py", "main",
             "Komut satırı girişi: --check yoklama modunu, yoksa inceleme modunu çalıştırır; geçici dizinde kaldırır, "
             "worker ve modelleri finally'da kapatır, sonuç kodunu döner.",
             ["cli", "entry-point", "demo"], "moderate")
edge(DW, "class:app/queue_worker.py:QueueWorker", "inherits", 0.9)
edge(mr, run, "calls", 0.8)
edge(boot, "function:app/main.py:create_app", "calls", 0.8)
edge(boot, "function:app/auth.py:create_key", "calls", 0.8)
edge(boot, seed, "calls", 0.8)
edge(boot, sfm, "calls", 0.8)
edge(smain, boot, "calls", 0.8)
edge(smain, chk, "calls", 0.8)

# ---------------------------------------------------------- scripts/smoke_e2e.py
f("scripts/smoke_e2e.py",
  "Gerçek HTTP üzerinden uçtan uca duman testi: uygulamayı geçici portta sahte model çıkartılarıyla kaldırır, "
  "fixtures/fis_market_clean.png'yi gerçek soketle yükler, işi done olana kadar yoklar ve gördüğü her zarfı "
  "commit'lenmiş contract_v1.schema.json'a karşı doğrular.",
  ["test-altyapisi", "e2e", "dogrulama", "ci-cd"], "complex",
  "HTTP katmanının altında hiçbir şey sahte değil; kırık bir rota, kuyruk, aşama ya da sözleşme sıfır olmayan çıkış "
  "koduyla görünür — run.py ve CI bu çıkış koduna kapı olur.")
SmokeError = klass("scripts/smoke_e2e.py", "SmokeError",
                   "Ters giden ilk şey; mesajı raporun tamamıdır.",
                   ["exception", "hata-yonetimi", "e2e"], "simple")
App = klass("scripts/smoke_e2e.py", "_App",
            "uvicorn sunucusunu ana iş parçacığı dışında geçici portta çalıştıran sarmalayıcı; start/stop ile işi kolaylaştırır.",
            ["server", "test-altyapisi", "sarmalayici"], "moderate", exported=False)
senv = func("scripts/smoke_e2e.py", "_strata_env",
            "Aşama 2'nin Stub URL'sini işaretlesin diye ortam değişkenlerini ayarlar; böylece servis edilen uygulama "
            "bile sahte yapılandırma sunucusuna bakar.",
            ["environment", "test-altyapisi", "e2e"], "moderate", exported=False)
sw = func("scripts/smoke_e2e.py", "_start_worker",
          "Gerçek QueueWorker'ı sahte modellere bakan bir çalıştırıcıyla başlatır; işler gerçekten kuyruktan geçer.",
          ["worker", "test-altyapisi", "e2e"], "moderate", exported=False)
sv = func("scripts/smoke_e2e.py", "_validated",
          "Yanıt gövdesini commit'lenmiş JSON Schema ile doğrular; sözleşme dışı bir zarf duman testini kırar.",
          ["dogrulama", "schema-definition", "e2e"], "moderate", exported=False)
sub = func("scripts/smoke_e2e.py", "_submit",
           "Fixture görüntüsünü gerçek bir POST ile yükler ve iş kimliğini döner.",
           ["http-client", "e2e", "test-altyapisi"], "moderate", exported=False)
poll = func("scripts/smoke_e2e.py", "_poll_to_done",
            "İş done (veya failed) olana kadar hem API'den hem veritabanından yoklar; zaman aşımında SmokeError.",
            ["polling", "e2e", "kuyruk"], "moderate", exported=False)
schk = func("scripts/smoke_e2e.py", "_check",
            "Dönen zarfı sözleşme, verdict ve ground truth tutarları üzerinden denetler; uyuşmazlık sıfır olmayan çıkış demek.",
            ["dogrulama", "e2e", "veri-tutarligi"], "moderate", exported=False)
srun = func("scripts/smoke_e2e.py", "_run",
            "Geçici dizinde tüm yığını kurar: sahte sunucular, uygulama, worker; yükleyip yoklar, sonra hepsini toplar.",
            ["bootstrap", "e2e", "test-altyapisi"], "moderate", exported=False)
smoke_main = func("scripts/smoke_e2e.py", "main",
                  "_run'ı çağırıp sonucu adım adım loglar; arıza durumunda adım adı ve mesajla sıfır olmayan kod döner.",
                  ["cli", "entry-point", "e2e"], "moderate")
edge(sw, "class:app/queue_worker.py:QueueWorker", "calls", 0.8)
edge(sw, run, "calls", 0.8)
edge(srun, sfm, "calls", 0.8)
edge(srun, "function:app/main.py:create_app", "calls", 0.8)
edge(schk, VAL, "calls", 0.8)
edge(smain, srun, "calls", 0.8)

# ------------------------------------------------------------------- spike/*
f("spike/probe_stage2.py",
  "Canlı sunuculara karşı elle çalıştırılan aşama 1 + aşama 2 sondası: gerçek fişte OCR çıktısını, Strata'nın ham "
  "yanıtını ve extract_json'ın onu çıkarıp çıkaramadığını olduğu gibi basar.",
  ["spike", "debug", "probe", "stage-2"], "simple",
  "Tek seferlik inceleme betiği; sabit mutlak yollar ve sys.path hilesi kullanır, üretime girmez.")
f("spike/probe_thinking.py",
  "Strata'da reasoning'i kapatan istek gövdesi anahtarını bulmaya yönelik ilk sondalar: birden çok 'thinking' "
  "bayrağı biçimini deneyip content ve reasoning_content'i karşılaştırır.",
  ["spike", "debug", "llm", "reasoning"], "simple")
f("spike/probe_thinking2.py",
  "Gerçek fiş görüntüsüyle aşama 2 sondası: max_tokens ve thinking bayrağı kombinasyonlarının finish_reason, "
  "content uzunluğu ve reasoning_content üzerindeki etkisini ölçer — T68'deki content=null kök nedeninin bulunması.",
  ["spike", "debug", "llm", "reasoning"], "simple")
f("spike/probe_thinking3.py",
  "Metin-only ufak isteklerle hangi bayrağın reasoning'i gerçekten kestiğini ayıran son sonda; chat_template_kwargs "
  "içindeki enable_thinking'in kazanan anahtar olduğunu doğrular.",
  ["spike", "debug", "llm", "reasoning"], "simple")
func("spike/probe_thinking.py", "try_body",
     "Verilen ek alanlarla Strata'ya bir chat isteği gönderir ve content/reasoning_content durumunu etiketle basar.",
     ["probe", "llm", "debug"], "simple", exported=False)
func("spike/probe_thinking2.py", "run",
     "Gerçek fiş görseli ve OCR metniyle Strata'yı çağırır; finish_reason, content uzunluğu ve reasoning uzunluğunu "
     "raporlayıp çıkan içeriği extract_json ile de dener.",
     ["probe", "llm", "debug"], "moderate", exported=False)
edge("file:spike/probe_thinking2.py", "function:app/structurer.py:extract_json", "calls", 0.8)
edge("file:spike/probe_stage2.py", "function:app/structurer.py:extract_json", "calls", 0.8)
edge("file:spike/probe_stage2.py", "class:app/ocr_client.py:OcrClient", "calls", 0.8)

# ------------------------------------------------------------------- tests/*
f("tests/test_config.py",
  "app/config.py'nin sözleşmesini sınar: PLAN.md ile birebir varsayılanlar, tipli getiricilerin ortamı çözümlemesi, "
  "geçersiz değerlerin varsayılana düşmesi ve bu projeye ait OCR_*/STRATA_* gibi öneklerin belgelenmiş olması.",
  ["test", "yapılandırma", "environment"], "moderate")
f("tests/test_contract.py",
  "Contract v1 şekillerinin testi: boş/eksik/null girdinin ev varsayılanlarıyla tam nesne üretmesi, Türkçe tutar ve "
  "oran biçimlerinin normalize edilmesi, iş zarfı varsayılanları ve geçersiz durumda hata vermesi.",
  ["test", "contract", "data-model"], "moderate")
f("tests/test_fake_models.py",
  "Sahte model sunucularının testi: fixture kitabının tüm ground truth'ları kapsaması, render_ocr_text'in Paddle "
  "biçimini üretmesi ve açılan sahte sunucuların gerçek OcrClient tarafından kullanılabilmesi.",
  ["test", "test-altyapisi", "mock"], "moderate")
f("tests/test_integration_m1.py",
  "M1 entegrasyonu: gerçek fixture PNG'si gerçek uygulamaya yüklenir, auth gerçek anahtarı doğrular, gerçek worker "
  "SQLite kuyruğunu boşaltır ve validator aritmetiği yeniden hesaplar. Tek sahte, httpx transport düzeyindeki iki model yanıtıdır.",
  ["test", "entegrasyon", "pipeline"], "complex")
f("tests/test_ocr_client.py",
  "Aşama 1 istemcisinin testi: istek gövdesinin chat/completions sözleşmesi, görüntünün base64 data URL olması, "
  "Paddle istemi ve max_tokens, kalite modunun aynı uç noktayı kullanması ve hata yollarının OcrError olması.",
  ["test", "api-client", "ocr"], "moderate")
f("tests/test_pipeline.py",
  "Üç aşamanın sırası ve sahipliğinin testi: OCR → yapılandırıcı → validator akışı, beklenen toplamların kalemlerden "
  "yeniden hesaplanması, model tutarlarının yalnızca gerçek tarafı olması ve modelin zarfa verdict/validation sızdıramaması.",
  ["test", "pipeline", "dogrulama"], "complex")
f("tests/test_smoke_real_structurer.py",
  "Kaynak kodu AST ile okuyan bekçı: scripts/smoke_e2e.py el yapımı bir aşama 2 isteği kurmak yerine gerçek "
  "app.structurer'ı kullanmalı; aksi hâlde servis edilen istemci bozulurken duman testi yeşil kalır.",
  ["test", "bekci", "ast", "regresyon"], "simple",
  "Modülü çalıştırmadan AST ile içe aktarımları ve tanımlı isimleri sayar; bu, bir duman testinin kendi "
  "ikamesini yazması sınıfı hataya kalıcı olarak geçit vermez.")
f("tests/test_structurer.py",
  "Aşama 2 istemcisinin geniş testi: istek gövdesi ve yönlendirmesi (Strata/Unsloth), enable_thinking bayrağı, OCR "
  "metni ile görüntünün birlikte gitmesi, savunmacı JSON çıkarma ve okunamayan/hata ayrımı.",
  ["test", "stage-2", "api-client", "llm"], "complex")
f("tests/test_tailscale.py",
  "scripts/tailscale_serve.ps1 betiğini çalıştırmadan ayrıştırır ve README'deki belgeleri ayrıştırma sonucuna karşı "
  "denetler; port, sertifika yolu ve geri alma komutu betikten ayrılamaz.",
  ["test", "belge-uyumu", "powershell", "tailnet"], "moderate")
f("tests/test_unreadable_survives.py",
  "Okunamayan fişin bir verdict olduğunu uçtan uca savunur: aşama 2'nin UnreadableError'ı demetin error alanına "
  "dönüşürse worker işi failed yapar ve okunamayan verdict, yeniden çekim önerisi ile entegratör gerekçesi kaybolur.",
  ["test", "regresyon", "verdict", "pipeline"], "moderate")

# --- test dosyalarının anlamlı fonksiyon/sınıfları
for nm, sm in [
    ("test_defaults_match_brief", "PLAN.md'nin belirlediği varsayılanların config'de birebir aynı olduğunu doğrular."),
    ("test_typed_getters_parse_env", "monkeypatch ile ortamı doldurup tipli getiricilerin (int/float/path) değerleri doğru çözdüğünü sınar."),
]:
    func("tests/test_config.py", nm, sm, ["test", "yapılandırma", "varsayılanlar"], "moderate", exported=False)
for nm, sm in [
    ("test_empty_dict_gets_house_defaults", "Boş sözlükten tüm alanları ev varsayılanlarıyla dolu bir Result üretir."),
    ("test_none_is_the_same_as_missing", "null gelen alanın alan yok sayıldığını ve varsayılanın kazandığını sınar."),
    ("test_fixture_shape_parses_whole", "Gerçek fixture sözlüğünün baştan sona geçerli bir Result'a dönüştüğünü doğrular."),
    ("test_envelope_defaults", "İş zarfının varsayılanları: queued durumu, boş meta ve null sonuç/doğrulama."),
    ("test_envelope_carries_result_and_validation", "Zarfla birlikte sonuç ve doğrulama bloklarının da taşındığını doğrular."),
]:
    func("tests/test_contract.py", nm, sm, ["test", "contract", "data-model"], "moderate", exported=False)
func("tests/test_fake_models.py", "test_fixture_book_covers_every_ground_truth",
     "Fixture kitabının işlenmiş her fixture'ı hem görüntü baytlarıyla hem OCR metniyle bulunur kıldığını doğrular.",
     ["test", "fixture", "test-altyapisi"], "moderate", exported=False)

for nm, sm, tg in [
    ("env", "tmp_path ve monkeypatch ile yalıtılmış bir uygulama+veritabanı ortamı kuran pytest fixture'ı.", ["fixture", "test-altyapisi"]),
    ("start_worker", "Sahte model yanıtlarıyla gerçek QueueWorker'ı başlatan yardımcı; KDV'yi tahrif etme seçeneği de var.", ["fixture", "worker", "test-altyapisi"]),
    ("poll", "İş done/failed olana kadar API'den yoklayan zaman aşımlı yardımcı.", ["polling", "test-altyapisi"]),
    ("test_fixture_image_travels_the_whole_pipeline", "Fixture PNG'sinin yükleyip worker'dan geçtikten sonra ok verdict ve doğru toplamlarla döndüğünü sınar.", ["test", "entegrasyon", "pipeline"]),
    ("test_tampered_kdv_from_the_model_yields_mismatch_naming_the_field", "Modelin tahrif edilmiş KDV'sinin mismatch verdict ve tam olarak totals.kdv alan adını ürettiğini doğrular.", ["test", "entegrasyon", "dogrulama"]),
]:
    func("tests/test_integration_m1.py", nm, sm, tg + ["entegrasyon"], "moderate", exported=False)
UnreadableErrT = klass("tests/test_pipeline.py", "UnreadableError",
                       "Aşama 2'nin okunamayan hatasının testteki taklidi; pipeline'ın bu tipi yakaladığını tetiklemek için kullanılır.",
                       ["test", "exception", "test-altyapisi"], "simple", exported=False)
FakeOcr = klass("tests/test_pipeline.py", "FakeOcr",
                "Sabit metin/süre veya OcrError döndüren sahte OCR istemcisi; aşama 1'i enjekte ederek test eder.",
                ["mock", "test-altyapisi", "ocr"], "simple", exported=False)
FakeStructurer = klass("tests/test_pipeline.py", "FakeStructurer",
                       "Verilen sözlüğü, sahte anahtarları veya UnreadableError'ı döndüren yapılandırma taklidi; modelin "
                       "zarfa sızdırma denemelerini buradan kurar.",
                       ["mock", "test-altyapisi", "stage-2"], "simple", exported=False)
for nm, sm in [
    ("test_runs_stage1_then_stage2_then_stage3", "Üç aşamanın tam sırada ve OCR metninin yapılandırıcıya aktarılarak çalıştığını doğrular."),
    ("test_ok_receipt_recomputes_the_expected_totals", "Beklenen toplamların modelin rakamlarından değil kalemlerin yeniden toplamından geldiğini sınar."),
    ("test_model_totals_are_only_the_actual_side_never_the_verdict", "Modelin toplamlarının yalnızca gerçek tarafı olduğunu, verdict'i belirlemediğini doğrular."),
    ("test_model_cannot_smuggle_a_verdict_or_validation_block", "Model yüküne konan verdict/validation bloklarının contract süzgecinden geçemediğini sınar."),
    ("test_stage1_failure_still_returns_a_whole_partial_result", "OCR patladığında dönen demetin yine tam bir sonuç/validation/meta taşıdığını doğrular."),
]:
    func("tests/test_pipeline.py", nm, sm, ["test", "pipeline", "dogrulama"], "moderate", exported=False)
edge(FakeOcr, "class:app/ocr_client.py:OcrClient", "related", 0.5)
edge(FakeStructurer, "class:app/structurer.py:Structurer", "related", 0.5)
edge(UnreadableErrT, "class:app/structurer.py:UnreadableError", "related", 0.5)

for nm, sm in [
    ("test_absent_fields_come_back_as_house_defaults", "Model eksik bıraktığında her alanın ev varsayılanıyla döndüğünü doğrular."),
    ("test_posts_chat_completions_to_strata_port", "İsteğin Strata portunda /v1/chat/completions'a gittiğini sınar."),
    ("test_uses_strata_model_by_default", "Varsayılan modelin config.strata_model() olduğunu doğrular."),
    ("test_thinking_is_disabled_for_the_reasoning_model", "Gövdede enable_thinking=False bayrağının bulunduğunu sınar (T68 regresyonu)."),
    ("test_quality_mode_routes_to_unsloth", "Kalite modunun isteği Unsloth Studio'ya yönlendirdiğini doğrular."),
    ("test_sends_ocr_text_and_image_together", "OCR metni ile görüntünün tek mesajda birlikte gönderildiğini doğrular."),
    ("test_empty_ocr_text_is_still_a_request", "Boş OCR metninin de geçerli bir istek olduğunu, istemin korunduğunu sınar."),
    ("test_answer_of_only_thoughts_is_unreadable_not_a_crash", "content=null + yalnızca reasoning içeren yanıtın çökme değil UnreadableError ürettiğini doğrular."),
    ("test_explicit_base_url_model_and_timeout_override_routing", "Açık verilen base_url/model/timeout değerlerinin yönlendirmeyi ezdiğini sınar."),
]:
    func("tests/test_structurer.py", nm, sm, ["test", "stage-2", "api-client"], "moderate", exported=False)
func("tests/test_tailscale.py", "tailscale_commands",
     "Ayrıştırılan .ps1 betiğindeki komut ve bayrakları döndürür; README'nin betikle aynı şeyi söylediğini denetleyen "
     "testler bu yardımcıyı kullanır.",
     ["test-yardimci", "powershell", "belge-uyumu"], "moderate", exported=False)
FakeOcr2 = klass("tests/test_unreadable_survives.py", "FakeOcr",
                 "Sabit metin döndüren en küçük OCR taklidi; okunamayan fiş senaryosunda aşama 1'i sabitler.",
                 ["mock", "test-altyapisi", "ocr"], "simple", exported=False)
RS = klass("tests/test_unreadable_survives.py", "RaisingStructurer",
           "Her zaman UnreadableError fırlatan yapılandırma taklidi; okunamayan verdict'in worker'a kadar sağ "
           "ulaştığını bu tetikler.",
           ["mock", "test-altyapisi", "stage-2"], "simple", exported=False)
edge(FakeOcr2, "class:app/ocr_client.py:OcrClient", "related", 0.5)
edge(RS, "class:app/structurer.py:Structurer", "related", 0.5)

# ------------------------------------------------------- imports (1:1, verbatim)
imp_count = 0
for src, targets in IMPORTS.items():
    for t in targets:
        edge(f"file:{src}", f"file:{t}", "imports", 0.7)
        imp_count += 1

# ------------------------------------------------------------ tested_by (prod -> test)
TESTED_BY = [
    ("file:app/config.py", "file:tests/test_config.py"),
    ("file:app/contract.py", "file:tests/test_contract.py"),
    ("file:app/ocr_client.py", "file:tests/test_ocr_client.py"),
    ("file:app/pipeline.py", "file:tests/test_pipeline.py"),
    ("file:app/pipeline.py", "file:tests/test_unreadable_survives.py"),
    ("file:app/queue_worker.py", "file:tests/test_unreadable_survives.py"),
    ("file:app/structurer.py", "file:tests/test_structurer.py"),
    ("file:app/structurer.py", "file:tests/test_smoke_real_structurer.py"),
    ("file:scripts/fake_models.py", "file:tests/test_fake_models.py"),
    ("file:scripts/serve_demo.py", "file:tests/test_serve_demo.py"),
    ("file:scripts/smoke_e2e.py", "file:tests/test_smoke_e2e.py"),
    ("file:app/main.py", "file:tests/test_integration_m1.py"),
    ("file:app/pipeline.py", "file:tests/test_integration_m1.py"),
]
for s, t in TESTED_BY:
    edge(s, t, "tested_by", 0.5)

# --------------------------------------------------------------- other depends_on
edge("file:tests/test_tailscale.py", "file:scripts/tailscale_serve.ps1", "depends_on", 0.6)
edge("file:tests/test_tailscale.py", "document:README.md", "depends_on", 0.6)
edge("file:tests/test_smoke_real_structurer.py", "file:scripts/smoke_e2e.py", "depends_on", 0.6)
edge("file:tests/test_smoke_real_structurer.py", "class:app/structurer.py:Structurer", "related", 0.5)
edge("file:spike/probe_thinking3.py", "file:spike/probe_thinking2.py", "related", 0.5)
edge("file:spike/probe_thinking2.py", "file:spike/probe_thinking.py", "related", 0.5)

# ------------------------------------------------------------------- partition
ids = {n["id"] for n in nodes}
assert len(ids) == len(nodes), "duplicate node ids"
by_file = {}
for n in nodes:
    by_file.setdefault(n.get("filePath"), []).append(n)

files_sorted = sorted(f["path"] for f in inp["files"])
parts = 3
size = math.ceil(len(files_sorted) / parts)
edge_by_source = {}
for e in edges:
    src_file = e["source"].split(":", 1)[1]
    src_file = src_file.rsplit(":", 1)[0] if e["source"].startswith(("function:", "class:")) else src_file
    if src_file not in set(files_sorted):
        # cross-batch source (e.g. production -> test edge); bucket it with the target's file
        src_file = e["target"].split(":", 1)[1].rsplit(":", 1)[0]
    edge_by_source.setdefault(src_file, []).append(e)

out = []
for k in range(parts):
    group = files_sorted[k * size:(k + 1) * size]
    if not group:
        continue
    gset = set(group)
    gn = [n for f in group for n in by_file.get(f, [])]
    ge = [e for f in group for e in edge_by_source.get(f, [])]
    out.append((k + 1, gn, ge, group))

total_n = total_e = 0
for k, gn, ge, group in out:
    payload = {"nodes": gn, "edges": ge}
    p = UA / "intermediate" / (f"batch-2-part-{k}.json" if parts > 1 else "batch-2.json")
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total_n += len(gn)
    total_e += len(ge)
    print(f"part {k}: {len(gn)} nodes, {len(ge)} edges  files={group[0]}..{group[-1]}")

imp_edges = sum(1 for e in edges if e["type"] == "imports")
print("TOTALS", total_n, "nodes", total_e, "edges; imports", imp_edges, "expected", imp_count)
assert total_n == len(nodes) and total_e == len(edges), "partition lost something"
print("node kinds:", {t: sum(1 for n in nodes if n['type'] == t) for t in {n['type'] for n in nodes}})
print("edge kinds:", {t: sum(1 for e in edges if e['type'] == t) for t in {e['type'] for e in edges}})
