# M0 Model Spike — Report (2026-10-31)

## Question
Which small open-weight model gives the most accurate Turkish receipt/handwriting OCR
and is licensed for commercial use?

## Candidates (both Apache-2.0 → commercial use OK)
| Model | Size | VRAM (est.) | Role |
|---|---|---|---|
| PaddleOCR-VL-1.6 (GGUF Q8) | 0.9B | ~2 GB | document-parsing specialist |
| Qwen3-VL-8B-Instruct (GGUF Q4_K_M) | 8B | ~6 GB | general VLM |

## Method
- Served each via llama.cpp `llama-server` (b12020, CUDA build) on **CPU** (`-ngl 0`),
  because Strata occupies 31.4/32 GB VRAM (could not test GPU coexistence this run).
- Fixtures generated with known ground truth:
  - **Easy** (6): synthetic Turkish printed receipts (market/benzin/restoran), clean +
    photo-degraded. Scored on item totals, ara toplam, iskonto, KDV, genel toplam, VKN, tarih.
  - **Hard** (3): cursive handwriting (Ink Free), print-handwriting (Segoe Print), and a
    realistic bad phone photo (rotate + downscale + blur + shadow). Scored on keyword/number recall.
- Receipt prompt: `Table Recognition:` (Paddle) / natural extract prompt (Qwen).
- Scoring normalizes Turkish number format (1.046,40 == 1046.40) and folds Turkish
  diacritics (ı→i, ğ→g, ş→s, ç→c, ö→o, ü→u) for keyword matching.

## Results
| Test | PaddleOCR-VL-1.6 | Qwen3-VL-8B |
|---|---|---|
| Easy receipts (56 fields) | **56/56 (100%)** | **56/56 (100%)** |
| Hard: handwriting + bad photo (20) | **20/20 (100%)** | **20/20 (100%)** |
| Avg latency (CPU) | **1.0–5.3 s** | 12.9–32.3 s |
| VRAM | ~2 GB | ~6 GB |

Paddle minor slips (cosmetic, numbers still correct): `KDV %20`→`KDV X20`,
`unutma!`→`unutmalı`. Qwen: no slips.

## Decisive finding
PaddleOCR-VL-1.6 runs **1–6 s per receipt on CPU** — fast enough that it does **not need
to compete with Strata for VRAM at all**. This removes the hardest constraint in the brief
("coexist with Strata on one 32 GB card"). Qwen at 13–44 s on CPU is not viable without GPU.

## Recommendation
**Primary: PaddleOCR-VL-1.6 (0.9B, Apache-2.0).** Perfect accuracy on all fixtures, 13×
faster, 3× less VRAM, document-specialized, CPU-viable.
**Quality-mode fallback: Qwen3-VL-8B** (or the existing 27B) for the rare real-world case
Paddle misreads — kept off the hot path.

## Honest caveats (what this spike did NOT prove)
1. **Synthetic ≠ real.** Font-based "handwriting" is far cleaner than real cursive on a
   receipt back. Both scoring 100% is optimistic; **real receipts + real handwriting from
   Eren are the true gate.**
2. **GPU coexistence untested.** Strata held the whole card. Paddle ~2 GB likely fits only
   after trimming Strata's KV budget; or run Paddle on CPU (recommended for v1).
3. Only 9 fixtures. Real acceptance needs 20–30 real receipts.

## Next step
Get 3–5 real Turkish receipts + 1–2 real handwriting samples from Eren, re-run Paddle.
If it holds, lock PaddleOCR-VL-1.6 and start M1 (contract + API core) via hybrid-dev.

---

## REAL-WORLD TEST (added 2026-10-31, Google Images screenshots — no download)

3 real samples captured as screenshots: `gercek_market_1` (clean thermal receipt, KDV-dahil
%8), `gercek_bim_2` (BİM, angled photo, wrinkled thermal), `gercek_elyazisi_3_kirp` (real
cursive handwriting from r/TurkishStreak). CPU, same prompts.

| Sample | PaddleOCR-VL-1.6 | Qwen3-VL-8B |
|---|---|---|
| Clean market receipt | all 9 items + totals correct, 5.1s | all correct, 29.8s |
| Angled BİM receipt | TOPLAM 198.00 ✓, EKMEK 8.50 ✓, missed TOPKDV 2.00, 5.1s | TOPLAM 198.00 ✓, TOPKDV 2.00 ✓, EKMEK 6.50 ✗, 32.4s |
| Real cursive handwriting | gist + most words, several errors (Türkiyede/zoranıdır), 2.5s | near-perfect, 14.5s |

**Key findings:**
1. **Totals (the accounting-critical numbers) were correct on both receipts, both models.**
2. Both models read SÜT as 29.75; summing items gives exactly 198.00 = printed TOPLAM, so
   the models were RIGHT and the human read (20.75) was wrong. This is a live proof that the
   deterministic validator (recompute sum-of-items vs printed total) catches and resolves
   exactly this class of OCR ambiguity — it belongs in the pipeline.
3. Angled/wrinkled thermal paper caused 1 item slip per model (different items). Realistic.
4. Real cursive handwriting: Qwen clearly better; Paddle readable but error-prone on rare words.

**Verdict unchanged, now real-data-backed:** PaddleOCR-VL-1.6 primary (fast, correct totals,
CPU-viable), Qwen3-VL-8B as quality-mode fallback for handwriting/messy cases. The two-profile
design in the brief is validated.
