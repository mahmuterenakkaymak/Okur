# -*- coding: utf-8 -*-
"""Batch 1 semantic assembly: nodes + edges -> batch-1-part-k.json"""
import json, pathlib, math, sys

ROOT = pathlib.Path(r"C:\Users\PC\Documents\GitHub\ocr-app")
UA = ROOT / ".ua"
res = json.loads((UA / "tmp/ua-file-extract-results-1.json").read_text(encoding="utf-8"))
inp = json.loads((UA / "tmp/batch-input-1.json").read_text(encoding="utf-8"))
IMP = inp["batchImportData"]
results = {r["path"]: r for r in res["results"]}

def rng(path, name, kind="functions"):
    r = results[path]
    for f in r.get(kind, []):
        if f["name"] == name:
            return [f["startLine"], f["endLine"]]
    raise SystemExit(f"MISSING {path} {kind}:{name}")

# ---- file nodes: path -> (type, summary, tags, complexity, languageNotes) ----
F = {
 "app/__init__.py": ("file",
  "app paketinin başlatıcı dosyası; boş olup config, db, auth, main gibi alt modüllerin `app.` önekiyle import edilmesini sağlar.",
  ["paket", "barrel", "entry-point"], "simple", None),
 "app/auth.py": ("file",
  "Çalışan API anahtarları (ocrk_ + 40 hex) ve yönetici oturumlarının sahibi: anahtarlar veritabanına yalnızca SHA-256 hash olarak yazılır, doğrulama sabit zamanda yapılır. Yönetici token'ı sunucudan hiç çıkmaz; oturum çerezi rastgele bir oturum kimliği taşır. Anahtar başına token bucket da burada, tek süreçte bellekte durur.",
  ["security", "authentication", "api-key", "rate-limit", "service"], "moderate",
  "threading.Lock ile korunan süreç-içi _buckets/_sessions sözlükleri: tek uygulama süreci varsayımıyla çalışır, yeniden başlatınca sıfırlanır."),
 "app/db.py": ("file",
  "SQLite (WAL) kalıcılık katmanı: api_keys, jobs, corrections ve events tablolarını PRAGMA user_version ile idempotent göç ettirir. İş satırları kuyruk sözleşmesine uyar; durum geçişleri created/started/finished damgalarını tek UTC saatinden ISO-8601 olarak basar.",
  ["database", "sqlite", "data-model", "migration", "queue"], "complex",
  "sqlite3.Row row_factory + JOB_COLUMNS/_IMMUTABLE beyaz listesiyle alan yazma kontrolü; JSON kolonları _update içinde otomatik serileştirilir."),
 "app/keys_cli.py": ("file",
  "Terminalden çalışan anahtarı yönetimi: add | list | revoke. Düz metin anahtar yalnızca `add` çıktısında bir kez ve kopyalama uyarısıyla basılır; `list` yalnızca kimlikleri gösterir.",
  ["cli", "entry-point", "api-key", "utility"], "moderate",
  "Windows'un kod sayfası ş/ğ içermediği için stdout/stderr utf-8'e yeniden yapılandırılır."),
 "app/main.py": ("file",
  "HTTP kabuğu ve uygulama fabrikası: create_app tüm middleware'i tek sırayla kurar (hata zarfı, anahtar doğrulama, yönetici koruması, yükleme sınırı, güvenlik başlıkları, istek günlüğü) ve /v1, /api/me, /admin/api yüzeylerini bağlar. Uygulamanın üretebildiği her hata aynı JSON zarfıyla döner.",
  ["entry-point", "api-handler", "middleware", "fastapi", "application-factory"], "complex",
  "Starlette middleware sırası bilinçli: yükleme sınırı gövdeyi tamponlamadan önce reddeder, güvenlik başlıkları auth reddetmelerini de kapsar, istek günlüğü en dıştadır."),
 "tests/test_admin_auth.py": ("file",
  "Yönetici giriş/çıkış ve oturum güvenliğini TestClient ile sınar: oturumsuz /admin/api çağrıları 401 zarfı alır, çerez httpOnly bir oturum kimliği taşır (token değil), token sabit zamanda karşılaştırılır ve süre admin_session_hours ile dolar.",
  ["test", "security", "yonetici-paneli", "oturum"], "moderate", None),
 "tests/test_admin_detail.py": ("file",
  "Yönetici iş detayının tek GET'te üçünü birden verdiğini doğrular: sözleşme v1 zarfı, diskteki fotoğraf ve doğrulama bloku. Demo tohumu kullanılır, böylece her vaka gerçek bir fiş fixturüdür.",
  ["test", "yonetici-paneli", "data-model", "entegrasyon"], "moderate", None),
 "tests/test_admin_keys.py": ("file",
  "Yönetici API'si üzerinden anahtar oluştur/listele/iptal et uçlarını ve tasarımın temel sözünü sınar: düz metin anahtar sadece bir kez ağa geçer, iptal edilen anahtar bir sonraki PWA çağrısında 401 alır.",
  ["test", "api-key", "security", "yonetici-paneli"], "moderate", None),
 "tests/test_admin_list.py": ("file",
  "Yönetici başvurular tablosunu gerçek demo tohumu üzerinden sınar: sütunlar, durum/çalışan/tarih filtreleri, başlık ve ürün araması, sıralama ve sayfalama — hepsi birbirinden gerçekten farklı fişlere karşı.",
  ["test", "yonetici-paneli", "filtreleme", "entegrasyon"], "complex", None),
 "tests/test_admin_sort_date.py": ("file",
  "tarih sütununun sıralamasasının tablodaki dd.MM.yyyy metninden değil satırın ISO gününden geldiğini sabitler; ay ve yıl sınırlarında doğru sırayı doğrular.",
  ["test", "siralama", "yonetici-paneli", "tarih"], "simple", None),
 "tests/test_auth.py": ("file",
  "auth modülünün birim testleri: anahtar biçimi ve öneki, SHA-256 hash'in tek kalıcı biçim olması, sabit zamanlı karşılaştırma, iptalin anında etkili olması ve hash'in çağıran'a sızmaması.",
  ["test", "security", "api-key", "unit-test"], "moderate", None),
 "tests/test_captured_at_survives.py": ("file",
  "captured_at'ın kuyruktan geçip GET'e ulaşmasını sınar: sütunu olmadığından route meta_json'a park eder, worker ise kendi captured_at'ı null olan pipeline demetiyle cevap verir. Yalnızca iki model sunucusu sahtedir, dolayısıyla yazılan meta üretimle birebirdir.",
  ["test", "kuyruk-worker", "meta", "entegrasyon"], "moderate", None),
 "tests/test_corrections.py": ("file",
  "Alan düzeyindeki düzeltmenin işi gerçekten yeniden yazdığını sınar: tek PATCH sonrası entegratörün GET /v1/jobs/{id}'i, yönetici detayı, çalışanın sonuç görünümü, iki liste ve üç dışa aktarım biçimi aynı hikâyeyi anlatır; doğrulama düzeltilen sayılar üzerinde tekrar koşar.",
  ["test", "düzeltme", "tutarlilik", "entegrasyon"], "complex", None),
 "tests/test_db.py": ("file",
  "db katmanının birim testleri: WAL ve foreign_keys pragmaları, idempotent göçler, iş satırının kuyruk sözleşmesi, client_ref idempotency'si, durum geçişi damgaları ve yazılamaz kolonların reddi.",
  ["test", "database", "migration", "unit-test"], "complex", None),
 "tests/test_exports.py": ("file",
  "Dışa aktarımın üç biçimini (JSON/CSV/XLSX) kendi okuyucularıyla geri okuyarak sınar: sözleşmenin 8 sütunu, Türkçe karakterlerin korunması, düzeltilmiş ve okunamayan fişlerin ve quality modunun biçimlere yansıması.",
  ["test", "disa-aktarim", "csv", "xlsx", "entegrasyon"], "complex", None),
 "tests/test_hardening.py": ("file",
  "Gerçek uygulama üzerinden sertleştirme testleri: taşan ve chunked yüklemeler 413, çöp dosyalar 422, EXIF'siz/dik kaydedilen telefon fotoğrafı, her cevapta güvenlik başlıkları ve istek günlüğünün job_id taşıması — test edilen middleware sırası üretimle aynıdır.",
  ["test", "security", "middleware", "günlükleme"], "complex", None),
 "tests/test_keys_cli.py": ("file",
  "keys_cli'nin add/list/revoke komutlarını capsys ile sınar: düz metnin yalnızca bir kez basılması, yalnızca hash'in saklanması, boş çalışan adının reddi, iptal edilmiş anahtarın derhal geçersiz olması ve argparse hatalarının çıkış kodu.",
  ["test", "cli", "api-key", "unit-test"], "moderate", None),
 "tests/test_main_app.py": ("file",
  "Uygulama fabrikasının yüzey testleri: /health ve /docs'un herkese açık olması, OpenAPI'nin contract v1'i ve X-API-Key şemasını tanıması, /v1'in anahtarsız/tek başına/iptal edilmiş anahtarla 401 zarfı dönmesi ve hata zarfının biçimi.",
  ["test", "fastapi", "openapi", "authentication"], "moderate", None),
 "tests/test_pwa_empty_states.py": ("file",
  "Saha PWA'sının boş durumlarını denetler: kayıtlı fiş yokken elle çizilmiş fiş çizimi ve geçmiş yüklenirken shimmer iskeleti gösterilir.",
  ["test", "pwa", "arayuz", "bos-durum"], "simple", None),
 "tests/test_pwa_history.py": ("file",
  "Geçmiş görünümünün sayfa bağlantısını ve yetki sınırını sınar: yalnızca çağıran anahtarın işleri erişilebilirdir, başkasının işi kendi listesinde görünmez.",
  ["test", "pwa", "yetki", "arayuz"], "moderate", None),
 "tests/test_pwa_shell.py": ("file",
  "PWA kabuğunun (index.html, manifest, service worker) sunulan varlıklarını ve birbirine bağlarını denetler.",
  ["test", "pwa", "arayuz", "static-asset"], "simple", None),
 "tests/test_pwa_submit_flow.py": ("file",
  "Sunulan gönderim sayfasının tüm modülleri ve DOM kancalarını gerçekten bağladığını doğrular: yüklenen app.js'in beklenen import'ları ve öğe kimlikleri içerir.",
  ["test", "pwa", "arayuz", "wiring"], "moderate", None),
 "tests/test_queue_worker.py": ("file",
  "Kuyruk worker'ının durum makinesi testleri: satır kapma, done/failed geçişleri, çalışırken çöken runner'ın işi düşürüp worker'ı ayakta tutması, patlama hacminin emilmesi, stop'un devam eden işi beklemesi ve bayat işlerin kurtarılması.",
  ["test", "kuyruk-worker", "durum-makinesi", "dayaniklilik"], "complex", None),
 "tests/test_rate_limit.py": ("file",
  "auth.authorize'ın token bucket davranışını sınar: kapasite bitince 429 ve Retry-After, sürenin yapılandırmaya göre dolması, 401'in token harcamaması.",
  ["test", "rate-limit", "security", "unit-test"], "moderate", None),
 "tests/test_routes_jobs.py": ("file",
  "/v1/jobs rota yüzeyinin testleri: iş oluşturma, client_ref idempotency'si, olgunlaşmış zarfın GET yanıtı, PWA geçmiş listesi ve yetkisiz erişim davranışları.",
  ["test", "api-handler", "kuyruk", "entegrasyon"], "complex", None),
 "tests/test_routes_worker.py": ("file",
  "Çalışan yüzü /api/me rotalarının testleri: kendi işlerinin listesi, detay ve küçük resmi, başka anahtarın işine erişilememesi ve görsel/sonuç durumlarının yansıması.",
  ["test", "api-handler", "pwa", "entegrasyon"], "complex", None),
 "tests/test_serve_demo.py": ("file",
  "Demo servisinin iki işini sabitler: --check gerçek yığınla kapı görevi görür, tohumlama ise her kuyruk durumunu, her kararı ve diskteki görselleriyle her ekranı incelenebilir kılar.",
  ["test", "demo", "arac", "entegrasyon"], "moderate", None),
 "tests/test_status.py": ("file",
  "Durum anlık görüntüsünün (servis propları, VRAM, kuyruk derinliği, Durum sayfası) temel sözünü sınar: durum okuması asla yükseltmez — reddeden sunucu, olmayan nvidia-smi ve boş kuyruk veriyle cevap verir (ok False, unavailable, sıfırlar).",
  ["test", "izleme", "durum", "gozlemlenebilirlik"], "moderate", None),
 "tests/test_upload_atomic_orphan.py": ("file",
  "T67 düzeltmesini kilitler: kuyruğa alınmış satır asla görselsiz kalmaz — önce baytlar diske, sonra onlara işaret eden satır yazılır; böylece worker kapabileceği bir satırı 'image: …' ile düşüremez.",
  ["test", "atomiklik", "yukleme", "duzenleme"], "simple", None),
 "tests/test_upload_exif_stripped.py": ("file",
  "PLAN kararı 7'yi doğrular: çalışanın telefonundaki EXIF/GPS kaydetmeden sağ çıkmaz. Satırdaki yol ile /api/me/jobs/{id}/image'ın döndürdüğü baytlar aynı dosya olduğu için KVKK yüzeyi iki iddiayla kapanır.",
  ["test", "kvkk", "gizlilik", "gorsel"], "moderate", None),
}

