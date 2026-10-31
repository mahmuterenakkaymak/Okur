// Submit flow: capture -> crop -> upload -> live status -> result. The four
// step cards live in index.html; this module only moves between them and
// paints the finished envelope into the result view.
//
// ASSUMPTION: one receipt at a time — a field worker never has two live
// jobs, so the flow tracks a single envelope and no history (that is T27).

import { createCapture } from "./capture.js";
import { createCropper } from "./crop.js";
import { getApiKey, getJob, isOnline, pollJob, setApiKey, submitJob } from "./api.js";
import { createHistory } from "./history.js";
import { createFlow } from "./flow.js";
import { cameraNotice, offlineNotice, recoveryFor, withTimeout } from "./recovery.js";
import { iskontoPara, para, sayi } from "./result_totals.js";
import { statusOf } from "./status.js";
import { createStages } from "./stages.js";
import { createVerdict } from "./verdict.js";

const ADIMLAR = {
  cekim: document.getElementById("adim-cekim"),
  kirp: document.getElementById("adim-kirp"),
  durum: document.getElementById("adim-durum"),
  sonuc: document.getElementById("adim-sonuc"),
  anahtar: document.getElementById("adim-anahtar"),
};

const durumEtiket = document.getElementById("durum-etiket");
const durumIpucu = document.getElementById("durum-ipucu");
const durumIlerleme = document.getElementById("durum-ilerleme");
const gecenSure = document.getElementById("gecen-sure");
const hataMesaji = document.getElementById("hata-mesaji");
const verdictTasi = document.getElementById("verdict-tasi");
const verdictDetay = document.getElementById("verdict-detay");
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
const netBant = document.getElementById("net-bant");
const kameraIpucu = document.getElementById("kamera-ipucu");
const tekrarDugme = document.getElementById("tekrar-dene");
const yenidenCek = document.getElementById("yeniden-cek");
const anahtarTamam = document.getElementById("anahtar-tamam");
const demoAlani = document.getElementById("demo-alani");
const ornekFis = document.getElementById("ornek-fis");

// D2: the four-stage row under the headline, ticking with the same clock the
// status card already keeps.
const asama = createStages({
  container: document.getElementById("asama-satiri"),
  sayac: gecenSure,
});

// D3: the chip that closes the receipt, with the re-shoot it offers straight
// from an unreadable verdict.
const verdict = createVerdict({
  chip: verdictTasi,
  detay: verdictDetay,
  onYeniden: () => kamerayaDon(),
});

const miktar = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 3 });

function metin(value) {
  return typeof value === "string" ? value : "";
}

let guncel = null;
let sonucEnvelope = null;
let startedAt = 0;
let clientRef = null;
let capturedAt = null;
let sonCrop = null;
const akis = createFlow();

function show(step) {
  for (const [name, card] of Object.entries(ADIMLAR)) card.hidden = name !== step;
  if (step === "cekim") capture.start();
  else capture.stop();
  cizNet();
}

function hideError() {
  hataMesaji.hidden = true;
  hataMesaji.textContent = "";
  tekrarDugme.hidden = true;
}

function showError(message) {
  show("kirp");
  hataMesaji.textContent = message;
  hataMesaji.hidden = false;
}

