[
  {
    "order": 1,
    "title": "Projenin Amacı ve Kapsamı",
    "description": "Turla README.md üzerinden başlıyoruz: tek makinede çalışan, buluta hiçbir şey göndermeyen bir fiş OCR servisi bu. Telefondaki fotoğraf FastAPI'ye (:8090) düşüyor, kuyruk worker'ı üç aşama çalıştırıyor ve saniyeler içinde sözleşme v1 JSON'u dönüyor; fiş görüntüleri ve SQLite verisi KVKK gereği data/ altında kalıyor. PROJECT_BRIEF.md ise kapsamı sabitleyen taraf: üç kullanıcı tipi (saha çalışanı, admin/entegratör, dış entegratör geliştirici), v1 kapsamı ve kapsam dışındakiler, stack ve VRAM kısıtları. Brief'in en kritik cümlesi ürünün kendisinin sürümlenmiş bir JSON sözleşme olduğu ve aritmetiğin deterministik Python'da kaldığı — turla birlikte sürekli karşımıza çıkacak olan karar bu.",
    "nodeIds": ["document:README.md", "document:PROJECT_BRIEF.md"]
  },
  {
    "order": 2,
    "title": "Mimari Haritası ve Görev Defteri",
    "description": "PLAN.md üç aşamalı hattın şemasını, dosya yapısını ve on tasarım kararını (CPU'da OCR, contract'ın koddan üretilmesi, idempotency, SHA-256 anahtarlar, EXIF temizliği) tek yerde topluyor; modüller arası on veri şeklini ve bir alan değiştiğinde birlikte dokunulması gereken yerleri 'wholes' başlığıyla listeliyor. Yani bir sonraki adımda açacağımız her dosyanın haritası burada. TASKS.md ise yapımın kendisi: her görev tek satırda kök neden, beklenen davranış ve `accept:` doğrulama komutu; T01-T69 tamamlanmış ve REVIEW ile canlı test bulguları aynı deftere eklenmiş durumda. Bu iki belgeyi bir okumak, koddaki garip görünen tercihlerin çoğunun bilinçli karar olduğunu gösteriyor.",
    "nodeIds": ["document:PLAN.md", "document:TASKS.md"]
  },
  {
    "order": 3,
    "title": "Yapılandırmanın Tek Yüzeyi",
    "description": "config.py grafın en çok bağımlılık çeken dosyası (fan-in 26): her ortam değişkenini tipli bir değere (str/int/float/Path) çevirip güvenli bir varsayılanla döndürüyor ve projedeki başka hiçbir modül os.environ okumuyor. Portlar, model yolları, ADMIN_TOKEN — hepsi bu tek kapıdan geçiyor, bu yüzden `.env` dosyasını değiştirmek davranışın tamamını değiştirmek anlamına geliyor. app/__init__.py ise bilinçli olarak boş bırakılmış paket işaretçisi; hiçbir sembol taşımadığı için `import app.config` döngüsel içe aktarma riski doğurmuyor.",
    "nodeIds": ["file:app/config.py", "file:app/__init__.py"],
    "languageLesson": "Python'da ortam değişkenleri doğası gereği hep string döner; config.py bunları modül seviyesinde tipli alanlara dönüştürerek hatalı port veya yol ayrıştırmayı import anına taşır. Bu 'tek yapılandırma yüzeyi' deseni, os.environ'ın saçıldığı bir kod tabanında değer bulmayı imkânsız hale getiren dağılmayı da engeller."
  },
  {
    "order": 4,
    "title": "Sözleşme v1: Ürünün Kendisi",
    "description": "contract.py sözleşme v1'in pydantic modellerini (Result, Validation, JobEnvelope ve alt blokları) tanımlıyor; null gelen alanı varsayılanla değiştiriyor ve fişin bastığı para biçimlerini app.numbers üzerinden tek noktadan float'a çeviriyor. Hiçbir alan null dönmediği için görünüm, dışa aktarma ve toplamlar null koruması yazmak zorunda kalmıyor. Buradaki asıl tasarım sırrı üretim yönü: gen_contract_doc.py bu modellerden contract_v1.schema.json ve CONTRACT.md dosyalarını bayt-kararlı yeniden yazıyor, dolayısıyla commit edilmiş şema ve entegratör belgesinin kendisi aynı zamanda üretim kontrolü. CONTRACT.md'yi de yanına alırsanız endpoint tablosunu, job envelope alan şemalarını ve ok | mismatch | unreadable karar kurallarını insan okunur haliyle görürsünüz.",
    "nodeIds": ["file:app/contract.py", "schema:contract/contract_v1.schema.json", "document:CONTRACT.md", "file:scripts/gen_contract_doc.py"],
    "languageLesson": "Pydantic modellerinden JSON Şema (draft 2020-12) üretmek, kod ile dokümantasyonu tek doğruluk kaynağına bağlar. Çıktının bayt-kararlı (byte-deterministic) olması için alan sırası ve serializasyon ayarları sabit tutulur; böylece `git diff` sözleşmede gerçekleşen tek gerçek değişikliği gösterir."
  },
  {
    "order": 5,
    "title": "Türkçe Fiş Sayılarını Ayrıştırmak",
    "description": "Türkçe fişler İngilizce/Amerikan sayı biçiminden saptığı için ('1.046,40', '198,82 TL', '%20', hatta bozuk OCR ile '8,%') tek bir ayrıştırıcıya ihtiyaç var; numbers.py tam olarak bunu yapıyor ve hem yapılandırıcının hem validator'ın aynı fonksiyonu kullanması iki aşamanın aynı sayıyı görmesini garant ediyor. Kritik ayrıntı: okunamayan değer sessizce 0.0 değil None dönüyor. Böylece eksik veya bozuk okunan bir basamak sıfıra yuvarlanıp toplamı yanlış kurmak yerine validator tarafından adlandırılmış bir uyuşmazlık olarak dışa vuruluyor — yüzeyde hatayı gizleme, göster ilkesinin kod hali.",
    "nodeIds": ["file:app/numbers.py"],
    "languageLesson": "Ayrıştırılamayan değer için 0.0 yerine None dönmek bir sentinel tercihidir: 0.0 geçerli bir iş değeri olabileceğinden 'bilinmiyor' durumunu ondan ayırmak gerekir. Çağrı tarafı None'ı ya tipli bir hata olarak taşır ya da doğrulama kararına dönüştürür."
  },
  {
    "order": 6,
    "title": "SQLite Kalıcılığı ve Dışa Aktarım",
    "description": "db.py verinin tek yuvası: WAL modunda SQLite üzerinde api_keys, jobs, corrections ve events tablolarını kuruyor, PRAGMA user_version ile idempotent migration uyguluyor ve kuyruk satırları için tek yazma kapısı (create_job / set_status / update_job) sunuyor. Tüm giriş noktaları connect() ile aynı veritabanını açtığı için 'kuyruk tablosu' ile 'iş kaydı' aynı şey — sonraki adımdaki worker bunu tüketiyor. exports.py ise iş kayıtlarını sözleşme 8'in tek düz satırından JSON, CSV ve XLSX olarak üretiyor; tek bir düz satır tanımı olduğu için admin panelinde yapılan bir alan düzeltmesi üç formata aynı anda yansıyor.",
    "nodeIds": ["file:app/db.py", "file:app/exports.py"],
    "languageLesson": "SQLite'ta WAL (write-ahead logging) okuyucuları yazarın kilitlemeden çalıştırmasını sağlar — tek süreçli bir API ile ona gömülü kuyruk worker'ının aynı dosyayı paylaşması bu yüzden mümkün. PRAGMA user_version şema sürümunu veritabanının içine sayı olarak yazar; migration'lar 'bu sürümde miyim?' kontrolüyle koşullu çalışır ve tekrar tekrar çalıştırılabilir (idempotent) kalır."
  },
  {
    "order": 7,
    "title": "HTTP Kabuğu: Uygulama Fabrikası",
    "description": "main.py grafın okuma sırasının başladığı yer: bağımlılık yolculuğu onu merkeze alınca bir adım içinde config, contract, db, auth ve üç router'a, iki adım içinde validator ve pipeline'a ulaşıyor. Uygulama fabrikası router'ları bağlıyor; API anahtarı ve admin oturumu middleware'lerini, yük sınırını, güvenlik başlıklarını, istek günlüğünü ve tek JSON hata zarfını sabit sırda kuruyor. Middleware sırasının sabit olması kritik — kimlik doğrulama, hız sınırından ve loglamadan önce gelmek zorunda. Buradan itibaren göreceğiniz her dosya ya bu kabuğun bir parçası ya da onun import ettiği bir alt katman.",
    "nodeIds": ["file:app/main.py"],
    "languageLesson": "FastAPI'de uygulama fabrikası (bir fonksiyonun `FastAPI()` örneği döndürmesi) aynı iskeleti test, demo ve üretim için farklı yapılandırmalarla kurmayı sağlar; `app.middleware` ve `include_router` çağrı sırası middleware zincirinin sırasını belirlediği için bu kurulum tek yerde ve sabit sırda tutulur."
  },
  {
    "order": 8,
    "title": "Üç Aşamayı Sıraya Koyan Orkestrasyon",
    "description": "pipeline.py üç aşamanın sahibidir: OCR metnini yapılandırıcıya, onun sonucunu deterministik validator'a besliyor ve aşama sırasını yalnızca bu modül biliyor. Anlayış farkı burada: modelin kendi toplamları yalnızca karşılaştırmanın 'actual' tarafında duruyor, beklenen değerler hiç LLM'den gelmiyor. Okunamayan fiş boş sonuçla kısa devre yapıyor, yani iş 'failed' olmak yerine okunamadı olarak kaydıyla kapanıyor — kuyrukta delik kalmıyor. Bir sonraki iki adımda bu sıranın ayaklarını tek tek açacağız.",
    "nodeIds": ["file:app/pipeline.py"]
  },
  {
    "order": 9,
    "title": "Aşama 1 ve 2: Model İstemcileri",
    "description": "ocr_client.py aşama 1: fiş görüntüsünü base64 data URL yapıp llama-server'ın OpenAI uyumlu /v1/chat/completions ucundan PaddleOCR-VL'ye (:8081) gönderiyor ve ham metin ile geçen süreyi döner; bu ayağın tek dış sınırı model sunucusu. structurer.py aşama 2: OCR metniyle fiş görselini alıp sözleşme v1 JSON nesnesine çeviriyor — normal modda Strata :8080, kalite modunda Unsloth Studio :8888 — ve hiçbir hesap yapmıyor, aritmetiğin sahibi validator. Akıl yürüten modellerde max_tokens bütçesinin tamamının düşünceye harcanıp content=null dönmesi gerçek bir hataydı (T68); gövdeye eklenen chat_template_kwargs ile thinking kapatılıp tavan 2500'e çıkarıldı, ayrıntısı 14. adımdaki canlı test raporunda.",
    "nodeIds": ["file:app/ocr_client.py", "file:app/structurer.py"],
    "languageLesson": "OpenAI uyumlu /v1/chat/completions arayüzü istemci tarafını sözleşmeye bağlar; görüntü `image_url` içinde base64 data URL olarak taşınır. `chat_template_kwargs` gibi sağlayıcıya özel alanlar şablon seviyesinde davranış değiştirir (burada thinking kapatma), yani aynı uç nokta farklı sunucu davranışları için tek istemci koduyla çalışmaya devam eder."
  },
  {
    "order": 10,
    "title": "Aşama 3: Deterministik Doğrulama",
    "description": "validator.py projenin felsefi merkezi ve 'LLM hiçbir sayıya sahip olmaz' kuralının uygulandığı yer: items[] üzerinden satır toplamlarını, ara toplamı, tek ve çok oranlı KDV'yi ve genel toplamı baştan hesaplıyor, sonra fişin bastığı değerlerle 0,01 toleransta karşılaştırıyor. 5. adımdaki numbers.py sayesinde beklenen ve basılan değerler aynı ayrıştırmadan geliyor; yanlış okunan bir basamak sessiz yanlış toplam değil, adlandırılmış bir mismatch alanı oluyor. Böylece validation.verdict üç durumdan birine net biçimde oturuyor: ok, mismatch, unreadable — ve uyuşmazlık ile okuma hatası birbirinden ayrılabiliyor.",
    "nodeIds": ["file:app/validator.py"],
    "languageLesson": "Para birimi karşılaştırmasında sabit mutlak tolerans (0,01) kullanmak, float toplama hatalarının birikmesini engellerken anlamlı olmayan kuru da tolere eder. Aritmetiği LLM'e devretmek yerine yeniden hesaplamak (recompute-and-compare), dil modelinin tutarlı ama yanlış sayı üretme modunu yapısal olarak imkânsızlaştırır."
  },
  {
    "order": 11,
    "title": "Kuyruk, Başlatıcı ve Canlı Durum",
    "description": "queue_worker.py jobs tablosunu gerçek bir kuyruk gibi tüketen tek daemon thread: queued → running → done/failed geçişini sürdürüyor, süreç çöküşünde recover() ile yarım kalan işleri geri kuyruğa alıyor ve bayatları başarısız işaretliyor. run.py tek komutluk başlatıcı: llama-server ve uvicorn süreçlerini doğuruyor, worker'ı kendi bünyesinde çalıştırıyor, her servisi sağlık kontrolünden geçirip tek tek yeşil ✓ ile raporluyor, --stop ile izlenen PID'leri ağacıyla birlikte durduruyor. status.py ise makinenin anlık görüntüsü: üç model sunucusunun sağlık yoklaması, nvidia-smi VRAM okuması ve SQLite kuyruk derinliği — ki durum sayfası tüm sunucular kapalıyken de yanıt vermek zorunda, çünkü operatör tam da o anda ona bakıyor.",
    "nodeIds": ["file:app/queue_worker.py", "file:run.py", "file:app/status.py"],
    "languageLesson": "SQLite'ı kuyruk olarak kullanmak durum makinesini (queued/running/done/failed) kalıcı hale getirir: süreç ölünce kuyruk kaybolmaz, recover() yalnızca 'running' görünen ama sahibi olmayan satırları geri alır. Monitörleme ucunun bağımlılıklar ölüyken de 200 dönmesi gerekir;health-check'i uygulama durumundan ayrı tutmak bu yüzden yaygın bir kuraldır."
  },
  {
    "order": 12,
    "title": "Üç Kapı ve Güvenlik Katmanı",
    "description": "Sistemin üç ayrı yüzü var ve her biri kendi router'ında. routes_jobs.py /v1/jobs'u taşıyor: POST bir kabul işlemi, hesap değil — görsel diske iniyor, satır queued kalıyor, 202 dönüyor ve client_ref idempotency'si aynı fişi iki kez yüklemeyi engelliyor. routes_worker.py /api/me/* ile çalışan PWA'sının anahtar-kapsamlı görünümlerini veriyor: biri başkasının işini istediğinde 403 değil 404 alıyor (varlığını sızdırmıyor) ve fiş görüntüleri KVKK gereği yalnızca bu kapılardan çıkıyor. routes_admin.py /admin/api altında oturum, alan bazlı düzeltme, kalite modunda yeniden koşu, dışa aktarma ve anahtar yönetimini topluyor. auth.py ise hepsinin altında: ocrk_ + 40 hex anahtarlar, veritabanında yalnızca SHA-256 hash, sabit zamanlı hmac.compare_digest karşılaştırması, anahtar başına token bucket ve asla sunucudan çıkmayan ADMIN_TOKEN.",
    "nodeIds": ["file:app/routes_jobs.py", "file:app/routes_worker.py", "file:app/routes_admin.py", "file:app/auth.py"],
    "languageLesson": "Kimlik doğrulaması ve hız sınırı middleware seviyesinde kurulur; API anahtarının hash'ini saklamak sızıntı halinde düz metin anahtarın ele geçmesini engeller, `hmac.compare_digest` ise zamanlama farkıyla anahtar tahminini (timing attack) kapatır. 403 yerine 404 dönmek (existence leak) kaynak varlığını gizlemenin standart yoludur."
  },
  {
    "order": 13,
    "title": "Operasyon: Yedek, Anahtar, HTTPS",
    "description": "Bu projede deployment tek makinenin kendisi, bu yüzden operasyon belgesi kod kadar önemli. OPERATIONS.md data/ yedeğini, çalışan anahtarı ve ADMIN_TOKEN rotasyonunu, log konumlarını, model ve binary yollarını, VRAM bütçesini ve tek komutluk günlük kabul kontrolünü anlatıyor; KVKK gereği data/ altının gitignore'da kalması gerektiğini özellikle vurguluyor. keys_cli.py anahtarları terminalden yönetiyor (add | list | revoke) ve düz metin anahtarı yalnızca add çıktısında bir kez basıyor — list kimlikleri gösterir, anahtarların kendisini asla. tailscale_serve.ps1 uygulamayı yalnızca tailnet üzerinde HTTPS'e açıyor: TLS'i tailscale kendi sonlandırırken uvicorn 127.0.0.1:8090'da düz HTTP kalıyor ve funnel hiç çağrılmayarak tek giriş tailnet'te tutuluyor. HIZLI-BASLANGIC.md de Türkçe hızlı girişle bu adımları beş dakikaya indiriyor.",
    "nodeIds": ["document:OPERATIONS.md", "file:app/keys_cli.py", "file:scripts/tailscale_serve.ps1", "document:HIZLI-BASLANGIC.md"],
    "languageLesson": "TLS'i uygulama sunucusunda değil tailscale gibi bir ağ katmanında sonlandırmak sertifika yenileme ve anahtar yönetimini uygulamadan ayırır. Uygulamanın 127.0.0.1'e bağlı kalıp dışa sadece proxy üzerinden açılması (loopback-only bind), yanlışlıkla bütün ağa açık port bırakma riskini ortadan kaldırır."
  },
  {
    "order": 14,
    "title": "Modeller Nasıl Seçildi: Spike'lar",
    "description": "Neden PaddleOCR-VL ve neden Qwen kalite modu yedeği — cevabı spike katmanında. REPORT.md M0 kıyaslamasında PaddleOCR-VL-1.6 ile Qwen3-VL-8B'yi Türkçe fiş ve el yazısı doğruluğu ile CPU hızında karşılaştırıyor ve ikisinin de Apache-2.0 olması ticari kullanım için kritik. bench.py sentetik fixture'ları toplu gönderip Türkçe sayı biçimini normalize ederek beklenen token isabetini ölçüyor ve sonucu bench_paddle.json gibi karşılaştırılabilir dosyalara yazıyor; benzer işi yapan make_fixtures.py ground-truth'u garantili ürettiği için ölçüm gerçek veriye dayanıyor. live_test.py ise anahtar üretip gerçek fişleri POST /v1/jobs ile kuyruğa atarak uçtan uca canlı hatı spike/live_real.json'e döküyor ve CANLI_TEST_RAPORU.md 679 birim testinin kaçırdığı thinking-token (content=null) hatasının kök nedenini, kanıtını ve onaylı düzeltmesini T68 olarak deftere bağlıyor — birim testinin canlı model davranışını yakalayamadığı yer tam burası.",
    "nodeIds": ["document:spike/REPORT.md", "file:spike/bench.py", "config:spike/bench_paddle.json", "file:spike/live_test.py", "document:spike/CANLI_TEST_RAPORU.md"],
    "languageLesson": "Model seçimi spike'ı ölçülebilir olmalı: aynı fixture seti, aynı istem ve normalize edilmiş bir isabet metriği olmadan iki modelin ham çıktısı karşılaştırılamaz. Canlı model hatalarını yakalamak için mock yerine gerçek sunucuya karşı çalışan ince sonda (probe) gerekir; ham yanıtların commit'i regresyonu sonra yeniden okunabilir kılar."
  },
  {
    "order": 15,
    "title": "Uçtan Uca Kanıt Kültürü",
    "description": "Son adım, turdaki her parçanın birlikte gerçekten çalıştığını kim kanıtlıyor sorusuna ayrılmış. fake_models.py OCR ve yapılandırma rolleri için commit edilmiş fixture ground-truth'unu gerçek HTTP üzerinden sunan OpenAI uyumlu sahte sunucular yazıyor; uygulama kodu bu modülü asla import etmediği için test gerçek soketi, gerçek kuyruğu ve gerçek pipeline'ı kullanıyor. smoke_e2e.py gerçek uygulamayı geçici bir portta ayağa kaldırıp fixtures/fis_market_clean.png'yi yüklüyor, işi done'a kadar kovalıyor ve gördüğü her zarfı contract_v1 şemasına karşı doğruluyor — HTTP altında hiçbir şey mock'lanmadığı için bozuk bir route, kuyruk, aşama veya sözleşme sıfırdan farklı bir exit kodu olarak çıkar. acceptance.py brief bölüm 9'un kabul kontrollerini tek komutta tabloya döküyor ve bir FAIL varsa 1 ile çıkıyor; serve_demo.py ise her fixture'ı farklı kuyruk durumu ve verdict ile tohumlayarak kamera ve model sunucusu olmadan her ekranın veri olması sağlıyor. REVIEW.md bu kültürün gerekçesini taşıyor: 665 pytest ve 192 node testi yeşilken üç sınır hatası (unreadable'ın failed'a dönmesi, gerçek Structurer'ın kapıdan geçmemesi, resim yazılmadan kuyruk satırının commit edilmesi) ancak uçtan uca bakınca görüldü.",
    "nodeIds": ["file:scripts/fake_models.py", "file:scripts/smoke_e2e.py", "file:scripts/acceptance.py", "file:scripts/serve_demo.py", "document:REVIEW.md"],
    "languageLesson": "'HTTP altında mock yok' ilkesi entegrasyon hatalarını unit testin kör noktasından çıkarır; başarının sözleşme şemasına karşı doğrulanması ve arızanın ayırt edici exit koduna bağlanması CI'ın insan yorumuna bakmadan kapılanmasını sağlar. Sahte sunucuların gerçek HTTP konuşması, istemci kodundaki sözleşme ihlallerini de test eder."
  }
]
