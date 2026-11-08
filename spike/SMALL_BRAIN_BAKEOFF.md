# Bake-off: smallest structurer model (2026-11-06)

Question: can the stage-2 structurer (today: Qwen3.8-Flash-Next ~80B MoE on Strata :8080,
image + OCR text in, contract v1 JSON out) run on a much smaller, CPU-only model without
losing extraction quality? Harness: `D:\small-bench\bake.py` (throwaway), using the app's
own `PROMPT`, defensive JSON parser and `app.validator` over the 6 repo fixtures; OCR text
is the real stage-1 PaddleOCR-VL output from `bench_paddle.json`. temperature 0, seed fixed,
images at 1024 vision tokens, CPU llama-server b12177 `-ngl 0` (zero VRAM). Strata arms hit
the live :8080 like production.

## Matrix (PASS = schema + totals 0.01 + item count + validator verdict ok)

| arm | hw | PASS | avg s/receipt | benzin_c | benzin_f | market_c | market_f | restoran_c | restoran_f |
|---|---|---:|---:|---|---|---|---|---|---|
| strata_img (current prod, 80B) | GPU | **5/6** | 6.5 | ok | **X** | ok | ok | ok | ok |
| vl2b_img (Qwen3-VL-2B-IQ4_XS) | CPU | 4/6 | 21.6 | X | X | ok | ok | ok | ok |
| vl2b_text | CPU | 0/6 | 7.2 | X | X | X | X | X | X |
| vl4b_img (Qwen3-VL-4B-IQ4_XS) | CPU | **5/6** | 30.6 | ok | **X** | ok | ok | ok | ok |
| vl4b_text | CPU | **5/6** | 22.5 | ok | **X** | ok | ok | ok | ok |
| t4b_text (Qwen3-4B-Instruct-2507-IQ4_XS) | CPU | **5/6** | 15.8 | ok | **X** | ok | ok | ok | ok |

`fis_benzin_foto` (photographed single-line fuel receipt) is failed by **every** model including
the current 80B — it is a quality-mode escalation case, not a small-model regression.

## Failure anatomy (raw outputs saved per arm)

- vl2b benzin_clean: single-line table columns mis-assigned — octane "95" became `miktar`,
  litres 32.47 became `birim_fiyat`, unit price 53.19 dropped; totals transcribed fine so only
  the arithmetic validator catches it.
- vl2b benzin_foto: whole row shifted one column; OCR row `1.727,08` mis-parsed as `iskonto=1.72708`.
- vl2b_text 0/6: at 2B scale the unstructured OCR text stream is not enough — the model needs
  the image. At 4B scale text-only reaches parity (see vl4b_text / t4b_text).
- All 4B arms fail only benzin_foto, the exact same fixture as production — parity.

## Conclusions

1. **4B IQ4_XS on CPU = production parity** on this fixture set, at 16-31 s/receipt offline,
   zero VRAM. The 80B structurer leg is replaceable.
2. **The image leg is model-scale-dependent**: mandatory at 2B, dispensable at 4B on these
   fixtures. Real-OCR-failure robustness of text-only is untested (needs the live `spike/fixtures_real`
   run with PaddleOCR-VL :8081 up) — the brief must gate on it.
3. Speed cost of the switch: ~2.4x slower than the warm 80B (6.5 s -> 15.8 s text-only),
   in exchange for zero VRAM and a 2.1 GB model that fits any customer box.
4. Keep the escalation path: quality mode (Unsloth 27B :8888) still owns mismatch/unreadable;
   a 4B should not be trusted to self-escalate differently than today.
5. Caveats: 6 synthetic fixtures is a small set; single-vendor family (Qwen3); no
   el-yazisi/handwriting fixture through stage 2 yet; production sampling temperature not
   yet pinned to 0 for small models; `strata_text` arm not run.

Artifacts: `D:\small-bench\results-<arm>.json` (full raw model outputs per fixture),
`D:\small-bench\bake.py`, llama.cpp CPU b12177. Models: unsloth Qwen3-VL-2B/4B-Instruct IQ4_XS
+ mmproj-F16, Qwen3-4B-Instruct-2507 IQ4_XS (hf-mirror.com worked when HF's Xet CDN stalled).

## Follow-up (2026-11-07 05:50) — full-stack live OCR gate: PARITY DID NOT HOLD on real receipts

With the installed model (llama.cpp CPU, port 8100) and live PaddleOCR-VL :8081 over
`fixtures_real`: gercek_market_1 `mismatch` (totals byte-identical to the 80B baseline — the
model splits 10 line items where there are 9, and the arithmetic validator correctly rejects
items-sum != header); gercek_bim_2 `mismatch` (baseline also mismatched — savings/discount row);
gercek_elyazisi_3_kirp `unreadable` (same as 80B — honest fail, quality mode is the escape hatch).
Verdict: synthetic-fixture parity OVERSTATED real-world parity; the synthetic set is OCR-friendly.
Recommendation: hold `STRUCTURER_BACKEND=small` off the default (revert the T91 cutover), keep it
behind the env flag, and rebuild parity evidence on 8-10 real receipts before flipping. Item
segmentation (not transcription) is the failure mode — prompt-level few-shot for line-item
counting is the first fix to try.