# ---- sub nodes: path -> list of (kind, name, summary, tags, complexity) ----
S = {
 "app/auth.py": [
  ("function","generate_key","config.KEY_PREFIX ile config.KEY_BYTES rastgele bayttan düz metin anahtar üretir (ocrk_ + 40 hex).",["api-key","security","utility"],"simple"),
  ("function","hash_key","Anahtarın SHA-256 hex özetini döndürür; veritabanının gördüğü tek anahtar biçimidir.",["hashing","security","utility"],"simple"),
  ("function","create_key","Çalışan için yeni anahtar kaydeder ve (key_id, düz metin) döndürür; düz metin yalnızca bu dönüşte vardır, satıra hash yazılır.",["api-key","database","security"],"simple"),
  ("function","verify","Düz metin anahtarın hash'ini api_keys satırlarıyla hmac.compare_digest üzerinden sabit zamanda karşılaştırır; iptal edilmemişse {id, worker, created_at} döndürür, hash'i dışarı çıkarmaz.",["authentication","security","database"],"moderate"),
  ("function","revoke_key","Anahtarı revoked = 1 yapar (iş geçmişindeki atıflar için satır kalır); iptali bu çağrı yapan True döner.",["api-key","database","security"],"simple"),
  ("function","authorize","Doğrulama ve anahtar başına token bucket'ı tek karara indirir: yok/bilinmeyen/iptal → 401 (token harcanmaz), bucket boş → 429 + retry-after, aksi halde 200. Satır 429'da da döner ki çağırıcı isabeti çalışana atayabilsin.",["authentication","rate-limit","api-handler"],"moderate"),
  ("function","_take_token","Kilitle korunan bucket'ından bir token harcar; kapasite-yenileme hesabıyla token yoksa bir sonraki token'a kalan saniyeyi döndürür.",["rate-limit","concurrency","utility"],"moderate"),
  ("function","admin_configured","ADMIN_TOKEN tanımlı mı; değilse yönetici panelinin hiç kapısı yoktur.",["security","yonetici-paneli","utility"],"simple"),
  ("function","admin_token_ok","ADMIN_TOKEN'ı sabit zamanla karşılaştırır; beklenmeyen ya da boş aday False. İki taraf da bayta çevrilir ki compare_digest ASCII dışı str'yi reddetmesin.",["security","authentication","validation"],"moderate"),
  ("function","start_session","httpOnly çerez için rastgele oturum kimliği üretir — asla token'ın kendisi değil — ve admin_session_hours kadar son kullanma damgalar; bu arada süresi geçen oturumları süpürür.",["oturum","security","utility"],"moderate"),
  ("function","session_ok","Oturum kimliği canlıysa True; bilinmiyorsa ya da süresi geçmişse False (ve geçmiş olan bellekten silinir).",["oturum","security","validation"],"moderate"),
  ("function","end_session","Bir oturumu sonlandırır; iki kez çıkış yapmak hata değildir.",["oturum","security","utility"],"simple"),
 ],
 "app/db.py": [
  ("function","_now","Şimdiyi milisaniye hassasiyetinde ISO-8601 UTC ('Z' sonekli) metin olarak döndürür; tüm görünümlerin tek saati.",["tarih","utility","serialization"],"simple"),
  ("function","connect","Veritabanının tek giriş noktası: varsayılan yol config.db_path()'ten, eksik ebeveyn dizinleri açar, foreign_keys'ı bağlar, bellek dışındaysa WAL'ı kurar ve göçleri uygular.",["database","sqlite","factory"],"moderate"),
  ("function","_migrate","PRAGMA user_version okuyup MIGRATIONS listesini sırayla, idempotent biçimde uygular ve sürümü yazar.",["migration","database","bootstrap"],"simple"),
  ("function","list_keys","Tüm anahtar satırlarını eskiden yeniye listeler; key_hash bilinçli olarak hiç seçilmez ki panel sırrı asla okuyamasın.",["api-key","database","security"],"simple"),
  ("function","create_job","Yeni kuyruk işi satırı ekler (created_at damgalı, started/finished NULL); job_id route'a satırı yaratmadan önce ad verme imkânı tanır, böylece görsel önce diske yazılabilir.",["database","kuyruk","data-model"],"moderate"),
  ("function","get_job","İş satırını sözlük olarak döndürür; yoksa None.",["database","data-model","utility"],"simple"),
  ("function","find_job_by_client_ref","UNIQUE(key_id, client_ref) idempotency'sinin araması: referans yoksa eşleşme de yoktur.",["idempotency","database","utility"],"simple"),
  ("function","list_jobs","status/worker/key_id/since filtrelerini parametreli WHERE ile kurar, created_at DESC + LIMIT/OFFSET ile sayfalı liste döndürür.",["database","filtreleme","sayfalama"],"moderate"),
  ("function","queue_depth","Durum başına açık kuyruk derinliğini döndürür; satırı olmayan durum 0 olarak görünür.",["kuyruk","izleme","database"],"simple"),
  ("function","update_job","Değiştirilebilir iş kolonlarını günceller (dict/list JSON alanları serileştirilir); status burada_setilemez, bunun için set_status gerekir.",["database","guncelleme","validation"],"simple"),
  ("function","set_status","queued → running → done/failed geçişlerini (yeniden çalıştırma için done/failed → queued) yönetir: running ilk seferde started_at, done/failed finished_at damgalar; ek kolonlar aynı işlemde güncellenir.",["durum-makinesi","database","transaction"],"moderate"),
  ("function","_check_columns","Güncellenecek adların JOB_COLUMNS beyaz listesinde ve değiştirilemezler dışında olduğunu doğrular; değilse ValueError.",["validation","database","guvenlik"],"simple"),
  ("function","_update","UPDATE cümlesini parametreli kurar, JSON kolonlarını serileştirir ve tek commit ile yazar.",["database","guncelleme","serialization"],"moderate"),
  ("function","add_correction","Düzeltilen her alan için kim (who) ve ne zaman (created_at) bilgisiyle tek denetim satırı yazar ve satırı döndürür.",["denetim","database","düzeltme"],"moderate"),
  ("function","log_event","events tablosuna job_id'li, damgalı bir olay satırı ekler.",["günlükleme","database","utility"],"simple"),
 ],
 "app/keys_cli.py": [
  ("function","_cmd_add","Boş olmayan çalışan adı için anahtar oluşturur ve düz metni yalnızca bu kez, kopyalama uyarısıyla basar; boş add 1 döner.",["cli","api-key","komut"],"moderate"),
  ("function","_cmd_list","Anahtarları hizalı tabloda (ID, çalışan, oluşturulma, durum) listeler; boş veritabanında dostça yönlendirir, anahtarların kendisini asla göstermez.",["cli","api-key","raporlama"],"moderate"),
  ("function","_cmd_revoke","auth.revoke_key ile anahtarı iptal eder; bilinmeyen ya da zaten iptal edilmişse hata mesajıyla 1 döner.",["cli","api-key","komut"],"simple"),
  ("function","main","argparse ile add/list/revoke alt komutlarını çözer, akışları utf-8'e sabitler, db.connect ile bağlantı açıp komutu çalıştırır ve bağlantıyı her hâlde kapatır.",["cli","entry-point","argparse"],"moderate"),
 ],
 "app/main.py": [
  ("function","create_app","Tüm HTTP uygulamasını kuran fabrika: FastAPI'yi oluşturur, üç router'ı bağlar, /health'u ekler ve middleware'leri sırayla (zarf, auth, yönetici koruması, yükleme sınırı, güvenlik başlıkları, istek günlüğü) kurar; run.py, smoke'lar ve testler aynı fabrikayı çağırır.",["application-factory","entry-point","fastapi"],"complex"),
  ("function","_connect","İstek başına tek SQLite bağlantısı açar; thread'ler arası paylaşım yasak, açmak bu ölçekte ucuz.",["database","connection","middleware"],"simple"),
  ("function","_add_auth_middleware","/v1 ve /api altına gelen her istekte X-API-Key'i auth.authorize ile doğrular: 401/429'u zarfa çevirir, 429'da Retry-After başlığı ekler, geçerli satırı request.state.key ile route'a teslim eder.",["middleware","authentication","rate-limit"],"moderate"),
  ("function","_add_admin_guard","/admin/api/ öneki altında oturum koruması: rota kaydedildiği anda korunur, statik /admin kabuğu (veri yok) açık kalır, oturumsuz çağrı 401 zarfı alır.",["middleware","oturum","yonetici-paneli"],"moderate"),
  ("function","_add_upload_cap","İlan edilen Content-Length config.max_upload_mb'ı aşıyorsa gövde tamponlanmadan 413 döner; chunked yüklemeyi routes_jobs baytlar üzerinde tekrar denetler.",["middleware","validation","guvenlik"],"moderate"),
  ("function","_add_security_headers","Her cevapta nosniff/DENY/no-referrer başlıkları ve CSP uygular; swagger-ui CDN'den geldiği için /docs ve /redoc CSP'den muaftır.",["middleware","security","csp"],"simple"),
  ("function","_add_request_logging","En dış middleware olarak her isteği süreyle tek satır günlüğe yazar; tüm handler'ları aşan bir çökme de 500 olarak satırını alır.",["middleware","günlükleme","gozlemlenebilirlik"],"moderate"),
  ("function","_configure_request_log","uvicorn kök logger'a dokunmadığı için basicConfig ile stream bağlar ve istek logger'ını INFO seviyesine çeker; mevcut bir stream varsa (pytest) dokunmaz.",["günlükleme","yapilandirma","bootstrap"],"simple"),
  ("function","_log_request","Metot, yol, durum kodu, süre, job_id ve çalışanı tek satırda loglar.",["günlükleme","utility","gozlemlenebilirlik"],"moderate"),
  ("function","_job_id","İsteğin hangi işle ilgili olduğunu bulur: route'un kendi ürettiği job_id, yoksa yoldaki /jobs/<id> eşleşmesi, o da yoksa '-'.",["utility","günlükleme","regex"],"simple"),
  ("function","_error","Uygulamanın tek hata zarfını üretir: {\"error\": {code, message, details?}} ve HTTP durum kodu.",["hata-yonetimi","api-handler","serialization"],"simple"),
  ("function","_add_error_envelope","HTTPException, RequestValidationError ve beklenmeyen Exception handler'larını zarfa bağlar; çökmede traceback yalnızca loga gider, cevaba değil.",["hata-yonetimi","middleware","guvenlik"],"moderate"),
  ("function","_code_for","Durum kodunu entegratör yüzeyine dönük kararlı koda çevirir; 413'ün İngilizce ifadesi 3.11/3.12 arasında değiştiği için sabitlenir.",["hata-yonetimi","uyumluluk","utility"],"simple"),
  ("function","_mount_static",".webmanifest MIME tipini kaydeder ve PWA ile yönetici statik paketlerini /app ve /admin altına bağlar; dizinler ilk açılışta oluşturulur.",["static","mount","fastapi"],"simple"),
  ("function","_describe_contract","OpenAPI belgesine contract v1 JobEnvelope şemasını, X-API-Key güvenlik şemasını ve /health muafiyetini işler.",["openapi","contract","dokumentasyon"],"moderate"),
 ],
 "tests/test_admin_auth.py": [
  ("function","client","Geçici DATA_DIR ve tanımlı ADMIN_TOKEN ile TestClient kurar; yönetici kimliği testlerinin ortak giriş kapısı.",["test-fixture","test","oturum"],"simple"),
 ],
 "tests/test_admin_detail.py": [
  ("function","env","Demo tohumunu (serve_demo.seed_jobs) geçici veritabanına yükleyip yönetici oturumu açmış TestClient hazırlar; her vaka gerçek bir fiş üzerinden koşar.",["test-fixture","test","demo"],"moderate"),
  ("function","test_the_page_holds_the_detail_controls","Detay sayfasının inceleme kontrollerini (değişiklik alanları, ham JSON, görsel) taşıdığını ve Türkçe etiketleri doğrular.",["test","arayuz","yonetici-paneli"],"moderate"),
 ],
 "tests/test_admin_keys.py": [
  ("function","env","Geçici veritabanı ve yönetici oturumuyla TestClient hazırlar; anahtar uçları bu oturumun arkasında sınanır.",["test-fixture","test","api-key"],"moderate"),
 ],
 "tests/test_admin_list.py": [
  ("function","env","serve_demo.seed_jobs ile her kuyruk durumunu ve her kararı içeren gerçek corpus'u kurar, yönetici oturumlu TestClient döndürür.",["test-fixture","test","demo"],"moderate"),
  ("function","test_the_page_holds_the_list_controls","Liste sayfasının filtre, arama, sıralama ve sayfalama kontrollerini ve Türkçe başlıkları içerdiğini denetler.",["test","arayuz","yonetici-paneli"],"moderate"),
  ("function","test_the_list_module_calls_the_admin_api","Tablonun kendi JS modülünün gerçekten /admin/api uçlarını çağırdığını (sahte veriyle beslenmediğini) doğrular.",["test","wiring","yonetici-paneli"],"moderate"),
 ],
 "tests/test_admin_sort_date.py": [
  ("function","env","Farklı ay ve yıllara yayılan fiş günleriyle (biri 02.11.2026, diğeri 01.12.2026) yönetici API'sini hazırlar; metin sıralamasının tuzağını kurar.",["test-fixture","test","tarih"],"complex"),
 ],
 "tests/test_auth.py": [
  ("function","conn","Test başına, göçleri çalıştırılmış tek bir SQLite bağlantısını geçici dosya üzerinde açar ve kapatır.",["test-fixture","test","database"],"simple"),
 ],
 "tests/test_captured_at_survives.py": [
  ("function","runner","Worker'a verilen pipeline koşucusu: yalnızca OcrClient ve Structurer sahtedir, dolayısıyla üretilen JobMeta üretimle birebir aynıdır.",["test-double","pipeline","kuyruk-worker"],"simple"),
  ("function","env","Geçici DATA_DIR, gerçek uygulama fabrikası, kayıtlı bir çalışan anahtarı ve boşaltılmış token bucket ile TestClient hazırlar.",["test-fixture","test","kuyruk-worker"],"moderate"),
  ("class","FakeOcr","transcribe ile sabit fiş metni ve ms döndüren OCR sahtesi; stage-1 arayüzünün sözleşmesini belgeleyen en küçük kurulum.",["test-double","fake","ocr"],"simple"),
  ("class","FakeStructurer","structure ile fixture sonucunu döndüren yapılandırıcı sahtesi; stage-2 arayüzünün sözleşmesini belgeleyen en küçük kurulum.",["test-double","fake","structurer"],"simple"),
 ],
 "tests/test_corrections.py": [
  ("function","env","Demo tohumlu veritabanı, yönetici oturumu, çalışan anahtarı ve TestClient'ı birlikte hazırlar; beş yüzeyin de aynı işi görmesi bu fikstüre dayanır.",["test-fixture","test","düzeltme"],"moderate"),
  ("function","duzeltme_kayitlari","corrections tablosundan bir işin düzeltme geçmişini sırayla okur.",["test-helper","denetim","database"],"simple"),
  ("function","calisan_detay","Çalışanın kendi API anahtarıyla /api/me iş detayını çeker; düzeltmenin çalışan yüzüne yansıdığını kanıtlar.",["test-helper","pwa","api-handler"],"simple"),
  ("function","calisan_satiri","Çalışanın liste görünümündeki tek iş satırını döndürür.",["test-helper","pwa","liste"],"simple"),
  ("function","bes_yuzey","Aynı işin beş yüzeyini (entegratör GET, yönetici detay, çalışan detay, iki liste) tek çağrıda toplar; düzeltmenin her yere aynı hikâye olarak düştüğünün ölçüm noktası.",["test-helper","tutarlilik","düzeltme"],"moderate"),
  ("function","disa_aktarim_satiri","exports.row'un ürettiği, üç dışa aktarım biçiminin kaynağı olan sözleşme satırını doğrudan okur.",["test-helper","disa-aktarim","contract"],"complex"),
  ("function","test_a_correction_touches_only_the_field_it_names","Bir alanın düzeltilmesinin diğer alanlara ve doğrulama dışındaki bloklara dokunmadığını satır satır doğrular.",["test","düzeltme","tutarlilik"],"moderate"),
  ("function","test_the_export_row_every_format_is_built_from_carries_the_correction","Düzeltilmiş işin JSON, CSV ve XLSX çıktılarında düzeltilmiş değerlerle yer aldığını her biçimin kendi okuyucusuyla kontrol eder.",["test","disa-aktarim","düzeltme"],"complex"),
 ],
 "tests/test_db.py": [
  ("function","conn","Göçleri çalıştırılmış, geçici dosyada bir SQLite bağlantısı açar; modülün tüm birim testleri bu bağlantı üzerinde koşar.",["test-fixture","database","test"],"simple"),
  ("function","make_key","İş satırlarının FOREIGN KEY'i karşılaması için api_keys'e kayıtlı bir çalışan anahtarı üretir.",["test-helper","api-key","database"],"simple"),
  ("function","test_set_status_carries_updates_in_one_call","set_status'un durumu ve ek kolonları tek çağrıda (tek işlemde) yazdığını, damgalarla birlikte doğrular.",["test","durum-makinesi","database"],"moderate"),
 ],
 "tests/test_exports.py": [
  ("function","env","Demo tohumuyla (ok, mismatch, okunamayan, kuyruktaki işler) yönetici oturumlu TestClient hazırlar; dışa aktarım testlerinin corpus'u.",["test-fixture","test","disa-aktarim"],"moderate"),
  ("function","csv_satirlari","CSV çıktısını BOM iddiasıyla birlikte okuyup sözlük satırlarına çevirir ve başlığın exports.FIELDS ile aynı olduğunu doğrular.",["test-helper","csv","dogrulama"],"simple"),
  ("function","kimler","Biçimden bağımsız olarak bir dışa aktarımın hangi işleri kapsadığını (job_id kümesi) döndürür; üç biçimin aynı seçimi verdiğini karşılaştırmayı kolaylaştırır.",["test-helper","disa-aktarim","karsilastirma"],"moderate"),
  ("function","test_xlsx_writes_amounts_as_real_numbers_under_a_bold_header","XLSX'te tutarların metin değil gerçek sayı, başlığın ise kalın yazıldığını openpyxl ile okuyarak doğrular.",["test","xlsx","disa-aktarim"],"moderate"),
  ("function","test_the_quality_mode_flag_reaches_all_three_formats","quality modu işaretinin JSON, CSV ve XLSX satırlarının üçünde de göründüğünü kontrol eder.",["test","disa-aktarim","quality-mode"],"moderate"),
  ("function","test_a_corrected_receipt_exports_corrected_in_every_format","Düzeltilmiş bir fişin üç biçimin hepsinde düzeltilmiş değerlerle dışa aktarıldığını uçtan uca doğrular.",["test","disa-aktarim","düzeltme"],"complex"),
 ],
 "tests/test_hardening.py": [
  ("function","env","Gerçek uygulama fabrikası, geçici DATA_DIR ve çalışan anahtarıyla TestClient hazırlar; middleware sırası üretimin kendi sırasıdır.",["test-fixture","test","security"],"moderate"),
  ("function","phone_photo","Gerçek dekodlanan, EXIF döndürme etiketi taşıyan telefon boyutunda JPEG üretir.",["test-helper","gorsel","exif"],"moderate"),
  ("function","submit","Verilen görselle /v1/jobs yüklemesi yapar; yükleme sınırı ve içerik doğrulama testlerinin ortak girişi.",["test-helper","yukleme","api-handler"],"simple"),
  ("function","multipart","Content-Length'suz chunked multipart gövdesi üretir; 413 sınırının parçalı yüklemelerde de çalıştığını sınamak için.",["test-helper","http","yukleme"],"moderate"),
  ("function","test_a_crash_leaves_the_envelope_on_the_wire_and_the_trace_in_the_log","Yakalanmayan bir hatanın cevaba sızmadığını, hata zarfının korunduğunu ve traceback'in yalnızca loga düştüğünü doğrular.",["test","hata-yonetimi","günlükleme"],"moderate"),
 ],
 "tests/test_keys_cli.py": [
  ("function","db_path","Ortam değişkenleriyle CLI'nin kullanacağı izole bir veritabanı yolu kurar.",["test-fixture","cli","database"],"simple"),
  ("function","run","keys_cli.main'i argv ile çağırıp çıkış kodunu döndürür; çıktının capsys ile okunması dışındaki tek giriş noktası.",["test-helper","cli","test"],"simple"),
 ],
 "tests/test_main_app.py": [
  ("function","env","Geçici veritabanıyla create_app'i TestClient arkasına alır ve geçerli bir çalışan anahtarı üretir.",["test-fixture","test","fastapi"],"moderate"),
 ],
 "tests/test_pwa_empty_states.py": [
  ("function","client","Statik PWA varlıklarını okumak için uygulama fabrikasını TestClient ile saran minimal fikstür.",["test-fixture","pwa","test"],"simple"),
 ],
 "tests/test_pwa_history.py": [
  ("function","env","Iki ayrı çalışana ait anahtar ve TestClient hazırlar; geçmişin yalnızca çağıran anahtarın işlerini gösterdiğini sınamanın temeli.",["test-fixture","test","yetki"],"moderate"),
  ("function","submit","Gerçek bir JPEG'i verilen anahtarla yükleyip job_id döndürür.",["test-helper","yukleme","pwa"],"simple"),
 ],
 "tests/test_pwa_shell.py": [
  ("function","client","PWA kabuğu varlıklarını çekmek için uygulamayı TestClient olarak hazırlar.",["test-fixture","pwa","test"],"simple"),
 ],
 "tests/test_pwa_submit_flow.py": [
  ("function","client","Sunulan gönderim sayfası ve app.js içeriğini okumak için TestClient fikstürü.",["test-fixture","pwa","test"],"simple"),
 ],
 "tests/test_queue_worker.py": [
  ("function","bundle","Worker'ın bir koşucudan alacağı sözleşme demetini (result/validation/meta/error) üreten sahte çıktı.",["test-helper","test-double","kuyruk-worker"],"simple"),
  ("function","wait_until","Koşul sağlanana kadar kısa aralıklarla yoklayan, 5 saniyelik zaman aşımı olan bekleme yardımcısı.",["test-helper","eşzamanlilik","test"],"moderate"),
  ("function","env","Görsel dosyası ve geçici veritabanıyla (path, conn, image_path) üçlüsünü hazırlar.",["test-fixture","test","kuyruk-worker"],"moderate"),
  ("function","running","Worker'ı başlatıp test gövdesini çalıştıran, çıkışta her hâlde stop eden context manager.",["test-helper","yasam-dongusu","kuyruk-worker"],"simple"),
  ("function","test_runner_exception_fails_job_but_the_worker_survives","Koşucunun fırlattığı hatanın işi failed yaptığına ama döngünün bir sonraki işe devam ettiğine bakar.",["test","dayaniklilik","kuyruk-worker"],"moderate"),
  ("function","test_burst_of_jobs_is_absorbed","Aynı anda kuyruğa giren çok sayıda işin düşmeden, tek tek işlenerek absorbe edildiğini doğrular.",["test","kuyruk","eşzamanlilik"],"moderate"),
  ("function","test_stop_waits_for_the_job_in_flight","stop()'un devam eden işi yarıda kesmediğini ve iş bittikten sonra döndüğünü doğrular.",["test","yasam-dongusu","kuyruk-worker"],"moderate"),
 ],
 "tests/test_rate_limit.py": [
  ("function","conn","Bucket testlerinin ihtiyaç duyduğu anahtarları kaydetmek için geçici SQLite bağlantısı.",["test-fixture","database","test"],"simple"),
  ("function","bucket","config'den okunan kapasite/yenileme yerine testin kendi sınırını veren token bucket sarmalayıcısı.",["test-helper","rate-limit","yapilandirma"],"simple"),
 ],
 "tests/test_routes_jobs.py": [
  ("function","env","Geçici DATA_DIR, gerçek fabrika ve çalışan anahtarıyla TestClient hazırlar; /v1/jobs testlerinin ortak girişi.",["test-fixture","test","api-handler"],"moderate"),
  ("function","submit","Verilen ek alanlarla /v1/jobs yüklemesi yapar (client_ref, captured_at, mode).",["test-helper","yukleme","api-handler"],"simple"),
  ("function","test_get_job_returns_the_matured_envelope","Olgunlaşmış bir işin GET yanıtının contract v1 zarfını, doğrulama bloğunu ve meta alanlarını eksiksiz taşıdığını uçtan uca doğrular.",["test","contract","api-handler"],"complex"),
 ],
 "tests/test_routes_worker.py": [
  ("function","env","Iki çalışan anahtarı ve TestClient ile /api/me yüzeyini hazırlar; sahip olmayan anahtarın erişememesi bu kurulumla sınanır.",["test-fixture","test","yetki"],"moderate"),
  ("function","submit","Çalışan yüzü testleri için iş yükler ve iş kimliğini döndürür.",["test-helper","yukleme","pwa"],"simple"),
  ("function","finish","İşi running üzerinden done'a taşıyıp sonuç ve doğrulama bloklarını (verdict, toplam) yazan yardımcı; çalışanın sonuç görünümünün ön koşulu.",["test-helper","durum-makinesi","pwa"],"moderate"),
 ],
 "tests/test_serve_demo.py": [
  ("function","_seed","serve_demo.seed_jobs'u geçici veritabanına çalıştırıp her kuyruk durumu ve karardan örnek iş üretir.",["test-helper","demo","database"],"simple"),
 ],
 "tests/test_status.py": [
  ("function","tasima","Yalnızca açık portlarda /v1/models'a 200 döndüren, diğerlerinde ConnectError fırlatan httpx MockTransport; servis proplarının sahte dünyası.",["test-double","http","izleme"],"moderate"),
  ("function","env","Sahte taşıma, sahte VRAM ve geçici veritabanıyla durum ürettiren TestClient fikstürü.",["test-fixture","test","izleme"],"complex"),
 ],
 "tests/test_upload_atomic_orphan.py": [
  ("function","env","_strip_exif'in kasıtlı patlatıldığı (monkeypatch) bir yüklemenin ardında iş satırı bırakmadığını kanıtlayacak kurulumu hazırlar.",["test-fixture","test","atomiklik"],"moderate"),
  ("function","submit","Yükleme yapıp hem HTTP yanıtını hem de veritabanındaki satır sayısını kontrol etmeye olanak veren gönderim yardımcısı.",["test-helper","yukleme","test"],"simple"),
 ],
 "tests/test_upload_exif_stripped.py": [
  ("function","env","Gerçek fabrika, geçici DATA_DIR ve çalışan anahtarıyla TestClient hazırlar; EXIF testi üretim kaydetme yolunun kendisini kullanır.",["test-fixture","test","kvkk"],"moderate"),
  ("function","phone_photo","Döndürme etiketi ve GPS bloğu içeren gerçek bir telefon fotoğrafı JPEG'i üretir.",["test-helper","gorsel","exif"],"moderate"),
  ("function","clean_photo","EXIF taşımayan karşılaştırma JPEG'i üretir; kaybın gerçekten EXIF'e özgü olduğunu kanıtlar.",["test-helper","gorsel","test"],"simple"),
  ("function","submit","Verilen JPEG'i /v1/jobs'a yükler; kaydedilen baytlar ile route'un döndürdükleri aynı dosyadan okunur.",["test-helper","yukleme","kvkk"],"simple"),
 ],
}

