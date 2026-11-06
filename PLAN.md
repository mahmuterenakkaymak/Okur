# PLAN — OCR API (Field-Capture Receipt OCR, Contract v1)

Local-first receipt OCR: phone PWA → FastAPI :8090 → PaddleOCR-VL-1.6 (llama.cpp :8081)
→ Strata :8080 structuring → deterministic validator → frozen JSON contract v1.
M0 is done (spike/REPORT.md): PaddleOCR-VL-1.6 Q8_0 read every fixture correctly, runs
1–5 s **on CPU** (~2 GB VRAM), so it coexists with Strata without a GPU mode switch.

## Architecture

```
run.py ── starts ──> llama-server :8081 (PaddleOCR-VL GGUF, -ngl 0 CPU default)
   └───────────────> uvicorn app :8090
                        ├─ auth (X-API-Key, hashed, constant-time, rate limit)
                        ├─ SQLite queue (jobs table, worker thread)
                        │    stage1 ocr_client → stage2 structurer → stage3 validator
                        ├─ /v1/* REST (integrators, contract v1)
                        ├─ /api/me/* (worker PWA views)
                        ├─ /admin/* (review, corrections, exports, keys, status)
                        └─ /app (installable PWA: camera → crop/rotate → submit → history)
Tailscale serve → HTTPS on tailnet only. Images + DB under data/ (gitignored).
```

## File layout

```
run.py                     launcher (start/stop OCR + app, --no-browser)
app/
  config.py                all env-configurable values, top of file
  contract.py              pydantic v1 models; exports contract/contract_v1.schema.json
  validator.py             pure Python: recompute totals/KDV/iskonto → verdict
  db.py                    SQLite (WAL): api_keys, jobs, corrections, events
  auth.py                  key gen/hash (SHA-256), hmac.compare_digest, token bucket
  ocr_client.py            stage 1: OpenAI-compatible client → :8081
  structurer.py            stage 2: Strata :8080 (quality mode: Unsloth :8888)
  pipeline.py              stage1→2→3 orchestration, timings, unreadable path
  queue_worker.py          SQLite queue consumer, queued→running→done/failed, crash recovery
  routes_jobs.py           POST/GET /v1/jobs, idempotent client_ref
  routes_worker.py         /api/me/*
  routes_admin.py          PATCH corrections, exports, keys CRUD, status, rerun
  exports.py               JSON / CSV / XLSX (openpyxl, numeric cells)
  status.py                health probes + nvidia-smi VRAM + queue depth
  keys_cli.py              python -m app.keys add|list|revoke
  main.py                  app factory, middleware, OpenAPI, static mounts
static/app/                PWA: index.html, app.js, capture.js, crop.js, api.js,
                           status.js, style.css, manifest.webmanifest, sw.js, icon.svg
static/admin/              admin UI: index.html, admin.js, style.css
contract/contract_v1.schema.json
CONTRACT.md                human doc for integrators
scripts/
  fake_models.py           OpenAI-compatible stub servers (tests/smoke/demo only)
  smoke_e2e.py             real HTTP end-to-end smoke (app + fake models, ephemeral ports)
  serve_demo.py            demo server: fake models + seeded jobs from fixtures, :8090
  acceptance.py            brief §9 automatable acceptance checks
  tailscale_serve.ps1
tests/                     pytest (one file per module) + tests/js/ (node --test)
fixtures/ fixtures_hard/   committed synthetic corpus + ground truth
data/                      images + ocr.db (gitignored, KVKK: personal data)
```

## Decisions

1. **Python 3.12 + FastAPI + SQLite (WAL) + vanilla JS.** No ORM, no Celery/Redis, no
   npm/build step: ≤10 workers and ≤500 receipts/day fit a single process + one worker
   thread; a build pipeline would be pure liability. JS logic lives in ES modules
   testable with `node --test` (no bundler).
2. **OCR on CPU by default (`-ngl 0`), VRAM mode configurable.** Spike's decisive
   finding: 1–5 s/receipt on CPU means zero contention with Strata's 31 GB. `OCR_NGL`
   env flips to GPU later without code changes.
3. **Model servers are the only external boundary.** `ocr_client`/`structurer` take an
   injectable `httpx` transport. Unit/integration tests use `httpx.MockTransport` with
   canned model outputs *at the HTTP layer* — every internal module is the real one.
   `scripts/fake_models.py` serves those canned outputs over real HTTP for smokes, so
   smokes exercise real sockets, real queue, real pipeline.
