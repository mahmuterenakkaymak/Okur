// Submit flow: capture -> crop -> upload -> live status -> result. The four
// step cards live in index.html; this module only moves between them and
// paints the finished envelope into the result view.
//
// ASSUMPTION: one receipt at a time — a field worker never has two live
// jobs, so the flow tracks a single envelope and no history (that is T27).

import { createCapture } from "./capture.js";
import { createCropper } from "./crop.js";
import { getApiKey, pollJob, setApiKey, submitJob } from "./api.js";
import { statusOf } from "./status.js";

const ADIMLAR = {
  cekim: document.getElementById("adim-cekim"),
  kirp: document.getElementById("adim-kirp"),
  durum: document.getElementById("adim-durum"),
  sonuc: document.getElementById("adim-sonuc"),
};

const durumEtiket = document.getElementById("durum-etiket");
const durumIpucu = document.getElementById("durum-ipucu");
const durumIlerleme = document.getElementById("durum-ilerleme");
const gecenSure = document.getElementById("gecen-sure");
const hataMesaji = document.getElementById("hata-mesaji");
const verdictTasi = document.getElementById("verdict-tasi");
const sonucUyari = document.getElementById("sonuc-uyari");
const sonucFirma = document.getElementById("sonuc-firma");
const sonucMeta = document.getElementById("sonuc-meta");
const urunGovde = document.getElementById("urun-govde");
const tAraToplam = document.getElementById("t-ara-toplam");
const tIskonto = document.getElementById("t-iskonto");
const tKdvOrani = document.getElementById("t-kdv-orani");
const tKdv = document.getElementById("t-kdv");
const tToplam = document.getElementById("t-toplam");
const tParaBirimi = document.getElementById("t-para-birimi");
const hamJson = document.getElementById("ham-json");
const hamJsonDugme = document.getElementById("ham-json-dugme");
const yeniFis = document.getElementById("yeni-fis");
const cekimeDon = document.getElementById("cekime-don");
const anahtarGirisi = document.getElementById("api-anahtari");
const anahtarIpucu = document.getElementById("anahtar-ipucu");

const TASI_CLASS = {
  ok: "chip-on",
  done: "chip-on",
  mismatch: "chip-off",
  unreadable: "chip-bad",
  failed: "chip-bad",
};

