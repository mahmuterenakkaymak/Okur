"""End-to-end smoke over real HTTP: one command, one exit code.

Boots the real app (auth middleware, SQLite queue, worker thread, pipeline,
validator) on an ephemeral port with the fake model stubs on theirs, uploads
fixtures/fis_market_clean.png over a real socket, polls the job to done and
checks every envelope it sees against the committed contract_v1.schema.json.
Nothing here is mocked below the HTTP layer, so a broken route, queue, stage or
contract shows up as a nonzero exit — which is what run.py and CI gate on.

    .venv/Scripts/python scripts/smoke_e2e.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
import time

import httpx
import jsonschema
import uvicorn

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # direct `python scripts/smoke_e2e.py`
    sys.path.insert(0, str(ROOT))

from app import auth, config, contract, db, pipeline  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ocr_client import OcrClient  # noqa: E402
from app.queue_worker import QueueWorker  # noqa: E402
from app.structurer import Structurer  # noqa: E402
from scripts.fake_models import start_fake_models  # noqa: E402

FIXTURE = "fis_market_clean"
WORKER = "smoke"
CLIENT_REF = "smoke-1"
POLL_TIMEOUT_S = 30.0
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))


class SmokeError(RuntimeError):
    """The first thing that went wrong; its message is the whole report."""


def _log(step: str, detail: str) -> None:
    print(f"{step:<13} {detail}", flush=True)


class _App:
    """The real app on uvicorn, ephemeral port, off the main thread."""

    def __init__(self, app) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        )
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 30.0) -> str:
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if self._server.should_exit or time.monotonic() > deadline:
                raise SmokeError("app did not come up")
            time.sleep(0.02)
        host, port, *_ = self._server.servers[0].sockets[0].getsockname()
        base_url = f"http://{host}:{port}"
        try:
            httpx.get(f"{base_url}/health", timeout=10.0).raise_for_status()
        except httpx.HTTPError as exc:
            raise SmokeError(f"/health on a fresh app failed: {exc}") from exc
        return base_url

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10.0)


def _stage2_env(stub_url: str) -> dict[str, str | None]:
    """Move config's stage-2 servers onto the stub; hands back what to restore.

    The shipped client resolves stage 2 from config — the small brain under the
    default backend, Strata under the STRUCTURER_BACKEND=strata rollback — so
    pointing both at the stub is what puts the real client over a real socket,
    whichever brain the smoke is running.
    """
    stub = httpx.URL(stub_url)
    values = {
        "STRATA_HOST": stub.host,
        "STRATA_PORT": str(stub.port),
        "SMALL_BRAIN_BASE_URL": stub_url,
    }
    saved = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    return saved


def _start_worker(db_path: pathlib.Path, models) -> QueueWorker:
    """The real queue worker running the real pipeline against the stubs."""
    ocr = OcrClient(base_url=models.ocr.base_url)
    structurer = Structurer()

    def runner(image_bytes, *, quality_mode=False, worker=""):
        return pipeline.run(
            image_bytes,
            quality_mode=quality_mode,
            worker=worker,
            ocr=ocr,
            structurer=structurer,
        )

    worker = QueueWorker(db_path=db_path, runner=runner, poll_interval=0.05)
    worker.start()
    return worker


def _validated(resp: httpx.Response) -> dict:
    """A response body that has to be contract v1."""
    body = resp.json()
    try:
        jsonschema.validate(body, SCHEMA)
    except jsonschema.ValidationError as exc:
        raise SmokeError(
            f"HTTP {resp.status_code} body breaks contract v1: {exc.message}"
        ) from exc
    return body


def _submit(base_url: str, key: str) -> str:
    png = config.ROOT / "fixtures" / f"{FIXTURE}.png"
    resp = httpx.post(
        f"{base_url}/v1/jobs",
        headers={"X-API-Key": key},
        files={"image": (png.name, png.read_bytes(), "image/png")},
        data={"client_ref": CLIENT_REF},
        timeout=30.0,
    )
    if resp.status_code != 202:
        raise SmokeError(f"POST /v1/jobs -> HTTP {resp.status_code}: {resp.text}")
    body = _validated(resp)
    if body["status"] != "queued":
        raise SmokeError(f"a fresh job is {body['status']}, expected queued")
    return body["job_id"]


def _poll_to_done(base_url: str, key: str, job_id: str, db_path) -> dict:
    """Follow the job to a terminal status, logging each stage it moves through."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    seen = ""
    while True:
        resp = httpx.get(
            f"{base_url}/v1/jobs/{job_id}", headers={"X-API-Key": key}, timeout=30.0
        )
        if resp.status_code != 200:
            raise SmokeError(f"GET /v1/jobs/{job_id} -> HTTP {resp.status_code}")
        body = _validated(resp)
        if body["status"] != seen:
            seen = body["status"]
            _log("job", seen)
        if body["status"] == "done":
            return body
        if body["status"] == "failed":
            raise SmokeError(f"job failed: {_failure(db_path, job_id)}")
        if time.monotonic() > deadline:
            raise SmokeError(f"job stuck in {seen} after {POLL_TIMEOUT_S:.0f}s")
        time.sleep(0.1)


