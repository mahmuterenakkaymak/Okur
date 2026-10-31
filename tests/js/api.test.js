import test from "node:test";
import assert from "node:assert/strict";
import {
  ApiError,
  POLL,
  STORAGE_KEY,
  backoffDelay,
  classifyFailure,
  getApiKey,
  isOnline,
  pollJob,
  setApiKey,
  submitJob,
} from "../../static/app/api.js";

// --- fakes: fetch replays a scripted response list, storage is a Map ---

function response(status, body = {}, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (name.toLowerCase() in headers ? headers[name.toLowerCase()] : null) },
    json: async () => body,
  };
}

function makeStorage(throws = false) {
  const map = new Map();
  const guard = () => {
    if (throws) throw new Error("storage disabled");
  };
  return {
    map,
    getItem(key) {
      guard();
      return map.has(key) ? map.get(key) : null;
    },
    setItem(key, value) {
      guard();
      map.set(key, String(value));
    },
    removeItem(key) {
      guard();
      map.delete(key);
    },
  };
}

function networkError() {
  const err = new TypeError("Failed to fetch");
  err.name = "TypeError";
  return err;
}

function envelope(status, extra = {}) {
  return { job_id: "job-1", status, client_ref: null, result: null, validation: null, meta: {}, ...extra };
}

function queued(n) {
  return Array.from({ length: n }, () => response(200, envelope("queued")));
}

/** fetch that walks the script, plus the clock the poll loop runs on. */
function harness(script = [], poll = {}) {
  const calls = [];
  const waits = [];
  const ticks = [];
  let clock = 0;
  const fetchFn = async (url, init = {}) => {
    calls.push({ url, init });
    const step = script.shift();
    if (step === undefined) throw new Error("script exhausted");
    if (step instanceof Error) throw step;
    return step;
  };
  const options = {
    apiKey: "ocrk_test",
    fetchFn,
    sleep: (ms) => {
      waits.push(ms);
      clock += ms;
      return Promise.resolve();
    },
    now: () => clock,
    onTick: (job, elapsed) => ticks.push({ job, elapsed }),
    initialMs: 100,
    maxMs: 1000,
    factor: 2,
    ceilingMs: 100000,
    ...poll,
  };
  return { calls, waits, ticks, options, fetchFn };
}

// --- key storage ---

test("the key round-trips through storage, trimmed", () => {
  const storage = makeStorage();
  assert.equal(setApiKey("  ocrk_abc  ", storage), "ocrk_abc");
  assert.equal(storage.map.get(STORAGE_KEY), "ocrk_abc");
  assert.equal(getApiKey(storage), "ocrk_abc");
});

test("an empty key clears the stored one", () => {
  const storage = makeStorage();
  setApiKey("ocrk_abc", storage);
  assert.equal(setApiKey("   ", storage), "");
  assert.equal(getApiKey(storage), "");
  assert.equal(storage.map.has(STORAGE_KEY), false);
});

test("unusable storage is not an error", () => {
  assert.equal(getApiKey(makeStorage(true)), "");
  assert.equal(setApiKey("ocrk_abc", makeStorage(true)), "ocrk_abc");
  assert.equal(getApiKey(undefined), "");
  assert.equal(isOnline(), true);
});

test("submitJob falls back to the stored key", async () => {
  const { calls, fetchFn } = harness([response(202, envelope("queued"))]);
  globalThis.localStorage = makeStorage();
  try {
    setApiKey("ocrk_stored", globalThis.localStorage);
    await submitJob(new Blob(["x"]), { fetchFn });
    assert.equal(calls[0].init.headers["X-API-Key"], "ocrk_stored");
  } finally {
    delete globalThis.localStorage;
  }
});

// --- submitJob ---

