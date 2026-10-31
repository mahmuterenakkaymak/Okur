# REVIEW — M1 (T01–T18, base 742bfd9; T11 landed last, at HEAD 17468f6)

Green today: 665 pytest, 192 node, smoke_e2e OK. M1's core (contract, validator, db, auth, queue) holds up; all three bugs sit at the seams T11's late arrival exposed.

**Bugs** (fix tasks appended to TASKS.md):
- B1 a stage-2 UnreadableError becomes failed, never verdict unreadable: pipeline.py:47-50 folds it into bundle["error"] and queue_worker._process fails any non-empty error, discarding the unreadable validation — a receipt the model could not structure shows the worker "İşlenemedi — tekrar dene" instead of D3's re-shoot, the integrator gets status failed with no reason, and the pipeline ASSUMPTION "both take the unreadable path" is false (only the empty-items path survives; serve_demo has to fake the state) → T65.
- B2 the smoke and the M1 integration still stand in for stage 2 with hand-rolled clients; their ASSUMPTIONs ("app/structurer.py is T11 and not in the tree yet… this class gets replaced once it lands") are false since T11 landed — the shipped Structurer's prompt, JSON extraction and quality routing are exercised by no end-to-end gate, only its own MockTransport unit tests → T66.
- B3 routes_jobs.create_job commits the queued row before the image exists: the worker can claim the row in that window and fail a good receipt with "image: …", and any failure between commit and update (e.g. _strip_exif on a decodable-but-odd upload) leaves an orphan queued row → T67.

**Risks:** _strip_exif stores no-EXIF uploads verbatim (routes_jobs.py:156) — PLAN decision 7 says re-encode, and PNG tEXt metadata survives; any valid worker key reads every worker's receipts via GET /v1/jobs/{id} (global by design for integrators, but a leaked phone key exposes the fleet, not one worker); M4 carry-overs still open (unthrottled admin login, CSP unsafe-inline, rerun overwrites corrections).

**ASSUMPTIONs checked:** the two false ones are B1/B2; sound: db's mode vocabulary matches routes_jobs/exports, ocr_client's quality no-op matches PLAN, keys_cli's honest app.keys_cli path (docs agree), queue_worker's captured_at merge (T52), validator's iskonto/mixed-rate trust rules.

**Missing tests:** nothing runs the real Structurer through the pipeline (B2); the envelope carries no failure reason, so an integrator cannot tell "retake the photo" from "model server down" — CONTRACT.md still documents no error envelope (M4 carry-over).
