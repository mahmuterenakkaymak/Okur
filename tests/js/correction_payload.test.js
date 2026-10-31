import test from "node:test";
import assert from "node:assert/strict";
import { duzeltmeAlanlari } from "../../static/admin/detail.js";

// Kaydet sends whatever the reviewer corrected, and the server reads each value
// with the same Turkish-number parser the pipeline uses. That parser has to tell
// "1.046" (a thousands group) from "1.0464" (a decimal), so a dot-plus-three
// digits typed into a number box is the one shape it must never arrive in.

// A field as the dialog marks it: its contract path and how it is read.
function girdi(yol, bicim, deger) {
  return { dataset: { yol, bicim }, value: deger };
}

const SAYI = "sayi";
const METIN = "metin";

test("a 3-decimal quantity is the number typed, not a thousands group", () => {
  // The verified defect: "0.250" reached the parser as text and landed on 250,
  // so a kg correction was 1000x off and the validator recomputed over it.
  const alanlar = duzeltmeAlanlari([
    girdi("items[0].miktar", SAYI, "0.250"),
    girdi("items[1].miktar", SAYI, "12.500"),
  ]);
  assert.deepEqual(alanlar, { "items[0].miktar": 0.25, "items[1].miktar": 12.5 });
});

test("every number-shaped field leaves as a JSON number", () => {
  const alanlar = duzeltmeAlanlari([
    girdi("items[2].miktar", SAYI, "1.5"),
    girdi("items[2].birim_fiyat", SAYI, "99"),
    girdi("totals.kdv_orani", SAYI, "0.08"),
    girdi("totals.toplam", SAYI, "1046.40"),
  ]);
  for (const deger of Object.values(alanlar)) {
    assert.equal(typeof deger, "number");
    assert.ok(Number.isFinite(deger));
  }
  assert.equal(alanlar["totals.kdv_orani"], 0.08);
  assert.equal(alanlar["totals.toplam"], 1046.4);
});

test("a product name stays the trimmed text it was typed as", () => {
  const alanlar = duzeltmeAlanlari([
    girdi("items[0].ad", METIN, "  Finish Parlak 750 ml  "),
  ]);
  assert.deepEqual(alanlar, { "items[0].ad": "Finish Parlak 750 ml" });
});

test("the payload survives the wire with its paths and values intact", () => {
  const alanlar = duzeltmeAlanlari([
    girdi("items[1].toplam", SAYI, "25.000"),
    girdi("items[1].ad", METIN, "Benzin 95"),
    girdi("totals.iskonto", SAYI, "52.32"),
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify({ fields: alanlar })), {
    fields: { "items[1].toplam": 25, "items[1].ad": "Benzin 95", "totals.iskonto": 52.32 },
  });
});

test("no edited field means an empty body, never a stray zero", () => {
  assert.deepEqual(duzeltmeAlanlari([]), {});
});
