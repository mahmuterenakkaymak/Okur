import json, pathlib

ROOT = pathlib.Path("C:/Users/PC/Documents/GitHub/ocr-app")
inp = json.load(open(ROOT / ".ua/tmp/batch-input-4.json", encoding="utf-8"))
imp = inp["batchImportData"]

nodes = [
    # ---------- FILE NODES ----------
    {"id": "file:app/validator.py", "type": "file", "name": "validator.py", "filePath": "app/validator.py",
     "summary": "Modelin çıkardığı fiş sonucunu deterministik aritmetikle doğrular: items[] üzerinden satır toplamlarını, ara toplamı, tek ve karışık oranlı KDV'yi ve genel toplamı yeniden hesaplar, 0.01 toleransla basılı değerlerle karşılaştırır. Tek oranlı fişleri hem KDV harici hem KDV dahildir tabanında dener, uyuşmazsa ihlal eden alanı adlandırarak döndürür; saf fonksiyondur, girdiyi değiştirmez.",
     "tags": ["validation", "deterministic", "aritmetik", "kdv", "domain-core"],
     "complexity": "moderate",
     "languageNotes": "LLM hiçbir sayının sahibi olmaz; tutarlılık tamamen Python ile doğrulanır. namedtuple tabanlı çok tabanlı KDV yaklaşımı (exclusive/inclusive)."},
    {"id": "file:scripts/__init__.py", "type": "file", "name": "__init__.py", "filePath": "scripts/__init__.py",
     "summary": "scripts paketini tanımlayan boş işaret dosyası; acceptance ve gen_contract_doc gibi geliştirme betiklerinin paket olarak içe aktarılmasını sağlar.",
     "tags": ["barrel", "paket", "entry-point"],
     "complexity": "simple"},
    {"id": "file:scripts/acceptance.py", "type": "file", "name": "acceptance.py", "filePath": "scripts/acceptance.py",
     "summary": "Brief bölüm 9'un otomatikleştirilebilir kabul kontrollerini canlı bir örnek üzerinde çalıştırır. --demo gerçek uygulama/auth/kuyruk + sahte model sahneleriyle geçici portta stack'i ayağa kaldırır; her kontrolden sonra tek satırlık bir tablo basar ve herhangi bir satır FAIL ise 1 ile çıkar, böylece operatör, run.py ve CI tek komutla geçiş kapısını denetler.",
     "tags": ["acceptance-test", "entegrasyon", "cli", "e2e", "dogrulama"],
     "complexity": "complex",
     "languageNotes": "httpx ile canlı HTTP, jsonschema ile contract v1 zarfı doğrulaması; Instance sınıfı iki kimliği (worker key + admin oturumu) taşır."},
    {"id": "file:scripts/gen_contract_doc.py", "type": "file", "name": "gen_contract_doc.py", "filePath": "scripts/gen_contract_doc.py",
     "summary": "app/contract.py pydantic modellerinden contract/contract_v1.schema.json ve CONTRACT.md artifacts'ını yeniden üretir. Her iki çıktı da bayt kararlıdır: modeller değişmeden tekrar çalıştırmak birebir aynı baytları yazar, böylece commit edilmiş dosyalar aynı zamanda yeniden-üretim kontrolüdür.",
     "tags": ["kod-uretimi", "dokumentasyon", "schema", "contract", "cli"],
     "complexity": "moderate"},

    # ---------- app/validator.py SUBNODES ----------
    {"id": "function:app/validator.py:validate", "type": "function", "name": "validate", "filePath": "app/validator.py",
     "lineRange": [25, 78],
     "summary": "Bir sonuç sözlüğü veya modelini contract v1 doğrulama bloğuna (şekil 3) çevirir: boş items durumunda unreadable, aksi halde yeniden hesaplanan taban ile basılı toplamları karşılaştırıp ok/uyuşmazlık kararı ve ihlal edilen alan adlarını döndürür.",
     "tags": ["validation", "deterministic", "domain-core", "public-api"],
     "complexity": "moderate"},
    {"id": "function:app/validator.py:_bases", "type": "function", "name": "_bases", "filePath": "app/validator.py",
     "lineRange": [81, 99],
     "summary": "Seçilen KDV tabanına göre beklenen _Base bloklarını üretir: tek oranlı fişte hem exclusive hem iki inclusive varyantı döndürür, karışık oranlıda (kdv_orani<=0) basılı kdv'yi zincir girdisi olarak güvenip tek blok verir; eşitlikte exclusive önce kazanır.",
     "tags": ["kdv", "aritmetik", "help", "deterministic"],
     "complexity": "moderate"},

    # ---------- scripts/acceptance.py SUBNODES ----------
    {"id": "class:scripts/acceptance.py:Instance", "type": "class", "name": "Instance", "filePath": "scripts/acceptance.py",
     "lineRange": [59, 123],
     "summary": "Kontrol edilen çalışan uygulamayı ve kontrollerin kapılarını çaldığı iki kimliği (worker API key + tembel açılan admin oturumu) sarar; fiş gönderme, contract v1 zarfı doğrulama ve bir işi done durumuna kadar kuyrukta bekletme yardımcılarını sağlar.",
     "tags": ["client", "entegrasyon", "test-harness", "http"],
     "complexity": "moderate"},
    {"id": "class:scripts/acceptance.py:CheckError", "type": "class", "name": "CheckError", "filePath": "scripts/acceptance.py",
     "lineRange": [52, 53],
     "summary": "Bir kabul kontrolünün beklediğini bulamadığında fırlattığı sinyal; mesajı sonuç tablosundaki satırın ayrıntı sütununa dönüşür.",
     "tags": ["exception", "sinyal", "acceptance-test"],
     "complexity": "simple"},
    {"id": "function:scripts/acceptance.py:check_contract", "type": "function", "name": "check_contract", "filePath": "scripts/acceptance.py",
     "lineRange": [129, 135],
     "summary": "Bir örneğin zarflarının contract v1 şemasına uyduğunu uçtan uca doğrulayan kabul kontrolü.",
     "tags": ["acceptance-test", "contract", "validation"],
     "complexity": "simple"},
    {"id": "function:scripts/acceptance.py:check_verdict_ok", "type": "function", "name": "check_verdict_ok", "filePath": "scripts/acceptance.py",
     "lineRange": [138, 147],
     "summary": "Temiz fixture fişinin doğrulama kararının ok olduğunu ve tutarların ground truth ile uyuştuğunu denetleyen kabul kontrolü.",
     "tags": ["acceptance-test", "validation", "dogrulama"],
     "complexity": "simple"},
    {"id": "function:scripts/acceptance.py:check_tampered_kdv", "type": "function", "name": "check_tampered_kdv", "filePath": "scripts/acceptance.py",
     "lineRange": [150, 164],
     "summary": "Bozulmuş bir KDV değerinin doğrulayıcı tarafından uyuşmazlık olarak yakalandığını uçtan uca test eden kabul kontrolü.",
     "tags": ["acceptance-test", "validation", "tamper"],
     "complexity": "moderate"},
    {"id": "function:scripts/acceptance.py:check_auth", "type": "function", "name": "check_auth", "filePath": "scripts/acceptance.py",
     "lineRange": [167, 190],
     "summary": "/v1 kapılarının worker API key'i olmadan reddedildiğini ve key ile kabul edildiğini doğrulayan kimlik doğrulama kabul kontrolü.",
     "tags": ["acceptance-test", "auth", "güvenlik"],
     "complexity": "moderate"},
    {"id": "function:scripts/acceptance.py:check_idempotent", "type": "function", "name": "check_idempotent", "filePath": "scripts/acceptance.py",
     "lineRange": [193, 208],
     "summary": "Aynı client_ref ile tekrarlanan gönderimin aynı işi döndürdüğünü (idempotency) denetleyen kabul kontrolü.",
     "tags": ["acceptance-test", "idempotency", "queue"],
     "complexity": "moderate"},
    {"id": "function:scripts/acceptance.py:check_export_parity", "type": "function", "name": "check_export_parity", "filePath": "scripts/acceptance.py",
     "lineRange": [211, 250],
     "summary": "Dışa aktarma biçimlerinin (CSV/XLSX/JSON) uygulamanın yazdığı satırları birebir taşıdığını okuyucu tarafından yeniden okuyarak doğrulayan en geniş kabul kontrolü.",
     "tags": ["acceptance-test", "export", "parity", "csv", "xlsx"],
     "complexity": "complex"},
    {"id": "function:scripts/acceptance.py:check_validator_edges", "type": "function", "name": "check_validator_edges", "filePath": "scripts/acceptance.py",
     "lineRange": [253, 262],
     "summary": "Doğrulayıcının kenar durum testlerinin olduğu gibi geçtiğini doğrulayan kabul kontrolü.",
     "tags": ["acceptance-test", "validation", "edge-case"],
     "complexity": "simple"},
    {"id": "function:scripts/acceptance.py:_boot_demo", "type": "function", "name": "_boot_demo", "filePath": "scripts/acceptance.py",
     "lineRange": [401, 416],
     "summary": "Kabul kontrollerini çalıştırmak için demo stack'ini geçici bir portta ayağa kaldırıp Instance'ını hazırlayan kurulum yardımcısı.",
     "tags": ["test-harness", "bootstrap", "demo"],
     "complexity": "moderate"},
    {"id": "function:scripts/acceptance.py:_live", "type": "function", "name": "_live", "filePath": "scripts/acceptance.py",
     "lineRange": [419, 436],
     "summary": "Kontrolleri verilen bir base_url ve worker key üzerinde sırayla çalıştırıp sonuç satırlarını toplayan canlı koşum akışı.",
     "tags": ["test-harness", "entegrasyon", "cli"],
     "complexity": "moderate"},
    {"id": "function:scripts/acceptance.py:main", "type": "function", "name": "main", "filePath": "scripts/acceptance.py",
     "lineRange": [462, 501],
     "summary": "argparse ile --demo/--base-url/--api-key seçeneklerini çözüp örnekleri hazırlar, kontrolleri çalıştırır ve herhangi biri FAIL ise 1 ile çıkarak CI geçiş kapısını kurar.",
     "tags": ["cli", "entry-point", "acceptance-test"],
     "complexity": "moderate"},

    # ---------- scripts/gen_contract_doc.py SUBNODES ----------
    {"id": "function:scripts/gen_contract_doc.py:_type_name", "type": "function", "name": "_type_name", "filePath": "scripts/gen_contract_doc.py",
     "lineRange": [112, 122],
     "summary": "Bir JSON Schema düğümünün tipini Türkçe doküman için okunur bir Python tipi adına çeviren küçük dönüştürücü.",
     "tags": ["kod-uretimi", "schema", "utility"],
     "complexity": "simple"},
    {"id": "function:scripts/gen_contract_doc.py:doc_text", "type": "function", "name": "doc_text", "filePath": "scripts/gen_contract_doc.py",
     "lineRange": [142, 149],
     "summary": "contract modellerinden CONTRACT.md gövdesini (sürüm notu, varsayılanlar ve alan tabloları) bayt kararlı biçimde üreten ana üretici.",
     "tags": ["kod-uretimi", "dokumentasyon", "contract"],
     "complexity": "simple"},
    {"id": "function:scripts/gen_contract_doc.py:main", "type": "function", "name": "main", "filePath": "scripts/gen_contract_doc.py",
     "lineRange": [157, 162],
     "summary": "Şema ve doküman artifacts'ını contract modülünden yeniden üreten CLI girişi.",
     "tags": ["cli", "entry-point", "kod-uretimi"],
     "complexity": "simple"},

    # ---------- TEST FILE NODES ----------
    {"id": "file:tests/test_acceptance.py", "type": "file", "name": "test_acceptance.py", "filePath": "tests/test_acceptance.py",
     "summary": "scripts/acceptance.py kabul kontrollerini sahte bir örnek üzerinde test eder: ayağa kalkmış demo karşısında geçiş, kontrol başarısızlığında sıfır olmayan çıkış, erişilemeyen örnek için traceback'siz hata ve contract/validator/export parity kontrollerinin doğru yakaladığı durumlar.",
     "tags": ["test", "acceptance-test", "test-harness"],
     "complexity": "moderate"},
    {"id": "file:tests/test_acceptance_live_key.py", "type": "file", "name": "test_acceptance_live_key.py", "filePath": "tests/test_acceptance_live_key.py",
     "summary": "Kabul betiğinin worker key çözümlemesini test eder: verilen bir anahtarın demo uç noktasını yoklamaması, komut satırı anahtarının ortam değişkenini yenmesi ve anahtarsız hatanın düzelten bayrağı adlandırması.",
     "tags": ["test", "auth", "cli", "acceptance-test"],
     "complexity": "moderate"},
    {"id": "file:tests/test_contract_doc_endpoints.py", "type": "file", "name": "test_contract_doc_endpoints.py", "filePath": "tests/test_contract_doc_endpoints.py",
     "summary": "CONTRACT.md uç nokta tablosunun okunur olduğunu ve tabloda listelenen her uç noktanın gerçek uygulamada kayıtlı olduğunu doğrulayan test.",
     "tags": ["test", "contract", "dokumentasyon"],
     "complexity": "simple"},
    {"id": "file:tests/test_contract_export.py", "type": "file", "name": "test_contract_export.py", "filePath": "tests/test_contract_export.py",
     "summary": "Dışa aktarılan şemanın bayt kararlı yeniden üretimi, deterministik şema metni ve CONTRACT.md tablolarının tüm contract alanlarını ve karar/uç nokta/sürüm notlarını kapsadığını doğrulayan test.",
     "tags": ["test", "schema", "contract", "kod-uretimi"],
     "complexity": "moderate"},
    {"id": "file:tests/test_quality_rerun.py", "type": "file", "name": "test_quality_rerun.py", "filePath": "tests/test_quality_rerun.py",
     "summary": "Kalite modunda yeniden koşumun (rerun) sonucu değiştirdiğini ve beş yüzeyin (detay, çalışan, yönetici, dışa aktarma, düzeltme) yeni sayıları takip ettiğini, kararın yeni tutarlardan yeniden hesaplandığını ve başarısız bir rerun'un işi olduğu gibi bıraktığını uçtan uca test eder.",
     "tags": ["test", "quality-mode", "rerun", "entegrasyon"],
     "complexity": "complex"},
    {"id": "file:tests/test_serve_demo_live_states.py", "type": "file", "name": "test_serve_demo_live_states.py", "filePath": "tests/test_serve_demo_live_states.py",
     "summary": "Demo sunucusunda queued ve running işlerinin worker tarafından doğru şekilde done'a taşındığını, yükleme-kuyruk-bitimi akışının korunduğunu test eder.",
     "tags": ["test", "demo", "queue", "entegrasyon"],
     "complexity": "moderate"},
    {"id": "file:tests/test_smoke_e2e.py", "type": "file", "name": "test_smoke_e2e.py", "filePath": "tests/test_smoke_e2e.py",
     "summary": "Uçtan uca smoke hattını gerçek HTTP üzerinden test eder: aşama kırıldığında sıfır olmayan çıkış, temiz zarfın kabulü, ground truth ile uyuşmayan tutarların ve mismatch kararının reddi, contract dışı zarfın düşmesi.",
     "tags": ["test", "e2e", "smoke", "entegrasyon"],
     "complexity": "moderate"},
    {"id": "file:tests/test_validator.py", "type": "file", "name": "test_validator.py", "filePath": "tests/test_validator.py",
     "summary": "validate() temel davranışını test eder: ground truth fixture'larının ok doğrulaması, beklenen/gerçek blokların taşınması, bozulmuş satır/kdv/genel toplam/ara toplam alanlarının adlandırılması ve tolerans içi kuruş sürüklenmesinin ok kalması.",
     "tags": ["test", "validation", "domain-core"],
     "complexity": "moderate"},
    {"id": "file:tests/test_validator_edges.py", "type": "file", "name": "test_validator_edges.py", "filePath": "tests/test_validator_edges.py",
     "summary": "validate() kenar durumlarını test eder: karışık KDV oranlı fişler, TL/lira para birimi biçimleri, sıfır miktarlı ve kg satırları, negatif iskonto, eksik totals bloğu, boş items unreadable ve KDV dahildir/haricidir taban seçimleri.",
     "tags": ["test", "validation", "edge-case", "kdv"],
     "complexity": "moderate"},
]