# ---- tested_by: production subject -> test file ----
TB = {
 "tests/test_admin_auth.py": "app/main.py",
 "tests/test_admin_detail.py": "app/main.py",
 "tests/test_admin_keys.py": "app/main.py",
 "tests/test_admin_list.py": "app/main.py",
 "tests/test_admin_sort_date.py": "app/main.py",
 "tests/test_auth.py": "app/auth.py",
 "tests/test_captured_at_survives.py": "app/queue_worker.py",
 "tests/test_corrections.py": "app/main.py",
 "tests/test_db.py": "app/db.py",
 "tests/test_exports.py": "app/exports.py",
 "tests/test_hardening.py": "app/main.py",
 "tests/test_keys_cli.py": "app/keys_cli.py",
 "tests/test_main_app.py": "app/main.py",
 "tests/test_pwa_empty_states.py": "app/main.py",
 "tests/test_pwa_history.py": "app/main.py",
 "tests/test_pwa_shell.py": "app/main.py",
 "tests/test_pwa_submit_flow.py": "app/main.py",
 "tests/test_queue_worker.py": "app/queue_worker.py",
 "tests/test_rate_limit.py": "app/auth.py",
 "tests/test_routes_jobs.py": "app/routes_jobs.py",
 "tests/test_routes_worker.py": "app/routes_worker.py",
 "tests/test_serve_demo.py": "scripts/serve_demo.py",
 "tests/test_status.py": "app/status.py",
 "tests/test_upload_atomic_orphan.py": "app/routes_jobs.py",
 "tests/test_upload_exif_stripped.py": "app/routes_jobs.py",
}

