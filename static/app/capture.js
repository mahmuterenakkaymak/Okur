// Camera capture for the worker PWA: getUserMedia preview with a freeze
// shutter, degrading to a file input (capture attribute) on desktops, on
// denied permission and on devices without a camera API.
//
// ASSUMPTION: config lives in Python (app/config.py); the page passes
// IMAGE_MAX_EDGE and JPEG_QUALITY through createCapture, so the defaults here
// mirror that module's defaults and JPEG_QUALITY keeps its percent unit.

import { createFeedback } from "./feedback.js";

export const DEFAULT_MAX_EDGE = 1600;
export const DEFAULT_JPEG_QUALITY = 85;

const STYLE_ID = "capture-styles";

const NOTES = {
  idle: "Kamera hazırlanıyor…",
  camera: "",
  file: "Bu cihazda kamera yok gibi görünüyor. Fişin fotoğrafını galeriden ya da dosyadan seçebilirsin.",
  denied:
    "Kamera izni reddedildi. Telefonunun ayarlarından izin verebilir, ya da fişin fotoğrafını dosya olarak yükleyebilirsin.",
};

const CSS = `
.cap { display: flex; flex-direction: column; gap: .9rem; }
.cap-view { position: relative; display: grid; place-items: center; overflow: hidden;
  aspect-ratio: 3 / 4; border-radius: 1rem; background: #0b0d11;
  border: 1px solid rgba(255,255,255,.07); }
.cap-video { width: 100%; height: 100%; object-fit: cover; display: none; }
.cap-frame { position: absolute; inset: 7% 6%; display: none; pointer-events: none;
  border: 2px dashed rgba(74,222,128,.5); border-radius: .9rem; }
.cap-note { margin: 0; padding: 1.2rem 1.1rem; display: none; text-align: center;
  font-size: .9rem; line-height: 1.55; color: #b9bcc4; }
.cap-actions { display: flex; align-items: center; justify-content: center; gap: .8rem; }
.cap-shutter { display: none; min-width: 3.6rem; height: 3.6rem; padding: 0; cursor: pointer;
  border-radius: 50%; border: 3px solid #4ade80; background: rgba(74,222,128,.14);
  color: #e8e6e1; font: inherit; font-weight: 600;
  transition: transform .12s ease, background-color .2s ease; }
.cap-shutter:active { transform: scale(.92); }
.cap-shutter:disabled { opacity: .45; cursor: default; }
.cap-mute { display: none; align-items: center; justify-content: center;
  width: 2.4rem; height: 2.4rem; padding: 0; cursor: pointer;
  border-radius: 50%; border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.05); color: #b9bcc4;
  transition: color .2s ease, border-color .2s ease; }
.cap-mute[aria-pressed="true"] { color: #6b6f78; }
.cap-file { display: none; align-items: center; padding: .7rem 1.15rem; cursor: pointer;
  border-radius: .8rem; border: 1px solid rgba(74,222,128,.35);
  background: rgba(74,222,128,.1); color: #d7f5e3; font-size: .92rem; font-weight: 600; }
.cap-input { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.cap-error { margin: 0; font-size: .84rem; color: #fbbf24; }
.cap-error:empty { display: none; }
.cap[data-state="camera"] .cap-video,
.cap[data-state="camera"] .cap-frame,
.cap[data-state="camera"] .cap-shutter { display: block; }
.cap[data-state="camera"] .cap-mute { display: inline-flex; }
.cap[data-state="idle"] .cap-note,
.cap[data-state="file"] .cap-note,
.cap[data-state="denied"] .cap-note { display: block; }
.cap[data-state="file"] .cap-file,
.cap[data-state="denied"] .cap-file { display: inline-flex; }
`;

const ICON_SOUND =
  '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' +
  '<path d="M4 9v6h4l5 4V5L8 9H4Z" fill="currentColor"/>' +
  '<path d="M16.2 8.8a4.2 4.2 0 0 1 0 6.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
const ICON_MUTED =
  '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' +
  '<path d="M4 9v6h4l5 4V5L8 9H4Z" fill="currentColor"/>' +
  '<path d="M16 9.5l5 5M21 9.5l-5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

/** Cap the long edge at maxEdge, preserving the ratio; never upscale. */
export function scaleToFit(width, height, maxEdge) {
  const long = Math.max(width, height);
  if (!(long > 0) || !(maxEdge > 0) || long <= maxEdge) {
    return { width, height };
  }
  const k = maxEdge / long;
  return { width: Math.round(width * k), height: Math.round(height * k) };
}

function isPermissionDenied(err) {
  const name = (err && err.name) || "";
  return (
    name === "NotAllowedError" ||
    name === "PermissionDeniedError" ||
    name === "SecurityError"
  );
}

