import { writeFileSync, readFileSync } from "node:fs";

const R = "C:/Users/PC/Documents/GitHub/ocr-app";
const nodes = [
  {
    id: "document:CONTRACT.md",
    type: "document",
    name: "CONTRACT.md",
    filePath: "CONTRACT.md",
    summary:
      "Entegratörler için sözleşme v1'in insan okunur referansı: endpoint tablosu, job envelope ile result/validation/meta alan şemaları ve ok | mismatch | unreadable karar kuralları. `/v1` donmuş sürüm kuralını, düzeltmelerin /admin/api altında olmasını ve Türkçe fiş sayı formatlarının (1.046,40 / %20 / 198,82 TL) normalize edilmesini belgeler.",
    tags: ["dokumentasyon", "api-contract", "şema", "entegrasyon", "sürümleme"],
    complexity: "moderate",
    languageNotes:
      "Alan adları fişin kendi Türkçe terimleri (ara_toplam, iskonto, kdv, okunamayan); pydantic tek doğruluk kaynağıdır ve JSON Schema ile bu belge ikisi birlikte üretilir. Arithmetiği LLM değil validator üretir: validation.expected her zaman items[] üzerinden yeniden hesaplanır.",
  },
  {
    id: "document:HIZLI-BASLANGIC.md",
    type: "document",
    name: "HIZLI-BASLANGIC.md",
    filePath: "HIZLI-BASLANGIC.md",
    summary:
      "Eren'e yönelik Türkçe hızlı başlangıç rehberi: model indirmeden demo sunucuyla beş dakikada deneme, gerçek hatla run.py çalıştırma, çalışan API anahtarı üretme, telefona PWA kurma ve küçükten büyüğe kontrol komutları. Kabul edilmiş açıkların ve sorun çıkarsa bakılacak yerlerin özetini taşır.",
    tags: ["dokumentasyon", "hızlı-başlangıç", "kurulum", "pwa", "operasyon"],
    complexity: "moderate",
    languageNotes:
      "İngilizce ana dokümanın (README.md) yanında tek kişiye yönelik, komut odaklı bir giriş katmanı; bilinen açıkları REVIEW.md'ye atıfla açıkça listeler.",
  },
  {
    id: "document:OPERATIONS.md",
    type: "document",
    name: "OPERATIONS.md",
    filePath: "OPERATIONS.md",
    summary:
      "Tek makineyi deployment'ın kendisi sayan operasyon kılavuzu: data/ yedeği, çalışan anahtarı ve ADMIN_TOKEN rotasyonu, log konumları, model ve binary yolları, VRAM bütçesi ile tek komutluk günlük kabul kontrolü. KVKK gereği data/ altının gitignore'da kalması gerektiğini vurgular.",
    tags: ["dokumentasyon", "operasyon", "yedekleme", "güvenlik", "izleme"],
    complexity: "moderate",
    languageNotes:
      "SQLite WAL modunda çalıştığı için yedek ocr.db, -wal ve -shm üçlüsünü bir arada almayı zorunlu kılar; OCR CPU'da (-ngl 0) çalışarak 32 GB kartı Strata ile paylaşır.",
  },
  {
    id: "document:PLAN.md",
    type: "document",
    name: "PLAN.md",
    filePath: "PLAN.md",
    summary:
      "Mimari ve modül sözleşmeleri belgesi: üç aşamalı hattın şeması, dosya yapısı, on tasarım kararı (CPU'da OCR, contract'ın koddan üretilmesi, idempotency, SHA-256 anahtarlar, EXIF temizliği) ve modüller arası on veri şekli. Bir alan değiştiğinde birlikte dokunulması gereken yerleri 'wholes' başlığıyla listeler.",
    tags: ["dokumentasyon", "mimari", "tasarım-kararları", "modül-sözleşmeleri", "kilometre-taşı"],
    complexity: "complex",
    languageNotes:
      "Wholes listesi, tek bir sözleşme alanı değişikliğinin temas yüzünü (contract.py, şema, CONTRACT.md, admin ekranı, export sütunları, PWA) önceden sabitleyerek yarım kalan değişiklikleri engelleyen bir tasarım sözleşmesidir.",
  },
  {
    id: "document:PROJECT_BRIEF.md",
    type: "document",
    name: "PROJECT_BRIEF.md",
    filePath: "PROJECT_BRIEF.md",
    summary:
      "İş gereksinimleri dokümanı: hedef, üç kullanıcı tipi (saha çalışanı, admin/entegratör, dış entegratör geliştirici), v1 kapsamı ve kapsam dışındakiler, stack ile VRAM/ağ kısıtları, arayüzler, on kabul testi, kilometre taşları ve açık riskler. Ürünün sürümlenmiş JSON sözleşme olduğunu ve aritmetiğin deterministik Python'da kaldığını sabitler.",
    tags: ["dokumentasyon", "gereksinimler", "kapsam", "kabul-testleri", "risk"],
    complexity: "moderate",
    languageNotes:
      "Kapsam dışı listesi (webhook, native uygulama, çok kiracılı SaaS, bulut OCR) kadar 'asla' maddeleri de içerir: bulut OCR ve telemetry hiç yok, v1'de açık internete çıkış yok.",
  },
  {
    id: "document:README.md",
    type: "document",
    name: "README.md",
    filePath: "README.md",
    summary:
      "Projenin ana giriş noktası: sistemin ne yaptığı, PowerShell quickstart'ı (.env ve uv ile kurulum), PWA kurulumu, entegratör rehberi (idempotency ve tek tip hata zarfı dahil), Tailscale ile tailnet üzerinde HTTPS ve semptom-çözüm tablolu sorun giderme. Diğer dört dokümana yönlendirme yaparak dokümantasyonun navigasyon katmanı olur.",
    tags: ["dokumentasyon", "entry-point", "kurulum", "entegrasyon", "sorun-giderme"],
    complexity: "complex",
    languageNotes:
      "Tailscale 'serve' ile 'funnel' ayrımını KVKK gerekçesiyle açıkça yazar: funnel, fiş görüntülerini ve API'yi tüm internete açan tek komuttur ve v1'de yasaktır.",
  },
  {
    id: "document:REVIEW.md",
    type: "document",
    name: "REVIEW.md",
    filePath: "REVIEW.md",
    summary:
      "M1'in (T01-T18) kabul incelemesi: 665 pytest ve 192 node testi yeşilken T11'in geç gelmesinin ortaya çıkardığı üç sınır hatası — B1 unreadable'ın failed'a dönüşmesi, B2 gerçek Structurer'ın uçtan uca kapıdan geçmemesi, B3 resim yazılmadan kuyruk satırının commit edilmesi. Kabul edilmiş riskleri ve eksik testleri düzeltme görevlerine bağlar.",
    tags: ["dokumentasyon", "kod-incelemesi", "hata-raporu", "test", "milestone"],
    complexity: "simple",
    languageNotes:
      "Bulgular ASSUMPTION yorumlarıyla birlikte denetlenir: hangi varsayımların artık yanlış olduğu (B1/B2) ile sağlam kalanlar ayrı ayrı belirtilir, her bulgu doğrudan bir T6x görevine bağlanır.",
  },
  {
    id: "document:TASKS.md",
    type: "document",
    name: "TASKS.md",
    filePath: "TASKS.md",
    summary:
      "M1-M4 yapımlık görev defteri: her görev tek satırda kök neden, beklenen davranış ve `accept:` doğrulama komutu olarak yazılı. T01-T69 tamamlanmış; REVIEW bulguları (T65-T67) ve canlı test bulguları (T68 thinking token, T69 KDV dahil taban) aynı deftere eklenmiştir.",
    tags: ["dokumentasyon", "görev-defteri", "yapım-sırası", "doğrulama", "kilometre-taşı"],
    complexity: "moderate",
    languageNotes:
      "`accept:` alanı görevin bitiş koşulunu çalıştırılabilir bir pytest/node komutuyla sabitler; görev metni düzeltilecek satır aralığını (pipeline.py:47-50) ve eskimiş test beklentilerini de adıyla sayar.",
  },
  {
    id: "config:package.json",
    type: "config",
    name: "package.json",
    filePath: "package.json",
    summary:
      "Depoyu Node için ESM ilan eden üç alanlık bildirim dosyası (name, private, type: module). Bağımlılık ve build adımı içermez; JS mantığı bundler'sız ES modülü olarak yazılır ve testler `node --test` ile koşar.",
    tags: ["configuration", "esm", "node", "build-system"],
    complexity: "simple",
    languageNotes:
      "node_modules ve package-lock bulunmaz; `type: module` tek başına, tests/js altındaki node testlerinin static/ altındaki ES modüllerini import edebilmesinin tek koşuludur.",
  },
  {
    id: "config:pyproject.toml",
    type: "config",
    name: "pyproject.toml",
    filePath: "pyproject.toml",
    summary:
      "Yalnızca pytest yapılandırması taşıyan iki satırlık manifest: testpaths = [\"tests\"] ile `python -m pytest` keşfini tests/ dizinine sabitler. Bağımlılık tablosu içermez.",
    tags: ["configuration", "pytest", "test", "build-system"],
    complexity: "simple",
    languageNotes:
      "Bağımlılıklar burada değil README'deki `uv pip install` satırında listelenir; venv'in kendi pip'i yoktur. Uygulama yapılandırması pyproject'te değil app/config.py üzerinden .env ile okunur.",
  },
];