# ---- cross-file calls (source fn node -> target symbol) ----
CALLS = [
 ("app/keys_cli.py", "_cmd_add", "app/auth.py", "create_key"),
 ("app/keys_cli.py", "_cmd_revoke", "app/auth.py", "revoke_key"),
 ("app/keys_cli.py", "main", "app/db.py", "connect"),
 ("app/auth.py", "create_key", "app/db.py", "_now"),
 ("app/main.py", "_connect", "app/db.py", "connect"),
 ("app/main.py", "_add_auth_middleware", "app/auth.py", "authorize"),
 ("app/main.py", "_add_admin_guard", "app/auth.py", "session_ok"),
 ("app/main.py", "_add_upload_cap", "app/routes_jobs.py", "too_large_message"),
]

PUBLIC_EXPORTS = {
 "app/auth.py": [n for k, n, *_ in S["app/auth.py"] if not n.startswith("_")],
 "app/db.py": [n for k, n, *_ in S["app/db.py"] if not n.startswith("_")],
 "app/keys_cli.py": ["main"],
 "app/main.py": ["create_app"],
}

files = sorted(F.keys())
nodes = {}
for p in files:
    ntype, summary, tags, cx, notes = F[p]
    node = {"id": f"{ntype}:{p}", "type": ntype, "name": pathlib.Path(p).name,
            "filePath": p, "summary": summary, "tags": tags, "complexity": cx}
    if notes:
        node["languageNotes"] = notes
    nodes[node["id"]] = node
    for kind, name, summ, tags2, cx2 in S.get(p, []):
        key = name if kind == "function" else name
        nid = f"{kind}:{p}:{name}"
        lr = rng(p, name, "functions" if kind == "function" else "classes")
        n2 = {"id": nid, "type": kind, "name": name, "filePath": p,
              "lineRange": lr, "summary": summ, "tags": tags2, "complexity": cx2}
        if nid in nodes:
            raise SystemExit("DUP " + nid)
        nodes[nid] = n2

