import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ApiError, POLL, pollJob } from "../../static/app/api.js";
import { STALE_AFTER_MS, statusOf } from "../../static/app/status.js";
import { recoveryFor } from "../../static/app/recovery.js";

// The phone has to outlast its own patience: tracking is what ends a wait, so
// a ceiling below the stale window would cut every healthy busy-queue wait
// short and hand the worker an "upload failed" sentence for a receipt that
// arrived and is still in the queue.

const apiSrc = readFileSync(new URL("../../static/app/api.js", import.meta.url), "utf8");

function response(status, body = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => body,
  };
}

function envelope(status, extra = {}) {
  return {
    job_id: "job-1",
    status,
    client_ref: null,
    result: null,
    validation: null,
    meta: {},
    ...extra,
  };
}

/**
 * fetch that answers `running` until `doneAfterMs` of virtual time and `done`
 * past it (never, for Infinity), plus the clock the poll loop runs on.
 */
function harness({ doneAfterMs = Infinity } = {}) {
  const calls = [];
  const ticks = [];
  let clock = 0;
  const options = {
    apiKey: "ocrk_test",
    fetchFn: async (url) => {
      calls.push({ url, elapsed: clock });
      return response(200, envelope(clock >= doneAfterMs ? "done" : "running"));
    },
    sleep: (ms) => {
      clock += ms;
      return Promise.resolve();
    },
    now: () => clock,
    onTick: (job, elapsed) => ticks.push({ job, elapsed }),
  };
  return { calls, ticks, options };
}

// --- the relation between the two windows ---

test("the poll ceiling outlasts the stale window it is named from", () => {
  assert.ok(STALE_AFTER_MS >= 45000 * 5, "the stale window keeps the documented budget");
  assert.ok(
    POLL.ceilingMs > STALE_AFTER_MS,
    `ceiling ${POLL.ceilingMs} must outlast stale ${STALE_AFTER_MS}`,
  );
  assert.match(
    apiSrc,
    /ceilingMs: STALE_AFTER_MS/,
    "it is named from the constant, so the two cannot drift apart",
  );
});

// --- driving the real ceiling on a virtual clock ---

test("a receipt still running at 200 s is still being polled", async () => {
  const { calls, ticks, options } = harness();
  const err = await pollJob("job-1", options).then(
    () => null,
    (thrown) => thrown,
  );
  assert.ok(err instanceof ApiError, "the ceiling throws the failure it was waiting for");

  const last = ticks[ticks.length - 1];
  assert.ok(
    last.elapsed >= 200000,
    `tracking gave up at ${last.elapsed} ms, inside a normal busy queue`,
  );
  assert.ok(calls.length > ticks.length - 3, "every tick came from a real poll");
  const view = statusOf(envelope("running"), { elapsedMs: last.elapsed });
  assert.equal(view.finished, false, "the job never stopped being live");
  assert.equal(view.stale, true, "and the card said the queue was busy the whole while");

  assert.equal(err.kind, "timeout");
  assert.match(err.message, /kuyruk yoğun olabilir/i);
  assert.doesNotMatch(err.message, /ulaşmadı|tekrar dene/);
});

test("a job that finishes at 200 s comes back instead of timing out", async () => {
  const { calls, options } = harness({ doneAfterMs: 200000 });
  const env = await pollJob("job-1", options);

  assert.equal(env.status, "done");
  assert.ok(calls[calls.length - 1].elapsed >= 200000, "the answer was read past 200 s");
});

// --- and the timeout keeps its own words and its own way out ---

test("a receipt already in the queue is not reported as an upload failure", () => {
  const err = new ApiError("timeout");
  const r = recoveryFor(err, { queued: true });

  assert.equal(r.action, "wait", "nothing to resend, nothing to re-shoot");
  assert.equal(r.message, err.message, "the poll's own sentence, verbatim");
  assert.match(r.message, /kuyruk yoğun olabilir/i);
  assert.doesNotMatch(r.message, /ulaşmadı|tekrar dene|kırpmayı/);
});
