import test from "node:test";
import assert from "node:assert/strict";
import { createFeedback, MUTE_KEY, VIBE_MS } from "../../static/app/feedback.js";
import { createCapture } from "../../static/app/capture.js";

// --- fakes: a WebAudio context that records what was started, a vibrating
// navigator, a Map-backed storage, and a small DOM for the capture wiring ---

function makeCtxClass({ state = "running" } = {}) {
  const ctx = {
    state,
    currentTime: 0,
    sampleRate: 48000,
    destination: { name: "destination" },
    buffers: 0,
    resumed: 0,
    sources: [],
    filters: [],
    gains: [],
    resume() {
      this.state = "running";
      this.resumed += 1;
      return Promise.resolve();
    },
    createBuffer(channels, frames) {
      ctx.buffers += 1;
      const data = new Float32Array(frames);
      return { getChannelData: () => data, length: frames };
    },
    createBufferSource() {
      const src = {
        buffer: null,
        connect(next) {
          return next;
        },
        start(...args) {
          src.started = args;
          ctx.sources.push(src);
        },
      };
      return src;
    },
    createBiquadFilter() {
      const filter = {
        type: "",
        frequency: { value: 0 },
        connect(next) {
          return next;
        },
      };
      ctx.filters.push(filter);
      return filter;
    },
    createGain() {
      const gain = {
        gain: {
          setValueAtTime(value, at) {
            gain.from = [value, at];
          },
          exponentialRampToValueAtTime(value, at) {
            gain.to = [value, at];
          },
        },
        connect(next) {
          return next;
        },
      };
      ctx.gains.push(gain);
      return gain;
    },
  };
  return function FakeAudioContext() {
    return ctx;
  };
}

function makeNav(vibes) {
  return { vibrate: (pattern) => vibes.push(pattern) };
}

function makeStorage() {
  const map = new Map();
  return {
    map,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
  };
}

function makeEl(tagName) {
  return {
    tagName,
    className: "",
    id: "",
    textContent: "",
    innerHTML: "",
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
      return Promise.resolve();
    },
  };
}

function makeDoc() {
  const head = makeEl("head");
  const doc = {
    head,
    getElementById: (id) => head.children.find((child) => child.id === id) || null,
    createElement(tag) {
      const node = makeEl(tag);
      if (tag !== "canvas") return node;
      node.getContext = () => ({ drawImage: () => {} });
      node.toBlob = (callback, type) => callback({ kind: "blob", type });
      return node;
    },
  };
  return doc;
}

function makeStream() {
  const tracks = [{ stopped: false, stop() {} }];
  return { tracks, getTracks: () => tracks };
}

// --- the click sound ---

test("an unmuted click plays a two-stage WebAudio shutter burst", () => {
  const AudioCtx = makeCtxClass();
  const feedback = createFeedback({ AudioCtx, nav: null, storage: null });

  feedback.click();

  const ctx = new AudioCtx();
  assert.equal(ctx.sources.length, 2);
  assert.ok(ctx.sources.every((src) => src.started), "both stages started");
  assert.equal(ctx.filters.length, 2);
  assert.equal(ctx.filters[0].type, "highpass");
  assert.ok(ctx.gains[0].from[0] > ctx.gains[1].from[0], "second stage is softer");
  assert.ok(ctx.gains[0].to[1] > ctx.gains[0].from[1], "each stage decays");
});

test("the noise buffer is built once and reused across clicks", () => {
  const AudioCtx = makeCtxClass();
  const feedback = createFeedback({ AudioCtx, nav: null, storage: null });

  feedback.click();
  feedback.click();

  const ctx = new AudioCtx();
  assert.equal(ctx.buffers, 1);
  assert.equal(ctx.sources.length, 4);
});

test("a suspended context is resumed before playing", () => {
  const AudioCtx = makeCtxClass({ state: "suspended" });
  const feedback = createFeedback({ AudioCtx, nav: null, storage: null });

  feedback.click();

  assert.equal(new AudioCtx().resumed, 1);
});

test("a muted click makes no sound at all", () => {
  const AudioCtx = makeCtxClass();
  const feedback = createFeedback({ AudioCtx, nav: null, storage: null });
  feedback.setMuted(true);

  feedback.click();

  assert.equal(new AudioCtx().sources.length, 0);
});

test("without WebAudio the click degrades to silence, not an error", () => {
  const vibes = [];
  const feedback = createFeedback({ AudioCtx: null, nav: makeNav(vibes), storage: null });
  assert.doesNotThrow(() => feedback.click());
  assert.deepEqual(vibes, [VIBE_MS]);
});

