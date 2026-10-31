const API = "/admin/api";
const BOLUM = { fisler: "bolum-fisler", anahtarlar: "bolum-anahtarlar", durum: "bolum-durum" };

const girisEkrani = document.getElementById("giris");
const girisFormu = document.getElementById("giris-formu");
const girisDugme = document.getElementById("giris-dugme");
const girisHata = document.getElementById("giris-hata");
const anahtarAlani = document.getElementById("yonetici-anahtari");
const panel = document.getElementById("panel");
const cikisDugme = document.getElementById("cikis-dugme");
const navDugmeleri = [...document.querySelectorAll(".nav-li")];

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
