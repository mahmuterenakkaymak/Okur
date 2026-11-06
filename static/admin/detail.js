// Fiş detayı: one receipt at a desk — the photograph beside the numbers read
// off it, the four amounts the validator recomputed against what the receipt
// printed, the fragments that never survived the photograph, and the raw
// envelope underneath for when the two disagree about something.
//
// The fields are editable because the correction flow starts here: an edited
// field is marked, Kaydet sends the marked ones as one PATCH, and the panel
// redraws from the answer. What stays on screen is therefore the server's own
// envelope, with the verdict recomputed over the corrected numbers.
import { iskontoPara, para, sayi } from "../app/result_totals.js";
import { DURUM, VERDICT } from "./list.js";
import { bildir } from "./toasts.js";

const API = "/admin/api";

// The contract's totals block, in the order a Turkish receipt prints it.
const TOPLAMLAR = [
  { alan: "ara_toplam", etiket: "Ara toplam", adim: "0.01", basamak: 2 },
  { alan: "iskonto", etiket: "İskonto", adim: "0.01", basamak: 2 },
  { alan: "kdv", etiket: "KDV", adim: "0.01", basamak: 2 },
  { alan: "kdv_orani", etiket: "KDV oranı", adim: "0.01", basamak: 2 },
  { alan: "toplam", etiket: "Genel toplam", adim: "0.01", basamak: 2 },
];
// The four amounts the validator recomputes (contract shape 3); kdv_orani is a
// chain input it trusts, so it is edited but never compared.
const KARSILASTIRMA = [
  { alan: "ara_toplam", etiket: "Ara toplam" },
  { alan: "iskonto", etiket: "İskonto" },
  { alan: "kdv", etiket: "KDV" },
  { alan: "toplam", etiket: "Genel toplam" },
];
const URUN_KOLONLARI = [
  { alan: "ad", etiket: "Ad", metin: true },
  { alan: "miktar", etiket: "Miktar", adim: "0.001" },
  { alan: "birim_fiyat", etiket: "Birim fiyat", adim: "0.01", basamak: 2 },
  { alan: "toplam", etiket: "Tutar", adim: "0.01", basamak: 2 },
];
const URUN_ALAN = { miktar: "miktar", birim_fiyat: "birim fiyat", toplam: "tutar" };
const KURUS = 0.005; // below it the difference column has nothing to say
// The pipeline's three stages, in the order they ran (meta.stage_ms).
const ASAMALAR = [
  { alan: "ocr", etiket: "Okuma" },
  { alan: "structure", etiket: "Yapılandırma" },
  { alan: "validate", etiket: "Doğrulama" },
];
const ASAMA_ETIKET = "Aşama süreleri";
const YOK = "—";
const SN = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
// A stage that took at least a tenth of a second is said in seconds; below it
// a millisecond count is the unit a person reads.
// ASSUMPTION: "≥1000 ms reads in seconds" only holds together with PLAN's own
// example ("Okuma 0,9 sn" for a 900 ms read) when the switch sits below 1000,
// so it is a tenth of a second; every value ≥1000 ms still reads in seconds.
const SN_ESIGI = 100;

/** Validation block -> the discrepancy panel (contract shape 3).
 *
 * A block straight from the queue may be missing either half, and a reviewer
 * reading "0,00" as a real amount is worse than an empty cell, so every absent
 * number lands on zero here and nowhere else.
 */
