import test from "node:test";
import assert from "node:assert/strict";
import {
  HATA_KALMA_MS,
  KALMA_MS,
  toastBilgisi,
} from "../../static/admin/toasts.js";

// D6 promises a slide-in confirmation for every mutation. The wording model
// is what the browser paints verbatim, so it is checked here: what each
// mutation says, which one carries the copy action, and that a missing value
// never reaches the screen as undefined.

test("a save confirms in Turkish and counts the corrected fields", () => {
  const b = toastBilgisi("kaydet", { alan: 3 });
  assert.equal(b.metin, "Kaydedildi ✓ 3 alan düzeltildi.");
  assert.equal(b.ton, "iyi");
  assert.equal(b.ozKapanir, true);
  assert.equal(b.kopyala, "", "there is nothing to copy from a save");
});

test("a save with no count still says the plain yes", () => {
  assert.equal(toastBilgisi("kaydet").metin, "Kaydedildi ✓");
});

test("export points at the download instead of the screen", () => {
  const b = toastBilgisi("disaktar");
  assert.match(b.metin, /^Dışa aktarma/);
  assert.match(b.metin, /indirilen dosyayı kontrol et/);
  assert.equal(b.ton, "iyi");
  assert.equal(b.ozKapanir, true);
});

test("the key toast repeats the shown-once promise and carries the copy", () => {
  const b = toastBilgisi("anahtar", { anahtar: "ocrk_abc123" });
  assert.equal(b.metin, "Anahtar oluşturuldu — bir daha gösterilmeyecek.");
  assert.equal(b.kopyala, "ocrk_abc123");
  assert.equal(b.ozKapanir, false, "a toast still worth copying from does not run away");
});

test("a key that never arrived leaves no copy action and no undefined", () => {
  for (const veri of [undefined, null, {}, { anahtar: null }]) {
    assert.equal(toastBilgisi("anahtar", veri).kopyala, "");
  }
});

test("the error variant keeps its own tone and its own words", () => {
  const b = toastBilgisi("hata", { metin: "Kaydedilemedi — bağlantıyı kontrol et." });
  assert.equal(b.ton, "hata");
  assert.equal(b.metin, "Kaydedilemedi — bağlantıyı kontrol et.");
  assert.equal(b.ozKapanir, true);
});

test("an error with nothing to say still says something, never undefined", () => {
  for (const veri of [undefined, null, {}, { metin: "   " }, { metin: null }]) {
    const b = toastBilgisi("hata", veri);
    assert.ok(b.metin.trim().length > 0, JSON.stringify(veri));
    assert.ok(!b.metin.includes("undefined"));
  }
});

test("every toast reads: non-empty text, a known tone, a copy flag", () => {
  for (const tur of ["kaydet", "disaktar", "anahtar", "hata"]) {
    const b = toastBilgisi(tur);
    assert.ok(b.metin.trim().length > 0, tur);
    assert.ok(["iyi", "hata"].includes(b.ton), `${tur}: ${b.ton}`);
    assert.equal(typeof b.kopyala, "string", tur);
    assert.equal(typeof b.ozKapanir, "boolean", tur);
  }
});

test("a failure stays on screen longer than a confirmation", () => {
  assert.ok(KALMA_MS > 0);
  assert.ok(HATA_KALMA_MS > KALMA_MS);
});
