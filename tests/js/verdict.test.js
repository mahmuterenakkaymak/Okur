import test from "node:test";
import assert from "node:assert/strict";
import { createVerdict } from "../../static/app/verdict.js";
import { statusOf } from "../../static/app/status.js";

// --- a DOM small enough for one chip and the slot under it ---

function makeEl(tagName) {
  const el = {
    tagName,
    className: "",
    innerHTML: "",
    attrs: {},
    style: {},
    children: [],
    handlers: {},
    reflows: 0,
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
    addEventListener(type, fn) {
      (this.handlers[type] ||= []).push(fn);
    },
    click() {
      for (const fn of this.handlers.click || []) fn({});
    },
    find(tag) {
      return this.children.find((child) => child.tagName === tag) || null;
    },
  };

  let text = "";
  Object.defineProperty(el, "textContent", {
    get() {
      return this.children.length
        ? this.children.map((child) => child.textContent).join("")
        : text;
    },
    set(value) {
      text = String(value);
      this.children.length = 0;
    },
  });
  Object.defineProperty(el, "offsetWidth", {
    get() {
      this.reflows += 1;
      return 0;
    },
  });
  return el;
}

function makeDoc() {
  const head = makeEl("head");
  return {
    head,
    getElementById: (id) => head.children.find((child) => child.id === id) || null,
    createElement: (tag) => makeEl(tag),
  };
}

function harness(extra = {}) {
  const doc = makeDoc();
  const chip = makeEl("span");
  const detay = makeEl("div");
  const dokunulan = [];
  const verdict = createVerdict({
    chip,
    detay,
    doc,
    onYeniden: () => dokunulan.push("cekim"),
    ...extra,
  });
  return { doc, chip, detay, dokunulan, update: verdict.update };
}

// the real status module drives the chip, so the two cannot drift apart
function durum(status, verdict = null, fields = []) {
  const validation = verdict ? { verdict, expected: {}, actual: {}, fields } : null;
  return statusOf({ job_id: "job-1", status, validation });
}

// --- ok: the checkmark draws itself ---

test("an ok verdict draws a green checkmark in place of the plain dot", () => {
  const { chip, update } = harness();
  update(durum("done", "ok"));

  assert.equal(chip.textContent, "Doğrulandı");
  assert.match(chip.className, /\bchip-on\b/);
  assert.match(chip.className, /\bvd-ikonlu\b/, "the dot steps aside for the icon");
  const ikon = chip.children[0];
  assert.match(ikon.innerHTML, /class="vd-cizgi"/);
  assert.match(ikon.innerHTML, /aria-hidden="true"/, "the label carries the verdict");
  assert.match(ikon.innerHTML, /<path /);
});

test("the checkmark is rebuilt on every paint so the draw replays", () => {
  const { chip, update } = harness();
  update(durum("done", "ok"));
  const bir = chip.children[0];

  update(durum("done", "ok"));
  assert.notEqual(chip.children[0], bir, "a fresh node restarts the stroke");
});

// --- mismatch: amber, shaking, pointing at the names ---

test("a mismatch turns the chip amber and shakes it", () => {
  const { chip, update } = harness();
  update(durum("done", "mismatch", ["items[2].toplam", "totals.kdv"]));

  assert.equal(chip.textContent, "Uyuşmazlık");
  assert.match(chip.className, /\bchip-off\b/);
  assert.match(chip.className, /\bvd-salla\b/);
  assert.equal(
    chip.getAttribute("aria-describedby"),
    "sonuc-uyari",
    "the field names live in the warning line under the header",
  );
});

test("the shake restarts when the same mismatch is opened again", () => {
  const { chip, update } = harness();
  update(durum("done", "mismatch", ["totals.kdv"]));
  const once = chip.reflows;

  update(durum("done", "mismatch", ["totals.kdv"]));
  assert.ok(chip.reflows > once, "a reflow between the class writes replays the shake");
  assert.match(chip.className, /\bvd-salla\b/);
});

