# REVIEW — M2 (T19–T33, base 9434ec9)

**Red today:** `tests/test_main_app.py::test_valid_key_reaches_the_router` and `::test_rate_limit_returns_429_with_retry_after` expect 404 from `GET /v1/jobs`; T16 (6012789) added that route, so both are stale, not regressions → T51. Everything else is green: 357 pytest, 136 node, `smoke_e2e.py`, `serve_demo.py --check`.

**Blocker outside M2:** `app/structurer.py` (T11) still does not exist — `pipeline._default_structurer` raises ImportError, so the real app cannot process a job. smoke/integration/demo each hold that seam with a stand-in and stay green. T11 must land before any real run.

**Bugs** (fix tasks appended to TASKS.md):
- B1 `captured_at` dies at the queue: the route stores it in `meta_json`, `queue_worker.py:136` rebuilds meta from the pipeline bundle alone, so every GET after `done` reports `captured_at: null` (verified end to end) — contract 1 and CONTRACT.md promise it → T52.
- B2 the demo's live screens are empty: `LIVE_STATES` seeds queued/running, `QueueWorker.start()` requeues the running one and the worker drains both in ~3 s (statuses after boot: 8 done, 1 failed) → T53.
- B3 `detayAc` (app.js:217) never calls `birak()`, so opening a history row mid-send leaves two poll loops sharing one `akis` token, fighting over the result view, and leaks the 500 ms tick interval → T54.
- B4 a negative `totals.iskonto` — a shape the validator explicitly accepts — prints as `−-52,32` in the result view → T55.
- B5 uploads are stored byte-for-byte: no Pillow re-encode, so EXIF/GPS from worker phones sits in `data/images` and `/api/me/jobs/{id}/image` serves it verbatim; the `crop.js:5` ASSUMPTION that the server re-encodes is false → T56 (pulls the T46 line forward; KVKK).

**Risks:** `crop.js` returns a crop rect no producer stores (contract v1 has no field for it); `POLL.ceilingMs` 180 s < worst-case pipeline (2×120 s model timeouts); history fetches every thumbnail at once against a 20-token bucket, so a full first page can 429 blank minis; `keys_cli` runs as `python -m app.keys_cli` while PLAN.md:42 and T19 still say `app.keys`.
**Missing tests:** nothing pins the lite-row field names `history.js` reads, and no test opens a `failed` job from history.
