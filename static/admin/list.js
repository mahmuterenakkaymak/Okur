// Fiş listesi: every submission, one row per job. Filtering, searching,
// sorting and paging all happen on the server (/admin/api/jobs), so the table
// costs the same at 25 rows or 25.000 and this module owns only the controls
// and the drawing. Receipt text is model output read off a photograph, so it
// reaches the page through textContent and never as markup.
import { para } from "../app/result_totals.js";

const API = "/admin/api";
const SAYFA_BOYU = 25;
const ARAMA_BEKLEMESI = 300; // ms of typing before a search is worth a request

export const DURUM = { queued: "Sırada", running: "İşleniyor", done: "Bitti", failed: "İşlenemedi" };
export const VERDICT = {
  ok: { etiket: "Temiz", renk: "iyi" },
  mismatch: { etiket: "Uyuşmazlık", renk: "uyari" },
  unreadable: { etiket: "Okunamadı", renk: "kotu" },
};
const KOLONLAR = [
  { baslik: "Fiş", sort: null },
  { baslik: "Çalışan", sort: "worker" },
  { baslik: "Tarih", sort: "tarih" },
  { baslik: "Firma", sort: "firma" },
  { baslik: "Toplam ₺", sort: "toplam", saga: true },
  { baslik: "Doğrulama", sort: "verdict" },
  { baslik: "Mod", sort: "kalite_mode" },
];
const ASAGI = ["tarih", "toplam"]; // a fresh sort starts with the newest/biggest
const OK = { asc: "▲", desc: "▼" };