4. **Contract v1 is code-generated.** `contract.py` (pydantic) is the single source of
   truth; `contract/contract_v1.schema.json` is exported from it and committed;
   `CONTRACT.md` documents it. `/v1/` is frozen — breaking changes go to `/v2/`.
5. **Idempotency:** `UNIQUE(key_id, client_ref)` in SQLite; a duplicate POST returns
   200 with the existing `job_id` (no re-queue). `client_ref` optional → null.
6. **Keys:** `ocrk_<40 hex>`, stored only as SHA-256, compared with
   `hmac.compare_digest(hash)` (constant-time on the hash). Per-key token-bucket rate
   limit → 429. Admin uses a separate `ADMIN_TOKEN` env + session cookie.
7. **Privacy:** uploaded images are re-encoded with Pillow (strips EXIF/GPS, applies
   orientation) and stored `data/images/<job_id>.jpg`. Served only to authenticated
   clients. `fixtures_real/` and `data/` are gitignored.
8. **Validator owns arithmetic; LLM never computes.** Validator recomputes line totals,
   ara toplam, iskonto, KDV (single- and multi-rate) from `items[]` and compares with
   model output; Turkish number format (`1.046,40`) normalized in one shared util.
   Verdicts: `ok | mismatch(fields) | unreadable`. Admin corrections re-run the
   validator so the verdict always reflects current data.
9. **Frontend prototype parity:** the old Flask app's proven UI ideas carry into the
   admin UI — Turkish labels, product table, totals/VAT summary, visible
   `_toplam_uyari`-style discrepancy panel (expected vs actual), raw JSON viewer.
10. **PWA camera with file fallback:** `getUserMedia` on phones; `<input type=file
    capture>` fallback on desktop/tests. Demo mode adds an "Örnek fiş" button so flows
    are reviewable without a camera.

## Contracts (data shapes between modules)

All external field names snake_case. Defaults when a field is missing: strings `""`,
numbers `0.0`, arrays `[]`, `para_birimi: "TRY"`, `quality_mode: false`,
`client_ref: null`, `okunamayan: []`.

1. **Job envelope (contract v1, API ⇄ integrator/PWA/admin):**
   `job_id` str(uuid), `status` `queued|running|done|failed`, `client_ref` str|null,
   `result` object|null (null until done), `validation` object|null,
   `meta {worker, captured_at ISO|null, received_at ISO, ocr_ms int, total_ms int,
   model str, quality_mode bool}`.
2. **result:** `header {isim, vergi_dairesi, vergi_no}`, `meta {tarih "dd.MM.yyyy",
   saat "HH:mm", no, tip}`, `items[] {ad str, miktar float, birim_fiyat float,
   toplam float}`, `totals {ara_toplam, iskonto, kdv, kdv_orani, toplam}` floats,
   `para_birimi`, `okunamayan str[]` (unreadable fragments, for quality-mode hints).
   Matches the committed `fixtures/*.json` ground-truth shape exactly.
3. **validation:** `verdict ok|mismatch|unreadable`, `expected {ara_toplam, iskonto,
   kdv, toplam}` (recomputed), `actual {...}` (model output), `fields str[]` — dotted
   paths of offenders (`items[2].toplam`, `totals.kdv`), `[]` when ok.
4. **OcrClient.transcribe(image_bytes, quality_mode) →** `{text str, ms int}`;
   raises `OcrError` on timeout/5xx.
5. **Structurer.structure(ocr_text, image_bytes) →** `result` dict (shape 2) + `ms`;
   raises `UnreadableError` when the model cannot produce schema-valid JSON.
6. **validate(result) →** validation block (shape 3). Pure function, no I/O.
7. **Queue row (db ⇄ worker):** job dict `{id, key_id, worker, client_ref, status,
   image_path, mode, result_json, validation_json, meta_json, error, created_at,
   started_at, finished_at}`.
8. **Export row (jobs ⇄ exports):** flat `{job_id, worker, client_ref, tarih, saat,
   firma, vergi_no, ara_toplam, iskonto, kdv, toplam, para_birimi, verdict,
   items_json, kalite_mode, gonderim_zamani}` — CSV/XLSX columns derive from exactly
   these keys; XLSX writes numbers as numbers.
9. **Status payload (status.py ⇄ /v1/status ⇄ admin page):**
   `{ocr {ok, latency_ms}, strata {ok, latency_ms}, unsloth {ok, latency_ms},
   vram {used_mb, total_mb, ok}, queue {queued, running, failed}}`.