test("submitJob posts the JPEG to /v1/jobs with X-API-Key", async () => {
  const { calls, options } = harness([response(202, envelope("queued", { client_ref: "ref-1" }))]);
  const job = await submitJob(new Blob(["jpeg-bytes"], { type: "image/jpeg" }), {
    ...options,
    clientRef: "ref-1",
    capturedAt: "2026-10-31T09:40:00",
  });

  assert.equal(calls[0].url, "/v1/jobs");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["X-API-Key"], "ocrk_test");
  const form = calls[0].init.body;
  assert.equal(form.get("image").name, "fis.jpg");
  assert.equal(form.get("mode"), "fast");
  assert.equal(form.get("client_ref"), "ref-1");
  assert.equal(form.get("captured_at"), "2026-10-31T09:40:00");
  assert.equal(job.job_id, "job-1");
  assert.equal(job.status, "queued");
});

test("quality mode and the optional fields stay optional", async () => {
  const { calls, options } = harness([response(202, envelope("queued")), response(202, envelope("queued"))]);
  await submitJob(new Blob(["x"]), { ...options, mode: "quality" });
  assert.equal(calls[0].init.body.get("mode"), "quality");
  assert.equal(calls[0].init.body.has("client_ref"), false);
  assert.equal(calls[0].init.body.has("captured_at"), false);

  await submitJob(new Blob(["x"]), options);
  assert.equal(calls[1].init.body.get("mode"), "fast");
});

test("a baseUrl is honoured, without a doubled slash", async () => {
  const { calls, options } = harness([response(202, envelope("queued")), response(200, envelope("done"))]);
  await submitJob(new Blob(["x"]), { ...options, baseUrl: "http://localhost:8090/" });
  assert.equal(calls[0].url, "http://localhost:8090/v1/jobs");

  await pollJob("job-1", { ...options, baseUrl: "http://localhost:8090" });
  assert.equal(calls[1].url, "http://localhost:8090/api/me/jobs/job-1");
});

// --- error classes ---

test("a rejected key is the key-invalid class", async () => {
  const { options } = harness([response(401, { error: { code: "unauthorized" } })]);
  await assert.rejects(submitJob(new Blob(["x"]), options), (err) => {
    assert.equal(err.kind, "key_invalid");
    assert.equal(err.status, 401);
    assert.match(err.message, /anahtar/i);
    return true;
  });
});

test("a 429 carries the server's Retry-After", async () => {
  const { options } = harness([response(429, { error: { code: "rate_limited" } }, { "retry-after": "7" })]);
  await assert.rejects(submitJob(new Blob(["x"]), options), (err) => {
    assert.equal(err.kind, "rate_limited");
    assert.equal(err.retryAfter, 7);
    assert.match(err.message, /fazla istek/);
    return true;
  });
});

test("no connection at all is the offline class", async () => {
  const { options } = harness([networkError()]);
  await assert.rejects(submitJob(new Blob(["x"]), options), (err) => {
    assert.equal(err.kind, "offline");
    assert.equal(err.status, 0);
    assert.match(err.message, /bağlantı/i);
    return true;
  });
});

test("anything else the server answers is a server error", async () => {
  for (const status of [422, 500, 503]) {
    const { options } = harness([response(status, { error: { code: "boom" } })]);
    await assert.rejects(submitJob(new Blob(["x"]), options), (err) => {
      assert.equal(err.kind, "server_error");
      assert.equal(err.status, status);
      return true;
    });
  }
});

test("classifyFailure folds a missing connection into offline", () => {
  assert.equal(classifyFailure({ status: 500, online: false }).kind, "offline");
  assert.equal(classifyFailure({ status: 0 }).kind, "offline");
  assert.equal(classifyFailure({ status: 429, retryAfter: 2 }).retryAfter, 2);
  assert.ok(classifyFailure({ status: 500 }) instanceof ApiError);
});

// --- backoff math ---

test("backoffDelay doubles up to the cap", () => {
  const delays = [0, 1, 2, 3, 4, 5].map((attempt) => backoffDelay(attempt, POLL));
  assert.deepEqual(delays, [1200, 2400, 4800, 9600, 15000, 15000]);
  assert.equal(backoffDelay(-1, POLL), POLL.initialMs);
});

