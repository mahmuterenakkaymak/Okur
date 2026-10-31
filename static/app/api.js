// API client for the worker PWA: the key lives in localStorage, every call
// carries X-API-Key, and every failure lands in one kind the UI can explain
// in Turkish (key invalid / rate limited / offline / server error).
//
// ASSUMPTION: the PWA submits through the frozen /v1 intake route (the only
// job POST) and polls its own key-scoped view under /api/me, which answers
// the same envelope plus image_url.

export const STORAGE_KEY = "ocr.api_key";

// Live status wants an early first answer (OCR runs in 1-5 s) and then a
// gentle tail; the ceiling is where a stuck queue stops being the worker's
// problem and becomes a message.
export const POLL = { initialMs: 1200, maxMs: 15000, factor: 2, ceilingMs: 180000 };

const COPY = {
  key_invalid:
    "API anahtarın geçersiz ya da iptal edilmiş. Yöneticinden yeni bir anahtar iste.",
  rate_limited: "Çok fazla istek gönderdin. Birkaç saniye içinde tekrar dene.",
  offline:
    "İnternet bağlantısı yok. Fiş sunucuya ulaşmadı, bağlantı kurulunca tekrar gönderebilirsin.",
  server_error: "Sunucuda bir sorun çıktı. Birazdan tekrar dene.",
  // ASSUMPTION: the poll ceiling is not a transport failure, so it gets its
  // own kind; the four classes in PLAN.md cover calls that came back.
  timeout: "Fiş hâlâ sonuçlanmadı. Kuyruk yoğun olabilir, birazdan tekrar bak.",
};

export class ApiError extends Error {
  constructor(kind, { status = 0, retryAfter = null } = {}) {
    super(COPY[kind] || COPY.server_error);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.retryAfter = retryAfter; // seconds, from Retry-After when the server sent one
  }
}

/** One HTTP/network failure -> the kind the UI branches on. */
export function classifyFailure({ status = 0, online = true, retryAfter = null } = {}) {
  if (!online || !status) return new ApiError("offline", { status });
  if (status === 401) return new ApiError("key_invalid", { status });
  if (status === 429) return new ApiError("rate_limited", { status, retryAfter });
  return new ApiError("server_error", { status });
}

/** Delay before poll number `attempt` (0-based): exponential, capped at maxMs. */
export function backoffDelay(attempt, { initialMs, maxMs, factor } = POLL) {
  const ms = initialMs * Math.pow(factor, Math.max(0, attempt));
  return Math.min(Math.round(ms), maxMs);
}

/** navigator.onLine, read as online where the flag does not exist. */
export function isOnline() {
  return globalThis.navigator ? globalThis.navigator.onLine !== false : true;
}

export function getApiKey(storage = globalThis.localStorage) {
  try {
    return (storage && storage.getItem(STORAGE_KEY)) || "";
  } catch {
    return "";
  }
}

/** Store (or, for an empty value, drop) the key; returns what is stored. */
export function setApiKey(key, storage = globalThis.localStorage) {
  const value = (key || "").trim();
  try {
    if (!storage) return value;
    if (value) storage.setItem(STORAGE_KEY, value);
    else storage.removeItem(STORAGE_KEY);
  } catch {
    // private mode / storage disabled: the call still works for this session
  }
  return value;
}

function retryAfterSeconds(headers) {
  const value = Number(headers && headers.get("Retry-After"));
  return Number.isFinite(value) && value >= 0 ? value : null;
}

async function call(path, { apiKey = "", fetchFn = globalThis.fetch, baseUrl = "", method = "GET", body }) {
  let response;
  try {
    response = await fetchFn(`${(baseUrl || "").replace(/\/+$/, "")}${path}`, {
      method,
      headers: { "X-API-Key": apiKey },
      body,
    });
  } catch {
    throw classifyFailure({ status: 0, online: isOnline() });
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw classifyFailure({
      status: response.status,
      online: isOnline(),
      retryAfter: retryAfterSeconds(response.headers),
    });
  }
  return data;
}

/**
 * Enqueue one receipt. `image` is the cropped JPEG blob; `clientRef` makes a
 * retry idempotent server-side, `capturedAt` is an ISO capture timestamp.
 */
export async function submitJob(image, options = {}) {
  const {
    mode = "fast",
    clientRef = null,
    capturedAt = null,
    apiKey = getApiKey(),
  } = options;
  const form = new FormData();
  form.append("image", image, "fis.jpg");
  form.append("mode", mode);
  if (clientRef) form.append("client_ref", clientRef);
  if (capturedAt) form.append("captured_at", capturedAt);
  return call("/v1/jobs", { ...options, apiKey, method: "POST", body: form });
}

/**
 * Follow one job until done/failed. Queued and running envelopes are handed
 * to onTick; a dead key stops at once, everything else (offline, 429, a
 * server hiccup) rides the backoff out to the ceiling, where the last
 * failure — or the timeout — is thrown.
 */
export async function pollJob(jobId, options = {}) {
  const {
    apiKey = getApiKey(),
    fetchFn,
    baseUrl = "",
    initialMs = POLL.initialMs,
    maxMs = POLL.maxMs,
    factor = POLL.factor,
    ceilingMs = POLL.ceilingMs,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    onTick = () => {},
    now = () => Date.now(),
  } = options;

  const started = now();
  let attempt = 0;
  let lastError = null;
  let retryAfterMs = 0;

  for (;;) {
    let envelope = null;
    try {
      envelope = await call(`/api/me/jobs/${jobId}`, { apiKey, fetchFn, baseUrl });
      lastError = null;
      retryAfterMs = 0;
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (err.kind === "key_invalid") throw err;
      lastError = err;
      retryAfterMs = err.retryAfter ? Math.round(err.retryAfter * 1000) : 0;
    }
    if (envelope && (envelope.status === "done" || envelope.status === "failed")) {
      return envelope;
    }
    onTick(envelope, now() - started);
    const wait = Math.max(retryAfterMs, backoffDelay(attempt++, { initialMs, maxMs, factor }));
    if (now() - started + wait > ceilingMs) break;
    await sleep(wait);
  }
  throw lastError || new ApiError("timeout", { status: 0 });
}