10. **Worker views (`/api/me/*`):** `{jobs: [envelope-lite {job_id, status,
    client_ref, received_at, thumbnail_url, verdict, toplam}], total int}`;
    detail returns the full envelope + `image_url`.

**Run 2 additions (small brain — see the run-2 section at the end of this file):**

11. **Stage-2 backend choice (`config` ⇄ `structurer` ⇄ `pipeline` ⇄ `status` ⇄
    `run.py`):** `structurer_backend()` → `"small" | "strata"` (empty or unknown
    → the default, which is `"strata"` until M8 and `"small"` after); the default
    lives in `config.py` and is never hardcoded elsewhere. `stage2_model(quality_mode)`
    → the model name that will actually run (`unsloth_model()` in quality mode,
    `small_brain_model()` on small, `strata_model()` otherwise) — the one source of
    `meta.model`. `small_brain_base_url()` default `http://127.0.0.1:8100`,
    `small_brain_port()` default 8100, `structurer_include_image()` default `True`
    (`0|false|no` → False), obeyed **only** by the small backend — Strata and quality
    mode always send the image.
12. **Small-brain install (installer ⇄ `config` ⇄ launcher ⇄ job errors):**
    `%LOCALAPPDATA%\ocr-small-brain\` (env `OCR_SMALL_BRAIN_DIR`) holds
    `llama/llama-server.exe`, `models/<gguf>` and `models/<mmproj>`;
    `small_brain_ready()` is True only when all three files exist, and False is what
    paints the launcher line red and turns a stage-2 connection error into
    "small brain not installed → `scripts\install_small_brain.ps1`".
    `scripts/small_brain_manifest.json` rows: `{id, url, mirror_url?, dest, sha256,
    size_bytes}` — `dest` is always relative to the install dir, `sha256` is 64 hex
    and mandatory, a missing `mirror_url` means "primary CDN only".
13. **`stage_ms` (pipeline ⇄ `meta_json` ⇄ GET `/v1/jobs/{id}` ⇄ admin detail):**
    `{ocr, structure, validate}` ints; a missing key or a non-numeric value reads as
    `0`, and the admin detail shows `"—"` for a job that never ran. Additive only:
    no contract 1/2/3 field changes shape or meaning.

**Wholes (all parts that must follow when one changes):**
- A correction (PATCH) must update: stored result, re-run validation, `GET
  /v1/jobs/{id}`, admin detail, PWA result view, all three export formats.
- A quality-mode rerun must replace result, update `meta.model/quality_mode/*_ms`,
  re-validate, and refresh every view + exports.
- Key revoke must make further PWA calls 401 and the PWA must show the key-error state.
- Any contract field change must touch: contract.py, exported schema, CONTRACT.md,
  admin detail renderer, exports columns, PWA result view — one task, all parts.
- **Switching the stage-2 backend** touches, in one breath: `structurer`'s server
  choice, `pipeline`'s `meta.model` (via `config.stage2_model`), the launcher's
  roll-call line *and whether a dead Strata fails the start*, `status.py`'s stage-2
  probe, the fake-model stub's reported model id, the env blocks of `smoke_e2e` /
  `serve_demo`, every test that pins `config.strata_model()` or a three-service
  roll-call (`tests/test_pipeline.py`, `test_captured_at_survives.py`,
  `test_integration_m1.py`, `test_smoke_e2e.py`, `test_run_py.py`,
  `test_launcher_rollcall.py`), and the README/OPERATIONS default line.
- **`stage_ms`** touches: pipeline timings, `JobMeta` + regenerated
  `contract_v1.schema.json` + CONTRACT.md, the `queue_worker` meta merge (T52's rule:
  never drop a stored key), `serve_demo`'s seeded meta, and the admin detail line.
- **The roll-call** touches: `run.py` `SERVICES`/`LABELS`/`roll_call()`/`stop()`
  (spawn *and* stop, or a child is orphaned on 8100), `tests/test_run_py.py`,
  `tests/test_launcher_rollcall.py`, and the README troubleshooting rows.
- **The demo admin token** touches: `serve_demo` (which pins it), README and
  HIZLI-BASLANGIC's "log in with the token in `.env`" line, and `.hybrid/visual.json`.

## Milestones

- **M1 — Contract + API core:** config, contract v1 + schema + CONTRACT.md, validator,
  db, auth, model clients, pipeline, queue, jobs API, OpenAPI, E2E contract test,
  real-HTTP smoke. (T01–T13)
- **M2 — Worker PWA:** worker API, installable Turkish PWA, camera capture, crop/rotate,
  submit with live status, history, stuck-state recovery, delight pass. (T14–T26)
- **M3 — Admin UI:** auth, list/filter, detail with correction + discrepancy panel +
  raw JSON, PATCH corrections, exports JSON/CSV/XLSX, key management, status page,
  quality-mode rerun, keyboard shortcuts, delight pass. (T27–T37)
- **M4 — Ship:** run.py launcher, hardening (rate limits, size caps, image validation),
  Tailscale HTTPS, README/OPERATIONS, acceptance harness, launcher delight. (T38–T43)

## Delight

- **D1 (M2):** shutter click sound + `navigator.vibrate` haptic on capture — the phone
  confirms the shot even in sunlight with the phone in a pocket-handshake.
- **D2 (M2):** live pipeline stages in Turkish ("Sırada → Okunuyor → Yapılandırılıyor →
  Doğrulandı") with an elapsed-seconds counter ticking; queued jobs visibly move.
- **D3 (M2):** verdict chip: `ok` draws an animated green checkmark; `mismatch` shakes
  and turns amber with the offending field names; `unreadable` offers one-tap re-shoot.
- **D4 (M2):** friendly Turkish empty states with a hand-drawn inline-SVG receipt
  doodle ("Henüz fiş yok — ilk fişini çek!") and a pull-to-refresh spin.
- **D5 (M3):** status page with a live queue-depth sparkline and a VRAM gauge that
  turns amber past 90 % — the operator feels the machine.
- **D6 (M3):** slide-in toasts for every mutation ("Kaydedildi ✓", "Anahtar oluşturuldu
  — bir daha gösterilmeyecek") with undo-style follow-up on key creation (copy button).
- **D7 (M4):** launcher roll-call: each service gets a green ✓ line as it goes healthy
  (`OCR ✓  Strata ✓  Uygulama ✓`), then the admin UI opens itself; failures print the
  exact log path and the retry command.

---

# Run 2 — Small brain: the CPU structurer (Qwen3-VL-4B), M5–M8

Brief: `PROJECT_BRIEF_SMALL_BRAIN.md`. Stage 2 stops depending on the 80B Strata
box: extraction runs locally on **Qwen3-VL-4B-Instruct IQ4_XS** behind a
CPU-only llama.cpp `llama-server` on **127.0.0.1:8100** (`-ngl 0 -c 8192
--image-min-tokens 1024 --image-max-tokens 1024 --temp 0`), ≈4 GB RAM, zero VRAM,
30.6 s/receipt mean, 45 s budget. Bake-off (`spike/SMALL_BRAIN_BAKEOFF.md`): 5/6
fixtures pass = parity with the 80B; the only failure (`fis_benzin_foto`) fails on
the 80B too, so it stays a quality-mode escalation case.

## Architecture changes (delta only)

```
run.py ─ starts ──> llama-server :8081  PaddleOCR-VL (stage 1)                unchanged
   │      starts ─> llama-server :8100  Qwen3-VL-4B (stage 2, "small brain")   NEW: owned, health-checked, stopped on exit
   └─────────────> uvicorn app  :8090
                     └ pipeline stage 2 → Structurer(backend=config.structurer_backend())
                          small  → http://127.0.0.1:8100    default from M8
                          strata → http://127.0.0.1:8080    kept: STRUCTURER_BACKEND=strata (rollback = one env line)
                          quality_mode → Unsloth :8888      unchanged, always sends the image
```
Nothing else moves. Prompt, defensive JSON extraction, `validator` arithmetic,
`/v1` routes, the PWA and the exports are untouched; exactly one field is added
(`meta.stage_ms`, additive). The app never spawns a model server — only `run.py`
does, so tests and the demo stay process-free.

## File layout additions

```
app/config.py        + structurer_backend() stage2_model(qm) small_brain_base_url/port/model
                       structurer_include_image() small_brain_dir/server/model_file/mmproj_file
                       small_brain_ready()
app/structurer.py    + backend resolution in __init__ (quality mode wins), + include_image
app/pipeline.py      meta.model ← config.stage2_model(...)  + stage_ms timings
app/contract.py      JobMeta + stage_ms (regenerate contract/contract_v1.schema.json, CONTRACT.md)
app/status.py        the stage-2 probe follows the resolved backend (contract-9 keys unchanged)
run.py               4th tracked service + two red lines (not installed / port busy)
scripts/install_small_brain.ps1     NEW installer: CDN retry → hf-mirror, SHA-256, -Check, -Force
scripts/small_brain_manifest.json   NEW {id,url,mirror_url,dest,sha256,size_bytes}
scripts/small_brain_gate.py         NEW brief §9 gates 1+3 (6 fixtures ±image), SKIP when not installed
scripts/live_ocr_gate.py            NEW brief §9 gate 2 (3 real receipts vs recorded baseline)
scripts/live_ocr_baseline.json      NEW recorded Strata baseline {file: {verdict, total_ms}}
scripts/serve_demo.py               seeds stage_ms; pins ADMIN_TOKEN=demo for the visual review
tests/test_small_brain_backend.py   integration: real app+queue+pipeline against a real-socket stub
tests/test_small_brain_missing.py   the job's "not installed" reason, no traceback
tests/test_launcher_small_brain.py  red lines: missing files, busy port
tests/test_install_small_brain.py   manifest + script parse (no network)
tests/test_stage_ms.py  test_small_brain_gate.py  test_live_ocr_gate.py
```
**No new dependency.** The installer is PowerShell plus the two model files it
downloads; the gates use the httpx already installed. `pyproject.toml` stays a
pytest-config-only file and the venv is unchanged this run.

## Decisions (run 2)

- **R1 — one resolver.** Only `config.structurer_backend()` and
  `config.stage2_model(quality_mode)` know which brain runs. `structurer` picks the
  server from it, `pipeline` names it in `meta.model` through it, `status` probes it,
  `run.py` starts it. A backend branch anywhere else is a bug.
- **R2 — quality mode is untouched.** `quality_mode=True` still means Unsloth :8888
  with the image, whatever the backend. Escalation stays manual (Eren's call).
- **R3 — `include_image` defaults ON.** Text-only at 4B matches parity on the
  synthetic set (bake-off `vl4b_text` 5/6) but is untested against real OCR
  failures; gate 3 produces that data, the cutover does not depend on it.
- **R4 — the launcher owns the process, the app never does.** Contract 9 keeps its
  key names, so the Durum page's stage-2 chip follows the configured brain instead
  of showing a permanent red "Strata ✗" on a CPU-only box (brief §7 forbids an
  admin-API schema change, so no new key is invented).
- **R5 — a missing model is a red line, not a dead stack.** Missing files skip the
  spawn, print `scripts\install_small_brain.ps1`, and the app still serves jobs,
  which then fail with `small brain not installed — …` in the error column, the admin
  detail and the phone's failure line. No traceback, no nonzero start (gate 4).
- **R6 — port 8100 busy is named, not swallowed.** The launcher bind-probes before
  spawning and prints the port and the retry command; the app keeps running (gate 5).
- **R7 — installs go to `%LOCALAPPDATA%\ocr-small-brain`, never into the repo**
  (models/ and vendor/ are gitignored; a 2.1 GB file in a working tree is a tax on
  every clone). SHA-256 is verified before a file is moved into place, the primary
  CDN is retried once and then `hf-mirror.com` is used — HF's Xet CDN stalled >30 s
  on 2026-11-06, so the mirror ships on day one.
- **R8 — cutover last, rollback cheap.** The default flips to `small` only in M8,
  after both gates exist, and `STRUCTURER_BACKEND=strata` restores today's exact
  path: byte-identical request body, same tests green (gate 6).
- **R9 — model-file env names avoid the brief's `SMALL_BRAIN_MODEL`**, which is the
  *served* id (echoed into `meta.model`): files use `OCR_SMALL_BRAIN_DIR`,
  `SMALL_BRAIN_SERVER`, `SMALL_BRAIN_MODEL_FILE`, `SMALL_BRAIN_MMPROJ`.
- **R10 — gates SKIP, they don't fail.** A clone without the 2.1 GB model prints SKIP
  and exits 0, so both gates can sit in `.hybrid/checks.json`'s smoke list next to
  the smokes that always run.
- **R11 — real receipts live in `fixtures_real/`** (the brief calls the set
  `spike/fixtures_real`); it is gitignored, so gate 2 is driven by the committed
  baseline `scripts/live_ocr_baseline.json` and SKIPs on a clean clone.
- **R12 — visual review is part of the work.** `.hybrid/visual.json`'s admin
  selectors never matched the shipped HTML (`#token`, `#btn-login`, `tr.job-row`,
  `#btn-sample`, `#nav-*`), so the admin flows have never really been screenshotted;
  this run corrects them and pins a demo admin token so they run at all.

## What users see (in scope, not only logic)

- **Launcher console (ops — the run's headline UI):** four roll-call lines — `OCR`,
  `Small brain`, `Strata` (only when `STRUCTURER_BACKEND=strata`), `Uygulama`. Red
  copy is exact: `Small brain ✗ model dosyaları yok` + `kurma:
  scripts\install_small_brain.ps1` + the directory it looked in, and
  `Small brain ✗ port 8100 dolu` + what holds the port + `python run.py --stop`.
- **Admin job detail (admin):** a Turkish "Aşama süreleri" line in the summary —
  `Okuma 0,9 sn · Yapılandırma 30,6 sn · Doğrulama 1 ms`; values ≥1000 ms humanised
  to seconds with a Turkish comma, `—` when there is nothing to show, and it must not
  overflow a 360 px viewport (the summary already wraps on phones). The raw-JSON
  panel keeps the raw integers.
- **Admin Durum (ops):** the stage-2 chip names the brain that is configured.
- **Worker PWA (field):** no layout change, two honesty fixes for the new latency —
  a job that died because the brain is missing shows the installer sentence instead
  of the generic "Birazdan tekrar dene", and `status.js` (tuned to the 80B's ~7 s
  structuring) gets a queue-safe `STALE_AFTER_MS` — 60 s is now shorter than one busy
  queue — plus a `Yapılandırılıyor` hint that says a long wait is normal on a CPU
  box, so a healthy 35 s job is not sold as stuck.
- **Integrators:** nothing; `/v1` is identical apart from the additive
  `meta.stage_ms`.

## Checks & visual review (updated this run)

- `.hybrid/checks.json` keeps both suites and gains two smokes:
  `scripts\small_brain_gate.py --if-installed` (from M8) and
  `scripts\live_ocr_gate.py --if-installed` (from M8). Both SKIP + exit 0 without the
  model, so brief §9 gates 1–3 become real commands instead of prose.
- `.hybrid/visual.json`: stale selectors corrected (`#yonetici-anahtari`,
  `#giris-dugme`, `#fis-tablo tbody tr[data-job]`, `#ornek-fis`,
  `button[data-bolum="…"]`) and pages kept/added: `worker-sonuc`, `worker-gecmis`,
  `admin-liste`, `admin-duzeltme` (fill `#detay-toplam`, save), `admin-anahtarlar`
  (create → plaintext-once dialog), `admin-durum`, and the new
  `admin-asama-sureleri` (search a firm → open a done job → shot the timing line →
  open the raw JSON).

## Milestones (run 2) — brief §10 maps onto M5–M8

- **M5 — backend plumbing (brief M1):** config keys, structurer backend selection,
  `meta.model` from the resolved backend, real-socket integration, default stays
  `strata`. (T70–T75)
- **M6 — process & install (brief M2):** launcher owns :8100, health, no orphans,
  not-installed and port-busy red lines, installer + manifest. (T76–T81)
- **M7 — toggle + observability + docs (brief M3):** `include_image`, `stage_ms` end
  to end, the admin timing line, Durum truth, README/OPERATIONS, demo token for the
  visual review. (T82–T88)
- **M8 — acceptance + cutover (brief M4):** both live gates, the default flip with
  every dependent part, phone latency honesty, docs. (T89–T94)

## Old decisions this run changes

- Decision 4 and the header line "stage 2: Strata :8080" become **"stage 2: the
  resolved backend — `small` (llama.cpp :8100) by default from M8, `strata` via
  `STRUCTURER_BACKEND=strata`"**. `/v1` stays frozen; the only addition is
  `meta.stage_ms`.
- Decision 2's "zero GPU contention" generalises: the whole pipeline is CPU-only now,
  so the 5090 is optional and the minimum-hardware story is a plain desktop.
- **D7's three-line roll-call becomes four** (OCR, Small brain, [Strata], Uygulama);
  a red Strata line stops failing the start when the backend is `small` — it is a
  note, not an outage.
- Contract 9's `strata` key now means "the configured stage-2 brain" (same key, same
  shape); OPERATIONS says so out loud.
- The new risk, stated so nobody relearns it: **the phone's timing assumptions were
  tuned to a 6.5 s structurer** (`static/app/status.js` ASSUMPTION,
  `STALE_AFTER_MS = 60000`). Gate data may show more; T92 recalibrates, and a
  customer CPU slower than this dev box moves the same numbers again.
