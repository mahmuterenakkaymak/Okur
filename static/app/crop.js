// Crop sheet for the worker PWA: a fixed crop box over a pan/zoomable canvas,
// 90 degree rotation, and EXIF orientation applied before anything else, so the
// recorded crop rect and the stored JPEG live in the same upright pixels.
//
// ASSUMPTION: the crop rect is recorded in the pixels of the upright, rotated
// image the user cropped (turns and orientation travel with it), because the raw
// file's pixels never reach the server (PLAN decision 7 re-encodes anyway).

import { DEFAULT_JPEG_QUALITY, DEFAULT_MAX_EDGE, scaleToFit } from "./capture.js";

export const DEFAULT_INSET = 0.06;
export const MAX_ZOOM = 4;

const STYLE_ID = "crop-styles";

const NOTES = {
  empty: "Kırpılacak fotoğraf yok — önce fişi çek.",
  loading: "Fotoğraf hazırlanıyor…",
  ready: "",
};

const CSS = `
.crop { display: flex; flex-direction: column; gap: .9rem; }
.crop-stage { position: relative; display: grid; place-items: center; overflow: hidden;
  aspect-ratio: 3 / 4; border-radius: 1rem; background: #0b0d11;
  border: 1px solid rgba(255,255,255,.07); }
.crop-canvas { width: 100%; height: 100%; display: none; touch-action: none; cursor: grab; }
.crop-canvas:active { cursor: grabbing; }
.crop-frame { position: absolute; inset: 0; display: none; pointer-events: none;
  outline: 1px solid rgba(255,255,255,.8); box-shadow: 0 0 0 100vmax rgba(6,8,11,.62);
  background-image:
    repeating-linear-gradient(to right, rgba(255,255,255,.2) 0 1px, transparent 1px 33.333%),
    repeating-linear-gradient(to bottom, rgba(255,255,255,.2) 0 1px, transparent 1px 33.333%); }
.crop-note { position: absolute; inset: 0; margin: 0; display: none; place-items: center;
  padding: 1.4rem; text-align: center; font-size: .9rem; line-height: 1.55; color: #b9bcc4; }
.crop-bar { display: flex; align-items: center; justify-content: center; gap: .6rem; }
.crop-btn { display: none; align-items: center; padding: .62rem 1.05rem; cursor: pointer;
  border-radius: .8rem; border: 1px solid rgba(255,255,255,.14);
  background: rgba(255,255,255,.05); color: #e8e6e1; font: inherit; font-size: .9rem;
  font-weight: 600; transition: transform .12s ease, background-color .2s ease, opacity .2s ease; }
.crop-btn:active { transform: scale(.96); }
.crop-btn:disabled { opacity: .4; cursor: default; }
.crop-apply { border-color: rgba(74,222,128,.4); background: rgba(74,222,128,.16); color: #d7f5e3; }
.crop-hint { display: none; margin: 0; text-align: center; font-size: .78rem; color: #8b8f99; }
.crop-error { margin: 0; font-size: .84rem; color: #fbbf24; text-align: center; }
.crop-error:empty { display: none; }
.crop[data-state="ready"] .crop-canvas { display: block; }
.crop[data-state="ready"] .crop-frame { display: block; }
.crop[data-state="ready"] .crop-btn { display: inline-flex; }
.crop[data-state="ready"] .crop-hint { display: block; }
.crop[data-state="empty"] .crop-note,
.crop[data-state="loading"] .crop-note { display: grid; }
`;

function between(value, a, b) {
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return Math.min(Math.max(value, lo), hi);
}

/** EXIF orientation (1-8) from JPEG bytes; 1 when there is nothing readable. */
export function exifOrientation(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  try {
    if (view.getUint16(0) !== 0xffd8) return 1;
    let p = 2;
    while (p + 4 <= view.byteLength) {
      if (view.getUint8(p) !== 0xff) {
        p += 1;
        continue;
      }
      if (view.getUint32(p + 4) === 0x45786966) return tiffOrientation(view, p + 10);
      p += 2 + view.getUint16(p + 2);
    }
  } catch {
    return 1;
  }
  return 1;
}

