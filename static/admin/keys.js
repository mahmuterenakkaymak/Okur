// Anahtar yönetimi: the operator's registry of worker keys. The table lists
// identities only — the server never sends a key or a hash back — and a new
// key's plaintext lives exactly as long as this page holds it: the create
// dialog shows it once with a copy button, and closing forgets it. Key text
// reaches the page through textContent, never as markup.
const API = "/admin/api";

export function createAnahtarYonetimi() {
  const ekle = document.getElementById("anahtar-ekle");
  const hata = document.getElementById("anahtar-hata");
  const tablo = document.getElementById("anahtar-tablo");
  const sar = tablo.parentElement;
  const govde = tablo.querySelector("tbody");
  const bos = document.getElementById("anahtar-bos");

  const olustur = document.getElementById("anahtar-olustur");
  const form = document.getElementById("anahtar-olustur-formu");
  const calisan = document.getElementById("anahtar-calisan");
  const olusturHata = document.getElementById("anahtar-olustur-hata");
  const olusturDugme = document.getElementById("anahtar-olustur-dugme");

  const tek = document.getElementById("anahtar-tek");
  const tekCalisan = document.getElementById("anahtar-tek-calisan");
  const tekKutusu = document.getElementById("anahtar-duz");
  const kopyala = document.getElementById("anahtar-kopyala");
  const kopyaDurum = document.getElementById("anahtar-kopya-durum");

  let sira = 0; // a late answer from a superseded request must not draw
  let duzMetin = ""; // the one plaintext this page ever holds; "" once shown

  async function yukle() {
    const tur = ++sira;
    let vucut;
    try {
      const yanit = await fetch(`${API}/keys`);
      if (!yanit.ok) throw new Error(`HTTP ${yanit.status}`);
      vucut = await yanit.json();
    } catch {
      if (tur !== sira) return;
      sar.hidden = true;
      bos.hidden = true;
      hata.hidden = false;
      return;
    }
    if (tur !== sira) return; // a newer request already owns the screen
    hata.hidden = true;
    ciz(Array.isArray(vucut?.keys) ? vucut.keys : []);
  }

  function ciz(satirlar) {
    govde.textContent = "";
    for (const anahtar of satirlar) govde.appendChild(satirElemani(anahtar));
    sar.hidden = satirlar.length === 0;
    bos.hidden = satirlar.length > 0;
  }

  function satirElemani(anahtar) {
    const durum = document.createElement("span");
    durum.className = `etiket ${anahtar.revoked ? "etiket-kotu" : "etiket-iyi"}`;
    durum.textContent = anahtar.revoked ? "İptal edildi" : "Aktif";

    const tr = document.createElement("tr");
    const id = document.createElement("td");
    id.textContent = `#${anahtar.id}`;
    const calisanHucre = document.createElement("td");
    calisanHucre.textContent = anahtar.worker;
    const tarih = document.createElement("td");
    tarih.textContent = zaman(anahtar.created_at);
    const islem = document.createElement("td");
    islem.className = "saga";
    if (!anahtar.revoked) {
      const dugme = document.createElement("button");
      dugme.type = "button";
      dugme.className = "btn btn-mini btn-iptal";
      dugme.dataset.id = String(anahtar.id);
      dugme.textContent = "İptal et";
      dugme.title = `${anahtar.worker} — bu anahtarla gelen istekler 401 alır`;
      islem.appendChild(dugme);
    } else {
      islem.textContent = "—";
    }
    tr.append(id, calisanHucre, tarih, durum, islem);
    return tr;
  }

  function zaman(iso) {
    const an = new Date(iso);
    return Number.isNaN(an.getTime())
      ? "—"
      : an.toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" });
  }

  // --- create: ask for a label, show the plaintext once ---

  function olusturAc() {
    form.reset();
    olusturHata.hidden = true;
    olustur.showModal();
    calisan.focus();
  }

  form.addEventListener("submit", async (olay) => {
    olay.preventDefault();
    const ad = calisan.value.trim();
    if (!ad) {
      olusturHata.textContent = "Çalışan adını boş bırakma.";
      olusturHata.hidden = false;
      calisan.focus();
      return;
    }
    olusturDugme.disabled = true;
    olusturDugme.textContent = "Oluşturuluyor…";
    try {
      const yanit = await fetch(`${API}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ worker: ad }),
      });
      const vucut = await yanit.json().catch(() => null);
      if (!yanit.ok) {
        olusturHata.textContent =
          vucut?.error?.message ?? "Sunucuya ulaşılamadı — tekrar dene.";
        olusturHata.hidden = false;
        return;
      }
      olustur.close();
      tekGoster(vucut);
    } finally {
      olusturDugme.disabled = false;
      olusturDugme.textContent = "Oluştur";
    }
  });

  function tekGoster(vucut) {
    duzMetin = String(vucut?.key ?? "");
    tekCalisan.textContent = `Çalışan: ${vucut?.worker ?? ""} · anahtar #${vucut?.key_id ?? ""}`;
    tekKutusu.textContent = duzMetin;
    kopyaDurum.hidden = true;
    tek.showModal();
    kopyala.focus();
  }

  document.getElementById("anahtar-olustur-vazgec").addEventListener("click", () => olustur.close());

  kopyala.addEventListener("click", async () => {
    // The browser only lets a page copy when it is the active tab, so the
    // failure path is real: the box stays selectable and says what to do.
    let oldu = false;
    try {
      await navigator.clipboard.writeText(duzMetin);
      oldu = true;
    } catch {
      oldu = false;
    }
    kopyaDurum.textContent = oldu
      ? "Kopyalandı ✓"
      : "Kopyalanamadı — anahtarı kutudan seçip kopyala.";
    kopyaDurum.classList.toggle("kayit-iyi", oldu);
    kopyaDurum.classList.toggle("kayit-hata", !oldu);
    kopyaDurum.hidden = false;
  });

  tek.addEventListener("close", () => {
    // The promise is "shown once": drop the text the moment the dialog goes.
    duzMetin = "";
    tekKutusu.textContent = "";
    yukle();
  });
  document.getElementById("anahtar-kapat").addEventListener("click", () => tek.close());

  // --- revoke ---

  govde.addEventListener("click", async (olay) => {
    const dugme = olay.target.closest("button[data-id]");
    if (!dugme) return;
    dugme.disabled = true;
    dugme.textContent = "İptal ediliyor…";
    try {
      await fetch(`${API}/keys/${dugme.dataset.id}/revoke`, { method: "POST" });
    } catch {
      // the row below still says Aktif; the refresh re-reads the truth
    }
    yukle();
  });

  ekle.addEventListener("click", olusturAc);
  document.getElementById("anahtar-tekrar").addEventListener("click", () => yukle());

  yukle();
  return { yenile: () => yukle() };
}
