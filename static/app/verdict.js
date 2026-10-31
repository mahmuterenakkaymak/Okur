// D3 verdict feedback: the chip a receipt ends on. `ok` draws its checkmark
// stroke, `mismatch` shakes in amber, `unreadable` puts a one-tap re-shoot
// directly under the verdict instead of leaving the worker hunting for a button.
//
// ASSUMPTION: the offending field names stay in the result card's warning line
// (one list on screen), so the chip points at it with aria-describedby rather
// than repeating them.

const STYLE_ID = "verdict-styles";

// The warning paragraph app.js paints under the header lives in index.html.
const UYARI_ID = "sonuc-uyari";

const RENKLER = {
  ok: "chip-on",
  done: "chip-on",
  mismatch: "chip-off",
  unreadable: "chip-bad",
  failed: "chip-bad",
};

const YENIDEN = "Fişi yeniden çek";
const YENIDEN_IPUCU = "Işığı ayarla, fişi tümüyle kareye al.";

// 20x20 line icons on the chip's own colour; the check is one stroke so it
// can be drawn, the rest are static because their motion is the shake.
const IKONLAR = {
  ok: '<svg viewBox="0 0 20 20" width="13" height="13" aria-hidden="true" focusable="false"><path class="vd-cizgi" d="M3.6 10.6 7.7 14.7 16.4 5.3" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  mismatch:
    '<svg viewBox="0 0 20 20" width="13" height="13" aria-hidden="true" focusable="false"><path d="M10 3.4 17.6 16.6H2.4Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M10 8v3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.2" r="1.05" fill="currentColor"/></svg>',
  unreadable:
    '<svg viewBox="0 0 20 20" width="13" height="13" aria-hidden="true" focusable="false"><path d="M3 7.4h3.1l1.2-2.2h5.4l1.2 2.2H17v8.9H3Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="10" cy="11.7" r="2.8" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
};

const CSS = `
.verdict.vd-ikonlu::before { display: none; }
.vd-ikon { display: inline-flex; align-items: center; }
.vd-ikon svg { display: block; }
.vd-cizgi { stroke-dasharray: 19; stroke-dashoffset: 19;
  animation: vd-cizim .5s .12s ease-out forwards; }
@keyframes vd-cizim { to { stroke-dashoffset: 0; } }
.vd-salla { animation: vd-salla .5s cubic-bezier(.36,.07,.19,.97) both; }
@keyframes vd-salla {
  10%, 90% { transform: translateX(-1px); }
  20%, 80% { transform: translateX(2px); }
  30%, 50%, 70% { transform: translateX(-4px); }
  40%, 60% { transform: translateX(4px); }
}
.vd-yeniden {
  display: flex; width: 100%; align-items: center; justify-content: center;
  gap: .5rem; margin: .1rem 0 .5rem;
  border-color: rgba(248,113,113,.42); background: rgba(248,113,113,.14); color: #ffdada;
}
.vd-ipucu { margin: 0 0 .9rem; font-size: .8rem; line-height: 1.5; color: #8b8f99; }
@media (prefers-reduced-motion: reduce) {
  .vd-cizgi { animation: none; stroke-dashoffset: 0; }
  .vd-salla { animation: none; }
}
`;

function injectStyles(doc) {
  if (!doc || doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

/**
 * The verdict chip. `update(statusOf())` paints one verdict — the icon node is
 * rebuilt every time so the checkmark draw and the shake replay on a job that
 * is opened again from history; `update(null)` returns to idle.
 */
export function createVerdict(options = {}) {
  const {
    chip = null,
    detay = null,
    onYeniden = null,
    doc = globalThis.document,
  } = options;

  injectStyles(doc);

  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function cizDetay(key) {
    if (!detay) return;
    detay.textContent = "";
    if (key !== "unreadable") return;
    const btn = el("button", "btn vd-yeniden", YENIDEN);
    btn.setAttribute("type", "button");
    btn.addEventListener("click", () => {
      if (onYeniden) onYeniden();
    });
    detay.appendChild(btn);
    detay.appendChild(el("p", "vd-ipucu", YENIDEN_IPUCU));
  }

  function update(view) {
    if (!chip) return;
    const key = view ? view.verdict || view.status : null;
    const etiket = (view && view.label) || "";
    const svg = IKONLAR[key] || "";

    chip.textContent = "";
    const temel = `chip verdict ${RENKLER[key] || "chip-off"}${svg ? " vd-ikonlu" : ""}`;
    chip.className = temel;
    if (svg) {
      const ikon = el("span", "vd-ikon");
      ikon.innerHTML = svg;
      chip.appendChild(ikon);
    }
    chip.appendChild(el("span", "vd-etiket", etiket));

    const fields = (view && Array.isArray(view.fields) && view.fields) || [];
    if (key === "mismatch") {
      // Re-reading the layout restarts the shake for a job reopened in place.
      void chip.offsetWidth;
      chip.className = `${temel} vd-salla`;
      if (fields.length) chip.setAttribute("aria-describedby", UYARI_ID);
      else chip.removeAttribute("aria-describedby");
    } else {
      chip.removeAttribute("aria-describedby");
    }

    cizDetay(key);
  }

  update(null);

  return { update, elements: { chip, detay } };
}