// [sourceId, targetId, type, weight]
const E = (type, w) => (s, t) => ({
  source: s,
  target: t,
  type,
  direction: "forward",
  weight: w,
});
const doc = E("documents", 0.5);
const rel = E("related", 0.5);
const cfg = E("configures", 0.6);

const SCHEMA = "schema:contract/contract_v1.schema.json";
const edges = [
  // CONTRACT.md
  doc("document:CONTRACT.md", "file:app/contract.py"),
  doc("document:CONTRACT.md", SCHEMA),
  doc("document:CONTRACT.md", "file:scripts/gen_contract_doc.py"),
  doc("document:CONTRACT.md", "file:app/validator.py"),
  doc("document:CONTRACT.md", "file:app/routes_jobs.py"),
  doc("document:CONTRACT.md", "file:app/routes_admin.py"),
  // OPERATIONS.md
  doc("document:OPERATIONS.md", "file:app/config.py"),
  doc("document:OPERATIONS.md", "file:app/keys_cli.py"),
  doc("document:OPERATIONS.md", "file:run.py"),
  doc("document:OPERATIONS.md", "file:scripts/acceptance.py"),
  doc("document:OPERATIONS.md", "file:scripts/tailscale_serve.ps1"),
  rel("document:OPERATIONS.md", "document:spike/REPORT.md"),
  rel("document:OPERATIONS.md", "document:CONTRACT.md"),
  rel("document:OPERATIONS.md", "document:README.md"),
  // HIZLI-BASLANGIC.md
  doc("document:HIZLI-BASLANGIC.md", "file:scripts/serve_demo.py"),
  doc("document:HIZLI-BASLANGIC.md", "file:run.py"),
  doc("document:HIZLI-BASLANGIC.md", "file:app/keys_cli.py"),
  doc("document:HIZLI-BASLANGIC.md", "file:scripts/tailscale_serve.ps1"),
  doc("document:HIZLI-BASLANGIC.md", "file:scripts/acceptance.py"),
  doc("document:HIZLI-BASLANGIC.md", "file:scripts/smoke_e2e.py"),
  rel("document:HIZLI-BASLANGIC.md", "document:README.md"),
  rel("document:HIZLI-BASLANGIC.md", "document:CONTRACT.md"),
  rel("document:HIZLI-BASLANGIC.md", "document:OPERATIONS.md"),
  // PLAN.md
  doc("document:PLAN.md", "file:run.py"),
  doc("document:PLAN.md", "file:app/config.py"),
  doc("document:PLAN.md", "file:app/contract.py"),
  doc("document:PLAN.md", "file:app/validator.py"),
  doc("document:PLAN.md", "file:app/db.py"),
  doc("document:PLAN.md", "file:app/auth.py"),
  doc("document:PLAN.md", "file:app/ocr_client.py"),
  doc("document:PLAN.md", "file:app/structurer.py"),
  doc("document:PLAN.md", "file:app/pipeline.py"),
  doc("document:PLAN.md", "file:app/queue_worker.py"),
  doc("document:PLAN.md", "file:app/routes_jobs.py"),
  doc("document:PLAN.md", "file:app/routes_worker.py"),
  doc("document:PLAN.md", "file:app/routes_admin.py"),
  doc("document:PLAN.md", "file:app/exports.py"),
  doc("document:PLAN.md", "file:app/status.py"),
  doc("document:PLAN.md", "file:app/keys_cli.py"),
  doc("document:PLAN.md", "file:app/main.py"),
  doc("document:PLAN.md", "file:scripts/fake_models.py"),
  doc("document:PLAN.md", "file:scripts/smoke_e2e.py"),
  doc("document:PLAN.md", "file:scripts/serve_demo.py"),
  doc("document:PLAN.md", "file:scripts/acceptance.py"),
  rel("document:PLAN.md", "document:spike/REPORT.md"),
  rel("document:PLAN.md", "document:CONTRACT.md"),
  // PROJECT_BRIEF.md
  doc("document:PROJECT_BRIEF.md", "file:app/contract.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/validator.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/routes_jobs.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/auth.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/queue_worker.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/exports.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/status.py"),
  doc("document:PROJECT_BRIEF.md", "file:app/main.py"),
  doc("document:PROJECT_BRIEF.md", "file:run.py"),
  rel("document:PROJECT_BRIEF.md", "document:PLAN.md"),
  rel("document:PROJECT_BRIEF.md", "document:CONTRACT.md"),
  // README.md
  doc("document:README.md", "file:app/config.py"),
  doc("document:README.md", "file:app/validator.py"),
  doc("document:README.md", "file:app/contract.py"),
  doc("document:README.md", SCHEMA),
  doc("document:README.md", "file:scripts/gen_contract_doc.py"),
  doc("document:README.md", "file:run.py"),
  doc("document:README.md", "file:scripts/serve_demo.py"),
  doc("document:README.md", "file:scripts/smoke_e2e.py"),
  doc("document:README.md", "file:scripts/acceptance.py"),
  doc("document:README.md", "file:scripts/tailscale_serve.ps1"),
  doc("document:README.md", "file:app/keys_cli.py"),
  rel("document:README.md", "document:PLAN.md"),
  rel("document:README.md", "document:CONTRACT.md"),
  rel("document:README.md", "document:OPERATIONS.md"),
  rel("document:README.md", "document:HIZLI-BASLANGIC.md"),
  rel("document:README.md", "document:PROJECT_BRIEF.md"),
  // REVIEW.md
  doc("document:REVIEW.md", "file:app/pipeline.py"),
  doc("document:REVIEW.md", "file:app/queue_worker.py"),
  doc("document:REVIEW.md", "file:app/structurer.py"),
  doc("document:REVIEW.md", "file:app/routes_jobs.py"),
  doc("document:REVIEW.md", "file:app/keys_cli.py"),
  doc("document:REVIEW.md", "file:scripts/smoke_e2e.py"),
  rel("document:REVIEW.md", "document:TASKS.md"),
  rel("document:REVIEW.md", "document:CONTRACT.md"),
  rel("document:REVIEW.md", "document:PLAN.md"),
  // TASKS.md
  doc("document:TASKS.md", "file:app/config.py"),
  doc("document:TASKS.md", "file:app/numbers.py"),
  doc("document:TASKS.md", "file:app/contract.py"),
  doc("document:TASKS.md", "file:app/validator.py"),
  doc("document:TASKS.md", "file:app/db.py"),
  doc("document:TASKS.md", "file:app/auth.py"),
  doc("document:TASKS.md", "file:app/ocr_client.py"),
  doc("document:TASKS.md", "file:app/structurer.py"),
  doc("document:TASKS.md", "file:app/pipeline.py"),
  doc("document:TASKS.md", "file:app/queue_worker.py"),
  doc("document:TASKS.md", "file:app/keys_cli.py"),
  doc("document:TASKS.md", "file:app/routes_worker.py"),
  doc("document:TASKS.md", "file:app/main.py"),
  doc("document:TASKS.md", "file:app/routes_jobs.py"),
  doc("document:TASKS.md", "file:app/exports.py"),
  doc("document:TASKS.md", "file:app/status.py"),
  doc("document:TASKS.md", "file:run.py"),
  doc("document:TASKS.md", "file:scripts/gen_contract_doc.py"),
  doc("document:TASKS.md", "file:scripts/fake_models.py"),
  doc("document:TASKS.md", "file:scripts/serve_demo.py"),
  doc("document:TASKS.md", "file:scripts/smoke_e2e.py"),
  doc("document:TASKS.md", "file:scripts/acceptance.py"),
  doc("document:TASKS.md", "file:scripts/tailscale_serve.ps1"),
  rel("document:TASKS.md", "document:spike/CANLI_TEST_RAPORU.md"),
  rel("document:TASKS.md", "document:README.md"),
  rel("document:TASKS.md", "document:OPERATIONS.md"),
  // config manifests — their real targets (static/*.js ESM consumers, tests/ pytest
  // discovery) are outside this project's analyzed file set, so the honest remaining
  // relationship is a topical link to the docs that state the commands they enable.
  rel("config:package.json", "document:PLAN.md"),
  rel("config:package.json", "document:TASKS.md"),
  rel("config:pyproject.toml", "document:TASKS.md"),
  rel("config:pyproject.toml", "document:HIZLI-BASLANGIC.md"),
];

