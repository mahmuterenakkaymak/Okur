// Durum sayfası: one live snapshot of the machine — the three model servers,
// VRAM and the open queue. Every value arrives through textContent, and a
// server that is down or a metric that cannot be measured shows as honest
// Turkish text, never as NaN, null or an empty cell.
const API = "/admin/api";

const SERVISLER = [
  { anahtar: "ocr", ad: "OCR", rol: "fiş okuma — aşama 1" },
  { anahtar: "strata", ad: "Strata", rol: "yapılandırma — aşama 2" },
  { anahtar: "unsloth", ad: "Unsloth", rol: "kalite modu" },
];
const KUYRUK = [
  { anahtar: "queued", ad: "Sırada" },
  { anahtar: "running", ad: "İşleniyor" },
  { anahtar: "failed", ad: "İşlenemedi", kotu: true },
];

export function createDurumIzleme() {
  const hata = document.getElementById("durum-hata");
  const bekleme = document.getElementById("durum-bekleme");
  const icerik = document.getElementById("durum-icerik");
  const servisler = document.getElementById("durum-servisler");
  const vramKutulari = document.getElementById("durum-vram");
  const kuyruk = document.getElementById("durum-kuyruk");
  const guncelleme = document.getElementById("durum-guncelleme");

  let sira = 0; // a late answer from a superseded request must not draw

  async function yukle() {
    const tur = ++sira;
    let vucut;
    try {
      const yanit = await fetch(`${API}/status`);
      if (!yanit.ok) throw new Error(`HTTP ${yanit.status}`);
      vucut = await yanit.json();
    } catch {
      if (tur !== sira) return;
      icerik.hidden = true;
      bekleme.hidden = true;
      hata.hidden = false;
      return;
    }
    if (tur !== sira) return; // a newer request already owns the screen
    hata.hidden = true;
    ciz(vucut ?? {});
    bekleme.hidden = true;
    icerik.hidden = false;
  }

  function ciz(vucut) {
    servisler.textContent = "";
    for (const servis of SERVISLER) {
      servisler.appendChild(servisKarti(servis, vucut[servis.anahtar]));
    }
    vramKutulari.textContent = "";
    vramKutulari.appendChild(vramKarti(vucut.vram));
    kuyruk.textContent = "";
    for (const bolum of KUYRUK) {
      kuyruk.appendChild(kuyrukKarti(bolum, (vucut.queue ?? {})[bolum.anahtar]));
    }
    guncelleme.textContent = `Son ölçüm ${new Date().toLocaleTimeString("tr-TR")}`;
  }

  function servisKarti(servis, durum) {
    const calisiyor = durum?.ok === true;
    const etiket = document.createElement("span");
    etiket.className = `etiket ${calisiyor ? "etiket-iyi" : "etiket-kotu"}`;
    const ms = Number.isFinite(durum?.latency_ms) ? durum.latency_ms : null;
    etiket.textContent = calisiyor
      ? ms === null
        ? "Çalışıyor"
        : `Çalışıyor · ${ms} ms`
      : "Erişilemiyor";
    return kart(servis.ad, servis.rol, etiket);
  }

  function vramKarti(vram) {
    const kullanilan = Number(vram?.used_mb);
    const toplam = Number(vram?.total_mb);
    const olculebilir =
      vram?.ok === true &&
      Number.isFinite(kullanilan) &&
      Number.isFinite(toplam) &&
      toplam > 0;
    const deger = document.createElement("p");
    deger.className = "durum-deger";
    if (!olculebilir) {
      deger.textContent = "Ölçülemedi";
      const not = document.createElement("p");
      not.className = "not";
      not.textContent = "nvidia-smi bu makinede yanıt vermiyor.";
      return kart("VRAM", deger, not);
    }
    const oran = Math.min(100, Math.round((kullanilan / toplam) * 100));
    deger.textContent = `${mb(kullanilan)} / ${mb(toplam)} MB`;
    const not = document.createElement("p");
    not.className = "not";
    not.textContent = `Kartın %${oran}’ı dolu`;
    const dolum = document.createElement("span");
    dolum.className = "vram-dolum";
    dolum.style.width = `${oran}%`;
    const olcek = document.createElement("div");
    olcek.className = "vram-olcek";
    olcek.appendChild(dolum);
    return kart("VRAM", deger, not, olcek);
  }

  function kuyrukKarti(bolum, adet) {
    const sayi = Number.isFinite(adet) ? adet : 0;
    const deger = document.createElement("p");
    deger.className = "durum-deger";
    deger.textContent = String(sayi);
    if (bolum.kotu && sayi > 0) deger.classList.add("sayi-kotu");
    return kart(bolum.ad, deger);
  }

  function kart(ad, ...parcalar) {
    const g = document.createElement("div");
    g.className = "durum-kart";
    const baslik = document.createElement("h3");
    baslik.textContent = ad;
    g.appendChild(baslik);
    for (const parca of parcalar) {
      if (typeof parca === "string") {
        const not = document.createElement("p");
        not.className = "not";
        not.textContent = parca;
        g.appendChild(not);
      } else {
        g.appendChild(parca);
      }
    }
    return g;
  }

  function mb(megabayt) {
    return new Intl.NumberFormat("tr-TR").format(megabayt);
  }

  document.getElementById("durum-yenile").addEventListener("click", () => yukle());
  document.getElementById("durum-tekrar").addEventListener("click", () => yukle());

  yukle();
  return { yenile: () => yukle() };
}
