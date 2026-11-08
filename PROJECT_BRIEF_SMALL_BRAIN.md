# Okur Run 2 — Small Brain: CPU structurer on Qwen3-VL-4B

## 1. Goal
Remove the stage-2 structurer's dependency on the 80B Strata model: run extraction of the
contract-v1 JSON locally on **Qwen3-VL-4B-Instruct (UD-IQ4_XS) via llama.cpp, CPU-only,
zero VRAM**, at production parity. The 2026-11-06 bake-off (see `spike/SMALL_BRAIN_BAKEOFF.md`)
measured 5/6 fixtures passing for every 4B arm versus 5/6 for the current 80B — parity —
while freeing the GPU entirely so the stack installs on customer hardware. The `/v1` contract,
the quality-mode escalation (Unsloth 27B :8888) and the manual mismatch-review flow stay
byte-identical in behavior.

## 2. Users and use cases
- Integrators: submit/GET receipts exactly as today; no visible change.
- Ops: installs the model with one script; the launcher owns/monitors the llama-server process.
- Admin (UI): sees per-job stage timings to watch the new latency profile.
- Product: a "minimum hardware" story (CPU box, ~4 GB spare RAM) for BusAIness deployments.

## 3. Scope
**In (v1):**
- Structurer backend selection: `small` (llama.cpp :8100) | `strata` (today's path, kept as
  env fallback). Default flips to `small` in M4.
- `include_image` config toggle: the VL-4B runs both modalities; default on. Data from
  acceptance test 3 decides a later text-only default (t4b demotion is a follow-up, not here).
- `run.py` launcher: start llama-server (health-checked, roll-call line), stop it on exit
  (no orphans), red-line with the installer path when model files are missing, and an
  explicit "port busy" message on conflict (the live-test's secondary finding).
- `scripts/install_small_brain.ps1`: downloads llama.cpp b12177 CPU build + Qwen3-VL-4B
  UD-IQ4_XS + mmproj-F16 into `%LOCALAPPDATA%\ocr-small-brain\` (env `OCR_SMALL_BRAIN_DIR`
  overrides), verifies SHA-256 against `scripts/small_brain_manifest.json`, retries the
  primary CDN once then falls back to `hf-mirror.com` (HF's Xet CDN stalls >30 s writes;
  proven 2026-11-06).
- Admin job detail: stage timings (ocr / structure / validate) per job.
- README + OPERATIONS: minimum-hardware line; STARTUP_WAIT_S note (OCR cold load ~90 s).
- Acceptance suite extension: a live-OCR gate script over `spike/fixtures_real` (3 real
  receipts, incl. handwriting) comparing against the recorded Strata baseline.

**Out (later / never):** PaddleOCR-VL (stage 1) replacement; `/v2` contract changes; GPU
acceleration for the small brain; multilingual receipts; automatic escalation to quality
mode (stays manual per Eren's decision); t4b text-only demotion (decide after test 3 data).

## 4. Method / architecture
No new services beyond one llama.cpp `llama-server` (CPU, `-ngl 0 -c 8192
--image-min-tokens 1024 --image-max-tokens 1024`, port 8100) managed by the launcher.
`app/structurer.py` gains a backend choice in its existing constructor plumbing; prompt,
defensive JSON extraction and `app/validator.py` arithmetic are untouched — the LLM never
owns a number. Config resolution order: env > `config/hybrid.json`-style app config >
defaults. `chat_template_kwargs.enable_thinking=false` stays on the request (T68 lesson).

## 5. Stack and environment
Python/FastAPI/SQLite as today. llama.cpp **b12177 CPU build** (MIT), Qwen3-VL-4B-Instruct
UD-IQ4_XS + mmproj-F16 (Apache-2.0). Windows 11 dev box; must run CPU-only on Linux later
(no OS-specific code beyond the launcher). Run: `python run.py` unchanged. Bake-off evidence:
`spike/SMALL_BRAIN_BAKEOFF.md`; harness (throwaway, outside repo): `D:\small-bench\bake.py`.

## 6. Data
Same fixtures as today (synthetic receipts) + `spike/fixtures_real` (real receipts, no
personal data; handwritten fuel/market notes). Privacy class unchanged.

## 7. Interfaces
- New config/env: `STRUCTURER_BACKEND=small|strata`, `SMALL_BRAIN_BASE_URL` (default
  `http://127.0.0.1:8100`), `SMALL_BRAIN_MODEL`, `STRUCTURER_INCLUDE_IMAGE=1|0`.
- `/v1/*` endpoints and the admin API: no behavior or schema change.
- run.py roll-call gains a fourth line (Small brain) with red/green states.
- Admin detail: `stage_ms: {ocr, structure, validate}` (additive field, ignore-if-unknown).

## 8. Constraints
Zero VRAM usage (hard: `-ngl 0`; the 5090 stays free — dev-box regression requirement).
RAM ≈ 4 GB for the model + context. Offline after install. Apache-2.0/MIT only. Worst-case
latency budget: ≤ 45 s/receipt on this CPU class (bake-off: 30.6 s mean with image). All 686
existing tests stay green.

## 9. Acceptance tests
1. Small brain live: the 6 repo fixtures score schema-valid 6/6 and validator-ok 5/6, with
   the only failure being `fis_benzin_foto` (bake-off parity).
2. Live-OCR gate: `gercek_market_1` and `gercek_bim_2` reach validator verdict `ok`;
   `gercek_elyazisi_3_kirp` is no worse than the recorded Strata baseline (not unreadable).
3. `STRUCTURER_INCLUDE_IMAGE=0` on the VL-4B: still 5/6 on the fixtures (informs the future
   t4b demotion decision; not a cutover gate).
4. Launcher with missing model files: red roll-call line naming `scripts\install_small_brain.ps1`,
   app still starts, jobs fail with a clear `small brain not installed` error, no traceback dumps.
5. Launcher with port 8100 already taken: explicit "port busy" red line; no silent uvicorn death.
6. Existing integration/contract tests pass unmodified; `/v1` schema unchanged.
7. Quality-mode rerun endpoint still targets :8888 and replaces result+meta as today.
8. Ctrl-C / app stop terminates llama-server (no orphan process holding 8100).

## 10. Milestones
- M1: backend plumbing — config keys, structurer backend selection, unit tests; default stays `strata`.
- M2: process & install — launcher ownership, health, fail-fast, port message, installer script + manifest.
- M3: toggle + observability — include_image toggle, admin stage timings, README/OPERATIONS updates.
- M4: acceptance + cutover — live-OCR gate script with recorded baseline, flip default to `small`, docs.

## 11. Open questions / risks
- Handwriting through stage 2 on a 4B is the least-probed case; gate 2 exists for exactly this.
- Customer CPU classes slower than this dev box — bake-off numbers are from a 5090-class
  desktop CPU; re-measure once real customer hardware exists.
- llama.cpp image-token budget (1024) mirrors the bake-off; if a future receipt style needs
  more, raising it costs time, not quality — tune later.
- HF Xet CDN instability: the installer must ship with the mirror fallback from day one.
