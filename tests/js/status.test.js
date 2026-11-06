import test from "node:test";
import assert from "node:assert/strict";
import {
  OCR_BUDGET_MS,
  PIPELINE,
  STAGES,
  STALE_AFTER_MS,
  stageIdFor,
  statusOf,
} from "../../static/app/status.js";

function envelope(status, extra = {}) {
  return { job_id: "job-1", status, client_ref: null, result: null, validation: null, meta: {}, ...extra };
}

function validation(verdict, fields = []) {
  return { verdict, expected: {}, actual: {}, fields };
}

// --- the live chain ---

test("a queued job sits at the front of the queue", () => {
  const view = statusOf(envelope("queued"), { elapsedMs: 0 });
  assert.equal(view.id, "queued");
  assert.equal(view.label, "Sırada");
  assert.equal(view.finished, false);
  assert.equal(view.stale, false);
  assert.ok(view.progress > 0 && view.progress < 0.3, "a bar that has barely started");
});

test("running reads first, then structures", () => {
  const early = statusOf(envelope("running"), { elapsedMs: OCR_BUDGET_MS - 1 });
  const late = statusOf(envelope("running"), { elapsedMs: OCR_BUDGET_MS });

  assert.equal(early.label, "Okunuyor");
  assert.equal(late.label, "Yapılandırılıyor");
  assert.ok(early.progress < late.progress, "the bar only moves forward");
  assert.equal(early.seconds, 7);
  assert.equal(late.seconds, 8);
});

test("the stepper walks the four Turkish stages in order", () => {
  assert.deepEqual(
    PIPELINE.map((id) => STAGES[id].label),
    ["Sırada", "Okunuyor", "Yapılandırılıyor", "Doğrulandı"],
  );
  const fractions = PIPELINE.map((id) => STAGES[id].progress);
  assert.deepEqual(fractions, [...fractions].sort((a, b) => a - b));
});

// --- terminal states ---

test("a verified receipt closes the chain at 100 %", () => {
  const view = statusOf(envelope("done", { validation: validation("ok") }), { elapsedMs: 45000 });
  assert.deepEqual(
    [view.id, view.label, view.verdict, view.progress, view.finished, view.stale],
    ["verified", "Doğrulandı", "ok", 1, true, false],
  );
  assert.deepEqual(view.fields, []);
});

test("a mismatch names the offending fields", () => {
  const view = statusOf(
    envelope("done", { validation: validation("mismatch", ["items[2].toplam", "totals.kdv"]) }),
    { elapsedMs: 9000 },
  );
  assert.equal(view.id, "mismatch");
  assert.equal(view.label, "Uyuşmazlık");
  assert.deepEqual(view.fields, ["items[2].toplam", "totals.kdv"]);
  assert.equal(view.progress, 1);
});

test("an unreadable receipt asks for a re-shoot", () => {
  const view = statusOf(envelope("done", { validation: validation("unreadable") }));
  assert.equal(view.id, "unreadable");
  assert.match(view.label, /Okunamadı/);
  assert.match(view.hint, /çek/);
});

test("a failed job is a finished state, not a spinner", () => {
  const view = statusOf(envelope("failed"), { elapsedMs: 120000 });
  assert.equal(view.id, "failed");
  assert.equal(view.label, "İşlenemedi");
  assert.equal(view.finished, true);
  assert.equal(view.stale, false, "a dead job is not a stuck one");
  assert.equal(view.progress, 1);
});

// --- what a dead job tells the worker ---

test("the missing-brain sentence is the one reason the phone repeats", () => {
  const sebep =
    "stage 2: small brain not installed — çalıştırmak için scripts\\install_small_brain.ps1";
  const view = statusOf(envelope("failed", { error: sebep }), { elapsedMs: 5000 });

  assert.equal(view.reason, sebep);
  assert.equal(view.hint, sebep, "the worker reads the command to run");
});

test("every other internal reason stays off the phone", () => {
  const ic =
    'stage 2: 2 validation errors for Result\nitems\n  Input should be a valid list [input_value={"ad":"KOLE"}]\n[WinError 1225] sunucu yanıt vermiyor';
  const view = statusOf(envelope("failed", { error: ic }), { elapsedMs: 5000 });

  assert.equal(view.reason, "");
  assert.equal(view.hint, "Bu fiş işlenemedi, tekrar deneyebilirsin.");
  assert.doesNotMatch(view.hint, /WinError|validation error|Result/);
});

test("a job that carries no reason at all keeps the Turkish hint", () => {
  assert.equal(
    statusOf(envelope("failed", { error: "   " })).hint,
    "Bu fiş işlenemedi, tekrar deneyebilirsin.",
  );
});

// --- stale ---