export function createFisListesi({ acis = () => {} } = {}) {
  const form = document.getElementById("fis-filtreler");
  const ara = document.getElementById("fis-ara");
  const durumSecimi = document.getElementById("fis-durum");
  const calisanSecimi = document.getElementById("fis-calisan");
  const baslangic = document.getElementById("fis-baslangic");
  const bitis = document.getElementById("fis-bitis");
  const temizle = document.getElementById("fis-temizle");
  const hata = document.getElementById("fis-hata");
  const tablo = document.getElementById("fis-tablo");
  const sar = tablo.parentElement;
  const basliklar = tablo.querySelector("thead tr");
  const govde = tablo.querySelector("tbody");
  const bos = document.getElementById("fis-bos");
  const bosBaslik = document.getElementById("fis-bos-baslik");
  const bosNot = document.getElementById("fis-bos-not");
  const sayfalama = document.getElementById("fis-sayfalama");
  const onceki = document.getElementById("fis-onceki");
  const sonraki = document.getElementById("fis-sonraki");
  const sayfaMetin = document.getElementById("fis-sayfa");

  const filtre = { status: "", worker: "", date_from: "", date_to: "", q: "" };
  let sort = "tarih";
  let dir = "desc";
  let offset = 0;
  let toplam = 0;
  let sira = 0; // a late answer from a superseded request must not draw
  let calisanAdlari = [];

  function sorgu() {
    const parametreler = new URLSearchParams();
    for (const [ad, deger] of Object.entries(filtre)) {
      if (deger) parametreler.set(ad, deger);
    }
    parametreler.set("sort", sort);
    parametreler.set("dir", dir);
    parametreler.set("limit", String(SAYFA_BOYU));
    parametreler.set("offset", String(offset));
    return parametreler.toString();
  }

  function iskeletCiz() {
    sar.hidden = false;
    basliklariCiz();
    govde.textContent = "";
    for (let satir = 0; satir < 6; satir++) {
      const tr = document.createElement("tr");
      for (const kolon of KOLONLAR) {
        const cubuk = document.createElement("span");
        cubuk.className = "iskelet";
        const td = document.createElement("td");
        td.appendChild(cubuk);
        tr.appendChild(td);
      }
      govde.appendChild(tr);
    }
  }

  function basliklariCiz() {
    basliklar.textContent = "";
    for (const kolon of KOLONLAR) {
      const th = document.createElement("th");
      th.scope = "col";
      if (kolon.saga) th.classList.add("saga");
      if (!kolon.sort) {
        th.textContent = kolon.baslik;
        basliklar.appendChild(th);
        continue;
      }
      const dugme = document.createElement("button");
      dugme.type = "button";
      dugme.textContent = kolon.baslik;
      if (kolon.sort === sort) {
        dugme.className = "siralama secili";
        const ok = document.createElement("span");
        ok.className = "ok";
        ok.textContent = OK[dir];
        dugme.appendChild(ok);
        th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      } else {
        dugme.className = "siralama";
        th.setAttribute("aria-sort", "none");
      }
      dugme.addEventListener("click", () => sirala(kolon.sort));
      th.appendChild(dugme);
      basliklar.appendChild(th);
    }
  }

  function td(icerik) {
    const hucre = document.createElement("td");
    if (typeof icerik === "string") hucre.textContent = icerik || "—";
    else hucre.appendChild(icerik);
    return hucre;
  }

  function satirElemani(is) {
    const kod = document.createElement("code");
    kod.className = "kod";
    kod.textContent = is.kisa_id || "—";
    kod.title = is.job_id || "";

    const dogrulama = VERDICT[is.verdict];
    const etiket = document.createElement("span");
    etiket.className = `etiket etiket-${dogrulama ? dogrulama.renk : "not"}`;
    etiket.textContent = dogrulama
      ? dogrulama.etiket
      : DURUM[is.status] || "—";

    const mod = document.createElement("span");
    mod.className = `etiket ${is.kalite_mode ? "etiket-kalite" : "etiket-not"}`;
    mod.textContent = is.kalite_mode ? "Kalite" : "Hızlı";

    const tutar = document.createElement("td");
    tutar.className = "saga";
    tutar.textContent = Number.isFinite(is.toplam) ? para(is.toplam) : "—";

    const firma = document.createElement("td");
    firma.className = "firma";
    firma.textContent = is.firma || "—";
    firma.title = is.firma || "";

    const tr = document.createElement("tr");
    tr.dataset.job = is.job_id || "";
    tr.tabIndex = 0;
    tr.append(td(kod), td(is.worker), td(is.tarih), firma, tutar, td(etiket), td(mod));
    return tr;
  }

  function ciz(satirlar) {
    basliklariCiz();
    govde.textContent = "";
    for (const is of satirlar) govde.appendChild(satirElemani(is));
    const filtreVar = Object.values(filtre).some(Boolean);
    sar.hidden = satirlar.length === 0;
    bos.hidden = satirlar.length > 0;
    bosBaslik.textContent = filtreVar
      ? "Bu filtrelerle eşleşen fiş yok."
      : "Henüz fiş yok.";
    bosNot.textContent = filtreVar
      ? "Aramayı kısalt, tarih aralığını genişlet ya da filtreleri temizle."
      : "Saha ekibi fiş gönderdiğinde kayıtlar burada listelenir.";
    temizle.disabled = !filtreVar;
    sayfalama.hidden = toplam === 0;
    const son = Math.min(offset + satirlar.length, toplam);
    sayfaMetin.textContent = `${toplam ? offset + 1 : 0}–${son} / ${toplam} fiş`;
    onceki.disabled = offset === 0;
    sonraki.disabled = son >= toplam;
  }

  async function yukle() {
    const tur = ++sira;
    hata.hidden = true;
    iskeletCiz();
    let vucut;
    try {
      const yanit = await fetch(`${API}/jobs?${sorgu()}`);
      if (!yanit.ok) throw new Error(`HTTP ${yanit.status}`);
      vucut = await yanit.json();
    } catch {
      if (tur !== sira) return;
      sar.hidden = true;
      bos.hidden = true;
      sayfalama.hidden = true;
      hata.hidden = false;
      return;
    }
    if (tur !== sira) return; // a newer request already owns the screen
    toplam = Number(vucut?.total) || 0;
    calisanlariDoldur(vucut?.workers);
    ciz(Array.isArray(vucut?.jobs) ? vucut.jobs : []);
  }

  function calisanlariDoldur(adlar) {
    const liste = Array.isArray(adlar) ? adlar : [];
    if (liste.join("\n") === calisanAdlari.join("\n")) return;
    calisanAdlari = liste;
    calisanSecimi.textContent = "";
    calisanSecimi.append(new Option("Tümü", ""));
    for (const ad of liste) calisanSecimi.append(new Option(ad, ad));
    calisanSecimi.value = filtre.worker;
  }

  function sirala(ad) {
    if (ad === sort) dir = dir === "asc" ? "desc" : "asc";
    else {
      sort = ad;
      dir = ASAGI.includes(ad) ? "desc" : "asc";
    }
    offset = 0;
    yukle();
  }

  function oku() {
    filtre.status = durumSecimi.value;
    filtre.worker = calisanSecimi.value;
    filtre.date_from = baslangic.value;
    filtre.date_to = bitis.value;
    filtre.q = ara.value.trim();
  }

  function uygula() {
    oku();
    offset = 0;
    yukle();
  }

  let bekleyen;
  for (const secim of [durumSecimi, calisanSecimi, baslangic, bitis]) {
    secim.addEventListener("change", uygula);
  }
  ara.addEventListener("input", () => {
    clearTimeout(bekleyen);
    bekleyen = setTimeout(uygula, ARAMA_BEKLEMESI);
  });
  form.addEventListener("submit", (olay) => olay.preventDefault());
  temizle.addEventListener("click", () => {
    form.reset();
    uygula();
  });
  document.getElementById("fis-yenile").addEventListener("click", () => {
    oku();
    yukle();
  });
  document.getElementById("fis-tekrar").addEventListener("click", () => yukle());
  // Rows are redrawn on every load, so the detail opens through one delegated
  // listener on the body instead of a handler per row.
  function detayAc(olay) {
    const tr = olay.target.closest("tr[data-job]");
    if (!tr) return;
    if (olay.type === "keydown" && olay.key !== "Enter" && olay.key !== " ") return;
    olay.preventDefault();
    acis(tr.dataset.job);
  }
  govde.addEventListener("click", detayAc);
  govde.addEventListener("keydown", detayAc);
  onceki.addEventListener("click", () => {
    offset = Math.max(0, offset - SAYFA_BOYU);
    yukle();
  });
  sonraki.addEventListener("click", () => {
    offset += SAYFA_BOYU;
    yukle();
  });

  yukle();
  return { yenile: () => yukle() };
}
