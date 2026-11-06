// The worker's view of one job: the four server statuses (plus the verdict a
// done job carries) become the Turkish stage to read, a fraction for the
// progress bar, and a stale flag once a live job stops moving.
//
// ASSUMPTION: the API reports only queued/running/done/failed, so the two
// running sub-stages are timed off the spike's numbers (OCR 1-5 s on CPU,
// structuring the slower pass) instead of a server-side stage field.

export const STALE_AFTER_MS = 60000;
export const OCR_BUDGET_MS = 8000;

// id -> what the worker sees; `progress` feeds the bar, `hint` the line below it.
export const STAGES = {
  queued: {
    label: "Sırada",
    hint: "Fiş sunucuya ulaştı, sırasını bekliyor.",
    progress: 0.05,
  },
  ocr: {
    label: "Okunuyor",
    hint: "Fişin üzerindeki yazılar okunuyor.",
    progress: 0.35,
  },
  structuring: {
    label: "Yapılandırılıyor",
    hint: "Ürünler, tutarlar ve KDV yerlerine yerleştiriliyor.",
    progress: 0.7,
  },
  verified: {
    label: "Doğrulandı",
    hint: "Tutarlar fişle karşılaştırıldı, her şey tutuyor.",
    progress: 1,
  },
  mismatch: {
    label: "Uyuşmazlık",
    hint: "Bazı tutarlar fişle uyuşmuyor, bir göz at.",
    progress: 1,
  },
  unreadable: {
    label: "Okunamadı",
    hint: "Bu fiş okunamadı, ışığı ayarlayıp bir kez daha çek.",
    progress: 1,
  },
  done: {
    label: "Bitti",
    hint: "Fiş işlendi.",
    progress: 1,
  },
  failed: {
    label: "İşlenemedi",
    hint: "Bu fiş işlenemedi, tekrar deneyebilirsin.",
    progress: 1,
  },
};

// The live chain the stepper walks: Sırada -> Okunuyor -> Yapılandırılıyor -> Doğrulandı.
export const PIPELINE = ["queued", "ocr", "structuring", "verified"];

const STALE_HINT = "Bu fiş diğerlerden uzun sürüyor, kuyruk yoğun olabilir.";
const TERMINAL = { done: true, failed: true };
const VERDICT_STAGE = { ok: "verified", mismatch: "mismatch", unreadable: "unreadable" };

function positive(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

// The job's own one-line reason ("small brain not installed — …"); only a
// failed job carries it, every other envelope simply has no such field.
function sebep(job) {
  return typeof job.error === "string" ? job.error.trim() : "";
}

/** Which stage a job is in; running advances with the time it has been live. */
export function stageIdFor(status, elapsedMs = 0, verdict = null) {
  if (status === "failed") return "failed";
  if (status === "done") return VERDICT_STAGE[verdict] || "done";
  if (status === "running") return positive(elapsedMs) < OCR_BUDGET_MS ? "ocr" : "structuring";
  return "queued";
}

/**
 * Envelope (full or the key-scoped lite row) + how long it has been live ->
 * the labels, fraction and stale flag one render of the status needs.
 */
export function statusOf(envelope, { elapsedMs = 0, staleAfterMs = STALE_AFTER_MS } = {}) {
  const job = envelope || {};
  const status = job.status || "queued";
  const validation = job.validation || null;
  const verdict = (validation && validation.verdict) || job.verdict || null;
  const elapsed = positive(elapsedMs);
  const id = stageIdFor(status, elapsed, verdict);
  const stage = STAGES[id];
  const finished = TERMINAL[status] === true;
  const stale = !finished && elapsed > positive(staleAfterMs);
  const reason = sebep(job);

  return {
    id,
    status,
    verdict,
    finished,
    stale,
    label: stage.label,
    hint: id === "failed" && reason ? reason : stale ? STALE_HINT : stage.hint,
    progress: stage.progress,
    reason,
    fields: (validation && Array.isArray(validation.fields) && validation.fields) || [],
    seconds: Math.floor(elapsed / 1000),
  };
}