export function uyusmazlikModeli(validation) {
  const beklenen = validation?.expected || {};
  const fiilde = validation?.actual || {};
  const alanlar = Array.isArray(validation?.fields) ? validation.fields : [];
  const satirlar = KARSILASTIRMA.map(({ alan, etiket }) => {
    // ASSUMPTION: the validator reads a printed "52,32-" as a 52,32 discount,
    // so this row compares magnitudes too — never a phantom 104,64 fark.
    const oku = alan === "iskonto" ? (deger) => Math.abs(sayi(deger)) : sayi;
    const b = oku(beklenen[alan]);
    const f = oku(fiilde[alan]);
    return {
      alan,
      etiket,
      beklenen: b,
      fiilde: f,
      fark: Math.round((f - b) * 100) / 100,
      uyusmaz: alanlar.includes(`totals.${alan}`),
    };
  });
  const urunler = [];
  for (const alan of alanlar) {
    const satir = /^items\[(\d+)\]\.(.+)$/.exec(alan);
    if (satir) urunler.push({ sira: Number(satir[1]) + 1, alan: satir[2] });
  }
  return { verdict: validation?.verdict || "unreadable", satirlar, urunler };
}

function metin(deger) {
  return typeof deger === "string" ? deger.trim() : "";
}

/** A stage's own milliseconds; the contract's 0 for absent or junk is no measurement. */
function olcu(deger) {
  const ms = Number(deger);
  return Number.isFinite(ms) && ms > 0 ? ms : null;
}

/** One duration the way an operator says it: "30,6 sn", "1 ms". */
function sure(ms) {
  return ms >= SN_ESIGI ? `${SN.format(ms / 1000)} sn` : `${Math.round(ms)} ms`;
}

/** meta.stage_ms -> the summary's timing line.
 *
 * A 0 here is the contract's "this stage never ran", not an instant stage, so
 * an unmeasured stage is an em dash and a job that never ran at all is a single
 * dash after the label. Display only: meta keeps the raw integers the JSON
 * panel prints.
 */
export function asamaSureleri(meta) {
  const asama = meta?.stage_ms;
  const olculen = ASAMALAR.map(({ alan }) => olcu(asama?.[alan]));
  if (!olculen.some((ms) => ms !== null)) return `${ASAMA_ETIKET} ${YOK}`;
  const sureler = olculen.map(
    (ms, i) => `${ASAMALAR[i].etiket} ${ms === null ? YOK : sure(ms)}`,
  );
  return `${ASAMA_ETIKET} ${YOK} ${sureler.join(" · ")}`;
}

const FARK_TOPLAMLAR = [
  { alan: "ara_toplam", etiket: "Ara toplam" },
  { alan: "iskonto", etiket: "İskonto" },
  { alan: "kdv", etiket: "KDV" },
  { alan: "toplam", etiket: "Genel toplam" },
];

/** Before-after rows for the rerun panel: only the values that actually moved.
 *
 * A rerun of a failed receipt has no "before" numbers at all, so an absent
 * amount reads as an em dash here rather than the 0,00 a reviewer would try
 * to compare against.
 */
export function kaliteFarki(eskiEnv, yeniEnv) {
  const satirlar = [];
  const ekle = (etiket, once, sonra) => {
    if (once !== sonra) satirlar.push({ etiket, once, sonra });
  };
  const tutar = (env, alan) => {
    const deger = env?.result?.totals?.[alan];
    return Number.isFinite(deger) ? para(deger) : "—";
  };
  const dogrulama = (env) =>
    VERDICT[env?.validation?.verdict]?.etiket || DURUM[env?.status] || "—";
  ekle("Doğrulama", dogrulama(eskiEnv), dogrulama(yeniEnv));
  ekle("Model", eskiEnv?.meta?.model || "—", yeniEnv?.meta?.model || "—");
  for (const { alan, etiket } of FARK_TOPLAMLAR) {
    ekle(etiket, tutar(eskiEnv, alan), tutar(yeniEnv, alan));
  }
  const adet = (env) =>
    Array.isArray(env?.result?.items) ? String(env.result.items.length) : "—";
  ekle("Ürün sayısı", adet(eskiEnv), adet(yeniEnv));
  return satirlar;
}

/** Edited fields -> the PATCH body, keyed by the contract's dotted paths.
 *
 * A number input holds "0.250", and the server reads a dot followed by three
 * digits as a thousands group — 250, a kg correction 1000x off. So a
 * number-shaped value leaves as a JSON number and is never re-parsed from text
 * the reviewer never typed; only the text fields travel as strings.
 */
