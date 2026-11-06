import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { SERVISLER } from "../../static/admin/status.js";

// T98 — what the Durum page's stage-2 chip claims. Contract 9 froze the status
// payload's key names, so the "strata" key carries whichever stage-2 brain is
// configured: app/status.py probes the small brain on :8100 while
// STRUCTURER_BACKEND=small and Strata on :8080 only otherwise. A chip titled
// "Strata" therefore lied on a CPU-only box — "Strata ✓" with nothing listening
// on :8080, during exactly the outage an operator has to diagnose. The chip now
// names the role the probe proves, never a server it may never have reached.

const KAYNAK = readFileSync(
  fileURLToPath(new URL("../../static/admin/status.js", import.meta.url)),
  "utf-8",
);

const asamaIki = SERVISLER.find((servis) => servis.anahtar === "strata");

test("the chips are contract 9's keys, in order, and no new key", () => {
  assert.deepEqual(
    SERVISLER.map((servis) => servis.anahtar),
    ["ocr", "strata", "unsloth"],
  );
});

test("the stage-2 chip names no server the probe may not be using", () => {
  assert.ok(asamaIki, "the stage-2 chip is gone");
  assert.notEqual(asamaIki.ad, "Strata");
  for (const sunucu of ["Strata", "Unsloth", "Qwen", "8080", "8100"]) {
    assert.ok(
      !asamaIki.ad.includes(sunucu) && !asamaIki.rol.includes(sunucu),
      `the chip claims "${sunucu}", which the probe may never reach`,
    );
  }
});

test("the stage-2 chip says what it proves: structuring, on the configured brain", () => {
  assert.equal(asamaIki.ad, "Yapılandırma");
  assert.match(asamaIki.rol, /STRUCTURER_BACKEND/);
  assert.match(asamaIki.rol, /aşama 2/);
});

test("the source still holds the SERVISLER literal the gate reads by key", () => {
  const blok = KAYNAK.match(/const SERVISLER = \[([\s\S]*?)\];/);
  assert.ok(blok, "the status page's service list disappeared");
  assert.deepEqual(
    [...blok[1].matchAll(/anahtar:\s*"([a-z_]+)"/g)].map((eslesme) => eslesme[1]),
    ["ocr", "strata", "unsloth"],
  );
  const satir = blok[1].match(/\{[^}]*anahtar:\s*"strata"[^}]*\}/)[0];
  assert.doesNotMatch(satir, /Strata/);
});
