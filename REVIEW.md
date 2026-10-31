# REVIEW — M3 (T34–T44, base c17ef59)

Green today: 487 pytest, 186 node. `app/structurer.py` (T11) still does not exist — the M2 blocker stands, the real app still cannot process a job.

**Bugs** (fix tasks appended to TASKS.md):
- B1 the admin list's default sort is wrong: `_sirala` (routes_admin.py:609) sorts `tarih` by the printed `dd.MM.yyyy` string — verified desc order puts 2026-11-02 above 2026-12-01; it must sort the row's ISO `_gun` → T57.
- B2 corrections corrupt 3-decimal numbers: `kaydet()` (detail.js:542) sends the raw `<input type=number>` string and `numbers.parse_number` reads dot+3-digits as a thousands separator — verified "0.250" → 250.0, "12.500" → 12500.0, so a kg-quantity fix lands 1000× off and the validator recomputes over the wrong number → T58.
- B3 CONTRACT.md:31–34 advertises PATCH `/v1/jobs/{id}`, POST `/v1/jobs/{id}/rerun`, GET `/v1/export`, GET `/v1/status`, but the routes_admin ASSUMPTIONs (195/233/307/392) shipped all four under `/admin/api/*` — the integrator-facing doc 404s on every one; the doc is the outlier (decision 6 + tests agree) → T59.

**Risks:** the list's date filter reads receipt date while export `since` reads `created_at`, so the exported file does not match the on-screen window (admin.js:60 ASSUMPTION admits partial carry-over, not the semantic switch); `/admin/api/login` has no rate limit — ADMIN_TOKEN is brute-forceable (fold into T46); the session cookie has no `Secure` until T47's HTTPS; key revoke is one click with no confirm and no toast (D6 covers save/export/create only); a quality rerun silently overwrites manual corrections — the confirmation dialog does not say so.

**ASSUMPTIONs checked:** status.js queue-depth (queued+running, failed excluded) is a fair reading; toasts.js shown-once toast timing is fine; serve_demo.py:265 "admin answers 404 until M3" is stale but harmless (accepts 200).

**Missing tests:** nothing sorts the admin list by `tarih` — the default sort — (only toplam/firma are tested; that gap let B1 ship); nothing pins the correction payload the frontend sends (B2); nothing asserts CONTRACT.md's endpoints exist (B3); export `ids` is untested and no UI ever sends it.