export function duzeltmeAlanlari(girdiler) {
  const alanlar = {};
  for (const girdiAlani of girdiler) {
    const deger = girdiAlani.value.trim();
    alanlar[girdiAlani.dataset.yol] =
      girdiAlani.dataset.bicim === "sayi" ? Number(deger) : deger;
  }
  return alanlar;
}

async function hataMesaji(yanit) {
  try {
    const govde = await yanit.json();
    if (govde?.error?.message) return govde.error.message;
  } catch {
    // a body that is not JSON has nothing better to say than its status
  }
  return `HTTP ${yanit.status}`;
}

export function createFisDetay({ onDuzeltme = () => {} } = {}) {
  const dialog = document.getElementById("fis-detay");
  const baslik = document.getElementById("detay-baslik");
  const ozet = document.getElementById("detay-ozet");
  const asama = document.getElementById("detay-asama");
  const durumEtiket = document.getElementById("detay-dogrulama");
  const hata = document.getElementById("detay-hata");
  const bekleme = document.getElementById("detay-bekleniyor");
  const icerik = document.getElementById("detay-icerik");
  const gorsel = document.getElementById("detay-gorsel");
  const resim = document.getElementById("detay-resim");
  const gorselNot = document.getElementById("detay-gorsel-not");
  const panel = document.getElementById("detay-panel");
  const urunGovde = document.getElementById("detay-urun-govde");
  const urunBos = document.getElementById("detay-urun-bos");
  const toplamlar = document.getElementById("detay-toplamlar");
  const karsilikKutusu = document.getElementById("detay-karsilastirma-kutusu");
  const karsilik = document.getElementById("detay-karsilastirma");
  const okunamayanKutusu = document.getElementById("detay-okunamayan");
  const okunamayanListe = document.getElementById("detay-okunamayan-liste");
  const jsonDugme = document.getElementById("detay-json-dugme");
  const jsonAlani = document.getElementById("detay-json");
  const kaydetDugme = document.getElementById("detay-kaydet");
  const kaydetDurum = document.getElementById("detay-kaydet-durum");
  const yenidenDugme = document.getElementById("detay-yeniden");
  const onayKutusu = document.getElementById("detay-yeniden-onay");
  const onaylaDugme = document.getElementById("detay-yeniden-onayla");
  const vazgecDugme = document.getElementById("detay-yeniden-vazgec");
  const farkKutusu = document.getElementById("detay-fark");
  const farkIcerik = document.getElementById("detay-fark-icerik");

  let sira = 0; // a late answer from a superseded open must not draw
  let gorselSira = 0;
  let sonId = "";
  let envelope = null;
  let kaydediliyor = false;
  let yenidenIsleniyor = false;
  let islenebilir = false; // only a finished read (done/failed) can be rerun

  function hucre(metin, saga) {
    const td = document.createElement("td");
    td.className = saga ? "saga" : "";
    td.textContent = metin;
    return td;
  }

  function girdi(kolon, deger, etiket, yol) {
    const alan = document.createElement("input");
    alan.type = kolon.metin ? "text" : "number";
    if (kolon.adim) alan.step = kolon.adim;
    // An amount field that opens as "1046.4" reads like a rounding mistake; a
    // quantity keeps however many decimals the receipt printed.
    const gosterim = kolon.metin
      ? metin(deger)
      : kolon.basamak === undefined
        ? String(sayi(deger))
        : sayi(deger).toFixed(kolon.basamak);
    alan.value = gosterim;
    // What a save sends is the field's own contract path, and what makes it
    // worth sending is a value that no longer matches the one drawn here.
    alan.dataset.baslangic = gosterim;
    alan.dataset.yol = yol;
    alan.dataset.bicim = kolon.metin ? "metin" : "sayi";
    alan.dataset.alan = kolon.alan;
    alan.setAttribute("aria-label", etiket);
    return alan;
  }

  function gorseliGoster(url) {
    const tur = ++gorselSira;
    resim.removeAttribute("src");
    gorsel.classList.remove("hazir");
    gorselNot.hidden = false;
    if (!url) {
      gorselNot.textContent = "Bu fiş için görsel saklanmamış.";
      return;
    }
    gorselNot.textContent = "Görsel yükleniyor…";
    resim.addEventListener(
      "load",
      () => {
        if (tur !== gorselSira) return;
        gorsel.classList.add("hazir");
        gorselNot.hidden = true;
      },
      { once: true },
    );
    resim.addEventListener(
      "error",
      () => {
        if (tur !== gorselSira) return;
        gorselNot.textContent = "Görsel yüklenemedi — sunucudaki dosya okunamıyor.";
      },
      { once: true },
    );
    resim.src = url;
  }

  function urunleriCiz(items) {
    urunGovde.textContent = "";
    const satirlar = Array.isArray(items) ? items : [];
    urunBos.hidden = satirlar.length > 0;
    satirlar.forEach((item, index) => {
      const tr = document.createElement("tr");
      for (const kolon of URUN_KOLONLARI) {
        const td = document.createElement("td");
        if (!kolon.metin) td.className = "saga";
        td.appendChild(
          girdi(
            kolon,
            item?.[kolon.alan],
            `${kolon.etiket} — ürün ${index + 1}`,
            `items[${index}].${kolon.alan}`,
          ),
        );
        tr.appendChild(td);
      }
      urunGovde.appendChild(tr);
    });
  }

  function toplamlariCiz(totals) {
    toplamlar.textContent = "";
    for (const kolon of TOPLAMLAR) {
      const alan = document.createElement("div");
      alan.className = "alan";
      const etiket = document.createElement("label");
      etiket.textContent = kolon.etiket;
      const girdiAlani = girdi(
        kolon,
        totals?.[kolon.alan],
        kolon.etiket,
        `totals.${kolon.alan}`,
      );
      etiket.htmlFor = `detay-${kolon.alan}`;
      girdiAlani.id = `detay-${kolon.alan}`;
      alan.append(etiket, girdiAlani);
      toplamlar.appendChild(alan);
    }
  }

  function karsilastirmayiCiz(validation) {
    karsilik.textContent = "";
    const model = uyusmazlikModeli(validation);
    karsilikKutusu.className = model.verdict === "ok" ? "uyusmazlik temiz" : "uyusmazlik";
    if (model.verdict !== "mismatch") {
      const satir = document.createElement("p");
      satir.className = "uyusmazlik-durum";
      satir.textContent =
        model.verdict === "ok"
          ? "Beklenen ile fişte yazan tutuyor — doğrulama temiz."
          : "Fişten okunabilir ürün çıkmadığı için doğrulama yapılmadı.";
      karsilik.appendChild(satir);
      return;
    }
    const tablo = document.createElement("table");
    tablo.className = "karsilastirma";
    const basliklar = tablo.appendChild(document.createElement("tr"));
    for (const [baslik, saga] of [
      ["Alan", false],
      ["Beklenen", true],
      ["Fişte yazan", true],
      ["Fark", true],
    ]) {
      const th = document.createElement("th");
      th.scope = "col";
      th.className = saga ? "saga" : "";
      th.textContent = baslik;
      basliklar.appendChild(th);
    }
    const govde = tablo.appendChild(document.createElement("tbody"));
    for (const satir of model.satirlar) {
      // A discount is a discount whichever way the receipt signed it.
      const yaz = satir.alan === "iskonto" ? iskontoPara : para;
      const tr = document.createElement("tr");
      if (satir.uyusmaz) tr.className = "uyusmaz";
      tr.append(
        hucre(satir.etiket, false),
        hucre(yaz(satir.beklenen), true),
        hucre(yaz(satir.fiilde), true),
        hucre(Math.abs(satir.fark) < KURUS ? "—" : para(satir.fark), true),
      );
      govde.appendChild(tr);
    }
    karsilik.appendChild(tablo);
    if (model.urunler.length) {
      const not = document.createElement("p");
      not.className = "uyusmazlik-not";
      not.textContent = `Uyuşmayan satırlar: ${model.urunler
        .map((urun) => `Ürün ${urun.sira} · ${URUN_ALAN[urun.alan] || urun.alan}`)
        .join(", ")}`;
      karsilik.appendChild(not);
    }
  }

  function okunamayaniCiz(okunamayan) {
    okunamayanListe.textContent = "";
    const parcalar = (Array.isArray(okunamayan) ? okunamayan : []).filter((parca) =>
      metin(parca),
    );
    okunamayanKutusu.hidden = parcalar.length === 0;
    for (const parca of parcalar) {
      const li = document.createElement("li");
      li.textContent = metin(parca);
      okunamayanListe.appendChild(li);
    }
  }

  function jsonuSifirla() {
    jsonAlani.hidden = true;
    jsonAlani.textContent = "";
    jsonDugme.textContent = "Ham JSON";
    jsonDugme.setAttribute("aria-expanded", "false");
  }

  function ciz(env, { gorsel = true } = {}) {
    envelope = env;
    islenebilir = env.status === "done" || env.status === "failed";
    // A fresh envelope makes an open confirmation and a stale before/after
    // diff belong to a state that no longer exists.
    onayKutusu.hidden = true;
    farkKutusu.hidden = true;
    const result = env.result;
    const header = result?.header || {};
    const meta = result?.meta || {};
    const kisa = metin(env.job_id).slice(0, 8);
    const firma = metin(header.isim);
    baslik.textContent = firma || `Fiş ${kisa}`;
    ozet.textContent = [
      firma && kisa, // with no firm the id is already the title
      metin(env.client_ref) && `Ref ${env.client_ref}`,
      metin(env.meta?.worker) && `Çalışan ${env.meta.worker}`,
      metin(meta.tarih),
      metin(meta.saat),
      metin(meta.no) && `Fiş No ${meta.no}`,
      env.meta?.quality_mode ? "Kalite modu" : "Hızlı mod",
    ]
      .filter(Boolean)
      .join(" · ");
    asama.textContent = asamaSureleri(env.meta);
    asama.hidden = false;

    const etiket = VERDICT[env.validation?.verdict] || {
      etiket: DURUM[env.status] || "—",
      renk: "not",
    };
    durumEtiket.className = `etiket etiket-${etiket.renk}`;
    durumEtiket.textContent = etiket.etiket;
    durumEtiket.hidden = false;

    if (gorsel) gorseliGoster(env.image_url);
    karsilikKutusu.hidden = !env.validation;
    // A save redraws under an open raw-JSON panel: it has to show the envelope
    // that is now on the server, not the one that was there before the save.
    if (jsonAlani.hidden) jsonuSifirla();
    else jsonAlani.textContent = JSON.stringify(env, null, 2);
    dugumuGuncelle();
    icerik.hidden = false;
    // A receipt still in the queue has a photograph worth judging on; only the
    // numbers it has not produced are missing.
    bekleme.hidden = !!result;
    panel.hidden = !result;
    if (!result) {
      // Nothing to correct, so nothing left on screen that could be saved.
      urunleriCiz([]);
      toplamlar.textContent = "";
      // A job that died names its own reason ("small brain not installed — …");
      // the reviewer reads the fix from it, so it goes on the line they see.
      const sebep = typeof env.error === "string" ? env.error.trim() : "";
      bekleme.textContent =
        env.status === "failed" && sebep
          ? `Bu fiş işlenemedi — ${sebep}`
          : env.status === "failed"
            ? "Bu fiş işlenemedi — ürünler ve toplamlar ancak işlenince burada görünür."
            : "Bu fiş henüz okunmadı — ürünler ve toplamlar işlenince burada görünür.";
      return;
    }
    urunleriCiz(result.items);
    toplamlariCiz(result.totals);
    karsilastirmayiCiz(env.validation);
    okunamayaniCiz(result.okunamayan);
  }

  async function ac(jobId) {
    sonId = jobId;
    if (!dialog.open) dialog.showModal();
    const tur = ++sira;
    hata.hidden = true;
    icerik.hidden = true;
    baslik.textContent = "Fiş detayı";
    ozet.textContent = "Yükleniyor…";
    asama.hidden = true; // the previous receipt's timings are not this job's
    durumEtiket.hidden = true;
    kayitDurumu("");
    onayKutusu.hidden = true;
    kaydetDugme.disabled = true; // an edit belongs to the receipt it was typed on
    let env;
    try {
      const yanit = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}`);
      if (!yanit.ok) throw new Error(`HTTP ${yanit.status}`);
      env = await yanit.json();
    } catch {
      if (tur !== sira) return;
      hata.hidden = false;
      return;
    }
    if (tur !== sira) return; // a newer open already owns the dialog
    ciz(env);
  }

  function duzenlenenler() {
    return [...dialog.querySelectorAll("input[data-yol]")].filter(
      (girdiAlani) => girdiAlani.value !== girdiAlani.dataset.baslangic,
    );
  }

  /** Marks the edited fields a number cannot be read from; how many there are.
   *
   * A number input holding garbage reads as empty, and an empty box sent as a
   * correction would land on 0,00 — an amount the reviewer never typed.
   */
  function gecerisizleriIsaretle() {
    let sayim = 0;
    for (const girdiAlani of duzenlenenler()) {
      const deger = girdiAlani.value.trim();
      const bozuk =
        girdiAlani.dataset.bicim === "sayi" &&
        (!deger || !Number.isFinite(Number(deger)));
      girdiAlani.classList.toggle("gecersiz", bozuk);
      if (bozuk) sayim++;
    }
    return sayim;
  }

  function kayitDurumu(metin, renk = "") {
    kaydetDurum.textContent = metin;
    kaydetDurum.className = ["kayit-durum", renk].filter(Boolean).join(" ");
    kaydetDurum.hidden = !metin;
  }

  function dugumuGuncelle() {
    kaydetDugme.disabled = kaydediliyor || duzenlenenler().length === 0;
    yenidenDugme.disabled = kaydediliyor || yenidenIsleniyor || !islenebilir;
    onaylaDugme.disabled = yenidenIsleniyor;
  }

  function farklariCiz(satirlar) {
    farkIcerik.textContent = "";
    farkKutusu.hidden = false;
    if (!satirlar.length) {
      const not = document.createElement("p");
      not.className = "uyusmazlik-durum";
      not.textContent = "Kalite modu aynı veriyi üretti — değişen bir alan yok.";
      farkIcerik.appendChild(not);
      return;
    }
    const tablo = document.createElement("table");
    tablo.className = "karsilastirma";
    const basliklar = tablo.appendChild(document.createElement("tr"));
    for (const [baslik, saga] of [
      ["Alan", false],
      ["Önce", true],
      ["Sonra", true],
    ]) {
      const th = document.createElement("th");
      th.scope = "col";
      th.className = saga ? "saga" : "";
      th.textContent = baslik;
      basliklar.appendChild(th);
    }
    const govde = tablo.appendChild(document.createElement("tbody"));
    for (const satir of satirlar) {
      const tr = document.createElement("tr");
      tr.append(
        hucre(satir.etiket, false),
        hucre(satir.once, true),
        hucre(satir.sonra, true),
      );
      govde.appendChild(tr);
    }
    farkIcerik.appendChild(tablo);
  }

  async function yenidenIsle() {
    if (!sonId || yenidenIsleniyor) return;
    const once = envelope;
    const tur = sira; // opening another receipt while this runs owns the dialog
    yenidenIsleniyor = true;
    onayKutusu.hidden = true;
    dugumuGuncelle();
    kayitDurumu("Kalite modu işleniyor… model fişi bir daha okuyor, bu birkaç saniye sürebilir.");
    try {
      const yanit = await fetch(`${API}/jobs/${encodeURIComponent(sonId)}/rerun`, {
        method: "POST",
      });
      if (!yanit.ok) throw new Error(await hataMesaji(yanit));
      const guncel = await yanit.json();
      if (tur !== sira || sonId !== guncel.job_id) return;
      ciz(guncel, { gorsel: false });
      farklariCiz(kaliteFarki(once, guncel));
      kayitDurumu(
        "Kalite modu bitti ✓ doğrulama yeni sayılarla yeniden çalıştı.",
        "kayit-iyi",
      );
      onDuzeltme(); // the list row underneath carries the same amounts
    } catch (hata) {
      if (tur !== sira) return;
      kayitDurumu(`Yeniden işlenemedi — ${hata.message}`, "kayit-hata");
    } finally {
      if (tur === sira) {
        yenidenIsleniyor = false;
        dugumuGuncelle();
      }
    }
  }

  async function kaydet() {
    if (!sonId) return;
    const gecerisiz = gecerisizleriIsaretle();
    if (gecerisiz) {
      kayitDurumu(
        `${gecerisiz} alanda sayı olmayan bir değer var — önce onları düzelt.`,
        "kayit-hata",
      );
      return;
    }
    const alanlar = duzeltmeAlanlari(duzenlenenler());
    const alanSayisi = Object.keys(alanlar).length;
    if (!alanSayisi) return;
    kaydediliyor = true;
    dugumuGuncelle();
    kayitDurumu("Kaydediliyor…");
    try {
      const yanit = await fetch(`${API}/jobs/${encodeURIComponent(sonId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: alanlar }),
      });
      if (!yanit.ok) throw new Error(`HTTP ${yanit.status}`);
      const guncel = await yanit.json();
      if (sonId !== guncel.job_id) return; // a newer open owns the dialog
      ciz(guncel, { gorsel: false });
      kayitDurumu("");
      bildir("kaydet", { alan: alanSayisi });
      onDuzeltme(); // the list row underneath carries the same amounts
    } catch {
      // The typed values stay on screen: a lost correction is worse than a
      // second try.
      kayitDurumu("");
      bildir("hata", { metin: "Kaydedilemedi — bağlantıyı kontrol edip tekrar dene." });
    } finally {
      kaydediliyor = false;
      dugumuGuncelle();
    }
  }

  document.getElementById("detay-kapat").addEventListener("click", () => dialog.close());
  document
    .getElementById("detay-tekrar")
    .addEventListener("click", () => sonId && ac(sonId));
  jsonDugme.addEventListener("click", () => {
    const acik = jsonAlani.hidden;
    jsonAlani.hidden = !acik;
    if (acik) jsonAlani.textContent = JSON.stringify(envelope, null, 2);
    jsonDugme.textContent = acik ? "JSON'u gizle" : "Ham JSON";
    jsonDugme.setAttribute("aria-expanded", String(acik));
  });
  // One listener for every field in the dialog: the mark is what tells the
  // reviewer a value on screen is no longer the value the model read, and it
  // is what the save collects.
  dialog.addEventListener("input", (olay) => {
    olay.target.classList.add("duzenlendi");
    olay.target.classList.remove("gecersiz");
    kayitDurumu("");
    dugumuGuncelle();
  });
  kaydetDugme.addEventListener("click", kaydet);
  yenidenDugme.addEventListener("click", () => {
    onayKutusu.hidden = false;
    onaylaDugme.focus();
  });
  vazgecDugme.addEventListener("click", () => {
    onayKutusu.hidden = true;
  });
  onaylaDugme.addEventListener("click", yenidenIsle);

  return { ac, kapat: () => dialog.close() };
}
