// API client for the worker PWA: the key lives in localStorage, every call
// carries X-API-Key, and every failure lands in one kind the UI can explain
// in Turkish (key invalid / rate limited / offline / server error), and an
// image the server refused (413/422) carries the server's own Turkish line.
//
// ASSUMPTION: the PWA submits through the frozen /v1 intake route (the only
// job POST) and polls its own key-scoped view under /api/me, which answers
// the same envelope plus image_url.

import { STALE_AFTER_MS } from "./status.js";

export const STORAGE_KEY = "ocr.api_key";

// Live status wants an early first answer (OCR runs in 1-5 s) and then a
// gentle tail; the ceiling is where a stuck queue stops being the worker's
// problem and becomes a message. It is named from the stale window: a live job
// only starts saying "kuyruk yoğun olabilir" past STALE_AFTER_MS, so tracking
// that stopped before that point would sell a healthy queue as a dead send.
// ASSUMPTION: one grace minute past the stale window, so the worker reads the
// stale note while the poll is still alive.
const QUEUE_GRACE_MS = 60000;
export const POLL = {
  initialMs: 1200,
  maxMs: 15000,
  factor: 2,
  ceilingMs: STALE_AFTER_MS + QUEUE_GRACE_MS,
};

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
  constructor(kind, { status = 0, retryAfter = null, message = "" } = {}) {
    super(message || COPY[kind] || COPY.server_error);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.retryAfter = retryAfter; // seconds, from Retry-After when the server sent one
  }
}

/** One HTTP/network failure -> the kind the UI branches on. */
export function classifyFailure({
  status = 0,
  online = true,
  retryAfter = null,
  serverMessage = "",
} = {}) {
  if (!online || !status) return new ApiError("offline", { status });
  if (status === 401) return new ApiError("key_invalid", { status });
  if (status === 429) return new ApiError("rate_limited", { status, retryAfter });
  // 413/422 are the server's verdict on this one image and its own copy says
  // what to fix (kırp / yeniden çek); the same bytes resent fail the same
  // way, so the worker reads that copy instead of "birazdan tekrar dene".
  if ((status === 413 || status === 422) && serverMessage) {
    return new ApiError("rejected", { status, message: serverMessage });
  }
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

/**
 * The server's own line about a failed call (main._error's envelope). A 422
 * leads with generic schema chatter, so the per-field copy it carries wins —
 * that one is the Turkish sentence written for the worker.
 */
function failureMessage(data) {
  const error = data && typeof data === "object" ? data.error : null;
  if (!error || typeof error !== "object") return "";
  const details = Array.isArray(error.details) ? error.details : [];
  const fields = details
    .map((detail) => (detail && typeof detail.message === "string" ? detail.message.trim() : ""))
    .filter(Boolean);
  if (fields.length) return fields.join(" · ");
  return typeof error.message === "string" ? error.message.trim() : "";
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
      serverMessage: failureMessage(data),
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
 * One page of the worker's own history (PLAN.md contract 10 lite rows).
 * The server scopes every page to the caller's key; paging walks that
 * feed newest-first.
 */
export async function listJobs({ limit = 20, offset = 0, ...options } = {}) {
  const { apiKey = getApiKey() } = options;
  return call(`/api/me/jobs?limit=${limit}&offset=${offset}`, { ...options, apiKey });
}

/** Full envelope of one of the caller's own jobs; anyone else's job 404s. */
export async function getJob(jobId, options = {}) {
  const { apiKey = getApiKey() } = options;
  return call(`/api/me/jobs/${jobId}`, { ...options, apiKey });
}

/**
 * Authenticated image bytes. Thumbnails sit behind X-API-Key, which an
 * <img src> cannot carry, so the history feed fetches blobs itself.
 */
export async function fetchImage(url, { apiKey = getApiKey(), fetchFn = globalThis.fetch } = {}) {
  let response;
  try {
    response = await fetchFn(url, { headers: { "X-API-Key": apiKey } });
  } catch {
    throw classifyFailure({ status: 0, online: isOnline() });
  }
  if (!response.ok) {
    throw classifyFailure({ status: response.status, online: isOnline() });
  }
  return response.blob();
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
