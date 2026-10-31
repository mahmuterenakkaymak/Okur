# OCR API — Field-Capture Receipt OCR with Stable JSON Contract

Local-first OCR **server + client** system. Field workers photograph Turkish receipts with
their phones; a local server (RTX 5090) runs PaddleOCR-VL-1.6 (0.9B) + Strata + a
deterministic validator; the product is a **versioned, documented JSON contract** that any
downstream system (accounting, Netsis, dashboards, third-party software) can integrate
against. Nothing leaves the machine except to authorized clients over an encrypted channel.

## 1. Goal

Replace manual receipt entry: a worker in the field takes a photo, the system returns
validated structured JSON within seconds, and any integration consumes the same stable
contract. "Done" = a worker captures a receipt on a phone over the tailnet and an external
system fetches the JSON result without touching the model stack.

## 2. Users and use cases

- **Field worker**: opens the client (PWA), photographs a receipt (optionally crops),
  sees accepted/queued/rejected status, views own submission history.
- **Eren (admin/integrator)**: reviews all submissions, corrects fields, exports
  JSON/CSV/XLSX, manages API keys, reads OpenAPI docs, integrates external systems.
- **Integrating developer (external)**: authenticates with an API key, submits images
  via `POST /v1/jobs`, polls `GET /v1/jobs/{id}` or lists results, relies on the frozen
  JSON schema + validation verdict. Never sees the model stack.

## 3. Scope

**In (v1):**
- **Server** (FastAPI on the 5090 PC): job API (`POST /v1/jobs` multipart, async queue,
  `GET /v1/jobs/{id}`, `GET /v1/jobs?worker=&status=`), API-key auth per client/worker,
  OpenAPI docs at `/docs`, frozen **JSON contract v1** (receipt schema + `validation`
  block + `meta` block), idempotent submissions (client-supplied `client_ref`).
- **Pipeline**: PaddleOCR-VL-1.6 GGUF Q8_0 (llama.cpp :8081) reads -> Strata (:8080)
  structures to schema -> deterministic Python validator recomputes line totals, discount,
  VAT; verdict `ok | mismatch | unreadable`.
- **Client PWA** (worker): installable web app, camera capture (getUserMedia), crop +
  rotate before upload, submit, per-worker history, Turkish UI.
- **Admin web UI** (ported prototype): all submissions, field-level correction, exports,
  API key management, server/VRAM status, quality-mode re-run (27B) for hard handwriting.
- **Remote access**: Tailscale — server exposed on the tailnet over HTTPS; workers'
  phones join the tailnet. No public internet exposure in v1.
- History in SQLite; images stored server-side under `data/`.

**Out (later / never):**
- Offline capture queue with background sync (v2 — but API is idempotent from day one
  so it plugs in cleanly)
- Webhooks / push notifications to integrators (v2; polling in v1)
- Native iOS/Android apps, app stores (never unless PWA proves insufficient)
- Public-internet multi-tenant SaaS, billing, self-serve signup (separate product decision)
- PDF/multi-page, batch folder import (v2), Netsis-specific export (v2, own brief)
- HEIC auto-conversion (v2; PWA camera outputs JPEG anyway)
- Any cloud OCR API (never), telemetry (never)

## 4. Method / architecture

```
Worker phone (PWA: camera -> crop/rotate -> POST /v1/jobs + X-API-Key)
        |  HTTPS over Tailscale (tailnet only)
FastAPI server :8090  ── auth (API keys, per worker/client) ── job queue (SQLite)
        |   stage 1: OCR server  llama.cpp llama-server :8081
        |            PaddleOCR-VL-1.6-GGUF Q8_0 (<= 2.5 GB VRAM, Apache-2.0)
        |   stage 2: Strata :8080 -> receipt JSON schema (language layer only)
        |   stage 3: validator.py (pure Python): recompute totals/KDV from items,
        |            compare with model output -> ok | mismatch(fields) | unreadable
        ├── GET /v1/jobs/{id} -> contract v1 JSON (integrators poll this)
        ├── Admin UI (ported prototype + corrections + exports + keys + status)
        └── PWA static client + /api/* for worker views
```

