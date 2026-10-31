import test from "node:test";
import assert from "node:assert/strict";
import { createCapture, scaleToFit } from "../../static/app/capture.js";

// --- minimal fake DOM: enough for createElement/appendChild/attributes/
// listeners plus a canvas that records what was encoded ---

function makeEl(tagName) {
  return {
    tagName,
    className: "",
    id: "",
    textContent: "",
    value: "",
    disabled: false,
    muted: false,
    width: 0,
    height: 0,
    videoWidth: 0,
    videoHeight: 0,
    srcObject: null,
    files: null,
    children: [],
    attrs: {},
    listeners: {},
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
    dispatch(type) {
      return Promise.all(
        (this.listeners[type] || []).map((fn) => fn({ target: this })),
      );
    },
    play() {
      this.played = true;
      return Promise.resolve();
    },
  };
}

function makeDoc() {
  const head = makeEl("head");
  const doc = {
    head,
    encodes: [],
    getElementById: (id) => head.children.find((child) => child.id === id) || null,
    createElement(tag) {
      const node = makeEl(tag);
      if (tag !== "canvas") return node;
      node.getContext = () => ({
        drawImage: (...args) => {
          node.drawn = args;
        },
      });
      node.toBlob = (callback, type, quality) => {
        doc.encodes.push({
          type,
          quality,
          width: node.width,
          height: node.height,
          drawn: node.drawn,
        });
        callback({ kind: "blob", type });
      };
      return node;
    },
  };
  return doc;
}

function makeStream() {
  const tracks = [{ stopped: false, stop() { this.stopped = true; } }];
  return { tracks, getTracks: () => tracks };
}

function makeDevices(streamOrError) {
  const calls = [];
  const devices = {
    calls,
    getUserMedia(constraints) {
      calls.push(constraints);
      if (streamOrError instanceof Error) {
        return Promise.reject(streamOrError);
      }
      return Promise.resolve(streamOrError);
    },
  };
  return devices;
}

function deniedError() {
  const err = new Error("no camera for you");
  err.name = "NotAllowedError";
  return err;
}

function missingError() {
  const err = new Error("no camera");
  err.name = "NotFoundError";
  return err;
}

function harness(options = {}) {
  const doc = makeDoc();
  const shots = [];
  const states = [];
  const capture = createCapture({
    doc,
    maxEdge: 1600,
    quality: 85,
    onShot: (shot) => shots.push(shot),
    onState: (state) => states.push(state),
    ...options,
  });
  return { doc, capture, shots, states, ...capture.elements };
}

// --- scaling math ---

test("scaleToFit caps the long edge without upscaling", () => {
  assert.deepEqual(scaleToFit(4000, 3000, 1600), { width: 1600, height: 1200 });
  assert.deepEqual(scaleToFit(1080, 1920, 1600), { width: 900, height: 1600 });
  assert.deepEqual(scaleToFit(800, 600, 1600), { width: 800, height: 600 });
  assert.deepEqual(scaleToFit(1600, 900, 1600), { width: 1600, height: 900 });
  assert.deepEqual(scaleToFit(0, 0, 1600), { width: 0, height: 0 });
  assert.deepEqual(scaleToFit(4000, 3000, 0), { width: 4000, height: 3000 });
});

// --- camera path ---

test("start opens the preview on the rear camera", async () => {
  const stream = makeStream();
  const { capture, states, video, shutter } = harness({
    mediaDevices: makeDevices(stream),
  });

  assert.equal(await capture.start(), "camera");
  assert.equal(capture.getState(), "camera");
  assert.deepEqual(states, ["idle", "camera"]);
  assert.equal(video.srcObject, stream);
  assert.equal(video.played, true);
  assert.equal(shutter.disabled, false);
  assert.deepEqual(video.attrs, { playsinline: "", autoplay: "" });
});

test("start asks for the environment camera", async () => {
  const doc = makeDoc();
  const devices = makeDevices(makeStream());
  const capture = createCapture({ doc, mediaDevices: devices });
  await capture.start();
  assert.deepEqual(devices.calls[0].video, {
    facingMode: { ideal: "environment" },
  });
  assert.equal(devices.calls[0].audio, false);
});

test("freeze encodes a JPEG capped at the configured max edge", async () => {
  const { doc, capture, video } = harness({
    mediaDevices: makeDevices(makeStream()),
  });
  await capture.start();
  video.videoWidth = 4000;
  video.videoHeight = 3000;

  const shot = await capture.freeze();

  assert.equal(shot.width, 1600);
  assert.equal(shot.height, 1200);
  assert.equal(shot.origin, "camera");
  assert.equal(shot.blob.kind, "blob");
  assert.equal(doc.encodes.length, 1);
  assert.equal(doc.encodes[0].type, "image/jpeg");
  assert.equal(doc.encodes[0].quality, 0.85);
  assert.deepEqual(doc.encodes[0].drawn, [video, 0, 0, 1600, 1200]);
});

