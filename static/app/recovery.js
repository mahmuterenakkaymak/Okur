// Stuck-state recovery: every way a send can wedge (upload timeout, dead
// network, revoked key, image the server refused, denied camera) maps to the
// one thing the worker can do about it — retry in place with the crop still
// loaded, wait for the network, fix the key, or re-crop / re-shoot.
//
// ASSUMPTION: the API puts no deadline on an upload, so the PWA declares one
// dead after UPLOAD_TIMEOUT_MS and offers the retry; the unchanged
// client_ref makes that retry idempotent server-side.

import { ApiError } from "./api.js";

export const UPLOAD_TIMEOUT_MS = 30000;

export const RECOVERIES = {
  retry: {
    action: "retry",
    message:
      "Fiş sunucuya ulaşmadı ya da sunucu yanıt vermedi. Kestiğin görüntü hazır duruyor — tekrar dene.",
  },
  offline: {
    action: "offline",
    message:
      "İnternet bağlantısı yok. Fiş sunucuya ulaşmadı, bağlantı kurulunca tekrar gönderebilirsin.",
  },
  key: {
    action: "key",
    message: "API anahtarın geçersiz ya da iptal edilmiş. Yöneticinden yeni bir anahtar iste.",
  },
  // The image itself is the problem, so resending it cannot help: the worker
  // crops tighter or shoots again, and the server's own line says which.
  retake: {
    action: "retake",
    message:
      "Bu görüntü sunucuya uymadı. Fişi daha küçük kırpmayı ya da yeniden çekmeyi dene.",
  },
  // The server took the receipt and has not finished it: nothing to resend,
  // nothing to re-shoot. The worker waits, and reads that from the status card.
  queue: {
    action: "wait",
    message: "Fiş sunucuya ulaştı, kuyruk yoğun olabilir. Birazdan tekrar bak.",
  },
};

// Kinds whose own ApiError copy already explains the situation in Turkish.
const OWN_COPY = new Set([
  "key_invalid",
  "offline",
  "rate_limited",
  "server_error",
  "rejected",
]);

/**
 * Any send-path failure -> { action, message } the UI branches on.
 *
 * `queued` is what the caller knows and the error cannot say: the accept
 * already came back, so the receipt sits in the server's queue. That turns a
 * timeout from "the send never landed, resend it" into "it is being worked on,
 * wait" — and the poll's own sentence (api.js COPY.timeout) is the one that
 * says so, kept verbatim instead of the retry copy.
 */
export function recoveryFor(error, { queued = false } = {}) {
  const kind = error && error.name === "ApiError" ? error.kind : "";
  if (kind === "timeout" && queued) {
    return { ...RECOVERIES.queue, message: error.message || RECOVERIES.queue.message };
  }
  const base =
    kind === "key_invalid"
      ? RECOVERIES.key
      : kind === "offline"
        ? RECOVERIES.offline
        : kind === "rejected"
          ? RECOVERIES.retake
          : RECOVERIES.retry;
  return { ...base, message: OWN_COPY.has(kind) ? error.message : base.message };
}

/** Reject with a timeout-class ApiError when `promise` outlives `ms`. */
export function withTimeout(
  promise,
  ms = UPLOAD_TIMEOUT_MS,
  {
    setTimeoutRef = (fn, t) => globalThis.setTimeout(fn, t),
    clearTimeoutRef = (id) => globalThis.clearTimeout(id),
  } = {},
) {
  let timer;
  return new Promise((resolve, reject) => {
    timer = setTimeoutRef(() => reject(new ApiError("timeout", { status: 0 })), ms);
    promise.then(
      (value) => {
        clearTimeoutRef(timer);
        resolve(value);
      },
      (err) => {
        clearTimeoutRef(timer);
        reject(err);
      },
    );
  });
}

/** Offline banner: hidden online, queue-safe notice offline. */
export function offlineNotice({ online = true, hasDraft = false } = {}) {
  if (online) return { visible: false, text: "" };
  return {
    visible: true,
    text: hasDraft
      ? "İnternet bağlantısı yok — kestiğin fiş cihazında hazır duruyor, bağlantı kurulunca tek dokunuşla gönderebilirsin."
      : "İnternet bağlantısı yok. Gönderdiğin fişler sunucu kuyruğunda güvende; yeni fişleri bağlantı kurulunca gönderebilirsin.",
  };
}

/** Guidance under the viewfinder when the camera permission is gone. */
export function cameraNotice(state) {
  return state === "denied"
    ? "Kamera izni kapalı görünüyor. Tarayıcı ayarlarından izni açabilir ya da \"Dosyadan seç\" ile galeriden yükleyebilirsin."
    : "";
}
