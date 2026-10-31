// D2 live pipeline feedback: the receipt's four Turkish stages as a row the
// worker reads at a glance — the highlight slides from one stage to the next
// while the elapsed seconds tick beside the headline.
//
// ASSUMPTION: statusOf() is the only stage source, so a finished job always
// closes the chain; the row never freezes mid-pipeline on a verdict.

import { PIPELINE, STAGES } from "./status.js";

const STYLE_ID = "stages-styles";

// The dot-to-dot line runs between the first and the last dot, i.e. from 1/8
// of the row to 7/8; the fill is a fraction of that 75 %.
const TRACK = 75;

const CSS = `
.pz { position: relative; margin: .15rem 0 .9rem; }
.pz-yol, .pz-dolgu { position: absolute; top: .41rem; height: 2px; border-radius: 999px; }
.pz-yol { left: 12.5%; right: 12.5%; background: rgba(255,255,255,.1); }
.pz-dolgu { left: 12.5%; width: 0; background: #4ade80; transition: width .5s ease; }
.pz-adimlar { position: relative; display: grid; grid-template-columns: repeat(4, 1fr);
  gap: .35rem; margin: 0; padding: 0; list-style: none; }
.pz-adim { display: flex; flex-direction: column; align-items: center; gap: .34rem;
  font-size: .62rem; line-height: 1.25; text-align: center; letter-spacing: -.005em;
  color: #6b6f78; transition: color .35s ease; }
.pz-nokta { width: .95rem; height: .95rem; border-radius: 50%; background: #171a21;
  border: 2px solid rgba(255,255,255,.18);
  transition: background-color .35s ease, border-color .35s ease; }
.pz-adim.bitti { color: #b9bcc4; }
.pz-adim.bitti .pz-nokta { background: #4ade80; border-color: #4ade80; }
.pz-adim.su { color: #e8e6e1; font-weight: 600; }
.pz-adim.su .pz-nokta { background: #4ade80; border-color: #4ade80;
  animation: pz-nabiz 1.7s ease-out infinite; }
@keyframes pz-nabiz {
  0% { box-shadow: 0 0 0 0 rgba(74,222,128,.5); }
  70%, 100% { box-shadow: 0 0 0 .45rem rgba(74,222,128,0); }
}
.pz[data-asama="mismatch"] .pz-adim:last-child { color: #fbbf24; }
.pz[data-asama="mismatch"] .pz-adim:last-child .pz-nokta { background: #fbbf24; border-color: #fbbf24; }
.pz[data-asama="unreadable"] .pz-adim:last-child,
.pz[data-asama="failed"] .pz-adim:last-child { color: #f87171; }
.pz[data-asama="unreadable"] .pz-adim:last-child .pz-nokta,
.pz[data-asama="failed"] .pz-adim:last-child .pz-nokta { background: #f87171; border-color: #f87171; }
@media (prefers-reduced-motion: reduce) {
  .pz-adim.su .pz-nokta { animation: none; }
  .pz-dolgu, .pz-adim, .pz-nokta { transition: none; }
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
 * The live stage row. `sayac` is the elapsed-seconds node the row ticks;
 * `update(statusOf())` paints one tick, `update(null)` returns to idle.
 */
export function createStages(options = {}) {
  const { container = null, sayac = null, doc = globalThis.document } = options;

  injectStyles(doc);

  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const root = el("div", "pz");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", "İşlem adımları");
  const yol = el("span", "pz-yol");
  const dolgu = el("span", "pz-dolgu");
  const liste = el("ol", "pz-adimlar");
  const adimlar = PIPELINE.map((id) => {
    const adim = el("li", "pz-adim bekliyor");
    adim.appendChild(el("span", "pz-nokta"));
    adim.appendChild(el("span", "pz-etiket", STAGES[id].label));
    liste.appendChild(adim);
    return adim;
  });
  root.appendChild(yol);
  root.appendChild(dolgu);
  root.appendChild(liste);
  if (container) container.appendChild(root);

  function update(view) {
    if (!view) {
      root.setAttribute("data-asama", "bos");
      for (const adim of adimlar) adim.className = "pz-adim bekliyor";
      dolgu.style.width = "0%";
      if (sayac) sayac.textContent = "";
      return;
    }

    const found = PIPELINE.indexOf(view.id);
    const index = found === -1 ? adimlar.length - 1 : found;
    const ok = view.id !== "failed";
    root.setAttribute("data-asama", view.id);

    adimlar.forEach((adim, i) => {
      const bitti = i < index || (i === index && view.finished === true && ok);
      const su = i === index && view.finished !== true;
      adim.className = `pz-adim ${bitti ? "bitti" : su ? "su" : "bekliyor"}`;
      if (su) adim.setAttribute("aria-current", "step");
      else adim.removeAttribute("aria-current");
    });

    dolgu.style.width = `${(index / (adimlar.length - 1)) * TRACK}%`;
    if (sayac) {
      const sn = Number(view.seconds);
      sayac.textContent = Number.isFinite(sn) && sn >= 0 ? `${sn} sn` : "";
    }
  }

  update(null);

  return { update, elements: { root, dolgu, adimlar } };
}
