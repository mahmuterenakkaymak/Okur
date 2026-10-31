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

export function createFisDetay({ onDuzeltme = () => {} } = {}) {
  const dialog = document.getElementById("fis-detay");
  const baslik = document.getElementById("detay-baslik");
  const ozet = document.getElementById("detay-ozet");
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

  let sira = 0; // a late answer from a superseded open must not draw
  let gorselSira = 0;
  let sonId = "";
  let envelope = null;
  let kaydediliyor = false;

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
      bekleme.textContent =
        env.status === "failed"
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
    durumEtiket.hidden = true;
    kayitDurumu("");
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
    const alanlar = {};
    for (const girdiAlani of duzenlenenler()) {
      alanlar[girdiAlani.dataset.yol] = girdiAlani.value.trim();
    }
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
      kayitDurumu(
        `Kaydedildi ✓ ${alanSayisi} alan düzeltildi, doğrulama yeniden çalıştı.`,
        "kayit-iyi",
      );
      onDuzeltme(); // the list row underneath carries the same amounts
    } catch {
      // The typed values stay on screen: a lost correction is worse than a
      // second try.
      kayitDurumu("Kaydedilemedi — bağlantıyı kontrol edip tekrar dene.", "kayit-hata");
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

  return { ac, kapat: () => dialog.close() };
}