test("freeze before the stream is ready yields nothing", async () => {
  const { doc, capture } = harness({ mediaDevices: makeDevices(makeStream()) });
  await capture.start();
  assert.equal(await capture.freeze(), null);
  assert.equal(doc.encodes.length, 0);
});

test("stop releases the camera tracks", async () => {
  const stream = makeStream();
  const { capture, video } = harness({ mediaDevices: makeDevices(stream) });
  await capture.start();

  capture.stop();

  assert.equal(stream.tracks[0].stopped, true);
  assert.equal(video.srcObject, null);
  assert.equal(capture.getState(), "idle");
});

// --- fallback paths ---

test("a file input with the capture attribute is always in the DOM", async () => {
  const { capture, input } = harness({ mediaDevices: makeDevices(makeStream()) });
  await capture.start();
  assert.equal(input.getAttribute("type"), "file");
  assert.equal(input.getAttribute("accept"), "image/*");
  assert.equal(input.getAttribute("capture"), "environment");
});

test("no camera API falls back to the file input", async () => {
  const { capture, states, note, shutter } = harness({ mediaDevices: null });

  assert.equal(await capture.start(), "file");
  assert.deepEqual(states, ["idle", "file"]);
  assert.match(note.textContent, /kamera yok/i);
  assert.equal(shutter.disabled, true);
});

test("denied permission takes the denial path and keeps the file input", async () => {
  const { capture, states, note, input, shutter } = harness({
    mediaDevices: makeDevices(deniedError()),
  });

  assert.equal(await capture.start(), "denied");
  assert.deepEqual(states, ["idle", "denied"]);
  assert.match(note.textContent, /izin/i);
  assert.equal(input.getAttribute("capture"), "environment");
  assert.equal(shutter.disabled, true);
});

test("a missing camera is a fallback, not a denial", async () => {
  const { capture } = harness({ mediaDevices: makeDevices(missingError()) });
  assert.equal(await capture.start(), "file");
});

// --- file path ---

test("fileToJpeg decodes the file and caps the long edge", async () => {
  const { doc, capture } = harness();
  let closed = false;
  const bitmap = { width: 1200, height: 2400, close: () => (closed = true) };
  const seen = [];
  globalThis.createImageBitmap = async (file) => {
    seen.push(file);
    return bitmap;
  };
  try {
    const shot = await capture.fileToJpeg({ name: "fis.jpg" });
    assert.deepEqual(seen, [{ name: "fis.jpg" }]);
    assert.equal(shot.width, 800);
    assert.equal(shot.height, 1600);
    assert.equal(shot.origin, "file");
    assert.equal(doc.encodes[0].quality, 0.85);
    assert.equal(closed, true);
  } finally {
    delete globalThis.createImageBitmap;
  }
});

test("picking a file emits a shot and re-arms the input", async () => {
  const { capture, shots, input, error } = harness();
  globalThis.createImageBitmap = async () => ({ width: 900, height: 1200 });
  try {
    input.files = [{ name: "fis.jpg" }];
    await input.dispatch("change");
    assert.equal(shots.length, 1);
    assert.equal(shots[0].origin, "file");
    assert.equal(shots[0].width, 900);
    assert.equal(input.value, "");
    assert.equal(error.textContent, "");
  } finally {
    delete globalThis.createImageBitmap;
  }
});

test("an unreadable file reports instead of throwing", async () => {
  const { capture, input, error } = harness();
  globalThis.createImageBitmap = async () => {
    throw new Error("corrupt");
  };
  try {
    input.files = [{ name: "bozuk.jpg" }];
    await input.dispatch("change");
    assert.match(error.textContent, /okunamadı/);
  } finally {
    delete globalThis.createImageBitmap;
  }
});

test("the shutter button emits a camera shot", async () => {
  const { capture, shots, shutter, video } = harness({
    mediaDevices: makeDevices(makeStream()),
  });
  await capture.start();
  video.videoWidth = 1600;
  video.videoHeight = 1200;

  await shutter.dispatch("click");

  assert.equal(shots.length, 1);
  assert.equal(shots[0].origin, "camera");
  assert.deepEqual([shots[0].width, shots[0].height], [1600, 1200]);
});

// --- styles ---

test("styles are injected once per document", async () => {
  const doc = makeDoc();
  createCapture({ doc });
  createCapture({ doc });
  assert.equal(doc.head.children.length, 1);
  assert.match(doc.head.children[0].textContent, /\.cap-shutter/);
});