function tiffOrientation(view, start) {
  const head = view.getUint16(start);
  if (head !== 0x4949 && head !== 0x4d4d) return 1;
  const little = head === 0x4949;
  const u16 = (offset) => view.getUint16(offset, little);
  const entries = start + view.getUint32(start + 4, little);
  for (let n = 0, count = u16(entries); n < count; n += 1) {
    const at = entries + 2 + n * 12;
    if (u16(at) === 0x0112) {
      const value = u16(at + 8);
      return value >= 1 && value <= 8 ? value : 1;
    }
  }
  return 1;
}

/** Upright size once the EXIF orientation is applied. */
export function orientationSize(width, height, orientation) {
  return orientation >= 5 && orientation <= 8
    ? { width: height, height: width }
    : { width, height };
}

/** Canvas matrix (a,b,c,d,e,f) drawing raw w×h pixels upright; w/h are the raw size. */
export function orientationTransform(orientation, width, height) {
  switch (orientation) {
    case 2:
      return [-1, 0, 0, 1, width, 0];
    case 3:
      return [-1, 0, 0, -1, width, height];
    case 4:
      return [1, 0, 0, -1, 0, height];
    case 5:
      return [0, 1, 1, 0, 0, 0];
    case 6:
      return [0, 1, -1, 0, height, 0];
    case 7:
      return [0, -1, -1, 0, height, width];
    case 8:
      return [0, -1, 1, 0, 0, width];
    default:
      return [1, 0, 0, 1, 0, 0];
  }
}

export function rotateSize(width, height, turns) {
  return ((turns % 4) + 4) % 4 % 2
    ? { width: height, height: width }
    : { width, height };
}

/** Canvas matrix for turns of 90 degree clockwise rotation; w/h are the output size. */
export function rotationMatrix(turns, width, height) {
  switch (((turns % 4) + 4) % 4) {
    case 1:
      return [0, 1, -1, 0, width, 0];
    case 2:
      return [-1, 0, 0, -1, width, height];
    case 3:
      return [0, -1, 1, 0, 0, height];
    default:
      return [1, 0, 0, 1, 0, 0];
  }
}

/** The crop box, inset by a fraction of the shorter edge so margins stay even. */
export function cropBox(width, height, inset = DEFAULT_INSET) {
  if (!(width > 0) || !(height > 0)) return { x: 0, y: 0, width: 0, height: 0 };
  const side = Math.min(width, height) * inset;
  return {
    x: side,
    y: side,
    width: width - side * 2,
    height: height - side * 2,
  };
}

/** Smallest scale that still covers the box, so no background ever shows inside it. */
export function coverScale(boxWidth, boxHeight, imageWidth, imageHeight) {
  if (!(imageWidth > 0) || !(imageHeight > 0)) return 1;
  return Math.max(boxWidth / imageWidth, boxHeight / imageHeight);
}

export function clampScale(scale, min) {
  return between(scale, min, min * MAX_ZOOM);
}

/** Keep the image covering the box while panning. */
export function clampOffset(box, imageWidth, imageHeight, scale, offset) {
  return {
    x: between(offset.x, box.x + box.width - imageWidth * scale, box.x),
    y: between(offset.y, box.y + box.height - imageHeight * scale, box.y),
  };
}

/** Whole-pixel rect of the image currently inside the box. */
export function cropRect(box, imageWidth, imageHeight, scale, offset) {
  const left = Math.round(between((box.x - offset.x) / scale, 0, imageWidth));
  const top = Math.round(between((box.y - offset.y) / scale, 0, imageHeight));
  return {
    x: left,
    y: top,
    width: Math.max(1, Math.round(between((box.x + box.width - offset.x) / scale, left, imageWidth)) - left),
    height: Math.max(1, Math.round(between((box.y + box.height - offset.y) / scale, top, imageHeight)) - top),
  };
}

