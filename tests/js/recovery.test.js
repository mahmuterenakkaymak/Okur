import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ApiError } from "../../static/app/api.js";
import {
  RECOVERIES,
  UPLOAD_TIMEOUT_MS,
  cameraNotice,
  offlineNotice,
  recoveryFor,
  withTimeout,
} from "../../static/app/recovery.js";

function fakeTimers() {
  const slots = [];
  return {
    setTimeoutRef: (fn) => {
      slots.push(fn);
      return slots.length;
    },
    clearTimeoutRef: (id) => {
      if (id) slots[id - 1] = null;
    },
    fireAll: () => {
      for (const fn of [...slots]) if (fn) fn();
    },
    pending: () => slots.filter(Boolean).length,
  };
}

// --- failure -> the one way out ---

test("a revoked key lands on the key screen", () => {
  const r = recoveryFor(new ApiError("key_invalid", { status: 401 }));
  assert.equal(r.action, "key");
  assert.match(r.message, /anahtar/i);
});

test("a dead network says so and waits", () => {
  const r = recoveryFor(new ApiError("offline"));
  assert.equal(r.action, "offline");
  assert.match(r.message, /bağlantı/i);
});

test("timeout, server and rate-limit hiccups all retry in place", () => {
  for (const err of [
    new ApiError("timeout"),
    new ApiError("server_error", { status: 500 }),
    new ApiError("rate_limited", { status: 429, retryAfter: 3 }),
    new Error("boom"),
  ]) {
    const r = recoveryFor(err);
    assert.equal(r.action, "retry");
    assert.ok(r.message.length > 10, "every failure explains itself in Turkish");
  }
  assert.match(RECOVERIES.retry.message, /tekrar dene/i);
});

// --- upload timeout ---

test("a fast upload wins and leaves no timer behind", async () => {
  const t = fakeTimers();
  assert.equal(await withTimeout(Promise.resolve("kabul"), UPLOAD_TIMEOUT_MS, t), "kabul");
  assert.equal(t.pending(), 0);
});

test("a stalled upload is declared dead as a timeout", async () => {
  const t = fakeTimers();
  const p = withTimeout(new Promise(() => {}), UPLOAD_TIMEOUT_MS, t);
  t.fireAll();
  await assert.rejects(p, (err) => err.name === "ApiError" && err.kind === "timeout");
});

test("an upload that fails on its own fails through", async () => {
  const t = fakeTimers();
  await assert.rejects(withTimeout(Promise.reject(new Error("pat")), UPLOAD_TIMEOUT_MS, t), /pat/);
  assert.equal(t.pending(), 0);
});

// --- offline banner ---

test("online, the banner stays out of the way", () => {
  assert.deepEqual(offlineNotice({ online: true, hasDraft: true }), { visible: false, text: "" });
});

test("offline with a crop promises the crop survived", () => {
  const bant = offlineNotice({ online: false, hasDraft: true });
  assert.equal(bant.visible, true);
  assert.match(bant.text, /cihazında/);
});

test("offline without one points at the server queue", () => {
  const bant = offlineNotice({ online: false });
  assert.equal(bant.visible, true);
  assert.match(bant.text, /kuyruğunda/);
});

// --- camera denied guidance ---

test("only the denied camera earns the extra guidance", () => {
  for (const state of ["idle", "camera", "file"]) assert.equal(cameraNotice(state), "");
  const not = cameraNotice("denied");
  assert.match(not, /izn/i);
  assert.match(not, /Dosyadan seç/);
});

// --- served-page wiring ---

const html = readFileSync(new URL("../../static/app/index.html", import.meta.url), "utf8");
const appSrc = readFileSync(new URL("../../static/app/app.js", import.meta.url), "utf8");

test("every recovery hook app.js reaches exists on the page", () => {
  const wired = new Set([...appSrc.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]));
  for (const id of ["net-bant", "kamera-ipucu", "tekrar-dene", "yeniden-cek", "adim-anahtar", "anahtar-tamam"]) {
    assert.ok(wired.has(id), `app.js must reach #${id}`);
    assert.ok(html.includes(`id="${id}"`), `index.html is missing #${id}`);
  }
});

test("recovery ships hidden until a state earns it", () => {
  for (const id of ["net-bant", "tekrar-dene", "yeniden-cek", "adim-anahtar"]) {
    assert.match(html, new RegExp(`id="${id}"[^>]*hidden`), `#${id} must start hidden`);
  }
});

test("the key screen and the re-shoot button speak Turkish", () => {
  assert.match(html, /API anahtarı çalışmıyor/);
  assert.match(html, /Fişi yeniden çek/);
  assert.match(html, /Tekrar dene/);
});

test("app.js wires the recovery module into the send path", () => {
  assert.ok(appSrc.includes('from "./recovery.js"'));
  for (const entry of ["recoveryFor", "withTimeout", "offlineNotice", "cameraNotice"]) {
    assert.ok(appSrc.includes(entry), entry);
  }
  assert.ok(appSrc.includes("gonder(sonCrop)"), "retry resends the kept crop");
});