const capture = createCapture({
  container: document.getElementById("cekim-alani"),
  mediaDevices: (globalThis.navigator && globalThis.navigator.mediaDevices) || null,
  onState: (state) => {
    kameraIpucu.textContent = cameraNotice(state);
  },
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
  asama.update(v);
  yenidenCek.hidden = !v.stale;
}

// One failure, one way out: the key screen for a dead key, the crop card
// with a retry (the crop is still loaded) for a failed upload, and for a
// history read the status card turned into the error note with re-shoot.
function hataGoster(err, { onCrop = false } = {}) {
  const r = recoveryFor(err);
  if (r.action === "key") {
    show("anahtar");
    ADIMLAR.anahtar.scrollIntoView({ block: "start", behavior: "smooth" });
    return;
  }
  if (onCrop && sonCrop) {
    show("kirp");
    hataMesaji.textContent = r.message;
    hataMesaji.hidden = false;
    tekrarDugme.hidden = false;
    return;
  }
  show("durum");
  durumEtiket.textContent = "Fiş yüklenemedi";
  durumIpucu.textContent = r.message;
  durumIlerleme.style.width = "0%";
  asama.update(null);
  yenidenCek.hidden = false;
}

async function gonder(crop) {
  sonCrop = crop;
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
  const tur = akis.devral(cizDurum);
  try {
    const kabul = await withTimeout(submitJob(crop.blob, { clientRef, capturedAt }));
    if (!akis.canli(tur)) return;
    guncel = kabul;
    cizDurum();
    const bitti = await pollJob(kabul.job_id, {
      onTick: (envelope) => {
        if (envelope && akis.canli(tur)) guncel = envelope;
      },
    });
    if (!akis.canli(tur)) return;
    sonucGoster(bitti);
    history.refresh();
  } catch (err) {
    if (!akis.canli(tur)) return;
    hataGoster(err, { onCrop: true });
  } finally {
    akis.kapat(tur);
  }
}

// A history tap opens the same result view; a job that has not finished yet
// resumes live tracking instead of showing a dead-end detail. The tap takes
// the screen away from whatever was running first, so a send in flight never
// keeps a second poll loop ticking behind the detail.
async function detayAc(job) {
  let tur = akis.dur();
  hideError();
  try {
    if (job.status === "done" || job.status === "failed") {
      const env = await getJob(job.job_id);
      if (!akis.canli(tur)) return;
      sonucGoster(env);
      return;
    }
    guncel = job;
    startedAt = Date.now();
    show("durum");
    cizDurum();
    tur = akis.devral(cizDurum);
    const bitti = await pollJob(job.job_id, {
      onTick: (envelope) => {
        if (envelope && akis.canli(tur)) guncel = envelope;
      },
    });
    if (!akis.canli(tur)) return;
    sonucGoster(bitti);
    history.refresh();
  } catch (err) {
    if (!akis.canli(tur)) return;
    hataGoster(err);
  } finally {
    akis.kapat(tur);
  }
}

function cizTablo(items) {
  urunGovde.textContent = "";
  const rows = items.length
    ? items.map((item) => [
        metin(item.ad),
        miktar.format(sayi(item.miktar)),
        para(item.birim_fiyat),
        para(item.toplam),
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
  verdict.update(v);

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
  const oran = sayi(totals.kdv_orani);
  tAraToplam.textContent = para(totals.ara_toplam);
  tIskonto.textContent = iskontoPara(totals.iskonto);
  tKdvOrani.textContent = oran ? `%${Math.round((oran > 1 ? oran : oran * 100) * 10) / 10}` : "";
  tKdv.textContent = para(totals.kdv);
  tToplam.textContent = para(totals.toplam);
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

function kamerayaDon() {
  akis.dur();
  cropper.clear();
  sonucEnvelope = null;
  guncel = null;
  sonCrop = null;
  hideError();
  show("cekim");
}

yeniFis.addEventListener("click", kamerayaDon);

cekimeDon.addEventListener("click", () => {
  akis.dur();
  cropper.clear();
  sonCrop = null;
  hideError();
  show("cekim");
});

// The upload died but the crop survived: resend the very same blob under
// the same client_ref, so a half-landed job is returned, not duplicated.
tekrarDugme.addEventListener("click", () => {
  if (sonCrop) gonder(sonCrop);
});

yenidenCek.addEventListener("click", () => {
  akis.dur();
  cropper.clear();
  sonCrop = null;
  hideError();
  show("cekim");
});

anahtarTamam.addEventListener("click", () => {
  show(sonCrop ? "kirp" : "cekim");
  anahtarGirisi.focus();
});

function cizNet() {
  const bant = offlineNotice({ online: isOnline(), hasDraft: !!sonCrop });
  netBant.hidden = !bant.visible;
  if (bant.visible) netBant.textContent = bant.text;
}
addEventListener("online", cizNet);
addEventListener("offline", cizNet);
cizNet();

const history = createHistory({
  container: document.getElementById("gecmis"),
  onOpen: (job) => detayAc(job),
});

anahtarGirisi.value = getApiKey();
anahtarGirisi.addEventListener("change", () => {
  anahtarIpucu.textContent = setApiKey(anahtarGirisi.value)
    ? "Kaydedildi ✓"
    : "Anahtar temizlendi.";
  history.refresh();
});

// Demo mode (scripts/serve_demo.py): the demo server hands out its key and
// sample receipts at /demo/config.json, so the whole flow — submit, live
// status, result — is reviewable without a camera. Anywhere else the fetch
// 404s and the page stays a plain worker PWA.
const demoHata = document.getElementById("demo-hata");
let demo = null;
let demoSira = 0;

fetch("/demo/config.json", { cache: "no-store" })
  .then((resp) => (resp.ok ? resp.json() : null))
  .then((conf) => {
    if (!conf || !conf.api_key || !Array.isArray(conf.samples) || !conf.samples.length) return;
    demo = conf;
    setApiKey(conf.api_key);
    anahtarGirisi.value = conf.api_key;
    anahtarIpucu.textContent = "Demo sunucusu: anahtar otomatik dolduruldu.";
    demoAlani.hidden = false;
    history.refresh();
  })
  .catch(() => {});

ornekFis.addEventListener("click", async () => {
  if (!demo) return;
  ornekFis.disabled = true;
  demoHata.hidden = true;
  try {
    const name = demo.samples[demoSira++ % demo.samples.length];
    const resp = await fetch(`/demo/samples/${encodeURIComponent(name)}`);
    if (!resp.ok) throw new Error(`sample ${name} failed`);
    clientRef = globalThis.crypto?.randomUUID?.() || `fis-${Date.now()}`;
    capturedAt = new Date().toISOString();
    await gonder({ blob: await resp.blob() });
  } catch {
    demoHata.textContent = "Örnek fiş alınamadı. Sayfayı yenileyip tekrar dene.";
    demoHata.hidden = false;
  } finally {
    ornekFis.disabled = false;
  }
});

show("cekim");
