import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ZOOM,
  clampOffset,
  clampScale,
  coverScale,
  createCropper,
  cropBox,
  cropRect,
  exifOrientation,
  orientationSize,
  orientationTransform,
  rotateSize,
  rotationMatrix,
} from "../../static/app/crop.js";

// --- fake DOM: elements with attributes/styles/listeners plus canvases that
// record the 2d calls the cropper makes ---

function makeEl(tagName) {
  return {
    tagName,
    className: "",
    id: "",
    textContent: "",
    disabled: false,
    style: {},
    width: 0,
    height: 0,
    clientWidth: 0,
    clientHeight: 0,
    children: [],
    attrs: {},
    listeners: {},
    draws: [],
    transforms: [],
    setAttribute(name, value) {
      this.attrs[name] = String(value);
    },
    getAttribute(name) {
      return name in this.attrs ? this.attrs[name] : null;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener(type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    dispatch(type, event = {}) {
      return Promise.all(
        (this.listeners[type] || []).map((fn) => fn({ target: this, ...event })),
      );
    },
    getContext() {
      return {
        save: () => {},
        restore: () => {},
        clearRect: () => {},
        fillRect: () => {},
        translate: () => {},
        scale: () => {},
        drawImage: (...args) => this.draws.push(args),
        transform: (...args) => this.transforms.push(args),
        setTransform: (...args) => this.transforms.push(args),
      };
    },
    toBlob(callback, type, quality) {
      this.encoded = { type, quality };
      callback({ kind: "blob", type });
    },
    setPointerCapture() {},
  };
}

function makeDoc() {
  const head = makeEl("head");
  const canvases = [];
  const doc = {
    head,
    canvases,
    getElementById: (id) => head.children.find((child) => child.id === id) || null,
    createElement(tag) {
      const node = makeEl(tag);
      if (tag === "canvas") canvases.push(node);
      return node;
    },
  };
  return doc;
}

function harness(options = {}) {
  const doc = makeDoc();
  const crops = [];
  const cropper = createCropper({
    doc,
    maxEdge: 1600,
    quality: 85,
    onCrop: (crop) => crops.push(crop),
    ...options,
  });
  const canvas = cropper.elements.canvas;
  canvas.clientWidth = 900;
  canvas.clientHeight = 1200;
  return { doc, cropper, crops, ...cropper.elements };
}

// --- EXIF bytes ---

function jpegWithOrientation(value, big = false) {
  const bytes = [];
  const u16 = (v) =>
    big ? bytes.push((v >> 8) & 255, v & 255) : bytes.push(v & 255, (v >> 8) & 255);
  const u32 = (v) =>
    big
      ? bytes.push(
          (v >> 24) & 255,
          (v >> 16) & 255,
          (v >> 8) & 255,
          v & 255,
        )
      : bytes.push(v & 255, (v >> 8) & 255, (v >> 16) & 255, (v >> 24) & 255);
  const ascii = (text) => {
    for (const ch of text) bytes.push(ch.charCodeAt(0));
  };

  bytes.push(0xff, 0xd8); // SOI
  bytes.push(0xff, 0xe1); // APP1
  u16(6 + 26 + 2);
  ascii("Exif");
  bytes.push(0, 0);
  ascii(big ? "MM" : "II");
  u16(0x2a);
  u32(8); // IFD0 right after the TIFF header
  u16(1); // one entry
  u16(0x0112); // orientation
  u16(3); // SHORT
  u32(1);
  u16(value);
  u16(0);
  u32(0); // no next IFD
  bytes.push(0xff, 0xd9); // EOI
  return new Uint8Array(bytes);
}

test("exifOrientation reads the tag in both byte orders", () => {
  assert.equal(exifOrientation(jpegWithOrientation(6)), 6);
  assert.equal(exifOrientation(jpegWithOrientation(8), true), 8);
});

test("exifOrientation falls back to upright without a usable tag", () => {
  assert.equal(exifOrientation(new Uint8Array([0x89, 0x50, 0x4e, 0x47])), 1);
  assert.equal(exifOrientation(jpegWithOrientation(0)), 1);
  assert.equal(exifOrientation(jpegWithOrientation(6).slice(0, 12)), 1);
  assert.equal(exifOrientation(new Uint8Array([])), 1);
});

// --- orientation and rotation geometry ---

test("orientationSize swaps the edges for the rotated orientations", () => {
  assert.deepEqual(orientationSize(4000, 3000, 1), { width: 4000, height: 3000 });
  assert.deepEqual(orientationSize(4000, 3000, 3), { width: 4000, height: 3000 });
  assert.deepEqual(orientationSize(4000, 3000, 6), { width: 3000, height: 4000 });
  assert.deepEqual(orientationSize(4000, 3000, 8), { width: 3000, height: 4000 });
});

const corners = (width, height) => [
  [0, 0],
  [width, 0],
  [0, height],
  [width, height],
];
const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
const asCorners = (points) =>
  points.map(([x, y]) => `${Math.round(x)},${Math.round(y)}`).sort();

test("orientationTransform maps the raw pixels onto the upright box", () => {
  for (let orientation = 1; orientation <= 8; orientation += 1) {
    const out = orientationSize(4000, 3000, orientation);
    const mapped = corners(4000, 3000).map(([x, y]) =>
      apply(orientationTransform(orientation, 4000, 3000), x, y),
    );
    assert.deepEqual(
      asCorners(mapped),
      asCorners(corners(out.width, out.height)),
      `orientation ${orientation}`,
    );
  }
});

test("rotateSize turns the box every quarter turn", () => {
  assert.deepEqual(rotateSize(1200, 1600, 0), { width: 1200, height: 1600 });
  assert.deepEqual(rotateSize(1200, 1600, 1), { width: 1600, height: 1200 });
  assert.deepEqual(rotateSize(1200, 1600, 2), { width: 1200, height: 1600 });
  assert.deepEqual(rotateSize(1200, 1600, 4), { width: 1200, height: 1600 });
  assert.deepEqual(rotateSize(1200, 1600, -1), { width: 1600, height: 1200 });
});

test("rotationMatrix turns the pixels inside the output box", () => {
  for (const turns of [-1, 0, 1, 2, 3, 4]) {
    const out = rotateSize(1200, 1600, turns);
    const mapped = corners(1200, 1600).map(([x, y]) =>
      apply(rotationMatrix(turns, out.width, out.height), x, y),
    );
    assert.deepEqual(
      asCorners(mapped),
      asCorners(corners(out.width, out.height)),
      `turns ${turns}`,
    );
  }
});

// --- crop box, pan and zoom math ---

test("cropBox insets by the shorter edge and stays centred", () => {
  assert.deepEqual(cropBox(900, 1200, 0.06), {
    x: 54,
    y: 54,
    width: 792,
    height: 1092,
  });
  assert.deepEqual(cropBox(0, 0), { x: 0, y: 0, width: 0, height: 0 });
});

test("coverScale is the smallest scale covering the box", () => {
  assert.equal(coverScale(792, 1092, 1200, 1600), 0.6825);
  assert.equal(coverScale(792, 1092, 1600, 1200), 0.91);
  assert.equal(coverScale(792, 1092, 0, 0), 1);
});

test("clampScale allows four steps of zoom over the fit", () => {
  assert.equal(clampScale(0.2, 1), 1);
  assert.equal(clampScale(2, 1), 2);
  assert.equal(clampScale(99, 1), MAX_ZOOM);
});

test("clampOffset keeps the image covering the box", () => {
  const box = cropBox(900, 1200);
  const clamp = (offset) => clampOffset(box, 1200, 1600, 0.6825, offset);
  assert.deepEqual(clamp({ x: 40.5, y: 54 }), { x: 40.5, y: 54 });
  assert.deepEqual(clamp({ x: 999, y: 999 }), { x: 54, y: 54 });
  assert.deepEqual(clamp({ x: -999, y: -999 }), { x: 27, y: 54 });
});

test("cropRect reports whole pixels clamped to the image", () => {
  const box = cropBox(900, 1200);
  assert.deepEqual(cropRect(box, 1200, 1600, 0.6825, { x: 40.5, y: 54 }), {
    x: 20,
    y: 0,
    width: 1160,
    height: 1600,
  });
  assert.deepEqual(cropRect(box, 1200, 1600, 0.6825, { x: 54, y: 54 }), {
    x: 0,
    y: 0,
    width: 1160,
    height: 1600,
  });
  assert.deepEqual(cropRect(box, 1200, 1600, 2.73, { x: 40.5, y: 54 }), {
    x: 5,
    y: 0,
    width: 290,
    height: 400,
  });
});

// --- the cropper ---

function bitmapOf(width, height) {
  return { width, height, closed: false, close() { this.closed = true; } };
}

function stubBitmaps(bitmap, options = {}) {
  const calls = [];
  globalThis.createImageBitmap = async (source, opts) => {
    calls.push(opts);
    if (options.rejectWith && opts) throw new Error("unsupported");
    return bitmap;
  };
  return calls;
}

async function loadedCropper(options = {}) {
  const bitmap = options.bitmap || bitmapOf(4000, 3000);
  const calls = stubBitmaps(bitmap, options);
  const context = harness();
  const file = {
    arrayBuffer: async () =>
      (options.jpeg ?? jpegWithOrientation(6)).buffer,
  };
  const state = await context.cropper.load(file);
  return { ...context, bitmap, calls, state };
}

test("load applies EXIF orientation before capping the long edge", async () => {
  const { doc, cropper, calls, state } = await loadedCropper();
  const [canvas, base, rotated] = doc.canvases;

  assert.equal(state, "ready");
  assert.deepEqual(calls, [{ imageOrientation: "none" }]);
  // 4000x3000 stored, orientation 6 -> 3000x4000 upright -> 1200x1600 capped.
  assert.deepEqual([base.width, base.height], [1200, 1600]);
  assert.deepEqual(base.transforms[0], [0, 0.4, -0.4, 0, 1200, 0]);
  assert.deepEqual([rotated.width, rotated.height], [1200, 1600]);
  assert.equal(cropper.getState().orientation, 6);
  assert.equal(canvas.width, 900);
});

test("a browser that ignores the orientation option is not rotated twice", async () => {
  const { doc, state } = await loadedCropper({
    bitmap: bitmapOf(4000, 3000),
    rejectWith: true,
  });
  const [, base] = doc.canvases;
  assert.equal(state, "ready");
  assert.deepEqual([base.width, base.height], [1600, 1200]);
  // identity, only the 1600/4000 cap left in the matrix.
  assert.deepEqual(base.transforms[0], [0.4, 0, 0, 0.4, 0, 0]);
});

test("the crop rect covers the full height and trims the sides", async () => {
  const { cropper } = await loadedCropper();
  assert.deepEqual(cropper.getState().rect, {
    x: 20,
    y: 0,
    width: 1160,
    height: 1600,
  });
});

test("the frame is placed over the crop box", async () => {
  const { frame } = await loadedCropper();
  assert.deepEqual(frame.style, {
    left: "6%",
    top: "4.5%",
    width: "88%",
    height: "91%",
  });
});

test("buttons stay dead until a photo is loaded", async () => {
  const { rotate, done, error } = harness();
  assert.equal(rotate.disabled, true);
  assert.equal(done.disabled, true);
  assert.equal(error.textContent, "");
});

test("rotate turns the image and re-fits the view", async () => {
  const { doc, cropper, rotate } = await loadedCropper();
  await rotate.dispatch("click");
  const rotated = doc.canvases.at(-1);

  assert.deepEqual([rotated.width, rotated.height], [1600, 1200]);
  assert.equal(cropper.getState().turns, 1);
  assert.equal(cropper.getState().rect.height, 1200);
});

test("four turns come back to the first frame", async () => {
  const { cropper, rotate } = await loadedCropper();
  for (let n = 0; n < 4; n += 1) await rotate.dispatch("click");
  assert.equal(cropper.getState().turns, 0);
});

test("reset drops the rotation and the zoom", async () => {
  const { cropper, canvas, reset } = await loadedCropper();
  await canvas.dispatch("wheel", { deltaY: -1000 });
  await reset.dispatch("click");
  assert.equal(cropper.getState().turns, 0);
  assert.equal(cropper.getState().scale, coverScale(792, 1092, 1200, 1600));
});

test("dragging pans the image but never uncovers the box", async () => {
  const { cropper, canvas } = await loadedCropper();
  const before = cropper.getState().rect.x;

  await canvas.dispatch("pointerdown", { pointerId: 1, clientX: 400, clientY: 600 });
  await canvas.dispatch("pointermove", { pointerId: 1, clientX: 300, clientY: 600 });
  await canvas.dispatch("pointerup", { pointerId: 1, clientX: 300, clientY: 600 });
  assert.ok(cropper.getState().rect.x > before);

  await canvas.dispatch("pointerdown", { pointerId: 1, clientX: 300, clientY: 600 });
  await canvas.dispatch("pointermove", { pointerId: 1, clientX: 900, clientY: 600 });
  await canvas.dispatch("pointerup", { pointerId: 1, clientX: 900, clientY: 600 });
  assert.equal(cropper.getState().rect.x, 0);
});

test("the wheel zooms up to the ceiling and back down", async () => {
  const { cropper, canvas } = await loadedCropper();
  const fit = coverScale(792, 1092, 1200, 1600);

  await canvas.dispatch("wheel", { deltaY: -1000 });
  assert.equal(cropper.getState().scale, fit * MAX_ZOOM);
  await canvas.dispatch("wheel", { deltaY: 1000 });
  assert.equal(cropper.getState().scale, fit);
});

test("a pinch zooms with the fingers", async () => {
  const { cropper, canvas } = await loadedCropper();
  const fit = coverScale(792, 1092, 1200, 1600);

  await canvas.dispatch("pointerdown", { pointerId: 1, clientX: 300, clientY: 500 });
  await canvas.dispatch("pointerdown", { pointerId: 2, clientX: 500, clientY: 500 });
  await canvas.dispatch("pointermove", { pointerId: 2, clientX: 700, clientY: 500 });
  assert.equal(cropper.getState().scale, fit * 2);

  await canvas.dispatch("pointerup", { pointerId: 2, clientX: 700, clientY: 500 });
  await canvas.dispatch("pointermove", { pointerId: 1, clientX: 300, clientY: 400 });
  assert.equal(cropper.getState().scale, fit * 2);
});

test("apply encodes the crop and carries the rect for the record", async () => {
  const { doc, cropper } = await loadedCropper();
  const crop = await cropper.apply();
  const out = doc.canvases.at(-1);

  assert.equal(crop.blob.kind, "blob");
  assert.equal(out.encoded.type, "image/jpeg");
  assert.equal(out.encoded.quality, 0.85);
  assert.deepEqual([crop.width, crop.height], [1160, 1600]);
  assert.deepEqual(crop.rect, { x: 20, y: 0, width: 1160, height: 1600 });
  assert.deepEqual([crop.turns, crop.orientation], [0, 6]);
  assert.deepEqual(out.draws[0], [
    doc.canvases[2],
    20,
    0,
    1160,
    1600,
    0,
    0,
    1160,
    1600,
  ]);
});

test("Tamam hands the crop to the caller", async () => {
  const { crops, done, cropper } = await loadedCropper();
  await done.dispatch("click");
  assert.equal(crops.length, 1);
  assert.deepEqual(crops[0].rect, cropper.getState().rect);
});

test("an undecodable photo reports instead of throwing", async () => {
  globalThis.createImageBitmap = async () => {
    throw new Error("corrupt");
  };
  try {
    const { cropper, error, note } = harness();
    const state = await cropper.load({ arrayBuffer: async () => new Uint8Array(4).buffer });
    assert.equal(state, null);
    assert.equal(cropper.getState().ready, false);
    assert.match(error.textContent, /açılamadı/);
    assert.match(note.textContent, /fişi çek/);
    assert.equal(await cropper.apply(), null);
  } finally {
    delete globalThis.createImageBitmap;
  }
});

test("clear releases the decoded bitmap", async () => {
  const { cropper, bitmap } = await loadedCropper();
  cropper.clear();
  assert.equal(bitmap.closed, true);
  assert.equal(cropper.getState().ready, false);
});

test("styles are injected once per document", () => {
  const doc = makeDoc();
  createCropper({ doc });
  createCropper({ doc });
  assert.equal(doc.head.children.length, 1);
  assert.match(doc.head.children[0].textContent, /\.crop-frame/);
});