# ---- imports edges: emit verbatim from batchImportData (guarantees exact count) ----
edges = []
for src, targets in imp.items():
    for t in targets:
        edges.append({"source": f"file:{src}", "target": f"file:{t}",
                      "type": "imports", "direction": "forward", "weight": 0.7})

# ---- contains edges: file -> each subnode I created ----
for n in nodes:
    if n["type"] in ("function", "class"):
        edges.append({"source": f"file:{n['filePath']}", "target": n["id"],
                      "type": "contains", "direction": "forward", "weight": 1.0})

# ---- exports edges: genuinely public (non-underscore) subnodes ----
pub = {
    "function:app/validator.py:validate",
    "class:scripts/acceptance.py:Instance", "class:scripts/acceptance.py:CheckError",
    "function:scripts/acceptance.py:check_contract", "function:scripts/acceptance.py:check_verdict_ok",
    "function:scripts/acceptance.py:check_tampered_kdv", "function:scripts/acceptance.py:check_auth",
    "function:scripts/acceptance.py:check_idempotent", "function:scripts/acceptance.py:check_export_parity",
    "function:scripts/acceptance.py:check_validator_edges", "function:scripts/acceptance.py:main",
    "function:scripts/gen_contract_doc.py:doc_text", "function:scripts/gen_contract_doc.py:main",
}
byid = {n["id"]: n for n in nodes}
for pid in pub:
    edges.append({"source": f"file:{byid[pid]['filePath']}", "target": pid,
                  "type": "exports", "direction": "forward", "weight": 0.8})