// --- pollJob ---

test("pollJob walks the stages and returns the finished envelope", async () => {
  const result = envelope("done", { result: { totals: { toplam: 42 } } });
  const { calls, waits, ticks, options } = harness([
    response(200, envelope("queued")),
    response(200, envelope("running")),
    response(200, result),
  ]);

  const job = await pollJob("job-1", options);

  assert.equal(job.status, "done");
  assert.equal(job.result.totals.toplam, 42);
  assert.deepEqual(waits, [100, 200]);
  assert.deepEqual(calls.map((call) => call.url), [
    "/api/me/jobs/job-1",
    "/api/me/jobs/job-1",
    "/api/me/jobs/job-1",
  ]);
  assert.equal(calls[0].init.headers["X-API-Key"], "ocrk_test");
  assert.deepEqual(ticks.map((tick) => tick.job.status), ["queued", "running"]);
  assert.deepEqual(ticks.map((tick) => tick.elapsed), [0, 100]);
});

test("a failed job is an answer, not an error", async () => {
  const { waits, options } = harness([response(200, envelope("failed", { meta: { model: "" } }))]);
  assert.equal((await pollJob("job-1", options)).status, "failed");
  assert.deepEqual(waits, []);
});

test("a revoked key stops the poll on the spot", async () => {
  const { calls, options } = harness([response(200, envelope("queued")), response(401, {}), response(200, envelope("queued"))]);
  await assert.rejects(pollJob("job-1", options), (err) => {
    assert.equal(err.kind, "key_invalid");
    return true;
  });
  assert.equal(calls.length, 2);
});

test("a rate limit waits for the server's Retry-After and keeps going", async () => {
  const { waits, options } = harness(
    [response(429, {}, { "retry-after": "7" }), response(200, envelope("done"))],
    { initialMs: 100, maxMs: 1000, factor: 2, ceilingMs: 60000 },
  );
  assert.equal((await pollJob("job-1", options)).status, "done");
  assert.deepEqual(waits, [7000]);
});

test("a blip mid-poll is retried, not reported", async () => {
  const { waits, ticks, options } = harness([
    response(200, envelope("queued")),
    networkError(),
    response(200, envelope("done")),
  ]);
  assert.equal((await pollJob("job-1", options)).status, "done");
  assert.deepEqual(waits, [100, 200]);
  assert.deepEqual(ticks.map((tick) => tick.job), [ticks[0].job, null]);
});

test("the ceiling gives up with a timeout when the queue is stuck", async () => {
  const { calls, waits, options } = harness(queued(10), {
    initialMs: 100,
    maxMs: 1000,
    factor: 2,
    ceilingMs: 1000,
  });
  await assert.rejects(pollJob("job-1", options), (err) => {
    assert.equal(err.kind, "timeout");
    assert.match(err.message, /sonuçlanmadı/);
    return true;
  });
  assert.deepEqual(waits, [100, 200, 400]);
  assert.equal(calls.length, 4);
});

test("the ceiling reports the last failure when there was one", async () => {
  const { options } = harness([response(200, envelope("queued")), networkError(), response(200, envelope("queued"))], {
    initialMs: 100,
    maxMs: 1000,
    factor: 2,
    ceilingMs: 150,
  });
  await assert.rejects(pollJob("job-1", options), (err) => {
    assert.equal(err.kind, "offline");
    return true;
  });
});

test("a server error that never clears surfaces at the ceiling", async () => {
  const { options } = harness(
    [response(503, {}), response(503, {}), response(503, {}), response(503, {}), response(503, {})],
    { initialMs: 100, maxMs: 1000, factor: 2, ceilingMs: 1000 },
  );
  await assert.rejects(pollJob("job-1", options), (err) => {
    assert.equal(err.kind, "server_error");
    assert.equal(err.status, 503);
    return true;
  });
});

