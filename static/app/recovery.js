// Stuck-state recovery: every way a send can wedge (upload timeout, dead
// network, revoked key, denied camera) maps to the one thing the worker can
// do about it — retry in place with the crop still loaded, wait for the
// network, or fix the key.
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
};

// Kinds whose own ApiError copy already explains the situation in Turkish.
const OWN_COPY = new Set(["key_invalid", "offline", "rate_limited", "server_error"]);

/** Any send-path failure -> { action, message } the UI branches on. */
export function recoveryFor(error) {
  const kind = error && error.name === "ApiError" ? error.kind : "";
  const base =
    kind === "key_invalid" ? RECOVERIES.key : kind === "offline" ? RECOVERIES.offline : RECOVERIES.retry;
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