const tutar = new Intl.NumberFormat("tr-TR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const miktar = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 3 });

function sayi(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function metin(value) {
  return typeof value === "string" ? value : "";
}

let guncel = null;
let sonucEnvelope = null;
let startedAt = 0;
let tickTimer = null;
let clientRef = null;
let capturedAt = null;

function show(step) {
  for (const [name, card] of Object.entries(ADIMLAR)) card.hidden = name !== step;
  if (step === "cekim") capture.start();
  else capture.stop();
}

function hideError() {
  hataMesaji.hidden = true;
  hataMesaji.textContent = "";
}

function showError(message) {
  show("kirp");
  hataMesaji.textContent = message;
  hataMesaji.hidden = false;
}

const capture = createCapture({
  container: document.getElementById("cekim-alani"),
  mediaDevices: (globalThis.navigator && globalThis.navigator.mediaDevices) || null,
  onShot: async (shot) => {
    clientRef = globalThis.crypto?.randomUUID?.() || `fis-${Date.now()}`;
    capturedAt = new Date().toISOString();
    hideError();
    show("kirp");
    await cropper.load(shot.blob);
  },
});

const cropper = createCropper({
  container: document.getElementById("kirp-alani"),
  onCrop: (crop) => gonder(crop),
});

function cizDurum() {
  const v = statusOf(guncel, { elapsedMs: Date.now() - startedAt });
  durumEtiket.textContent = v.label;
  durumIpucu.textContent = v.hint;
  durumIlerleme.style.width = `${Math.round(v.progress * 100)}%`;
  gecenSure.textContent = `${v.seconds} sn`;
}

async function gonder(crop) {
  hideError();
  if (!getApiKey()) {
    showError(
      "Fişi göndermek için önce API anahtarın gerekiyor — yöneticinden aldığın anahtarı yukarıdaki kutuya yapıştır.",
    );
    return;
  }
  show("durum");
  guncel = null;
  startedAt = Date.now();
  cizDurum();
  tickTimer = setInterval(cizDurum, 500);
  try {
    const kabul = await submitJob(crop.blob, { clientRef, capturedAt });
    guncel = kabul;
    cizDurum();
    const bitti = await pollJob(kabul.job_id, {
      onTick: (envelope) => {
        if (envelope) guncel = envelope;
      },
    });
    sonucGoster(bitti);
  } catch (err) {
    showError(err && err.message ? err.message : "Fiş gönderilemedi, tekrar dene.");
  } finally {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

function cizTablo(items) {
  urunGovde.textContent = "";
  const rows = items.length
    ? items.map((item) => [
        metin(item.ad),
        miktar.format(sayi(item.miktar)),
        tutar.format(sayi(item.birim_fiyat)),
        tutar.format(sayi(item.toplam)),
      ])
    : [["Bu fişte okunabilen ürün bulunamadı.", "", "", ""]];
  for (const cells of rows) {
    const tr = document.createElement("tr");
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    urunGovde.appendChild(tr);
  }
}

function sonucGoster(env) {
  sonucEnvelope = env;
  const v = statusOf(env);
  verdictTasi.textContent = v.label;
  verdictTasi.className = `chip ${TASI_CLASS[v.verdict] || TASI_CLASS[v.status] || "chip-off"}`;

  const result = env.result || {};
  const header = result.header || {};
  const meta = result.meta || {};
  sonucFirma.textContent = metin(header.isim);
  sonucMeta.textContent = [
    metin(meta.tarih),
    metin(meta.saat),
    metin(meta.no) && `Fiş No ${meta.no}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const uyariSatirlari = [];
  const okunamayan = (Array.isArray(result.okunamayan) ? result.okunamayan : []).filter(
    (parca) => metin(parca),
  );
  if (okunamayan.length) {
    uyariSatirlari.push(`Okunamayan bölümler: ${okunamayan.join(", ")}`);
  }
  if (v.fields.length) {
    uyariSatirlari.push(`Uyuşmayan alanlar: ${v.fields.join(", ")}`);
  }
  sonucUyari.textContent = uyariSatirlari.join(" · ");
  sonucUyari.hidden = !uyariSatirlari.length;

  cizTablo(Array.isArray(result.items) ? result.items : []);

  const totals = result.totals || {};
  const iskonto = sayi(totals.iskonto);
  const oran = sayi(totals.kdv_orani);
  tAraToplam.textContent = tutar.format(sayi(totals.ara_toplam));
  tIskonto.textContent = iskonto ? `−${tutar.format(iskonto)}` : tutar.format(0);
  tKdvOrani.textContent = oran ? `%${Math.round((oran > 1 ? oran : oran * 100) * 10) / 10}` : "";
  tKdv.textContent = tutar.format(sayi(totals.kdv));
  tToplam.textContent = tutar.format(sayi(totals.toplam));
  tParaBirimi.textContent = metin(result.para_birimi) || "TRY";

  hamJson.hidden = true;
  hamJson.textContent = "";
  hamJsonDugme.textContent = "Ham JSON";
  hamJsonDugme.setAttribute("aria-expanded", "false");

  show("sonuc");
  ADIMLAR.sonuc.scrollIntoView({ block: "start", behavior: "smooth" });
}

hamJsonDugme.addEventListener("click", () => {
  const open = hamJson.hidden;
  hamJson.hidden = !open;
  if (open) hamJson.textContent = JSON.stringify(sonucEnvelope, null, 2);
  hamJsonDugme.textContent = open ? "JSON'u gizle" : "Ham JSON";
  hamJsonDugme.setAttribute("aria-expanded", String(open));
});

yeniFis.addEventListener("click", () => {
  cropper.clear();
  sonucEnvelope = null;
  guncel = null;
  hideError();
  show("cekim");
});

cekimeDon.addEventListener("click", () => {
  cropper.clear();
  hideError();
  show("cekim");
});

anahtarGirisi.value = getApiKey();
anahtarGirisi.addEventListener("change", () => {
  anahtarIpucu.textContent = setApiKey(anahtarGirisi.value)
    ? "Kaydedildi ✓"
    : "Anahtar temizlendi.";
});

show("cekim");
