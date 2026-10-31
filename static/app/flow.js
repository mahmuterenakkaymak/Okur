// The live screens belong to one flow at a time: the send in flight, or the
// history row the worker just tapped. `devral` takes the screen and hands back
// a token every await of that flow checks with `canli`, so a retired flow can
// never paint over its successor. The 500 ms tick belongs to the flow too:
// taking the screen — or leaving it with `dur` — clears the old interval, so a
// card the worker moved on from never keeps ticking in the background.

export const ARALIK_MS = 500;

export function createFlow(options = {}) {
  const intervalMs = options.intervalMs ?? ARALIK_MS;
  const kur = options.kur || globalThis.setInterval;
  const sil = options.sil || globalThis.clearInterval;

  let sira = 0;
  let timer = null;

  // Retires the running flow and stops its tick; returns the new token.
  function dur() {
    sira += 1;
    if (timer !== null) {
      sil(timer);
      timer = null;
    }
    return sira;
  }

  function devral(onTick) {
    const tur = dur();
    timer = kur(onTick, intervalMs);
    return tur;
  }

  // A flow that finished on its own closes its own tick; one that was already
  // superseded must not touch the timer its successor started.
  function kapat(tur) {
    if (tur === sira && timer !== null) {
      sil(timer);
      timer = null;
    }
  }

  function canli(tur) {
    return tur === sira;
  }

  return { devral, dur, kapat, canli };
}