- LLMs only at the language layer; **all arithmetic deterministic Python** (AGENTS.md #7).
- Handwriting: stage 1 transcription; admin quality-mode re-runs via 27B (Unsloth Studio).
- Contract v1 is frozen at M1 and versioned in the URL (`/v1/`); breaking changes go to
  `/v2/`, never mutate `/v1/`.

## 5. Stack and environment

- Server: Windows 11, RTX 5090 32 GB. Strata resident (~30 GB); OCR budget <= 2.5 GB
  (Q8_0). If headroom is short, trim Strata's KV budget (one-time, measured in M0).
- Python 3.12, FastAPI + uvicorn, SQLite (jobs + keys + history), openpyxl, httpx,
  Pillow (server-side EXIF/orientation only; crop happens client-side).
- OCR model: `PaddlePaddle/PaddleOCR-VL-1.6-GGUF` Q8_0 + BF16 mmproj via the stack's
  llama.cpp `llama-server` on :8081 (official Blackwell support; RTX 5090 listed).
- Structuring: Strata `http://127.0.0.1:8080`; quality mode: Unsloth Studio :8888.
- Tailscale serve/funnel-to-tailnet HTTPS on :8090 (tailscale-serve-windows skill).
- Run: `python run.py` (starts OCR server + app + opens admin UI); PWA at
  `https://<tailnet-host>/app`.

## 6. Data

- Receipt images = personal data (names, card last-4): stored only under `data/`,
  served only to authenticated clients on the tailnet. `.gitignore` covers `data/`.
- API keys: hashed at rest; per-key worker identity; no shared master key in v1.
- Test corpus: synthetic Turkish receipt PNG fixtures (committed) + Eren's private real
  receipts for M0/acceptance (not committed).

## 7. Interfaces

- **JSON contract v1** (frozen, documented in OpenAPI + `CONTRACT.md`):
  `{ "job_id", "status", "client_ref", "result": { header, meta, items[], totals,
  para_birimi, okunamayan }, "validation": { verdict, expected, actual, fields[] },
  "meta": { worker, captured_at, received_at, ocr_ms, total_ms, model, quality_mode } }`
- **REST (integrators)**: `POST /v1/jobs` (image, mode, client_ref) -> 202 `{job_id}`;
  `GET /v1/jobs/{id}`; `GET /v1/jobs?status=&worker=&since=`; all require `X-API-Key`.
- **REST (worker PWA)**: `POST /v1/jobs` (own key), `GET /v1/jobs?mine=true`.
- **Admin**: review/correct (`PATCH /v1/jobs/{id}`), export `GET /v1/export?format=`,
  keys CRUD, `GET /v1/status` (servers, VRAM, queue depth).
- **CLI**: `python run.py [--ocr-port 8081] [--app-port 8090] [--no-browser] [--stop]`.

## 8. Constraints

- Offline-first for models: zero non-localhost model traffic; tailnet is the only
  ingress; no public port forwarding.
- OCR server <= 2.5 GB VRAM alongside Strata; no GPU mode switch for daily use.
- Target: photo -> contract JSON < 15 s (both stages, 5090); queue absorbs bursts.
- Auth: constant-time key compare; keys hashed; rate limit per key.
- Dependencies Apache-2.0/MIT; model Apache-2.0.
- UI text Turkish; code/comments/commits English; contract field names snake_case.

## 9. Acceptance tests

1. `python run.py` with Strata up: OCR + app green in 60 s; OCR server <= 2.5 GB per
   nvidia-smi.
2. `POST /v1/jobs` with synthetic Turkish receipt (valid key) -> 202; poll -> `done`;
   contract v1 validates against the committed JSON Schema; validator verdict `ok`.
3. Fixture with wrong KDV in structuring output -> verdict `mismatch`, `fields` names it.
4. Wrong/missing API key -> 401; rate limit returns 429.
5. Same `client_ref` submitted twice -> single job (idempotent), second call returns the
   existing `job_id`.
6. Phone on tailnet: PWA captures, crops, uploads, shows result; worker sees own history
   only.
7. Admin correction persists and flows through to `GET /v1/jobs/{id}` and exports.
8. CSV/XLSX export of selected jobs contains exactly those rows with numeric values.
9. No outbound non-localhost connections during a full run (models) — tailnet traffic
   only for client requests.
10. Validator unit tests: discount, multi-KDV-rate, currency edge cases.

## 10. Milestones

- **M0 (feasibility spike, MERGEN directly):** download Q8_0 GGUF, serve on the 5090
  next to Strata, measure VRAM/latency, run 3 real Turkish receipts + 1 handwriting
  sample. Gate: printed Turkish receipt readable, <= 2.5 GB. Fallback: Qwen3-VL-8B or
  PP-OCRv6 hybrid.
- **M1:** Contract + API core — JSON Schema v1 + CONTRACT.md, FastAPI, auth, queue,
  pipeline, validator + unit tests, fixtures, OpenAPI.
- **M2:** Worker PWA — camera, crop/rotate, submit, status, history (Turkish).
- **M3:** Admin UI — ported prototype + corrections + exports + key management + status.
- **M4:** Tailscale exposure + launcher + quality mode + hardening (rate limits, error
  hints, README, stop handling).

## 11. Open questions / risks

- **Server availability**: PC-as-server means the office PC must be on and reachable;
  field workers lose service when it's off. Acceptable for v1? (VPS+GPU later changes
  cost + data-residency picture.)
- **Turkish coverage of PaddleOCR-VL on real receipts** is benchmark-claimed, not
  Eren-verified -> M0 gate; fallback Qwen3-VL-8B (~6 GB).
- Handwriting CER of a 0.9B model may disappoint -> quality mode is the escape hatch.
- llama.cpp GGUF vision path on Blackwell: official repo + community 5090 reports, but
  M0 must prove it on this exact machine.
- Strata KV-budget trim may be needed to free 2-3 GB (local-agent-stack config, one-time).
- Tailscale on workers' phones: acceptable for a known team; if integrators/workers are
  external, a public HTTPS front-end becomes a separate decision (TLS, hardening, data
  policy).
- Scale assumptions (workers, receipts/day) unconfirmed -> queue design assumes
  <= ~10 workers, <= ~500 receipts/day.