function injectStyles(doc) {
  if (!doc || doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

export function createCropper(options = {}) {
  const {
    container = null,
    doc = globalThis.document,
    maxEdge = DEFAULT_MAX_EDGE,
    quality = DEFAULT_JPEG_QUALITY,
    inset = DEFAULT_INSET,
    onCrop = () => {},
  } = options;

  injectStyles(doc);

  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const root = el("div", "crop");
  const stage = el("div", "crop-stage");
  const canvas = el("canvas", "crop-canvas");
  const frame = el("div", "crop-frame");
  const note = el("p", "crop-note");
  const bar = el("div", "crop-bar");
  const rotate = el("button", "crop-btn crop-rotate", "Çevir");
  const reset = el("button", "crop-btn crop-reset", "Sıfırla");
  const done = el("button", "crop-btn crop-apply", "Tamam");
  const hint = el("p", "crop-hint", "Sürükleyerek kaydır, iki parmağınla yakınlaştır.");
  const error = el("p", "crop-error");

  for (const button of [rotate, reset, done]) {
    button.setAttribute("type", "button");
    button.disabled = true;
  }
  rotate.setAttribute("aria-label", "Fotoğrafı 90 derece çevir");
  reset.setAttribute("aria-label", "Çevirme ve yakınlaştırmayı sıfırla");
  done.setAttribute("aria-label", "Kırp ve gönder");

  stage.appendChild(canvas);
  stage.appendChild(frame);
  stage.appendChild(note);
  bar.appendChild(rotate);
  bar.appendChild(reset);
  bar.appendChild(done);
  root.appendChild(stage);
  root.appendChild(bar);
  root.appendChild(hint);
  root.appendChild(error);
  if (container) container.appendChild(root);

  const jpegQuality = quality > 1 ? quality / 100 : quality;
  const ctx = canvas.getContext("2d");
  const pointers = new Map();

  let bitmap = null;
  let base = null;
  let rotated = null;
  let view = { width: 0, height: 0 };
  let turns = 0;
  let orientation = 1;
  let scale = 1;
  let offset = { x: 0, y: 0 };
  let pinch = 0;
  let state = "idle";

  // the shell must render the empty note before load() resolves.
  setState("empty");

  function setState(next) {
    state = next;
    root.setAttribute("data-state", next);
    note.textContent = NOTES[next] || "";
    for (const button of [rotate, reset, done]) button.disabled = next !== "ready";
    return state;
  }

  function setError(message) {
    error.textContent = message;
  }

  function box() {
    return cropBox(view.width, view.height, inset);
  }

  function draw() {
    const dpr = globalThis.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, view.width, view.height);
    if (!rotated) return;
    ctx.save();
    ctx.translate(offset.x, offset.y);
    ctx.scale(scale, scale);
    ctx.drawImage(rotated, 0, 0);
    ctx.restore();
  }

  function paintFrame() {
    const rect = box();
    if (!rect.width || !rect.height) return;
    const percent = (value, total) => `${(value / total) * 100}%`;
    frame.style.left = percent(rect.x, view.width);
    frame.style.top = percent(rect.y, view.height);
    frame.style.width = percent(rect.width, view.width);
    frame.style.height = percent(rect.height, view.height);
  }

  function fit() {
    const dpr = globalThis.devicePixelRatio || 1;
    view = { width: canvas.clientWidth || 0, height: canvas.clientHeight || 0 };
    canvas.width = Math.round(view.width * dpr);
    canvas.height = Math.round(view.height * dpr);
    paintFrame();
    if (rotated) {
      const rect = box();
      scale = coverScale(rect.width, rect.height, rotated.width, rotated.height);
      offset = clampOffset(box(), rotated.width, rotated.height, scale, {
        x: rect.x + (rect.width - rotated.width * scale) / 2,
        y: rect.y + (rect.height - rotated.height * scale) / 2,
      });
    }
    draw();
  }

  function currentRect() {
    if (!rotated) return { x: 0, y: 0, width: 0, height: 0 };
    const rect = box();
    if (!rect.width || !rect.height) {
      return { x: 0, y: 0, width: rotated.width, height: rotated.height };
    }
    return cropRect(rect, rotated.width, rotated.height, scale, offset);
  }

  function zoomBy(factor) {
    if (!rotated || !(factor > 0)) return;
    const rect = box();
    const min = coverScale(rect.width, rect.height, rotated.width, rotated.height);
    const next = clampScale(scale * factor, min);
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    const k = next / scale;
    scale = next;
    offset = clampOffset(rect, rotated.width, rotated.height, scale, {
      x: cx - (cx - offset.x) * k,
      y: cy - (cy - offset.y) * k,
    });
    draw();
  }

  function pan(dx, dy) {
    if (!rotated) return;
    offset = clampOffset(box(), rotated.width, rotated.height, scale, {
      x: offset.x + dx,
      y: offset.y + dy,
    });
    draw();
  }

  function spin() {
    const size = rotateSize(base.width, base.height, turns);
    rotated = doc.createElement("canvas");
    rotated.width = size.width;
    rotated.height = size.height;
    const c = rotated.getContext("2d");
    const m = rotationMatrix(turns, size.width, size.height);
    c.transform(m[0], m[1], m[2], m[3], m[4], m[5]);
    c.drawImage(base, 0, 0);
  }

  /** Decode, undo the EXIF rotation and cap the long edge at maxEdge. */
  function normalize(image, exif) {
    const upright = orientationSize(image.width, image.height, exif);
    const size = scaleToFit(upright.width, upright.height, maxEdge);
    const canvas2 = doc.createElement("canvas");
    canvas2.width = size.width;
    canvas2.height = size.height;
    const c = canvas2.getContext("2d");
    const k = size.width / upright.width;
    const m = orientationTransform(exif, image.width, image.height);
    c.transform(m[0] * k, m[1] * k, m[2] * k, m[3] * k, m[4] * k, m[5] * k);
    c.drawImage(image, 0, 0);
    if (bitmap && bitmap !== image && bitmap.close) bitmap.close();
    return canvas2;
  }

  async function decode(source) {
    if (!source || typeof source.arrayBuffer !== "function") {
      return { image: source, exif: 1 };
    }
    const exif = exifOrientation(new Uint8Array(await source.arrayBuffer()));
    try {
      // "none" keeps the stored pixels, so the transform above is the only rotation.
      const image = await globalThis.createImageBitmap(source, {
        imageOrientation: "none",
      });
      return { image, exif };
    } catch {
      // a browser without that option has already applied EXIF itself.
      return { image: await globalThis.createImageBitmap(source), exif: 1 };
    }
  }

  async function load(source) {
    setError("");
    setState("loading");
    try {
      const { image, exif } = await decode(source);
      orientation = exif;
      bitmap = image;
      base = normalize(image, exif);
      turns = 0;
      spin();
      fit();
      setState("ready");
      return state;
    } catch {
      base = null;
      rotated = null;
      setState("empty");
      setError("Fotoğraf açılamadı, tekrar dene.");
      return null;
    }
  }

  function clear() {
    if (bitmap && bitmap.close) bitmap.close();
    bitmap = null;
    base = null;
    rotated = null;
    pointers.clear();
    draw();
    setState("empty");
  }

  async function apply() {
    if (!rotated) return null;
    const rect = currentRect();
    const out = doc.createElement("canvas");
    out.width = rect.width;
    out.height = rect.height;
    out.getContext("2d").drawImage(
      rotated,
      rect.x,
      rect.y,
      rect.width,
      rect.height,
      0,
      0,
      rect.width,
      rect.height,
    );
    const blob = await new Promise((resolve, reject) => {
      out.toBlob(
        (result) =>
          result ? resolve(result) : reject(new Error("jpeg encode failed")),
        "image/jpeg",
        jpegQuality,
      );
    });
    return {
      blob,
      width: rect.width,
      height: rect.height,
      rect,
      turns,
      orientation,
    };
  }

  rotate.addEventListener("click", () => {
    if (!rotated) return;
    turns = (turns + 1) % 4;
    spin();
    fit();
  });

  reset.addEventListener("click", () => {
    if (!rotated) return;
    turns = 0;
    spin();
    fit();
  });

  done.addEventListener("click", async () => {
    setError("");
    try {
      const crop = await apply();
      if (crop) onCrop(crop);
    } catch {
      setError("Kırpma başarısız oldu, tekrar dene.");
    }
  });

  canvas.addEventListener("pointerdown", (event) => {
    if (!rotated) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
    pinch = pointers.size === 2 ? spread() : 0;
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    const before = pointers.get(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size >= 2) {
      const distance = spread();
      zoomBy(pinch ? distance / pinch : 1);
      pinch = distance;
      return;
    }
    pan(event.clientX - before.x, event.clientY - before.y);
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    pinch = 0;
  }

  function spread() {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y) || 1;
  }

  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);

  canvas.addEventListener(
    "wheel",
    (event) => {
      if (!rotated) return;
      if (event.preventDefault) event.preventDefault();
      zoomBy(Math.exp(-event.deltaY * 0.0015));
    },
    { passive: false },
  );

  if (typeof globalThis.addEventListener === "function") {
    globalThis.addEventListener("resize", () => {
      if (rotated) fit();
    });
  }

  return {
    load,
    apply,
    clear,
    fit,
    getState: () => ({
      ready: state === "ready",
      turns,
      orientation,
      scale,
      rect: currentRect(),
    }),
    elements: { root, canvas, frame, note, rotate, reset, done, error },
  };
}
