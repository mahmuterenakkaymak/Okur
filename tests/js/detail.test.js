import test from "node:test";
import assert from "node:assert/strict";
import { uyusmazlikModeli } from "../../static/admin/detail.js";

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
