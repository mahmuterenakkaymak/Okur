import test from "node:test";
import assert from "node:assert/strict";
import { iskontoPara, para, sayi } from "../../static/app/result_totals.js";

// The result view writes these strings straight into the totals row, so every
// case below is a line a field worker actually reads.

// --- Turkish money ---

test("amounts print with Turkish separators and two decimals", () => {
  assert.equal(para(1046.4), "1.046,40");
  assert.equal(para(0), "0,00");
  assert.equal(para(1 / 3), "0,33", "a kuruş is the smallest thing a receipt has");
});

test("a negative amount carries exactly one minus, in the typographic glyph", () => {
  assert.equal(para(-52.32), "−52,32");
  assert.doesNotMatch(para(-52.32), /[-−]{2}/, "the old code wrote −-52,32");
  assert.doesNotMatch(para(-52.32), /-/u, "one sign, and it matches the discount line");
});

test("a value that rounds to nothing is not shown as negative", () => {
  assert.equal(para(-0), "0,00");
  assert.equal(para(-0.001), "0,00");
});

// --- the discount line ---

test("a discount is printed with its minus, however the receipt signed it", () => {
  // The validator accepts both "52,32-" and "-52,32" as the same 52,32 iskonto,
  // so the two must land on screen identically.
  assert.equal(iskontoPara(52.32), "−52,32");
  assert.equal(iskontoPara(-52.32), "−52,32");
  assert.doesNotMatch(iskontoPara(-52.32), /[-−]{2}/);
});

test("no discount is a plain zero, never a lone minus", () => {
  assert.equal(iskontoPara(0), "0,00");
  assert.equal(iskontoPara(-0), "0,00");
  assert.equal(iskontoPara(0.001), "0,00", "rounded away, so nothing to discount");
});

// --- shapes the queue can hand over (PLAN.md contracts: never NaN on screen) ---

test("a missing or blurred amount reads as zero", () => {
  for (const value of [null, undefined, "", NaN, Infinity, -Infinity, {}, []]) {
    assert.equal(para(value), "0,00", String(value));
    assert.equal(iskontoPara(value), "0,00", String(value));
  }
});

test("sayi keeps a usable number and drops everything else to 0", () => {
  assert.equal(sayi(2.5), 2.5);
  assert.equal(sayi("2.5"), 2.5);
  assert.equal(sayi(-1), -1);
  assert.equal(sayi(null), 0);
  assert.equal(sayi("8,%"), 0);
  assert.equal(sayi(Infinity), 0);
});
