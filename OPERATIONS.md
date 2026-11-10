# OPERATIONS

The machine the app runs on *is* the deployment: one launcher, one SQLite file,
one folder of images, two model servers it calls over HTTP. Everything an
operator has to know is here; what the API promises its callers is
[`CONTRACT.md`](CONTRACT.md), how to install and drive it is
[`docs/REFERENCE.md`](docs/REFERENCE.md).

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

Strata and Unsloth have no files to place: this app never loads a model, it posts
to `STRATA_HOST:STRATA_PORT` (`127.0.0.1:8080`) and, for `mode: "quality"`, to
`UNSLOTH_HOST:UNSLOTH_PORT` (`127.0.0.1:8888`). The small brain — stage 2's CPU
option, its own section below — is the one model this machine keeps, and it keeps it
outside the repo. `OCR_MODEL_NAME`, `STRATA_MODEL` and `UNSLOTH_MODEL` are labels
only — they are echoed into `meta.model` and should say what is actually serving.

Ports an operator cares about: `8090` app (`APP_HOST`/`APP_PORT`), `8081` OCR
(`OCR_HOST`/`OCR_PORT`), `8100` small brain (`SMALL_BRAIN_BASE_URL`), plus the two
stage-2 servers above. All of them listen on loopback; Tailscale is the only thing
that reaches the outside.

## Small brain — stage 2 on a CPU-only box

Stage 2 has a second shape: the same `llama-server` binary as stage 1, serving
Qwen3-VL-4B-Instruct (IQ4_XS, ≈2.1 GB) and its F16 vision projector (≈0.8 GB) on
`127.0.0.1:8100`, spawned and stopped by `run.py` as its own child. That is the
minimum-hardware deployment — both stages and the app on one box, no second machine,
no GPU in the loop; the measurements are in `spike/SMALL_BRAIN_BAKEOFF.md`.

| | |
| --- | --- |
| Minimum hardware | CPU only — no GPU, no CUDA, no driver. **~4 GB free RAM** for the brain (model + 8k context + one image at 1024 vision tokens) on top of what stage 1 already wants; a laptop i5 runs it, it is not fast |
| VRAM | zero — the launcher always starts it with `-ngl 0`, so whatever the card holds is untouched (VRAM notes) |
| Install dir | `%LOCALAPPDATA%\ocr-small-brain\` — `llama\llama-server.exe`, `models\Qwen3-VL-4B-Instruct-IQ4_XS.gguf`, `models\mmproj-F16.gguf`; `OCR_SMALL_BRAIN_DIR` moves the whole thing, and none of it ever lands in the repo |
| Port | `8100` on loopback, taken from `SMALL_BRAIN_BASE_URL` — the launcher binds it and the client posts to it, one env value for both |
| Files missing | the roll-call prints `Small brain ✗ model dosyaları yok` with the install command and the directory it looked in, the app still starts, and a job that reaches stage 2 fails with "small brain not installed" |

### Install

```powershell
.\scripts\install_small_brain.ps1          # downloads what is missing, leaves what is installed alone
.\scripts\install_small_brain.ps1 -Check   # installed/missing report, always exit 0
.\scripts\install_small_brain.ps1 -Force   # re-download every row
```

Everything to download is one row of `scripts\small_brain_manifest.json`:
`{id, url, mirror_url?, dest, sha256, size_bytes}`, where `dest` is always relative to
the install dir. Each download lands on a `<dest>.part` temp file and moves into place
only after its byte count and its `sha256` match the manifest, so a half-downloaded
GGUF never becomes an installed model. The primary CDN is tried once more before the
script falls back to the row's `hf-mirror.com` mirror — Hugging Face's own CDN stalled
on 2 GB writes on 2026-11-06, which is why the rows carry mirrors at all.

### Start, check, and the wait

`STRUCTURER_BACKEND=small`, the configured default, makes the brain stage 2; an empty
or unknown value keeps it. `python run.py` then spawns it and waits on
`GET http://127.0.0.1:8100/v1/models` — the same probe the Durum page runs, so
`curl.exe http://127.0.0.1:8100/v1/models` answers the same question by hand: a JSON
model list means stage 2 is alive, a refused connection means
`data/logs/small-brain.log` says why. Contract 9 froze the status payload's key names,
so the `strata` key reports whichever stage-2 brain is configured — the small brain on
`8100` while `STRUCTURER_BACKEND=small`, Strata otherwise — and a CPU-only Durum page
is green instead of permanently red.

The startup wait is shared: `STARTUP_WAIT_S` applies to every service, and a cold OCR
load reads ≈90 s on a slow disk (more with a `-ngl` swap), which is past its `60`
default. A first `OCR ✗ 60 sn içinde hazır olmadı` on such a disk is not a broken
model: put `STARTUP_WAIT_S=120` in `.env` and start again.

### Latency — 45 s per receipt