test("a job that stops moving goes stale after a minute", () => {
  const before = statusOf(envelope("running"), { elapsedMs: STALE_AFTER_MS });
  const after = statusOf(envelope("running"), { elapsedMs: STALE_AFTER_MS + 1 });

  assert.equal(before.stale, false);
  assert.equal(after.stale, true);
  assert.equal(after.label, "Yapılandırılıyor", "the stage stays, only the note changes");
  assert.match(after.hint, /uzun sürüyor/);
});

test("the stale window can be shortened", () => {
  assert.equal(statusOf(envelope("queued"), { elapsedMs: 5000, staleAfterMs: 4000 }).stale, true);
});

// --- shapes the API hands over ---

test("a lite row carries its verdict at the top level", () => {
  const lite = { job_id: "job-1", status: "done", client_ref: null, received_at: "", thumbnail_url: null, verdict: "mismatch", toplam: 99 };
  const view = statusOf(lite);
  assert.equal(view.id, "mismatch");
  assert.equal(view.verdict, "mismatch");
  assert.deepEqual(view.fields, [], "the lite row has no field list to show");
});

test("a done job with no verdict yet is finished, not green", () => {
  const view = statusOf(envelope("done"));
  assert.equal(view.id, "done");
  assert.equal(view.label, "Bitti");
  assert.equal(view.verdict, null);
  assert.equal(view.finished, true);
});

test("an envelope that never arrived still renders", () => {
  for (const job of [undefined, null, {}, { status: "weird" }]) {
    const view = statusOf(job, { elapsedMs: NaN });
    assert.equal(view.id, "queued");
    assert.equal(view.seconds, 0);
    assert.equal(view.stale, false);
    assert.ok(view.label && view.hint && view.progress > 0);
  }
});

test("stageIdFor is the same mapping on its own", () => {
  assert.equal(stageIdFor("queued", 60000), "queued");
  assert.equal(stageIdFor("running", 0), "ocr");
  assert.equal(stageIdFor("running", 60000), "structuring");
  assert.equal(stageIdFor("done", 0, "ok"), "verified");
  assert.equal(stageIdFor("failed", 0, "ok"), "failed");
});

// --- the CPU-box latency (T92) ---

test("a normal 30-45 s CPU receipt is never sold as stuck", () => {
  for (const ms of [30000, 35000, 45000]) {
    const view = statusOf(envelope("running"), { elapsedMs: ms });
    assert.equal(view.label, "Yapılandırılıyor");
    assert.equal(view.stale, false, `${ms} ms is one receipt, not an outage`);
    assert.doesNotMatch(view.hint, /uzun sürüyor/);
  }
});

test("the stale window is queue-safe, not one receipt long", () => {
  // A job's elapsed counts its wait behind the receipt ahead of it; a queue of
  // several normal CPU receipts is still healthy.
  assert.ok(STALE_AFTER_MS >= 45000 * 5, "a busy queue outlasts the old 60 s");
  assert.equal(statusOf(envelope("running"), { elapsedMs: 45000 * 3 }).stale, false);
  assert.equal(statusOf(envelope("queued"), { elapsedMs: 45000 * 5 }).stale, false);
  assert.equal(statusOf(envelope("running"), { elapsedMs: STALE_AFTER_MS + 1 }).stale, true);
});

test("the Yapılandırılıyor hint says a long wait is the CPU box working", () => {
  const hint = STAGES.structuring.hint;

  assert.match(hint, /yerlerine yerleştiriliyor/, "still says what is happening");
  assert.match(hint, /dakika/, "names the wait");
  assert.match(hint, /normal|hâlâ işlemde/, "and calls it expected");
  assert.doesNotMatch(hint, /hata|uyuşmuyor|okunamadı|tekrar dene/, "no error wording");
  assert.equal(statusOf(envelope("running"), { elapsedMs: 40000 }).hint, hint);
});

test("only that one hint moved; the rest of the copy is untouched", () => {
  assert.deepEqual(
    PIPELINE.map((id) => [id, STAGES[id].label, STAGES[id].progress]),
    [
      ["queued", "Sırada", 0.05],
      ["ocr", "Okunuyor", 0.35],
      ["structuring", "Yapılandırılıyor", 0.7],
      ["verified", "Doğrulandı", 1],
    ],
  );
  assert.equal(STAGES.queued.hint, "Fiş sunucuya ulaştı, sırasını bekliyor.");
  assert.equal(STAGES.ocr.hint, "Fişin üzerindeki yazılar okunuyor.");
  assert.equal(STAGES.verified.hint, "Tutarlar fişle karşılaştırıldı, her şey tutuyor.");
  assert.equal(STAGES.mismatch.hint, "Bazı tutarlar fişle uyuşmuyor, bir göz at.");
  assert.equal(STAGES.unreadable.hint, "Bu fiş okunamadı, ışığı ayarlayıp bir kez daha çek.");
  assert.equal(STAGES.done.hint, "Fiş işlendi.");
  assert.equal(STAGES.failed.hint, "Bu fiş işlenemedi, tekrar deneyebilirsin.");
});
