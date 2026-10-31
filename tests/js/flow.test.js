import test from "node:test";
import assert from "node:assert/strict";
import { ARALIK_MS, createFlow } from "../../static/app/flow.js";

// --- a clock that records every interval, so a leaked tick fails ----------

function saat() {
  const kurulan = [];
  const silinen = [];
  let sonraki = 1;

  const clock = {
    kurulan,
    silinen,
    kur(fn, ms) {
      const id = sonraki++;
      kurulan.push({ id, fn, ms });
      return id;
    },
    sil(id) {
      silinen.push(id);
    },
    tikle(id) {
      kurulan.find((t) => t.id === id).fn();
    },
    get acik() {
      return kurulan.filter((t) => !silinen.includes(t.id));
    },
  };
  return clock;
}

function harness(options = {}) {
  const clock = saat();
  const akis = createFlow({ kur: clock.kur, sil: clock.sil, ...options });
  return { clock, akis };
}

// The shape app.js uses: take the screen, await the network, paint only while
// still current, close the tick on the way out.
async function akisla(akis, { onTick, bekle, boya }) {
  const tur = akis.devral(onTick);
  try {
    const env = await bekle();
    if (!akis.canli(tur)) return false;
    boya(env);
    return true;
  } finally {
    akis.kapat(tur);
  }
}

// --- taking the screen ---------------------------------------------------

test("devral starts a single 500 ms tick and hands back a live token", () => {
  const { clock, akis } = harness();
  const tik = [];
  const tur = akis.devral(() => tik.push(1));

  assert.equal(clock.kurulan.length, 1);
  assert.equal(clock.kurulan[0].ms, ARALIK_MS);
  assert.equal(clock.kurulan[0].ms, 500);
  assert.ok(akis.canli(tur));

  clock.tikle(clock.kurulan[0].id);
  assert.deepEqual(tik, [1], "the tick repaints the flow that started it");
});

test("the tick interval can be retuned for tests", () => {
  const { clock, akis } = harness({ intervalMs: 10 });
  akis.devral(() => {});
  assert.equal(clock.kurulan[0].ms, 10);
});

test("devral retires the flow it replaces: the old token is dead", () => {
  const { akis } = harness();
  const ilk = akis.devral(() => {});
  const ikinci = akis.devral(() => {});

  assert.ok(!akis.canli(ilk), "a retired flow must not paint");
  assert.ok(akis.canli(ikinci));
});

test("devral clears the interval it replaces — never two loops at once", () => {
  const { clock, akis } = harness();
  akis.devral(() => {});
  akis.devral(() => {});

  assert.equal(clock.silinen.length, 1);
  assert.equal(clock.acik.length, 1, "exactly one tick survives the handover");
});

// --- leaving the screen --------------------------------------------------

test("dur kills the running tick and the token together", () => {
  const { clock, akis } = harness();
  const tur = akis.devral(() => {});
  const sonrasi = akis.dur();

  assert.equal(clock.acik.length, 0, "no 500 ms tick is left behind");
  assert.ok(!akis.canli(tur));
  assert.ok(akis.canli(sonrasi));
});

test("dur with nothing running clears nothing", () => {
  const { clock, akis } = harness();
  akis.dur();
  assert.deepEqual(clock.silinen, []);
});

// --- closing a flow that finished on its own -----------------------------

test("kapat stops the tick of the flow that is still current", () => {
  const { clock, akis } = harness();
  const tur = akis.devral(() => {});
  akis.kapat(tur);

  assert.equal(clock.acik.length, 0);
});

test("kapat by a superseded flow leaves the new flow's tick alone", () => {
  const { clock, akis } = harness();
  const ilk = akis.devral(() => {});
  const ikinci = akis.devral(() => {});
  const acikOlan = clock.acik[0].id;

  akis.kapat(ilk);
  assert.deepEqual(clock.acik.map((t) => t.id), [acikOlan]);

  akis.kapat(ikinci);
  assert.equal(clock.acik.length, 0);
});

// --- the bug this module exists for --------------------------------------

test("a history tap during a send leaves one flow on screen and one tick", async () => {
  const { clock, akis } = harness();
  const boyanan = [];
  let gonderBitti;

  const gonder = akisla(akis, {
    onTick: () => {},
    bekle: () => new Promise((resolve) => { gonderBitti = resolve; }),
    boya: (env) => boyanan.push(env),
  });

  const detay = akisla(akis, {
    onTick: () => {},
    bekle: async () => "detay",
    boya: (env) => boyanan.push(env),
  });

  assert.equal(clock.acik.length, 1, "the send's tick died with the handover");

  gonderBitti("gönderim");
  assert.deepEqual(await Promise.all([gonder, detay]), [false, true]);
  assert.deepEqual(boyanan, ["detay"], "only the detail the worker asked for paints");
  assert.equal(clock.acik.length, 0, "both flows closed their own ticks");
});

test("a retired tick is never re-armed: one interval per flow, all closed", () => {
  const { clock, akis } = harness();
  akis.devral(() => {});
  akis.devral(() => {});
  akis.dur();

  assert.equal(clock.kurulan.length, 2);
  assert.equal(clock.acik.length, 0);
});