A CPU box buys parity with time: stage 1 reads a receipt in 1–5 s, stage 2 then takes
16–31 s to structure it (`spike/SMALL_BRAIN_BAKEOFF.md`), so plan on **30–45 s per
receipt** end to end and budget 45 s whenever the queue is not empty. That fits every
timeout the app sets — `STRUCTURER_TIMEOUT_S` (120) is the ceiling for stage 2 alone —
and the phone is tuned to the same budget: a 45 s wait reads as "Yapılandırılıyor"
progress in Turkish, not as an error, and a job is only called stuck when the queue
has clearly stalled. What it means for a shift: one worker thread, so 10 receipts
drain in ~7–8 minutes, and a lunch rush is a latency problem and never a crash. Every
contract field is identical to a Strata run — only `meta.model` and the wall clock
differ, and `stage_ms.structure` is where the 30 s shows up.

### Port 8100 is taken

`run.py` bind-probes before it spawns, so the conflict is named instead of losing the
race: `Small brain ✗ port 8100 dolu`, with the pid and image name of the holder. Free
it in the order that loses nothing:

1. `python run.py --stop` — the launcher's own child is the usual holder.
2. `netstat -ano | findstr :8100`, then stop that pid — a second llama-server or a
   leftover from a crash is not ours to track.
3. Or move the brain: `SMALL_BRAIN_BASE_URL=http://127.0.0.1:8101` moves the bind and
   the client together.

### Rollback — one line

`STRUCTURER_BACKEND` defaults to `small`; a box that has Strata running switches back
to it with one line in `.env` and a restart. Nothing else is part of the rollback —
the same database, images, keys and `/v1` answer throughout:

```env
STRUCTURER_BACKEND=strata
```

```powershell
.venv/Scripts/python run.py --stop
.venv/Scripts/python run.py --no-browser
```

From the next submission on, jobs queue for Strata, `meta.model` says `strata`, and
the roll-call waits on `:8080` instead of binding `:8100`. The brain stays installed
and idle: its line still prints, but a blocked one is a note rather than a
requirement, and the job receipts in flight on the small brain are unaffected.

### Uninstall

The brain is three files in one folder and nothing else: no registry keys, no service,
nothing inside the repo. Stop the stack, then delete the directory — the one the
installer wrote to, which is `OCR_SMALL_BRAIN_DIR` or `%LOCALAPPDATA%\ocr-small-brain`:

```powershell
.venv/Scripts/python run.py --stop
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\ocr-small-brain"
```

`data/` survives it untouched — receipts, jobs, keys and logs are the deployment, and
no brain install or uninstall reads them. The next `python run.py` prints
`Small brain ✗ model dosyaları yok`: install it again, or move stage 2 to Strata with
the one line above.

### Env reference

| `.env` name | Default | What it moves |
| --- | --- | --- |
| `STRUCTURER_BACKEND` | `small` — the default lives in `app/config.py`, nowhere else | which brain stage 2 runs: `small` is this box's `:8100`, `strata` is `STRATA_HOST:STRATA_PORT`; empty or junk keeps the default |
| `SMALL_BRAIN_BASE_URL` | `http://127.0.0.1:8100` | the brain's host and port; a host that is not this box means the brain runs elsewhere and `run.py` spawns no child |
| `SMALL_BRAIN_MODEL` | `Qwen3-VL-4B-Instruct` | the label that lands in `meta.model` — say what really serves |
| `OCR_SMALL_BRAIN_DIR` | `%LOCALAPPDATA%\ocr-small-brain` | install dir: the installer writes here, the launcher reads here |
| `SMALL_BRAIN_SERVER` / `SMALL_BRAIN_MODEL_FILE` / `SMALL_BRAIN_MMPROJ` | `<dir>\llama\llama-server.exe`, `<dir>\models\<gguf>`, `<dir>\models\mmproj-F16.gguf` | the three installed files, one env name each; `small_brain_ready()` is the check that all three exist |
| `STRUCTURER_INCLUDE_IMAGE` | `true` | small backend only: send the photo next to the OCR text; `0`/`false`/`no` is text-only. Strata and quality mode always send the image |
| `STARTUP_WAIT_S` | `60` | seconds the roll-call waits per service — see the cold-load note above |

## VRAM notes

The 32 GB card is shared with Strata, and that is the whole budget — so stage 1
runs on CPU by default and never asks the GPU for anything.

| | |
| --- | --- |
| Stage 1 default | `-ngl 0` → CPU, ~2 GB VRAM, 1–5 s per receipt (`spike/REPORT.md`: 1.0–5.3 s average, measured against Strata holding 31.4/32 GB) |
| `OCR_NGL` | GPU layers for llama-server; raise it only when Strata is off or the card genuinely has room, and re-measure before trusting it |
| Stage 2 | a separate process this app only calls over HTTP — its VRAM is Strata's or Unsloth Studio's problem, not the app's; the small brain is that process too, and `-ngl 0` keeps it out of the card entirely |
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
