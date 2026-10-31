// Durum sayfası: one live snapshot of the machine — the three model servers,
// VRAM and the open queue. Every value arrives through textContent, and a
// server that is down or a metric that cannot be measured shows as honest
// Turkish text, never as NaN, null or an empty cell.
const API = "/admin/api";

export const PENCERE_MS = 5 * 60 * 1000; // sparkline'ın geriye baktığı pencere
export const YENILEME_MS = 5000; // kendiliğinden tazeleme; sayfayı yeniden yüklemeye gerek yok

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

/** Açık kuyruk derinliği: sıradaki + işlenen; eksik yarılar 0 sayılır.
 *
 * ASSUMPTION: PLAN.md'deki "queue-depth" bitmemiş yığın olarak okunuyor,
 * bu yüzden işlenemedi kovucuğu sparkline'a girmiyor.
 */
export function kuyrukDerinligi(kuyruk) {
  const say = (deger) => (Number.isFinite(deger) ? deger : 0);
  return say(kuyruk?.queued) + say(kuyruk?.running);
}

/** Şu anın örneğini ekler, pencerenin dışına düşeni atar; girdiyi değiştirmez. */
export function ornekEkle(ornekler, simdi, derinlik) {
  return [...ornekler, { t: simdi, v: derinlik }].filter(
    (ornek) => ornek.t > simdi - PENCERE_MS,
  );
}

/** Her örneğin pencere içindeki [x, y] konumu; çizilecek bir şey yoksa null. */
export function sparklineNoktalar(ornekler, genislik, yukseklik, simdi) {
  if (!ornekler?.length) return null;
  const tepe = Math.max(1, ...ornekler.map((ornek) => ornek.v));
  return ornekler.map((ornek) => ({
    x: ((ornek.t - (simdi - PENCERE_MS)) / PENCERE_MS) * genislik,
    y: yukseklik - 1 - (ornek.v / tepe) * (yukseklik - 2),
  }));
}

/** %90'ı geçince ölçek kehribara döner: kartın yeri daralıyor. */
export function vramAmber(oranim) {
  return Number.isFinite(oranim) && oranim > 90;
}

function svgOge(ad, nitelikler) {
  const oge = document.createElementNS("http://www.w3.org/2000/svg", ad);
  for (const [anahtar, deger] of Object.entries(nitelikler)) {
    oge.setAttribute(anahtar, String(deger));
  }
  return oge;
}

export function createDurumIzleme() {
  const hata = document.getElementById("durum-hata");
  const bekleme = document.getElementById("durum-bekleme");
  const icerik = document.getElementById("durum-icerik");
  const servisler = document.getElementById("durum-servisler");
  const vramKutulari = document.getElementById("durum-vram");
  const kuyruk = document.getElementById("durum-kuyruk");
  const guncelleme = document.getElementById("durum-guncelleme");
  const sparkSar = document.getElementById("durum-kuyruk-spark");
  const durumBolumu = document.getElementById("bolum-durum");

  let sira = 0; // a late answer from a superseded request must not draw
  let ornekler = []; // son 5 dakikanın kuyruk derinliği örnekleri

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
    ornekler = ornekEkle(ornekler, Date.now(), kuyrukDerinligi((vucut ?? {}).queue));
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
    sparklineCiz();
    guncelleme.textContent = `Son ölçüm ${new Date().toLocaleTimeString("tr-TR")}`;
  }

  function sparklineCiz() {
    sparkSar.textContent = "";
    const noktalar = sparklineNoktalar(ornekler, 300, 44, Date.now());
    if (!noktalar) return;
    const cizgi = noktalar
      .map((nokta) => `${nokta.x.toFixed(1)},${nokta.y.toFixed(1)}`)
      .join(" ");
    const svg = svgOge("svg", {
      viewBox: "0 0 300 44",
      preserveAspectRatio: "none",
      class: "durum-spark",
      role: "img",
      "aria-label": "Son 5 dakikanın açık kuyruk derinliği grafiği",
    });
    const ilk = noktalar[0];
    const son = noktalar[noktalar.length - 1];
    svg.appendChild(
      svgOge("polygon", {
        class: "spark-alan",
        points: `${ilk.x.toFixed(1)},44 ${cizgi} ${son.x.toFixed(1)},44`,
      }),
    );
    svg.appendChild(svgOge("polyline", { class: "spark-cizgi", points: cizgi }));
    svg.appendChild(
      svgOge("circle", { class: "spark-son", cx: son.x, cy: son.y, r: 2.6 }),
    );
    sparkSar.appendChild(svg);
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
    const oranHam = (kullanilan / toplam) * 100;
    const oran = Math.min(100, Math.round(oranHam));
    const amber = vramAmber(oranHam);
    deger.textContent = `${mb(kullanilan)} / ${mb(toplam)} MB`;
    const not = document.createElement("p");
    not.className = "not";
    not.textContent = amber
      ? `Kartın %${oran}’ı dolu — yer daralıyor`
      : `Kartın %${oran}’ı dolu`;
    if (amber) not.classList.add("vram-not-amber");
    const dolum = document.createElement("span");
    dolum.className = amber ? "vram-dolum vram-amber" : "vram-dolum";
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

  // Live without a reload: the page refreshes itself while the Durum section
  // is on screen, and sleeps behind other tabs or a hidden window.
  setInterval(() => {
    if (document.hidden || durumBolumu.hidden) return;
    yukle();
  }, YENILEME_MS);

  yukle();
  return { yenile: () => yukle() };
}
