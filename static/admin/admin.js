import { createFisDetay } from "./detail.js";
import { DURUM, createFisListesi } from "./list.js";
import { createAnahtarYonetimi } from "./keys.js";
import { createDurumIzleme } from "./status.js";

const API = "/admin/api";
const BOLUM = { fisler: "bolum-fisler", anahtarlar: "bolum-anahtarlar", durum: "bolum-durum" };

// --- the review desk's model, kept DOM-free so node --test can drive it ---

/** Which action a keypress means for the list screen, or null for none.
 *
 * ASSUMPTION: inline editing with validation before save already lives in
 * detail.js (T37); this layer adds the keyboard access to that desk, and a
 * shortcut must never steal a key from a field being typed into.
 */
export function klavyeEylemi({
  key,
  ctrlKey = false,
  metaKey = false,
  altKey = false,
  yaziAlani = false,
  panelAcik = false,
  bolum = "fisler",
  detayAcik = false,
}) {
  if (detayAcik) return key === "Escape" ? "kapat" : null;
  if (!panelAcik || ctrlKey || metaKey || altKey || yaziAlani) return null;
  if (bolum !== "fisler") return null;
  if (key === "j") return "asagi";
  if (key === "k") return "yukari";
  if (key === "e") return "disaktar";
  if (key === "/") return "arama";
  return null;
}

/** The row j/k lands on: with nothing selected j enters the first row and
 * k the last, and the ends hold instead of wrapping. */
export function komstuSatir(index, yon, adet) {
  if (adet <= 0) return -1;
  if (index < 0) return yon > 0 ? 0 : adet - 1;
  return Math.min(adet - 1, Math.max(0, index + yon));
}

/** The active filters as removable chips, in the order the form shows them. */
export function filtreCipleri(filtre) {
  const cipler = [];
  if (filtre.q) cipler.push({ alan: "q", etiket: `Arama: ${filtre.q}` });
  if (filtre.status)
    cipler.push({ alan: "status", etiket: `Durum: ${DURUM[filtre.status] || filtre.status}` });
  if (filtre.worker) cipler.push({ alan: "worker", etiket: `Çalışan: ${filtre.worker}` });
  if (filtre.date_from) cipler.push({ alan: "date_from", etiket: `Başlangıç: ${filtre.date_from}` });
  if (filtre.date_to) cipler.push({ alan: "date_to", etiket: `Bitiş: ${filtre.date_to}` });
  return cipler;
}

/** The export URL for the current view.
 *
 * ASSUMPTION: the export endpoint narrows by worker and since, so those two
 * filters alone carry into the file; status, end date and search stay on
 * screen.
 */
export function disaAktarimUrl(filtre, format = "csv") {
  const parametreler = new URLSearchParams({ format });
  if (filtre.worker) parametreler.set("worker", filtre.worker);
  if (filtre.date_from) parametreler.set("since", filtre.date_from);
  return `${API}/export?${parametreler}`;
}