def _failure(db_path, job_id: str) -> str:
    """The queue row's error column — the API envelope has no reason to give."""
    conn = db.connect(db_path)
    try:
        return db.get_job(conn, job_id)["error"] or "no reason recorded"
    finally:
        conn.close()


def _check(body: dict) -> None:
    """A done job has to agree with the fixture it was photographed from."""
    truth = json.loads(
        (config.ROOT / "fixtures" / f"{FIXTURE}.json").read_text(encoding="utf-8")
    )
    result = body["result"] or {}
    validation = body["validation"] or {}
    meta = body["meta"]
    if validation.get("verdict") != "ok":
        raise SmokeError(
            f"verdict {validation.get('verdict')!r} on {validation.get('fields')}"
        )
    if result.get("items") != truth["items"]:
        raise SmokeError("items differ from the fixture ground truth")
    if result.get("totals") != truth["totals"]:
        raise SmokeError(
            f"totals {result.get('totals')} differ from {truth['totals']}"
        )
    if body["client_ref"] != CLIENT_REF or meta["worker"] != WORKER:
        raise SmokeError(
            f"job attributed to {meta['worker']!r} / {body['client_ref']!r}"
        )
    if meta["model"] != config.stage2_model(False) or meta["quality_mode"] is not False:
        raise SmokeError(f"meta reports {meta['model']!r} quality_mode={meta['quality_mode']}")


def _run(workdir: pathlib.Path) -> None:
    os.environ["DATA_DIR"] = str(workdir)  # uploaded images land here, not in ./data
    db_path = workdir / "smoke.db"
    conn = db.connect(db_path)
    _, key = auth.create_key(conn, WORKER)
    conn.close()

    models = start_fake_models()
    _log("model stubs", f"ocr {models.ocr.base_url}, structurer {models.structurer.base_url}")
    stage2 = _stage2_env(models.structurer.base_url)
    app = _App(create_app(db_path=db_path))
    worker = None
    try:
        base_url = app.start()
        _log("app", f"{base_url} (/health ok)")
        worker = _start_worker(db_path, models)
        _log("worker", "draining the queue")
        job_id = _submit(base_url, key)
        _log("submitted", f"{FIXTURE}.png -> job {job_id}")
        _check(_poll_to_done(base_url, key, job_id, db_path))
        _log("verified", "contract v1, verdict ok, amounts match ground truth")
    finally:
        if worker is not None:
            worker.stop()
        app.stop()
        models.shutdown()
        for name, value in stage2.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    started = time.perf_counter()
    # ignore_errors: the worker's recovery connection can outlive stop() on
    # Windows, and a smoke must not fail over a leftover temp directory.
    with tempfile.TemporaryDirectory(
        prefix="ocr-smoke-", ignore_cleanup_errors=True
    ) as workdir:
        try:
            _run(pathlib.Path(workdir))
        except Exception as exc:
            _log("SMOKE FAILED", str(exc))
            return 1
    _log("SMOKE OK", f"end to end in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