# ---- calls edges (confident cross-file) ----
calls = [
    ("file:scripts/acceptance.py", "function:app/validator.py:validate"),
    ("file:tests/test_validator.py", "function:app/validator.py:validate"),
    ("file:tests/test_validator_edges.py", "function:app/validator.py:validate"),
]
for s, t in calls:
    edges.append({"source": s, "target": t, "type": "calls", "direction": "forward", "weight": 0.8})

# ---- tested_by edges (production -> test), confident pairs ----
tested = [
    ("app/validator.py", "tests/test_validator.py"),
    ("app/validator.py", "tests/test_validator_edges.py"),
    ("app/validator.py", "tests/test_quality_rerun.py"),
    ("app/validator.py", "tests/test_acceptance.py"),
    ("scripts/acceptance.py", "tests/test_acceptance.py"),
    ("scripts/acceptance.py", "tests/test_acceptance_live_key.py"),
    ("scripts/gen_contract_doc.py", "tests/test_contract_export.py"),
    ("scripts/gen_contract_doc.py", "tests/test_contract_doc_endpoints.py"),
    ("scripts/serve_demo.py", "tests/test_serve_demo_live_states.py"),
    ("app/contract.py", "tests/test_contract_export.py"),
]
for prod, test in tested:
    edges.append({"source": f"file:{prod}", "target": f"file:{test}",
                  "type": "tested_by", "direction": "forward", "weight": 0.5})

# ---- self-checks ----
expected_imports = sum(len(v) for v in imp.values())
actual_imports = sum(1 for e in edges if e["type"] == "imports")
assert expected_imports == actual_imports, f"import mismatch {actual_imports}!={expected_imports}"
ids = [n["id"] for n in nodes]
assert len(ids) == len(set(ids)), "duplicate node id"
for e in edges:
    assert e["source"] != e["target"], f"self edge {e}"

out = {"nodes": nodes, "edges": edges}
(ROOT / ".ua/intermediate/batch-4.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"nodes={len(nodes)} edges={len(edges)} imports={actual_imports}/{expected_imports}")
from collections import Counter
print(Counter(e['type'] for e in edges))