edges = []
seen_edge = set()
def E(src, tgt, t, w):
    if src == tgt:
        raise SystemExit(f"SELF {src}")
    k = (src, tgt, t)
    if k in seen_edge:
        return
    seen_edge.add(k)
    edges.append({"source": src, "target": tgt, "type": t, "direction": "forward", "weight": w})

for p in files:
    fid = f"{F[p][0]}:{p}"
    for kind, name, *_ in S.get(p, []):
        E(fid, f"{kind}:{p}:{name}", "contains", 1.0)
    for name in PUBLIC_EXPORTS.get(p, []):
        E(fid, f"function:{p}:{name}", "exports", 0.8)
    for tgt in IMP.get(p, []):
        E(fid, f"file:{tgt}", "imports", 0.7)
for test_file, prod in TB.items():
    E(f"file:{prod}", f"file:{test_file}", "tested_by", 0.5)
for sp, sfn, tp, tfn in CALLS:
    E(f"function:{sp}:{sfn}", f"function:{tp}:{tfn}", "calls", 0.8)

# ---- validation ----
NMAP = inp["neighborMap"]
xsym = set()
for neighs in NMAP.values():
    for n in neighs:
        for s in n.get("symbols", []):
            xsym.add((n["path"], s))
known_files = set(files) | {t for v in IMP.values() for t in v} | set(TB.values())
for e in edges:
    for side in ("source", "target"):
        v = e[side]
        if v in nodes:
            continue
        if v.startswith("file:"):
            if v[5:] not in known_files:
                raise SystemExit(f"UNKNOWN FILE REF {v}")
            continue
        rest = v.split(":", 1)
        if len(rest) == 2 and rest[0] in ("function", "class"):
            path, sym = rest[1].rsplit(":", 1)
            if (path, sym) in xsym or any(n["id"] == v for n in nodes.values()):
                continue
            raise SystemExit(f"UNKNOWN SYMBOL REF {v}")
        raise SystemExit(f"UNRESOLVED {side} {v}")
