import test from "node:test";
import assert from "node:assert/strict";
import {
  PENCERE_MS,
  YENILEME_MS,
  kuyrukDerinligi,
  ornekEkle,
  sparklineNoktalar,
  vramAmber,
} from "../../static/admin/status.js";

// The Durum page's sparkline and VRAM gauge are driven by the pure model
// below: what counts as queue depth, which samples stay in the 5-minute
// window, where each sample lands on the canvas, and when the gauge turns
// amber. The DOM layer only paints what these decide.

const SIMDI = 1_700_000_000_000;

// --- queue depth ---

test("queue depth is the open backlog: queued plus running", () => {
  assert.equal(kuyrukDerinligi({ queued: 2, running: 1, failed: 5 }), 3);
  assert.equal(kuyrukDerinligi({ queued: 4 }), 4, "a half that never arrived");
  assert.equal(kuyrukDerinligi({ running: 1 }), 1);
});

test("a queue payload that never arrived is depth zero, never NaN", () => {
  for (const kuyruk of [undefined, null, {}, { queued: null, running: "x" }]) {
    assert.equal(kuyrukDerinligi(kuyruk), 0);
  }
});

// --- the 5-minute window ---

test("the window is five minutes and refreshes well inside it", () => {
  assert.equal(PENCERE_MS, 5 * 60 * 1000);
  assert.ok(YENILEME_MS > 0 && YENILEME_MS < PENCERE_MS / 10);
});

test("ornekEkle appends the current sample and keeps the window", () => {
  const ornekler = ornekEkle(
    [
      { t: SIMDI - 6 * 60 * 1000, v: 9 }, // fell out of the window
      { t: SIMDI - 4 * 60 * 1000, v: 2 },
    ],
    SIMDI,
    3,
  );
  assert.deepEqual(ornekler, [
    { t: SIMDI - 4 * 60 * 1000, v: 2 },
    { t: SIMDI, v: 3 },
  ]);
});

test("ornekEkle does not touch the array it was handed", () => {
  const once = [{ t: SIMDI, v: 1 }];
  ornekEkle(once, SIMDI + 1000, 2);
  assert.equal(once.length, 1);
});

// --- sparkline geometry ---

test("no samples means nothing to draw", () => {
  assert.equal(sparklineNoktalar([], 300, 44, SIMDI), null);
  assert.equal(sparklineNoktalar(undefined, 300, 44, SIMDI), null);
});

test("samples land across the window: newest at the right edge, half-old in the middle", () => {
  const noktalar = sparklineNoktalar(
    [
      { t: SIMDI - PENCERE_MS / 2, v: 1 },
      { t: SIMDI, v: 2 },
    ],
    300,
    44,
    SIMDI,
  );
  assert.equal(noktalar.length, 2);
  assert.equal(Math.round(noktalar[0].x), 150);
  assert.equal(noktalar[1].x, 300);
});

test("the deepest sample pins the top, zero sits at the bottom", () => {
  const noktalar = sparklineNoktalar(
    [
      { t: SIMDI - 2 * 60 * 1000, v: 0 },
      { t: SIMDI - 60 * 1000, v: 8 },
      { t: SIMDI, v: 4 },
    ],
    300,
    44,
    SIMDI,
  );
  assert.equal(noktalar[0].y, 43, "zero hugs the baseline");
  assert.equal(noktalar[1].y, 1, "the peak touches the top");
  assert.equal(noktalar[2].y, 22, "half the peak is half the height");
});

test("an all-zero window draws a flat line, not NaN", () => {
  const noktalar = sparklineNoktalar(
    [
      { t: SIMDI - 60 * 1000, v: 0 },
      { t: SIMDI, v: 0 },
    ],
    300,
    44,
    SIMDI,
  );
  for (const nokta of noktalar) {
    assert.ok(Number.isFinite(nokta.x) && Number.isFinite(nokta.y));
    assert.equal(nokta.y, 43);
  }
});

// --- the amber threshold ---

test("the gauge stays green up to 90 % and turns amber past it", () => {
  assert.equal(vramAmber(0), false);
  assert.equal(vramAmber(89.9), false);
  assert.equal(vramAmber(90), false, "past 90, not at 90");
  assert.equal(vramAmber(90.4), true);
  assert.equal(vramAmber(100), true);
});

test("an unmeasurable ratio is never amber", () => {
  for (const oran of [undefined, null, NaN, Infinity, "95"]) {
    assert.equal(vramAmber(oran), false);
  }
});
