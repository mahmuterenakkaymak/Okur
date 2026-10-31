# REVIEW — M4 (T45–T50, base d9a41af)

Green today: 599 pytest / 21 red, 192 node, smoke_e2e OK, acceptance --demo 7/7. All 21 reds are stale tests, not code regressions — T46 and T50 changed behaviour the old tests pinned and shipped without updating them.

**Bugs** (fix tasks appended to TASKS.md):
- B1 T46's `_require_image` (routes_jobs.py:132) refuses the shared fixture `b"\xff\xd8\xff\xe0fakejpeg"`, redding 19 tests — tests/test_routes_jobs.py (15) and tests/test_captured_at_survives.py (4) can no longer submit at all; the T46 ASSUMPTION admits the fixtures needed fixing and never fixed them → T60.
- B2 tests/test_upload_exif_stripped.py::test_an_undecodable_upload_is_still_accepted still asserts T56's pre-T46 contract (202 + verbatim store); T46 rejects undecodable bytes 422 at the door → T61.
- B3 tests/test_run_py.py:258 counts 2 ✓, but T50's roll-call prints three (OCR, Strata, Uygulama — pinned by test_launcher_rollcall.py) → T62.
- B4 the PWA swallows T46's Turkish intake copy: `too_large_message()` promises "the worker's phone shows this copy verbatim", but `classifyFailure` (api.js:39) maps 413/422 to the generic server_error "Birazdan tekrar dene" — the worker is told to retry when the fix is crop/retake → T63.
- B5 OPERATIONS.md:40,131's daily check `acceptance.py --base-url` can never pass: `_live()` (acceptance.py:418) reads the key only from `/demo/config.json`, which only serve_demo serves → T64.

**Risks:** `/admin/api/login` is still unthrottled (M3 said fold into T46; T46 did not); the admin cookie has no `Secure` (routes_admin.py:628 ASSUMPTION documents the http-dev tradeoff — fine on the tailnet, bad if 8090 ever leaks to the LAN); CSP `script-src 'unsafe-inline'` — the comment credits it with stopping injected OCR text, but textContent is what actually stops it; revoke is still one-click and a rerun still silently overwrites corrections (both M3 carry-overs).

**ASSUMPTIONs checked:** the single-worker claim holds (create_app never starts a QueueWorker; README tells operators not to run bare uvicorn); Strata-down-fails-start matches brief 9.1; the tailscale rollback keeping the exported key matches the no-silent-delete rule; test_docs' `-m` importability limit is honest; `_require_image`'s ASSUMPTION is the B1 confession.

**Missing tests:** nothing pins the PWA surfacing the server's error message (B4); nothing runs acceptance against a non-demo instance (B5); CONTRACT.md documents no error envelope at all — 401/429/413/422 live only in README, while CONTRACT.md is the integrator's door.