imp_count = sum(1 for e in edges if e["type"] == "imports")
expected = sum(len(v) for v in IMP.values())
assert imp_count == expected, f"import edges {imp_count} != {expected}"

# ---- partition into 4 parts of 8 files ----
PARTS = 5
size = math.ceil(len(files) / PARTS)
chunks = [files[i:i + size] for i in range(0, len(files), size)]
outdir = UA / "intermediate"
outdir.mkdir(parents=True, exist_ok=True)
report = []
def owner_path(e):
    """In-batch file an edge belongs to: its source if that node is ours,
    otherwise its target (cross-batch-source tested_by edges ride with the
    test file so they are not dropped)."""
    for side in ("source", "target"):
        v = e[side]
        if v in nodes:
            return nodes[v]["filePath"]
        if v.startswith("file:") and v[5:] in set(files):
            return v[5:]
    return None

for i, chunk in enumerate(chunks, start=1):
    cs = set(chunk)
    pnodes = [n for n in nodes.values() if n["filePath"] in cs]
    pedges = [e for e in edges if owner_path(e) in cs]
    frag = {"nodes": pnodes, "edges": pedges}
    out = outdir / f"batch-1-part-{i}.json"
    out.write_text(json.dumps(frag, ensure_ascii=False, indent=2), encoding="utf-8")
    report.append((out.name, len(pnodes), len(pedges)))

print("nodes", len(nodes), "edges", len(edges), "imports", imp_count)
for r in report:
    print(r)
over = [r for r in report if r[1] > 60 or r[2] > 120]
print("parts over limit:", over)
covered = sum(r[1] for r in report), sum(r[2] for r in report)
print("coverage nodes/edges", covered)
