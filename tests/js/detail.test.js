import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { uyusmazlikModeli } from "../../static/admin/detail.js";
import { asamaSureleri } from "../../static/admin/detail.js";

// The discrepancy panel is the reviewer's only sight of the validator's
// arithmetic, so its rows are checked against real validation blocks (contract
// shape 3) here instead of against a screen.

test("the offending total is the row that stands out, and the fark is signed", () => {
  const model = uyusmazlikModeli({
    verdict: "mismatch",
    expected: { ara_toplam: 1046.4, iskonto: 52.32, kdv: 198.82, toplam: 1197.9 },
    actual: { ara_toplam: 1046.4, iskonto: 52.32, kdv: 198.82, toplam: 1192.9 },
    fields: ["totals.toplam"],
  });
  assert.equal(model.verdict, "mismatch");
  assert.deepEqual(
    model.satirlar.map((satir) => satir.alan),
    ["ara_toplam", "iskonto", "kdv", "toplam"],
  );
  const toplam = model.satirlar.at(-1);
  assert.equal(toplam.uyusmaz, true);
  assert.equal(toplam.fark, -5);
  assert.deepEqual(
    model.satirlar.filter((satir) => satir.uyusmaz).map((satir) => satir.alan),
    ["toplam"],
  );
});

test("a discount printed as 52,32- is the same 52,32 discount", () => {
  // The validator takes abs() of a printed "52,32-", so the panel must not
  // invent a 104,64 difference out of the two signs of one discount.
  const model = uyusmazlikModeli({
    verdict: "mismatch",
    expected: { iskonto: 52.32 },
    actual: { iskonto: -52.32 },
    fields: ["totals.toplam"],
  });
  const iskonto = model.satirlar.find((satir) => satir.alan === "iskonto");
  assert.deepEqual(
    [iskonto.beklenen, iskonto.fiilde, iskonto.fark],
    [52.32, 52.32, 0],
  );
  assert.equal(iskonto.uyusmaz, false);
});

test("an offending product line is named by its row, counted the way a person counts", () => {
  const model = uyusmazlikModeli({
    verdict: "mismatch",
    fields: ["items[2].toplam", "items[0].miktar", "totals.kdv"],
  });
  assert.deepEqual(model.urunler, [
    { sira: 3, alan: "toplam" },
    { sira: 1, alan: "miktar" },
  ]);
  assert.equal(model.satirlar.find((satir) => satir.alan === "kdv").uyusmaz, true);
});

test("a clean receipt marks nothing, an absent block is unreadable and never NaN", () => {
  const temiz = uyusmazlikModeli({
    verdict: "ok",
    expected: { ara_toplam: 30, iskonto: 0, kdv: 6, toplam: 36 },
    actual: { ara_toplam: 30, iskonto: 0, kdv: 6, toplam: 36 },
    fields: [],
  });
  assert.deepEqual(temiz.satirlar.map((satir) => satir.uyusmaz), [
    false,
    false,
    false,
    false,
  ]);
  assert.deepEqual(temiz.satirlar.map((satir) => satir.fark), [0, 0, 0, 0]);

  for (const eksik of [null, undefined, {}, { verdict: "unreadable" }]) {
    const model = uyusmazlikModeli(eksik);
    assert.equal(model.verdict, "unreadable");
    assert.deepEqual(model.urunler, []);
    for (const satir of model.satirlar) {
      for (const deger of [satir.beklenen, satir.fiilde, satir.fark]) {
        assert.ok(Number.isFinite(deger), `${satir.alan}: ${deger}`);
      }
    }
  }
});

// --- aşama süreleri (the timings line) -------------------------------------
//
// An operator opens a finished job for one thing: where the time went. So the
// line is checked as the exact string the panel paints into #detay-asama, from
// the same meta.stage_ms the contract carries.

test("the three stage timings read the way an operator says them", () => {
  assert.equal(
    asamaSureleri({
      job_id: "4b7c",
      stage_ms: { ocr: 900, structure: 30600, validate: 1 },
    }),
    "Aşama süreleri — Okuma 0,9 sn · Yapılandırma 30,6 sn · Doğrulama 1 ms",
  );
});