// --- the haptic ---

test("every capture vibrates, muted or not", () => {
  const vibes = [];
  const feedback = createFeedback({
    AudioCtx: null,
    nav: makeNav(vibes),
    storage: null,
  });

  feedback.click();
  feedback.setMuted(true);
  feedback.click();

  assert.deepEqual(vibes, [VIBE_MS, VIBE_MS]);
});

test("without a vibrating navigator the click still plays", () => {
  const AudioCtx = makeCtxClass();
  const feedback = createFeedback({ AudioCtx, nav: null, storage: null });
  assert.doesNotThrow(() => feedback.click());
  assert.equal(new AudioCtx().sources.length, 2);
});

// --- the mute state ---

test("mute persists in storage and returns on the next visit", () => {
  const storage = makeStorage();
  createFeedback({ AudioCtx: null, nav: null, storage }).setMuted(true);
  assert.equal(storage.map.get(MUTE_KEY), "1");

  const revisit = createFeedback({ AudioCtx: null, nav: null, storage });
  assert.equal(revisit.isMuted(), true);
});

test("unmuting clears the stored flag", () => {
  const storage = makeStorage();
  const feedback = createFeedback({ AudioCtx: null, nav: null, storage });
  feedback.setMuted(true);
  feedback.setMuted(false);
  assert.equal(storage.map.has(MUTE_KEY), false);
  assert.equal(feedback.isMuted(), false);
});

test("toggleMuted flips and reports the new state", () => {
  const feedback = createFeedback({ AudioCtx: null, nav: null, storage: null });
  assert.equal(feedback.toggleMuted(), true);
  assert.equal(feedback.toggleMuted(), false);
});

test("a broken storage keeps the toggle working", () => {
  const storage = {
    getItem() {
      throw new Error("storage disabled");
    },
    setItem() {
      throw new Error("storage disabled");
    },
  };
  const feedback = createFeedback({ AudioCtx: null, nav: null, storage });
  assert.equal(feedback.isMuted(), false);
  assert.equal(feedback.toggleMuted(), true);
});

// --- capture wiring ---

function captureHarness(options = {}) {
  const doc = makeDoc();
  const clicks = [];
  const feedback = options.feedback || {
    muted: false,
    click: () => clicks.push(1),
    isMuted() {
      return this.muted;
    },
    toggleMuted() {
      this.muted = !this.muted;
      return this.muted;
    },
  };
  const capture = createCapture({
    doc,
    mediaDevices: { getUserMedia: () => Promise.resolve(makeStream()) },
    feedback,
    onShot: () => {},
    ...options,
  });
  return { capture, clicks, feedback, ...capture.elements };
}

test("the shutter button fires the capture feedback", async () => {
  const { capture, clicks, shutter, video } = captureHarness();
  await capture.start();
  video.videoWidth = 1600;
  video.videoHeight = 1200;

  await shutter.dispatch("click");

  assert.deepEqual(clicks, [1]);
});

test("the mute button starts unmuted with a pressed=false label", async () => {
  const { muteBtn } = captureHarness();
  assert.equal(muteBtn.getAttribute("aria-pressed"), "false");
  assert.equal(muteBtn.getAttribute("aria-label"), "Sessiz çekimi aç");
  assert.match(muteBtn.innerHTML, /svg/);
});

test("tapping the mute button mutes, repaints, and taps back", async () => {
  const { capture, feedback, muteBtn } = captureHarness();
  await capture.start();

  await muteBtn.dispatch("click");
  assert.equal(feedback.isMuted(), true);
  assert.equal(muteBtn.getAttribute("aria-pressed"), "true");
  assert.equal(muteBtn.getAttribute("aria-label"), "Sesli çekimi aç");

  await muteBtn.dispatch("click");
  assert.equal(feedback.isMuted(), false);
  assert.equal(muteBtn.getAttribute("aria-pressed"), "false");
});

test("the mute button is wired into the actions row next to the shutter", async () => {
  const { capture } = captureHarness();
  const actions = capture.elements.root.children.find((child) =>
    child.children.includes(capture.elements.shutter),
  );
  assert.ok(actions.children.includes(capture.elements.muteBtn));
});

test("capture styles cover the mute button", () => {
  const doc = makeDoc();
  createCapture({ doc, feedback: { click: () => {}, isMuted: () => false, toggleMuted: () => false } });
  assert.match(doc.head.children[0].textContent, /\.cap-mute/);
});