function kur() {
  const girisEkrani = document.getElementById("giris");
  const girisFormu = document.getElementById("giris-formu");
  const girisDugme = document.getElementById("giris-dugme");
  const girisHata = document.getElementById("giris-hata");
  const anahtarAlani = document.getElementById("yonetici-anahtari");
  const panel = document.getElementById("panel");
  const cikisDugme = document.getElementById("cikis-dugme");
  const navDugmeleri = [...document.querySelectorAll(".nav-li")];
  const detayDialog = document.getElementById("fis-detay");
  const araAlani = document.getElementById("fis-ara");
  const cipSar = document.getElementById("fis-cipler");
  const disaAktarDugme = document.getElementById("fis-disaktar");
  const disaAktarDurum = document.getElementById("fis-disaktar-durum");
  let fisListesi = null;
  let anahtarlar = null;
  let durumIzleme = null;
  // A corrected amount moves the list row underneath the dialog, so a save
  // refreshes it instead of leaving the table showing the old total.
  const detay = createFisDetay({ onDuzeltme: () => fisListesi?.yenile() });

  function hataGoster(metin) {
    girisHata.textContent = metin;
    girisHata.hidden = false;
    girisFormu.classList.remove("sallanma");
    void girisFormu.offsetWidth; // restart the shake on a repeated failure
    girisFormu.classList.add("sallanma");
    anahtarAlani.focus();
    anahtarAlani.select();
  }

  function paneliGoster() {
    girisEkrani.hidden = true;
    panel.hidden = false;
    bolumuGoster(gecerliBolum(location.hash));
  }

  function giriseDon() {
    detay.kapat(); // a receipt must not stay open over the login screen
    panel.hidden = true;
    girisEkrani.hidden = false;
    girisHata.hidden = true;
    anahtarAlani.value = "";
    anahtarAlani.focus();
  }

  function gecerliBolum(hash) {
    const ad = decodeURIComponent(hash || "").replace("#/", "");
    return ad in BOLUM ? ad : "fisler";
  }

  function bolumuGoster(ad) {
    for (const [bolum, id] of Object.entries(BOLUM)) {
      document.getElementById(id).hidden = bolum !== ad;
    }
    for (const dugme of navDugmeleri) {
      const secili = dugme.dataset.bolum === ad;
      dugme.classList.toggle("secili", secili);
      dugme.setAttribute("aria-current", secili ? "page" : "false");
    }
    // The table only exists behind a session, so an anonymous hash change must
    // not ask for it; the first real look builds it, later ones refresh in place.
    if (ad === "fisler" && !panel.hidden) {
      if (fisListesi) fisListesi.yenile();
      else fisListesi = createFisListesi({ acis: detay.ac });
    }
    if (ad === "anahtarlar" && !panel.hidden) {
      if (anahtarlar) anahtarlar.yenile();
      else anahtarlar = createAnahtarYonetimi();
    }
    if (ad === "durum" && !panel.hidden) {
      if (durumIzleme) durumIzleme.yenile();
      else durumIzleme = createDurumIzleme();
    }
  }

  async function girisYap(anahtar) {
    const yanit = await fetch(`${API}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: anahtar }),
    });
    if (yanit.ok) {
      paneliGoster();
      return;
    }
    if (yanit.status === 503) {
      hataGoster("Sunucuda ADMIN_TOKEN tanımlı değil — sunucu yöneticinden iste.");
      return;
    }
    hataGoster("Anahtar geçersiz, tekrar dene.");
  }

  girisFormu.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const anahtar = anahtarAlani.value.trim();
    if (!anahtar) {
      hataGoster("Yönetici anahtarını boş bırakma.");
      return;
    }
    girisDugme.disabled = true;
    girisDugme.textContent = "Giriş yapılıyor…";
    girisHata.hidden = true;
    try {
      await girisYap(anahtar);
    } catch {
      hataGoster("Sunucuya ulaşılamadı — bağlantını kontrol et.");
    } finally {
      girisDugme.disabled = false;
      girisDugme.textContent = "Giriş yap";
    }
  });

  cikisDugme.addEventListener("click", async () => {
    cikisDugme.disabled = true;
    try {
      await fetch(`${API}/logout`, { method: "POST" });
    } catch {
      // the cookie is useless either way: the page drops straight to login
    } finally {
      cikisDugme.disabled = false;
      giriseDon();
    }
  });

  for (const dugme of navDugmeleri) {
    dugme.addEventListener("click", () => {
      location.hash = `#/${dugme.dataset.bolum}`;
    });
  }
  addEventListener("hashchange", () => bolumuGoster(gecerliBolum(location.hash)));

  // --- the review desk: filter chips, row selection, shortcuts ------------

  const filtreFormu = document.getElementById("fis-filtreler");
  const CIP_KONTROL = {
    q: () => araAlani,
    status: () => document.getElementById("fis-durum"),
    worker: () => document.getElementById("fis-calisan"),
    date_from: () => document.getElementById("fis-baslangic"),
    date_to: () => document.getElementById("fis-bitis"),
  };

  function filtreDegerleri() {
    return {
      q: araAlani.value.trim(),
      status: CIP_KONTROL.status().value,
      worker: CIP_KONTROL.worker().value,
      date_from: CIP_KONTROL.date_from().value,
      date_to: CIP_KONTROL.date_to().value,
    };
  }

  function cipleriCiz() {
    cipSar.textContent = "";
    const cipler = filtreCipleri(filtreDegerleri());
    cipSar.hidden = cipler.length === 0;
    for (const cip of cipler) {
      const etiket = document.createElement("span");
      etiket.className = "cip";
      etiket.append(cip.etiket);
      const sil = document.createElement("button");
      sil.type = "button";
      sil.className = "cip-sil";
      sil.textContent = "×";
      sil.setAttribute("aria-label", `Filtreyi kaldır: ${cip.etiket}`);
      sil.addEventListener("click", () => {
        const kontrol = CIP_KONTROL[cip.alan]();
        kontrol.value = "";
        // list.js reloads on the control's own event: a search on input
        // (debounced), every other filter on change.
        kontrol.dispatchEvent(
          new Event(cip.alan === "q" ? "input" : "change", { bubbles: true }),
        );
      });
      etiket.appendChild(sil);
      cipSar.appendChild(etiket);
    }
  }

  filtreFormu.addEventListener("change", cipleriCiz);
  araAlani.addEventListener("input", cipleriCiz);
  // "Filtreleri temizle" resets the form without firing an event; the
  // microtask runs after list.js's own click handler has emptied the controls.
  document.getElementById("fis-temizle").addEventListener("click", () => {
    queueMicrotask(cipleriCiz);
  });

  function disaAktar() {
    location.assign(disaAktarimUrl(filtreDegerleri()));
    disaAktarDurum.textContent = "Dışa aktarma yolda — indirilen dosyayı kontrol et.";
    disaAktarDurum.hidden = false;
  }
  disaAktarDugme.addEventListener("click", disaAktar);

  function satirHareket(yon) {
    const satirlar = [...document.querySelectorAll("#fis-tablo tbody tr[data-job]")];
    const mevcut = satirlar.findIndex((tr) =>
      tr.classList.contains("secili-satir"),
    );
    const hedef = komstuSatir(mevcut, yon, satirlar.length);
    if (hedef < 0) return;
    satirlar.forEach((tr, i) => tr.classList.toggle("secili-satir", i === hedef));
    satirlar[hedef].focus({ preventScroll: true });
    satirlar[hedef].scrollIntoView({ block: "nearest" });
  }

  function yaziAlaniMi(hedef) {
    return (
      !!hedef &&
      (hedef.isContentEditable ||
        (typeof hedef.matches === "function" &&
          hedef.matches("input, textarea, select")))
    );
  }

  document.addEventListener("keydown", (olay) => {
    const eylem = klavyeEylemi({
      key: olay.key,
      ctrlKey: olay.ctrlKey,
      metaKey: olay.metaKey,
      altKey: olay.altKey,
      yaziAlani: yaziAlaniMi(olay.target),
      panelAcik: !panel.hidden,
      bolum: gecerliBolum(location.hash),
      detayAcik: detayDialog.open,
    });
    if (!eylem) return;
    olay.preventDefault();
    if (eylem === "kapat") detay.kapat();
    else if (eylem === "arama") {
      araAlani.focus();
      araAlani.select();
    } else if (eylem === "disaktar") disaAktar();
    else satirHareket(eylem === "asagi" ? 1 : -1);
  });

  async function basla() {
    let girisVar = false;
    try {
      girisVar = (await fetch(`${API}/session`)).ok;
    } catch {
      hataGoster("Sunucuya ulaşılamadı — bağlantını kontrol et.");
      return;
    }
    if (girisVar) paneliGoster();
    else anahtarAlani.focus();
  }
  basla();
}

// The page runs this file as its entry module; node --test imports the
// pure model above, where there is no document to wire.
if (typeof document !== "undefined") kur();
