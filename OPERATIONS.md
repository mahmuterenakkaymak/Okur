# OPERATIONS

The machine the app runs on *is* the deployment: one launcher, one SQLite file,
one folder of images, two model servers it calls over HTTP. Everything an
operator has to know is here; what the API promises its callers is
[`CONTRACT.md`](CONTRACT.md), how to install and drive it is
[`README.md`](README.md).

## Backup — data/

Everything stateful sits under `data/` (`DATA_DIR`, `DB_PATH` in `app/config.py`
move it elsewhere). It is gitignored and it has to stay that way: receipt images
carry shop names, addresses and payment fragments — KVKK personal data.

| Path | What it is | Back it up |
| --- | --- | --- |
| `data/ocr.db` + `data/ocr.db-wal` + `data/ocr.db-shm` | keys, jobs, corrections, events (SQLite in WAL mode) | yes — all three together |
| `data/images/<job_id>.jpg` | uploads, re-encoded with EXIF stripped and orientation baked in | yes |
| `data/certs/` | the certificate and private key `tailscale_serve.ps1` exported | yes, and treat it as a secret |
| `data/logs/` | request and model-server logs | operator's call |
| `data/ocr.pid`, `data/app.pid` | launcher tracking, valid only while running | no |

WAL keeps committed rows in `-wal` until the next checkpoint, so copying
`ocr.db` alone can lose the newest jobs. Stop first, then copy the whole tree:

```powershell
.venv/Scripts/python run.py --stop
robocopy data D:\backup\ocr-2026-11-01 /E
```

`/E` copies the tree without deleting anything at the destination — no backup
command in this project is allowed to destroy an older one. Restore by copying
the files back into an empty `data/` and starting the stack; a job interrupted
by the crash or the stop is picked up again on boot (`STALE_JOB_MINUTES` decides
when a `running` row counts as abandoned). Prove a restored instance works
against it directly:

```powershell
.venv/Scripts/python run.py --no-browser
$env:OCR_ACCEPTANCE_KEY = "ocrk_<a live worker key>"
.venv/Scripts/python scripts/acceptance.py --base-url http://127.0.0.1:8090
```

## Key rotation

Two secrets, neither ever stored in plaintext: worker keys live in the database
as SHA-256 hashes, `ADMIN_TOKEN` lives only in `.env`.

**Worker keys** (`ocrk_<40 hex>`, one per worker, shown exactly once at
creation — nothing can print one again):

```powershell
.venv/Scripts/python -m app.keys_cli list
.venv/Scripts/python -m app.keys_cli add ayse
.venv/Scripts/python -m app.keys_cli revoke 3
```

Rotate by adding the new key, pasting it into the phone, then revoking the old
one; confirm the PWA stops on its key-error state, which is the proof the revoke
reached the API (further calls answer 401). Rotate the day a phone is lost or a
worker leaves — not at the end of the month. `list` shows identities only, so a
screenful of it is safe to share.

**`ADMIN_TOKEN`** is read from the environment at boot, so rotation is: put the
new value in `.env`, then `python run.py --stop` and `python run.py`. Admin
sessions live in memory, so the restart logs every admin out — that is part of
the point. With `ADMIN_TOKEN` unset the admin panel has no door at all: `/v1`
keeps answering, `/admin/api/*` answers 401.

## Log locations

`run.py` appends each service's own output to its own file and prints the path
in its roll-call; a service that fails its health check is reported with the
exact file to read and the retry command.

| File | What is in it |
| --- | --- |
| `data/logs/app.log` | uvicorn, plus one request line per request: `POST /v1/jobs 202 41ms job=… worker=ayse`, and the traceback of any 500 |
| `data/logs/ocr.log` | llama-server: model load, context size, VRAM/CPU placement, per-request timings |
| `data/logs/small-brain.log` | llama-server (stage 2, port 8100): model load, context size, per-request timings |

Tracebacks never leave the server: a crash logs its stack and answers
`{"error": {"code": "internal_error", …}}`. Nothing rotates the logs, so
truncating or archiving them is an operator action — safe to do while the stack
is stopped, and `data/` backups may skip them.

## Model paths

`run.py` checks all four before it starts anything and prints every missing
path with the `.env` name that would fix it, so a fresh machine fails in one
line instead of a 60 s health timeout. `models/` and `vendor/` are gitignored —
multi-GB, re-downloadable.

| `.env` name | Default | What it is |
| --- | --- | --- |
| `LLAMA_SERVER` | `vendor/llama/llama-server.exe` | the llama.cpp server binary serving stage 1 |
| `OCR_MODEL` | `models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF.gguf` | PaddleOCR-VL-1.6 GGUF (Q8_0) |
| `OCR_MMPROJ` | `models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF-mmproj.gguf` | its vision projector |
| `OCR_CHAT_TEMPLATE` | `models/paddleocr-vl-1.6/chat_template.jinja` | the template llama-server takes via `--chat-template-file` |
| `OCR_CTX` | `4096` | context slots for stage 1 |
| `OCR_NGL` | `0` | GPU layers; 0 = CPU (see VRAM notes) |

Stages 2 and 3 have no files to place: this app never loads a model, it posts
to `STRATA_HOST:STRATA_PORT` (`127.0.0.1:8080`) and, for `mode: "quality"`, to
`UNSLOTH_HOST:UNSLOTH_PORT` (`127.0.0.1:8888`). `OCR_MODEL_NAME`, `STRATA_MODEL`
and `UNSLOTH_MODEL` are labels only — they are echoed into `meta.model` and
should say what is actually serving.

Ports an operator cares about: `8090` app (`APP_HOST`/`APP_PORT`), `8081` OCR
(`OCR_HOST`/`OCR_PORT`), plus the two stage-2 servers above. All four listen on
loopback; Tailscale is the only thing that reaches the outside.

## VRAM notes

The 32 GB card is shared with Strata, and that is the whole budget — so stage 1
runs on CPU by default and never asks the GPU for anything.

| | |
| --- | --- |
| Stage 1 default | `-ngl 0` → CPU, ~2 GB VRAM, 1–5 s per receipt (`spike/REPORT.md`: 1.0–5.3 s average, measured against Strata holding 31.4/32 GB) |
| `OCR_NGL` | GPU layers for llama-server; raise it only when Strata is off or the card genuinely has room, and re-measure before trusting it |
| Stage 2 | a separate process this app only calls over HTTP — its VRAM is Strata's or Unsloth Studio's problem, not the app's |
| Live reading | admin → Durum shows used/total MB from `nvidia-smi` next to queue depth, amber past 90 %; on a CPU-only box it reads unavailable, which is a fact and not an error |

Two consequences worth remembering: OCR throughput is CPU-bound, so a queue
spike is a latency problem and not a crash; and a receipt that takes far longer
than 5 s is usually a huge photo, not a slow model — `IMAGE_MAX_EDGE` (1600) and
`JPEG_QUALITY` (85) already shrink uploads before they reach stage 1.

## Daily checks

```powershell
$env:OCR_ACCEPTANCE_KEY = "ocrk_<a live worker key>"
.venv/Scripts/python scripts/acceptance.py --base-url http://127.0.0.1:8090
```

One command, one table, nonzero exit on any FAIL: contract validation, a
deliberate KDV mismatch, 401 and 429, idempotent `client_ref`, export row parity.
The checks upload through the worker door, so they need a live worker key —
`--api-key` says so on the command line instead, and only a `serve_demo` stack is
keyless, because only it answers `/demo/config.json`. Beyond it, three things
tell you the machine is healthy: the Durum page is all green, `failed` jobs are
at or near zero, and `data/` is still growing.
