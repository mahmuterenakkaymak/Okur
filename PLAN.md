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

**Wholes (all parts that must follow when one changes):**
- A correction (PATCH) must update: stored result, re-run validation, `GET
  /v1/jobs/{id}`, admin detail, PWA result view, all three export formats.
- A quality-mode rerun must replace result, update `meta.model/quality_mode/*_ms`,
  re-validate, and refresh every view + exports.
- Key revoke must make further PWA calls 401 and the PWA must show the key-error state.
- Any contract field change must touch: contract.py, exported schema, CONTRACT.md,
  admin detail renderer, exports columns, PWA result view — one task, all parts.

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
