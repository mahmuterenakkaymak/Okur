// History feed: the worker's own submissions, newest first. Pages load as a
// hidden sentinel scrolls into view (infinite scroll), pulling the card down
// refreshes, and a tap hands the lite row to onOpen — the detail itself is
// the app's result view, so this module only renders the list.
//
// ASSUMPTION: lite rows carry no currency and contract v1 defaults to TRY,
// so the feed formats `toplam` as Turkish lira.

import { fetchImage, getApiKey, listJobs } from "./api.js";
import { statusOf } from "./status.js";

const SAYFA = 20; // lite rows per page
const CEKME_EŞİĞİ = 72; // px of pull that counts as "refresh"

const TASI_CLASS = {
  verified: "chip-on",
  done: "chip-on",
  queued: "chip-off",
  ocr: "chip-off",
  structuring: "chip-off",
  mismatch: "chip-off",
  unreadable: "chip-bad",
  failed: "chip-bad",
};

const tarih = new Intl.DateTimeFormat("tr-TR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const tutar = new Intl.NumberFormat("tr-TR", {
  style: "currency",
  currency: "TRY",
});

function tarihMetin(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : tarih.format(date);
}

export function createHistory({ container, onOpen = () => {} }) {
  const liste = document.getElementById("gecmis-liste");
  const bos = document.getElementById("gecmis-bos");
  const durum = document.getElementById("gecmis-durum");
  const sentinel = document.getElementById("gecmis-sentinel");
  const yenileme = document.getElementById("gecmis-yenileme");

  let items = [];
  let toplam = null; // null until the first page answers
  let loading = false;
  const miniler = new Map(); // thumbnail_url -> Promise<objectURL>

  function miniUrl(url) {
    if (!miniler.has(url)) {
      const pending = fetchImage(url).then((blob) => URL.createObjectURL(blob));
      pending.catch(() => miniler.delete(url));
      miniler.set(url, pending);
    }
    return miniler.get(url);
  }

  function satir(job) {
    const v = statusOf(job);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "fis-satiri";

    const mini = document.createElement("span");
    mini.className = "fis-mini";
    const img = document.createElement("img");
    img.alt = "";
    mini.appendChild(img);

    const ozet = document.createElement("span");
    ozet.className = "fis-ozet";
    const zaman = document.createElement("span");
    zaman.className = "fis-tarih";
    zaman.textContent = tarihMetin(job.received_at);
    const para = document.createElement("span");
    para.className = "fis-tutar";
    const miktar = Number(job.toplam);
    para.textContent = job.toplam == null || !Number.isFinite(miktar)
      ? ""
      : tutar.format(miktar);
    ozet.append(zaman, para);

    const chip = document.createElement("span");
    chip.className = `chip ${TASI_CLASS[v.id] || "chip-off"}`;
    chip.setAttribute("role", "status");
    chip.textContent = v.label;

    button.append(mini, ozet, chip);
    button.addEventListener("click", () => onOpen(job));
    if (job.thumbnail_url) {
      miniUrl(job.thumbnail_url)
        .then((url) => {
          img.src = url;
          img.classList.add("yuklu");
        })
        .catch(() => {});
    }

    const li = document.createElement("li");
    li.appendChild(button);
    return li;
  }

  function ciz() {
    liste.textContent = "";
    for (const job of items) liste.appendChild(satir(job));
    const anahtarli = Boolean(getApiKey());
    const hepsiYuklendi = toplam !== null && items.length >= toplam;
    sentinel.hidden = !anahtarli || hepsiYuklendi || loading;
    bos.hidden = !(anahtarli && toplam === 0 && !durum.textContent);
  }

  async function sayfaEkle() {
    if (loading || (toplam !== null && items.length >= toplam)) return;
    if (!getApiKey()) {
      durum.textContent = "Geçmişini görmek için önce API anahtarını gir.";
      ciz();
      return;
    }
    loading = true;
    durum.textContent = "";
    try {
      const body = await listJobs({ limit: SAYFA, offset: items.length });
      items = items.concat(Array.isArray(body?.jobs) ? body.jobs : []);
      toplam = Number(body?.total) || 0;
    } catch (err) {
      durum.textContent =
        err && err.message ? err.message : "Geçmiş bir türlü yüklenemedi.";
      toplam = toplam === null ? 0 : toplam; // a dead key must not spin the sentinel
    } finally {
      loading = false;
      yenileme.hidden = true;
      yenileme.classList.remove("donuyor");
      ciz();
    }
  }

  function yenile() {
    items = [];
    toplam = null;
    durum.textContent = "";
    yenileme.hidden = false;
    yenileme.classList.add("donuyor");
    sayfaEkle();
  }

  let baslangicY = null;
  let cekme = 0;
  container.addEventListener("touchstart", (event) => {
    if ((window.scrollY || 0) > 0 || loading) {
      baslangicY = null;
      return;
    }
    baslangicY = event.touches[0].clientY;
    cekme = 0;
  }, { passive: true });
  container.addEventListener("touchmove", (event) => {
    if (baslangicY === null) return;
    cekme = Math.max(0, event.touches[0].clientY - baslangicY);
    if (cekme > 8) {
      yenileme.hidden = false;
      yenileme.style.transform = `rotate(${Math.round(Math.min(cekme, 120) * 1.6)}deg)`;
    }
  }, { passive: true });
  const birak = () => {
    const mi = baslangicY !== null && cekme >= CEKME_EŞİĞİ;
    baslangicY = null;
    cekme = 0;
    yenileme.style.transform = "";
    if (mi) yenile();
  };
  container.addEventListener("touchend", birak);
  container.addEventListener("touchcancel", birak);

  const gozlemci = new IntersectionObserver(
    (girdiler) => {
      if (girdiler.some((girdi) => girdi.isIntersecting)) sayfaEkle();
    },
    { rootMargin: "240px" },
  );
  gozlemci.observe(sentinel);

  sayfaEkle();

  return { refresh: yenile };
}