test("an ok verdict neither shakes nor points at the warning line", () => {
  const { chip, update } = harness();
  update(durum("done", "mismatch", ["totals.kdv"]));
  update(durum("done", "ok"));

  assert.doesNotMatch(chip.className, /vd-salla/);
  assert.equal(chip.getAttribute("aria-describedby"), null);
});

// --- unreadable: one tap back to the camera ---

test("an unreadable verdict hands over a one-tap re-shoot", () => {
  const { chip, detay, dokunulan, update } = harness();
  update(durum("done", "unreadable"));

  assert.equal(chip.textContent, "Okunamadı");
  assert.match(chip.className, /\bchip-bad\b/);
  const dugme = detay.find("button");
  assert.equal(dugme.getAttribute("type"), "button");
  assert.equal(dugme.textContent, "Fişi yeniden çek");
  assert.match(detay.children[1].className, /vd-ipucu/);
  assert.match(detay.children[1].textContent, /kareye al/);

  dugme.click();
  assert.deepEqual(dokunulan, ["cekim"]);
});

test("the re-shoot affordance goes away with the next verdict", () => {
  const { detay, update } = harness();
  update(durum("done", "unreadable"));
  assert.ok(detay.children.length);

  update(durum("done", "ok"));
  assert.deepEqual(detay.children, []);
});

// --- the verdicts that get no icon ---

test("a failed job keeps the plain dot and offers no re-shoot", () => {
  const { chip, detay, update } = harness();
  update(durum("failed"));

  assert.equal(chip.textContent, "İşlenemedi");
  assert.match(chip.className, /\bchip-bad\b/);
  assert.doesNotMatch(chip.className, /vd-ikonlu/);
  assert.deepEqual(detay.children, []);
});

test("a done job whose verdict never arrived still paints", () => {
  const { chip, update } = harness();
  update(durum("done"));

  assert.equal(chip.textContent, "Bitti");
  assert.match(chip.className, /\bchip-on\b/);
});

// --- shapes that must not reach the screen as undefined ---

test("a mismatch with no field list points at nothing", () => {
  const { chip, update } = harness();
  update(statusOf({ job_id: "job-1", status: "done", validation: { verdict: "mismatch" } }));

  assert.match(chip.className, /\bvd-salla\b/);
  assert.equal(chip.getAttribute("aria-describedby"), null);
});

test("an envelope with no validation at all still paints", () => {
  const { chip, update } = harness();
  update(statusOf({ job_id: "job-1", status: "running" }, { elapsedMs: 2000 }));

  assert.equal(chip.textContent, "Okunuyor");
  assert.match(chip.className, /\bchip-off\b/);
});

test("update(null) puts the chip back to idle", () => {
  const { chip, detay, update } = harness();
  update(durum("done", "unreadable"));

  update(null);
  assert.equal(chip.textContent, "");
  assert.match(chip.className, /^chip verdict chip-off$/);
  assert.deepEqual(detay.children, []);
});

test("a verdict without a detail slot still paints the chip", () => {
  const chip = makeEl("span");
  const verdict = createVerdict({ chip, detay: null, doc: makeDoc() });

  assert.doesNotThrow(() => verdict.update(durum("done", "unreadable")));
  assert.equal(chip.textContent, "Okunamadı");
});

// --- the motion ---

test("the injected styles draw the check, shake the chip, and respect reduced motion", () => {
  const { doc } = harness();
  const css = doc.head.children[0].textContent;

  assert.match(css, /\.vd-cizgi\s*\{[^}]*stroke-dashoffset:\s*19/);
  assert.match(css, /@keyframes vd-cizim\s*\{\s*to\s*\{\s*stroke-dashoffset:\s*0/);
  assert.match(css, /\.vd-salla\s*\{[^}]*animation:\s*vd-salla/);
  assert.match(css, /@keyframes vd-salla/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});

test("the styles are injected once, however many chips are built", () => {
  const doc = makeDoc();
  createVerdict({ chip: makeEl("span"), doc });
  createVerdict({ chip: makeEl("span"), doc });

  assert.equal(doc.head.children.length, 1);
});