test("a duration switches to seconds with a Turkish comma, ms stays ms", () => {
  const okuma = (ms) =>
    asamaSureleri({ stage_ms: { ocr: ms, structure: 0, validate: 0 } });
  // Below a tenth of a second a millisecond count is the unit a person reads.
  assert.equal(okuma(1), "Aşama süreleri — Okuma 1 ms · Yapılandırma — · Doğrulama —");
  assert.equal(okuma(42), "Aşama süreleri — Okuma 42 ms · Yapılandırma — · Doğrulama —");
  // A tenth of a second and above is said in seconds, comma and all — and
  // every value ≥1000 ms is therefore seconds.
  assert.equal(okuma(100), "Aşama süreleri — Okuma 0,1 sn · Yapılandırma — · Doğrulama —");
  assert.equal(okuma(1000), "Aşama süreleri — Okuma 1 sn · Yapılandırma — · Doğrulama —");
  assert.equal(okuma(1234), "Aşama süreleri — Okuma 1,2 sn · Yapılandırma — · Doğrulama —");
  assert.equal(okuma(65000), "Aşama süreleri — Okuma 65 sn · Yapılandırma — · Doğrulama —");
});

test("a job that never ran is a dash, and so is a stage that never ran", () => {
  // 0 is the contract's "no measurement" (missing key, junk, a stage that did
  // not run), never an instant stage — so nothing here may print "0 ms".
  for (const meta of [
    undefined,
    null,
    {},
    { stage_ms: null },
    { stage_ms: {} },
    { stage_ms: { ocr: 0, structure: 0, validate: 0 } },
    { stage_ms: { ocr: "junk", structure: null, validate: NaN } },
  ]) {
    assert.equal(asamaSureleri(meta), "Aşama süreleri —");
  }
  // A half-measured job still says what it knows and dashes the rest.
  assert.equal(
    asamaSureleri({ stage_ms: { ocr: 900, structure: 0, validate: 1 } }),
    "Aşama süreleri — Okuma 0,9 sn · Yapılandırma — · Doğrulama 1 ms",
  );
});

test("painting the line leaves the raw integers the JSON panel prints alone", () => {
  const meta = { worker: "Ayşe", stage_ms: { ocr: 900, structure: 30600, validate: 1 } };
  asamaSureleri(meta);
  assert.deepEqual(meta, {
    worker: "Ayşe",
    stage_ms: { ocr: 900, structure: 30600, validate: 1 },
  });
  for (const ms of Object.values(JSON.parse(JSON.stringify(meta)).stage_ms)) {
    assert.ok(Number.isInteger(ms), String(ms));
  }
});

// The other half of the task is the line fitting a phone: it is the header's
// longest string, so it has to wrap instead of pushing the dialog past 360 px.

const detayHtml = readFileSync(new URL("../../static/admin/index.html", import.meta.url), "utf8");
const detayCss = readFileSync(new URL("../../static/admin/style.css", import.meta.url), "utf8");
const detaySrc = readFileSync(new URL("../../static/admin/detail.js", import.meta.url), "utf8");

test("the timings line is on the page, hidden until a job paints it", () => {
  assert.match(detayHtml, /<p class="not" id="detay-asama" hidden><\/p>/);
  assert.ok(detaySrc.includes('document.getElementById("detay-asama")'));
  assert.match(detaySrc, /asama\.textContent = asamaSureleri\(env\.meta\)/);
  assert.match(detaySrc, /asama\.hidden = false/);
  // Opening another receipt must not leave the previous job's timings up.
  assert.match(detaySrc, /asama\.hidden = true/);
});

test("the timings line wraps on a phone instead of overflowing it", () => {
  assert.match(detayCss, /\.detay-kimlik \.not \{[^}]*overflow-wrap: anywhere/);
  const kisik = detayCss.slice(detayCss.indexOf('@media (max-width: 30rem)'));
  assert.match(kisik, /\.detay-ust \{ flex-wrap: wrap/);
  assert.match(kisik, /\.detay-kimlik \{ flex: 1 1 100%/);
});
