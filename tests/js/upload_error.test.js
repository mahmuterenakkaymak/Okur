import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ApiError, classifyFailure, submitJob } from "../../static/app/api.js";
import { RECOVERIES, recoveryFor } from "../../static/app/recovery.js";

// Intake refuses a bad image in Turkish (routes_jobs.too_large_message and
// _require_image), and the worker's phone is the audience for that copy.
const TOO_LARGE =
  "Görsel 8 MB sınırını aşıyor. Fotoğrafı kırpıp yeniden göndermeyi deneyin.";
const NOT_AN_IMAGE = "geçerli bir görsel değil (JPEG ya da PNG olmalı)";
const GENERIC = "Sunucuda bir sorun çıktı. Birazdan tekrar dene.";

const options = { apiKey: "ocrk_test" };

function fetchReturning(status, body) {
  return async () => ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => body,
  });
}

/** The envelope main._error writes: {error: {code, message, details?}}. */
function envelope(code, message, details) {
  return { error: { code, ...(message ? { message } : {}), ...(details ? { details } : {}) } };
}

/** One upload against a scripted answer, resolved to the error it throws. */
async function submit(body, status = 422) {
  const err = await submitJob(new Blob(["jpeg-bytes"], { type: "image/jpeg" }), {
    ...options,
    fetchFn: fetchReturning(status, body),
  }).catch((thrown) => thrown);
  assert.equal(err.name, "ApiError");
  return err;
}

// --- the server's own words reach the worker ---

test("a 413 shows the server's crop-and-retake line, not a retry promise", async () => {
  const err = await submit(envelope("payload_too_large", TOO_LARGE), 413);
  assert.equal(err.kind, "rejected");
  assert.equal(err.status, 413);
  assert.equal(err.message, TOO_LARGE);
});

test("a 422 answers with the field copy, not the schema chatter", async () => {
  const err = await submit(
    envelope("validation_error", "request did not match the schema", [
      { field: "body.image", message: NOT_AN_IMAGE },
    ]),
  );
  assert.equal(err.kind, "rejected");
  assert.equal(err.status, 422);
  assert.equal(err.message, NOT_AN_IMAGE);
});

test("every field the server named reaches the worker", async () => {
  const err = await submit(
    envelope("validation_error", "request did not match the schema", [
      { field: "body.image", message: NOT_AN_IMAGE },
      { field: "body.captured_at", message: "is not an ISO-8601 timestamp" },
    ]),
  );
  assert.equal(err.message, `${NOT_AN_IMAGE} · is not an ISO-8601 timestamp`);
});

test("a refusal the server left unexplained stays a server error", async () => {
  for (const body of [envelope("boom"), {}, null]) {
    const err = await submit(body);
    assert.equal(err.kind, "server_error");
    assert.equal(err.message, GENERIC);
  }
});

test("a server fault keeps the generic copy even when it explains itself", async () => {
  // 500 is the app's own problem; sending the worker off to re-crop would be
  // a wrong answer, so only 413/422 borrow the server's line.
  const err = await submit(envelope("internal_error", "unexpected server error"), 500);
  assert.equal(err.kind, "server_error");
  assert.equal(err.message, GENERIC);
});

test("a dead connection still outranks the status line", async () => {
  const err = classifyFailure({ status: 413, online: false, serverMessage: TOO_LARGE });
  assert.equal(err.kind, "offline");
});

test("classifyFailure folds the server's line into the rejected kind", () => {
  const rejected = classifyFailure({ status: 413, serverMessage: TOO_LARGE });
  assert.equal(rejected.kind, "rejected");
  assert.equal(rejected.message, TOO_LARGE);
  assert.equal(classifyFailure({ status: 413 }).kind, "server_error");
  assert.equal(classifyFailure({ status: 422 }).kind, "server_error");
});

// --- and the way out is a tighter crop, not a resend ---

test("a refused image points at the crop, never at a resend", () => {
  const r = recoveryFor(new ApiError("rejected", { status: 413, message: TOO_LARGE }));
  assert.equal(r.action, "retake");
  assert.equal(r.message, TOO_LARGE);
  assert.match(RECOVERIES.retake.message, /kırp/i);
  assert.match(RECOVERIES.retake.message, /yeniden çek/i);
});

test("the other failures keep their own ways out", () => {
  assert.equal(recoveryFor(new ApiError("server_error", { status: 500 })).action, "retry");
  assert.equal(recoveryFor(new ApiError("rate_limited", { status: 429 })).action, "retry");
  assert.equal(recoveryFor(new ApiError("key_invalid", { status: 401 })).action, "key");
  assert.equal(recoveryFor(new ApiError("offline")).action, "offline");
});

const appSrc = readFileSync(new URL("../../static/app/app.js", import.meta.url), "utf8");

test("the crop card hides the retry button when the image itself was refused", () => {
  assert.match(appSrc, /tekrarDugme\.hidden = r\.action === "retake"/);
});