function injectStyles(doc) {
  if (!doc || doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

export function createCapture(options = {}) {
  const {
    container = null,
    mediaDevices = null,
    doc = globalThis.document,
    maxEdge = DEFAULT_MAX_EDGE,
    quality = DEFAULT_JPEG_QUALITY,
    onShot = () => {},
    onState = () => {},
    feedback = createFeedback(),
  } = options;

  injectStyles(doc);

  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const root = el("div", "cap");
  const view = el("div", "cap-view");
  const video = el("video", "cap-video");
  video.setAttribute("playsinline", "");
  video.setAttribute("autoplay", "");
  video.muted = true;
  const frame = el("div", "cap-frame");
  const note = el("p", "cap-note");
  const shutter = el("button", "cap-shutter", "Çek");
  shutter.setAttribute("type", "button");
  shutter.setAttribute("aria-label", "Fişi çek");
  const muteBtn = el("button", "cap-mute");
  muteBtn.setAttribute("type", "button");
  const input = el("input", "cap-input");
  input.setAttribute("type", "file");
  input.setAttribute("accept", "image/*");
  input.setAttribute("capture", "environment");
  const fileButton = el("label", "cap-file", "Dosyadan seç");
  fileButton.appendChild(input);
  const actions = el("div", "cap-actions");
  const error = el("p", "cap-error");

  view.appendChild(video);
  view.appendChild(frame);
  view.appendChild(note);
  actions.appendChild(muteBtn);
  actions.appendChild(shutter);
  actions.appendChild(fileButton);
  root.appendChild(view);
  root.appendChild(actions);
  root.appendChild(error);
  if (container) container.appendChild(root);

  // config.jpeg_quality() is a percent; toBlob wants a 0-1 fraction.
  const jpegQuality = quality > 1 ? quality / 100 : quality;
  let stream = null;
  let state = "idle";

  // the shell must render the loading note before start() resolves.
  setState("idle");

  function paintMute(muted) {
    muteBtn.innerHTML = muted ? ICON_MUTED : ICON_SOUND;
    muteBtn.setAttribute("aria-pressed", String(muted));
    muteBtn.setAttribute("aria-label", muted ? "Sesli çekimi aç" : "Sessiz çekimi aç");
  }
  paintMute(feedback.isMuted());
  muteBtn.addEventListener("click", () => paintMute(feedback.toggleMuted()));

  function setState(next) {
    state = next;
    root.setAttribute("data-state", next);
    note.textContent = NOTES[next] || "";
    shutter.disabled = next !== "camera";
    onState(next);
    return state;
  }

  function toJpeg(canvas, source, width, height, origin) {
    const size = scaleToFit(width, height, maxEdge);
    canvas.width = size.width;
    canvas.height = size.height;
    canvas.getContext("2d").drawImage(source, 0, 0, size.width, size.height);
    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) =>
          blob
            ? resolve({ blob, ...size, origin })
            : reject(new Error("jpeg encode failed")),
        "image/jpeg",
        jpegQuality,
      );
    });
  }

  async function start() {
    if (!mediaDevices || typeof mediaDevices.getUserMedia !== "function") {
      return setState("file");
    }
    try {
      stream = await mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      return setState("camera");
    } catch (err) {
      return setState(isPermissionDenied(err) ? "denied" : "file");
    }
  }

  function stop() {
    for (const track of (stream && stream.getTracks()) || []) track.stop();
    stream = null;
    video.srcObject = null;
    setState("idle");
  }

  function freeze() {
    if (!video.videoWidth || !video.videoHeight) return Promise.resolve(null);
    return toJpeg(
      doc.createElement("canvas"),
      video,
      video.videoWidth,
      video.videoHeight,
      "camera",
    );
  }

  async function fileToJpeg(file) {
    const bitmap = await globalThis.createImageBitmap(file);
    try {
      return await toJpeg(
        doc.createElement("canvas"),
        bitmap,
        bitmap.width,
        bitmap.height,
        "file",
      );
    } finally {
      if (bitmap.close) bitmap.close();
    }
  }

  shutter.addEventListener("click", async () => {
    error.textContent = "";
    feedback.click();
    try {
      const shot = await freeze();
      if (shot) onShot(shot);
    } catch {
      error.textContent = "Fotoğraf çekilemedi, tekrar dene.";
    }
  });

  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    error.textContent = "";
    try {
      onShot(await fileToJpeg(file));
    } catch {
      error.textContent = "Fotoğraf okunamadı, tekrar dene.";
    }
    input.value = "";
  });

  return {
    start,
    stop,
    freeze,
    fileToJpeg,
    getState: () => state,
    elements: { root, video, note, shutter, input, error, muteBtn },
  };
}
