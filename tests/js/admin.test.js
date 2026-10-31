import test from "node:test";
import assert from "node:assert/strict";
import {
  disaAktarimUrl,
  filtreCipleri,
  klavyeEylemi,
  komstuSatir,
} from "../../static/admin/admin.js";

// The review desk's keyboard and filter model is pure; the screen it drives
// is list.js's table. So the tests here assert which action a keypress means
// and which filters are live, not how a pixel looks.

const acik = { panelAcik: true };

test("j and k walk the rows, e exports, / searches", () => {
  assert.equal(klavyeEylemi({ key: "j", ...acik }), "asagi");
  assert.equal(klavyeEylemi({ key: "k", ...acik }), "yukari");
  assert.equal(klavyeEylemi({ key: "e", ...acik }), "disaktar");
  assert.equal(klavyeEylemi({ key: "/", ...acik }), "arama");
  assert.equal(klavyeEylemi({ key: "x", ...acik }), null);
});

test("the shortcuts sleep behind the login screen and in the other sections", () => {
  assert.equal(klavyeEylemi({ key: "j" }), null, "logged out");
  assert.equal(klavyeEylemi({ key: "e", panelAcik: false }), null);
  for (const bolum of ["anahtarlar", "durum"]) {
    for (const key of ["j", "k", "e", "/"]) {
      assert.equal(klavyeEylemi({ key, ...acik, bolum }), null, `${bolum}: ${key}`);
    }
  }
});

test("a key typed into a field is text, never a shortcut", () => {
  for (const key of ["j", "k", "e", "/"]) {
    assert.equal(klavyeEylemi({ key, ...acik, yaziAlani: true }), null, key);
  }
});

test("modified keys belong to the browser", () => {
  for (const mod of ["ctrlKey", "metaKey", "altKey"]) {
    assert.equal(klavyeEylemi({ key: "e", ...acik, [mod]: true }), null);
    assert.equal(klavyeEylemi({ key: "/", ...acik, [mod]: true }), null);
  }
});

test("an open detail answers only Esc, and Esc answers even from a field", () => {
  const detay = { ...acik, detayAcik: true };
  assert.equal(klavyeEylemi({ key: "Escape", ...detay }), "kapat");
  assert.equal(klavyeEylemi({ key: "Escape", ...detay, yaziAlani: true }), "kapat");
  for (const key of ["j", "k", "e", "/"]) {
    assert.equal(klavyeEylemi({ key, ...detay }), null, key);
  }
  assert.equal(klavyeEylemi({ key: "Escape", ...acik }), null, "nothing open to close");
});

test("j enters the first row with nothing selected, k the last, and the ends hold", () => {
  assert.equal(komstuSatir(-1, 1, 10), 0);
  assert.equal(komstuSatir(-1, -1, 10), 9);
  assert.equal(komstuSatir(4, 1, 10), 5);
  assert.equal(komstuSatir(4, -1, 10), 3);
  assert.equal(komstuSatir(0, -1, 10), 0, "no wrapping past the top");
  assert.equal(komstuSatir(9, 1, 10), 9, "no wrapping past the bottom");
  assert.equal(komstuSatir(0, 1, 0), -1, "an empty table has no row to land on");
});

test("no filter means no chips", () => {
  assert.deepEqual(
    filtreCipleri({ q: "", status: "", worker: "", date_from: "", date_to: "" }),
    [],
  );
});

test("every live filter gets a chip that names it in Turkish", () => {
  assert.deepEqual(
    filtreCipleri({
      q: "şok",
      status: "done",
      worker: "ayşe",
      date_from: "2026-10-01",
      date_to: "2026-10-31",
    }),
    [
      { alan: "q", etiket: "Arama: şok" },
      { alan: "status", etiket: "Durum: Bitti" },
      { alan: "worker", etiket: "Çalışan: ayşe" },
      { alan: "date_from", etiket: "Başlangıç: 2026-10-01" },
      { alan: "date_to", etiket: "Bitiş: 2026-10-31" },
    ],
  );
});

test("a status the list has never heard of still gets a chip, not undefined", () => {
  const [cip] = filtreCipleri({ status: "iptal" });
  assert.equal(cip.etiket, "Durum: iptal");
});

test("export carries the filters the endpoint understands", () => {
  assert.equal(
    disaAktarimUrl({ q: "", status: "", worker: "", date_from: "", date_to: "" }),
    "/admin/api/export?format=csv",
  );
  const url = new URL(
    disaAktarimUrl(
      { q: "şok", status: "done", worker: "ayşe", date_from: "2026-10-01", date_to: "2026-10-31" },
      "xlsx",
    ),
    "http://yerel",
  );
  assert.equal(url.pathname, "/admin/api/export");
  assert.deepEqual(
    [...url.searchParams.entries()],
    [
      ["format", "xlsx"],
      ["worker", "ayşe"],
      ["since", "2026-10-01"],
    ],
  );
});
