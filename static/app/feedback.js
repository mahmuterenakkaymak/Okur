// D1 capture feedback: a WebAudio shutter click plus a navigator.vibrate
// haptic, so the phone confirms the shot even in sunlight. The mute toggle
// silences the click; the haptic always stays.
//
// ASSUMPTION: "silent when the user has muted" covers the sound only — the
// vibrate is the silent pocket confirmation D1 exists for, so muting keeps it.

export const MUTE_KEY = "ocr.capture_muted";

// One short buzz: felt through a pocket, never annoying on a desk.
export const VIBE_MS = 18;

function readMuted(storage) {
  try {
    return !!storage && storage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeMuted(muted, storage) {
  try {
    if (!storage) return;
    if (muted) storage.setItem(MUTE_KEY, "1");
    else storage.removeItem(MUTE_KEY);
  } catch {
    // private mode / storage disabled: the toggle still works this session
  }
}

export function createFeedback(options = {}) {
  const {
    AudioCtx = globalThis.AudioContext || globalThis.webkitAudioContext || null,
    nav = globalThis.navigator || null,
    storage = globalThis.localStorage,
  } = options;

  let muted = readMuted(storage);
  let ctx = null;
  let noise = null;

  // A 50 ms white-noise burst is the raw material of a mechanical click;
  // one buffer is reused for every shot.
  function noiseBuffer() {
    if (!noise) {
      const frames = Math.ceil(ctx.sampleRate * 0.05);
      noise = ctx.createBuffer(1, frames, ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < frames; i += 1) data[i] = Math.random() * 2 - 1;
    }
    return noise;
  }

  function playClick() {
    if (!AudioCtx) return;
    try {
      if (!ctx) ctx = new AudioCtx();
      // Autoplay policy: the context starts suspended until a user gesture.
      if (ctx.state === "suspended" && typeof ctx.resume === "function") ctx.resume();
      const t0 = ctx.currentTime;
      const buffer = noiseBuffer();
      // Two-stage click: mirror slap, then a softer curtain follow-through.
      for (const [level, at] of [[0.55, 0], [0.3, 0.05]]) {
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        const edge = ctx.createBiquadFilter();
        edge.type = "highpass";
        edge.frequency.value = 1400;
        const env = ctx.createGain();
        env.gain.setValueAtTime(level, t0 + at);
        env.gain.exponentialRampToValueAtTime(0.001, t0 + at + 0.05);
        src.connect(edge).connect(env).connect(ctx.destination);
        src.start(t0 + at, 0, 0.05);
      }
    } catch {
      // audio blocked or unsupported: the haptic still confirms the shot
    }
  }

  /** One capture: the click (unless muted) and the haptic. */
  function click() {
    if (!muted) playClick();
    if (nav && typeof nav.vibrate === "function") {
      try {
        nav.vibrate(VIBE_MS);
      } catch {
        // engines that refuse vibration outside a gesture still got the click
      }
    }
  }

  function isMuted() {
    return muted;
  }

  function setMuted(next) {
    muted = !!next;
    writeMuted(muted, storage);
    return muted;
  }

  function toggleMuted() {
    return setMuted(!muted);
  }

  return { click, isMuted, setMuted, toggleMuted };
}