// ---- self-checks ----
const ids = nodes.map((n) => n.id);
const dup = ids.filter((x, i) => ids.indexOf(x) !== i);
const selfEdges = edges.filter((e) => e.source === e.target);
const batchFiles = JSON.parse(
  readFileSync("C:/Users/PC/Documents/GitHub/ocr-app/.ua/tmp/batch-input-5.json", "utf8"),
).files.map((f) => f.path);
const missingNodePerFile = batchFiles.filter(
  (p) => !ids.some((id) => id.endsWith(":" + p)),
);
const universe = new Set();
const bs = JSON.parse(
  readFileSync("C:/Users/PC/Documents/GitHub/ocr-app/.ua/intermediate/batches.json", "utf8"),
);
for (const b of bs.batches || bs) for (const f of b.files) universe.add(f.path);

const localIds = new Set(ids);
const badTargets = [];
for (const e of edges) {
  for (const ref of [e.source, e.target]) {
    if (localIds.has(ref)) continue;
    const path = ref.replace(/^[a-z]+:/, "");
    if (!universe.has(path)) badTargets.push(`${e.type}: ${ref} (path not in project universe)`);
  }
}
const sumImports = Object.values(
  JSON.parse(readFileSync("C:/Users/PC/Documents/GitHub/ocr-app/.ua/tmp/batch-input-5.json", "utf8")).batchImportData,
).reduce((a, v) => a + v.length, 0);
const importEdges = edges.filter((e) => e.type === "imports").length;

console.log("nodes:", nodes.length, "edges:", edges.length);
console.log("dup node ids:", dup.length ? dup : "none");
console.log("self edges:", selfEdges.length);
console.log("files without a node:", missingNodePerFile.length ? missingNodePerFile : "none");
console.log("batchImportData sum:", sumImports, "/ imports edges:", importEdges);
console.log("targets outside universe:", badTargets.length ? badTargets : "none");

if (dup.length || selfEdges.length || missingNodePerFile.length || badTargets.length || sumImports !== importEdges) {
  console.error("VALIDATION FAILED");
  process.exit(1);
}

writeFileSync(
  "C:/Users/PC/Documents/GitHub/ocr-app/.ua/intermediate/batch-5.json",
  JSON.stringify({ nodes, edges }, null, 2) + "\n",
  "utf8",
);
console.log("WROTE batch-5.json");
