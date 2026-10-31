// D6 mutation toasts: every mutation in the admin panel answers with a
// slide-in confirmation, and the one thing the operator must not lose — a key
// shown once — gets a copy button that stays until used. The wording model is
// pure (node --test drives it); the DOM layer below only paints what it says.
//
// ASSUMPTION: the key toast appears when the shown-once dialog closes, not at
// creation — a modal dialog dims everything behind it, so a toast born beside
// the dialog would be invisible until it was already too late to read.

export const KALMA_MS = 4200;
export const HATA_KALMA_MS = 8400; // a failure deserves a longer read
const CIKIS_MS = 240; // matches the toast-cikis animation
const KOPYA_KAPAMA_MS = 1400; // copied: a beat to see the ✓, then away

const TURLAR = {
  kaydet: (veri) => ({
    metin: veri.alan
      ? `Kaydedildi ✓ ${Number(veri.alan)} alan düzeltildi.`
      : "Kaydedildi ✓",
    ton: "iyi",
    kopyala: "",
    ozKapanir: true,
  }),
  disaktar: () => ({
    metin: "Dışa aktarma yolda — indirilen dosyayı kontrol et.",
    ton: "iyi",
    kopyala: "",
    ozKapanir: true,
  }),
  anahtar: (veri) => ({
    metin: "Anahtar oluşturuldu — bir daha gösterilmeyecek.",
    ton: "iyi",
    kopyala: String(veri.anahtar ?? ""),
    ozKapanir: false, // it must outlive the hand reaching for the mouse
  }),
  hata: (veri) => ({
    metin: String(veri.metin ?? "").trim() || "İşlem yapılamadı — tekrar dene.",
    ton: "hata",
    kopyala: "",
    ozKapanir: true,
  }),
};

/** What a mutation's toast says: { metin, ton iyi|hata, kopyala, ozKapanir }. */
export function toastBilgisi(tur, veri = {}) {
  const kur = TURLAR[tur] || TURLAR.hata;
  return kur(veri || {});
}

let sar = null;

// A modal <dialog> sits in the browser's top layer and covers the page, so
// the tray lives inside the open dialog when there is one and on the body
// otherwise — a toast that slides in behind a backdrop is a toast unheard.
function kapsayici() {
  const kap = document.querySelector("dialog[open]") || document.body;
  if (!sar) {
    sar = document.createElement("div");
    sar.className = "toasts";
    sar.setAttribute("aria-live", "polite");
  }
  if (sar.parentElement !== kap) kap.appendChild(sar);
  return sar;
}

export function bildir(tur, veri) {
  const bilgi = toastBilgisi(tur, veri);
  const toast = document.createElement("div");
  toast.className = `toast toast-${bilgi.ton}`;
  toast.setAttribute("role", bilgi.ton === "hata" ? "alert" : "status");

  const metin = document.createElement("p");
  metin.className = "toast-metin";
  metin.textContent = bilgi.metin;
  toast.appendChild(metin);

  let otur = 0;
  let kapandi = false;
  const kapat = () => {
    if (kapandi) return;
    kapandi = true;
    clearTimeout(otur);
    toast.classList.add("toast-cikiyor");
    setTimeout(() => toast.remove(), CIKIS_MS);
  };

  if (bilgi.kopyala) {
    const dugme = document.createElement("button");
    dugme.type = "button";
    dugme.className = "btn btn-mini toast-dugme";
    dugme.textContent = "Kopyala";
    dugme.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(bilgi.kopyala);
        dugme.textContent = "Kopyalandı ✓";
        dugme.disabled = true;
        setTimeout(kapat, KOPYA_KAPAMA_MS);
      } catch {
        dugme.textContent = "Kopyalanamadı";
      }
    });
    toast.appendChild(dugme);
  }

  const capat = document.createElement("button");
  capat.type = "button";
  capat.className = "toast-capat";
  capat.textContent = "×";
  capat.setAttribute("aria-label", "Bildirimi kapat");
  capat.addEventListener("click", kapat);
  toast.appendChild(capat);

  kapsayici().appendChild(toast);
  if (bilgi.ozKapanir) {
    otur = setTimeout(kapat, bilgi.ton === "hata" ? HATA_KALMA_MS : KALMA_MS);
  }
}
