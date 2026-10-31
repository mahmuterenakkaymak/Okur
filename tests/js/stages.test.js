import test from "node:test";
import assert from "node:assert/strict";
import { createStages } from "../../static/app/stages.js";
import { statusOf } from "../../static/app/status.js";

// --- a DOM small enough for a row of four list items ---

function makeEl(tagName) {
  return {
    tagName,
    className: "",
    textContent: "",
    children: [],
    attrs: {},
    style: {},
    setAttribute(name, value) {
      this.attrs[name] = String(value);
    },
    getAttribute(name) {
      return name in this.attrs ? this.attrs[name] : null;
    },
    removeAttribute(name) {
      delete this.attrs[name];
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
  };
}

function makeDoc() {
  const head = makeEl("head");
  const gecenSure = makeEl("p");
  gecenSure.className = "sure";
  return {
    head,
    gecenSure,
    getElementById: (id) => {
      if (id === "gecen-sure") return gecenSure;
      return head.children.find((child) => child.id === id) || null;
    },
    createElement: (tag) => makeEl(tag),
  };
}

function harness() {
  const doc = makeDoc();
  const container = makeEl("div");
  const stages = createStages({ container, doc, sayac: doc.gecenSure });
  return { doc, container, sayac: doc.gecenSure, update: stages.update, ...stages.elements };
}

// the real status module drives the row, so the two cannot drift apart
function durum(status, elapsedMs = 0, verdict = null) {
  const validation = verdict ? { verdict, expected: {}, actual: {}, fields: [] } : null;
  return statusOf({ job_id: "job-1", status, validation }, { elapsedMs });
}

const classes = (adimlar) => adimlar.map((adim) => adim.className.replace("pz-adim ", ""));
const etiketler = (adimlar) => adimlar.map((adim) => adim.children[1].textContent);

// --- the row itself ---

test("the row shows the four Turkish stages in pipeline order", () => {
  const { adimlar, root, container } = harness();
  assert.deepEqual(etiketler(adimlar), ["Sırada", "Okunuyor", "Yapılandırılıyor", "Doğrulandı"]);
  assert.equal(root.getAttribute("aria-label"), "İşlem adımları");
  assert.ok(container.children.includes(root), "the row mounts into the status card");
});

test("an idle row has no stage lit and no elapsed time", () => {
  const { adimlar, sayac, dolgu } = harness();
  assert.deepEqual(classes(adimlar), ["bekliyor", "bekliyor", "bekliyor", "bekliyor"]);
  assert.equal(dolgu.style.width, "0%");
  assert.equal(sayac.textContent, "");
});

// --- the live chain ---

test("a queued job lights the first stage and starts the counter at zero", () => {
  const { adimlar, sayac, dolgu, update } = harness();
  update(durum("queued", 0));

  assert.deepEqual(classes(adimlar), ["su", "bekliyor", "bekliyor", "bekliyor"]);
  assert.equal(adimlar[0].getAttribute("aria-current"), "step");
  assert.equal(dolgu.style.width, "0%");
  assert.equal(sayac.textContent, "0 sn");
});

test("the highlight walks the chain while the job runs", () => {
  const { adimlar, sayac, dolgu, update } = harness();

  update(durum("running", 3000));
  assert.deepEqual(classes(adimlar), ["bitti", "su", "bekliyor", "bekliyor"]);
  assert.equal(adimlar[1].getAttribute("aria-current"), "step");
  assert.equal(adimlar[0].getAttribute("aria-current"), null, "only one stage is current");
  assert.equal(sayac.textContent, "3 sn");
  const okunuyorGenisligi = Number.parseFloat(dolgu.style.width);

  update(durum("running", 9000));
  assert.deepEqual(classes(adimlar), ["bitti", "bitti", "su", "bekliyor"]);
  assert.equal(sayac.textContent, "9 sn");
  assert.ok(
    Number.parseFloat(dolgu.style.width) > okunuyorGenisligi,
    "the line only grows",
  );
});

test("the counter ticks on every repaint", () => {
  const { sayac, update } = harness();
  const tikler = [];
  for (const ms of [4000, 5000, 6000]) {
    update(durum("running", ms));
    tikler.push(sayac.textContent);
  }
  assert.deepEqual(tikler, ["4 sn", "5 sn", "6 sn"]);
});

// --- the end of the chain ---

test("a verified receipt closes the chain with no live stage left", () => {
  const { adimlar, dolgu, sayac, update } = harness();
  const view = durum("done", 45000, "ok");
  update(view);

  assert.equal(view.id, "verified");
  assert.deepEqual(classes(adimlar), ["bitti", "bitti", "bitti", "bitti"]);
  assert.equal(adimlar.some((adim) => adim.getAttribute("aria-current")), false, "nothing pulses");
  assert.equal(dolgu.style.width, "75%");
  assert.equal(sayac.textContent, "45 sn");
});

test("a mismatch keeps the chain closed and hands the last stage the warning colour", () => {
  const { adimlar, root, update } = harness();
  root.setAttribute("data-asama", "queued"); // a stale value must not survive

  update(durum("done", 9000, "mismatch"));
  assert.equal(root.getAttribute("data-asama"), "mismatch");
  assert.deepEqual(classes(adimlar), ["bitti", "bitti", "bitti", "bitti"]);
});

test("an unreadable receipt marks the last stage red", () => {
  const { root, update } = harness();
  update(durum("done", 4000, "unreadable"));
  assert.equal(root.getAttribute("data-asama"), "unreadable");
});

test("a failed job never shows a completed final stage", () => {
  const { adimlar, root, update } = harness();
  update(durum("failed", 20000));
  assert.equal(root.getAttribute("data-asama"), "failed");
  assert.deepEqual(classes(adimlar), ["bitti", "bitti", "bitti", "bekliyor"]);
});

// --- shapes that must not reach the screen as NaN ---

test("a view with no usable seconds shows no counter", () => {
  const { sayac, update } = harness();
  update({ id: "ocr", finished: false });
  assert.equal(sayac.textContent, "");

  update({ id: "queued", finished: false, seconds: NaN });
  assert.equal(sayac.textContent, "");
});

test("update(null) puts the row back to idle and clears the counter", () => {
  const { adimlar, sayac, dolgu, update } = harness();
  update(durum("running", 12000));
  assert.notEqual(sayac.textContent, "");

  update(null);
  assert.deepEqual(classes(adimlar), ["bekliyor", "bekliyor", "bekliyor", "bekliyor"]);
  assert.equal(dolgu.style.width, "0%");
  assert.equal(sayac.textContent, "");
});

test("a row without a counter node still paints", () => {
  const stages = createStages({ container: null, doc: makeDoc() });
  assert.doesNotThrow(() => stages.update(durum("running", 2000)));
});

// --- the motion ---

test("the injected styles animate the fill, the live dot, and respect reduced motion", () => {
  const { doc } = harness();
  const css = doc.head.children[0].textContent;
  assert.match(css, /\.pz-dolgu\s*\{[^}]*transition:\s*width \.5s ease/);
  assert.match(css, /\.pz-adim\s*\{[^}]*transition:\s*color \.35s ease/);
  assert.match(css, /@keyframes pz-nabiz/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});

test("the styles are injected once, however many rows are built", () => {
  const { doc } = harness();
  createStages({ container: null, doc });
  createStages({ container: null, doc });
  assert.equal(doc.head.children.length, 1);
});
