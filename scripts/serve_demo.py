"""Demo server: the real app on fake model stubs with seeded jobs, :8090.

Boots the same app run.py will ship — auth, SQLite queue, worker thread,
pipeline, validator — against scripts/fake_models, and seeds one job per
committed fixture (fixtures + fixtures_hard) across every queue state and
verdict, so every screen has data with no camera and no model server. The
PWA picks the demo up at /demo/config.json (its key pre-filled) and grows
an "Örnek fiş" button that submits a real fixture image through the live
queue.

    .venv/Scripts/python scripts/serve_demo.py           # review at :8090
    .venv/Scripts/python scripts/serve_demo.py --check   # boot, probe, exit 0
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import threading
import time

import httpx
import uvicorn
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import ValidationError

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # direct `python scripts/serve_demo.py`
    sys.path.insert(0, str(ROOT))

from app import auth, config, contract, db, pipeline  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ocr_client import OcrClient  # noqa: E402
from app.queue_worker import QueueWorker  # noqa: E402
from app.structurer import Structurer  # noqa: E402
from app.validator import validate  # noqa: E402
from scripts.fake_models import default_dirs, start_fake_models  # noqa: E402

WORKER = "demo"
MISMATCH_FIXTURE = "fis_market_foto"  # tampered total -> the discrepancy panel
FAILED_FIXTURE = "fis_kotu_cekim"  # a bad capture that never structured
LIVE_STATES = {"fis_benzin_clean": "queued", "fis_restoran_foto": "running"}
# what seed_jobs names them, which is how the worker spots them again
LIVE_REFS = frozenset(f"demo-{name}" for name in LIVE_STATES)


class DemoError(RuntimeError):
    """The first thing that went wrong; its message is the whole report."""


def _log(step: str, detail: str) -> None:
    print(f"{step:<13} {detail}", flush=True)


def fixture_names() -> list[str]:
    """Every committed fixture, both dirs, fixtures first."""
    return [
        path.stem for directory in default_dirs() for path in sorted(directory.glob("*.json"))
    ]


def _fixture_file(name: str, suffix: str) -> pathlib.Path:
    for directory in default_dirs():
        path = directory / f"{name}{suffix}"
        if path.is_file():
            return path
    raise DemoError(f"no fixture {suffix} for {name!r}")


def _fixture_image(name: str) -> pathlib.Path:
    return _fixture_file(name, ".png")


def _result_for(name: str) -> contract.Result:
    truth = json.loads(_fixture_file(name, ".json").read_text(encoding="utf-8"))
    try:
        result = contract.Result.parse(truth)
    except ValidationError:
        # ASSUMPTION: fixtures_hard ground truths predate the contract shape
        # (amount-only items, keyword lists), so they demo the unreadable path.
        result = contract.Result()
    if name == MISMATCH_FIXTURE:
        result.totals.toplam += 5.0  # a hidden discount line the model missed
    return result


def _store_image(png: pathlib.Path, images_dir: pathlib.Path, job_id: str) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    path = images_dir / f"{job_id}.jpg"
    Image.open(png).convert("RGB").save(path, "JPEG", quality=config.jpeg_quality())
    return str(path)


def seed_jobs(conn, *, key_id: int, images_dir: str | os.PathLike[str]) -> list[dict]:
    """One job per committed fixture, spread over every state and verdict.

    Clean fixtures land done/ok, the tampered one opens the discrepancy
    panel, the hard ones demo unreadable, one job failed and two are still
    moving through the queue so the live views have company.
    """
    images_dir = pathlib.Path(images_dir)
    jobs = []
    for index, name in enumerate(fixture_names()):
        job = db.create_job(
            conn, key_id=key_id, worker=WORKER, client_ref=f"demo-{name}"
        )
        image = _store_image(_fixture_image(name), images_dir, job["id"])
        db.update_job(conn, job["id"], image_path=image)
        if name in LIVE_STATES:
            if LIVE_STATES[name] == "running":
                db.set_status(conn, job["id"], "running")
        elif name == FAILED_FIXTURE:
            db.set_status(
                conn, job["id"], "failed",
                error="stage 2: structuring timed out after 120s",
            )
        else:
            result = _result_for(name)
            db.update_job(
                conn,
                job["id"],
                result_json=result.model_dump(),
                validation_json=validate(result),
                meta_json={
                    "worker": WORKER,
                    "ocr_ms": 900 + 137 * index,
                    "total_ms": 1900 + 263 * index,
                    "model": config.strata_model(),
                    "quality_mode": False,
                },
            )
            db.set_status(conn, job["id"], "running")
            db.set_status(conn, job["id"], "done")
        jobs.append(db.get_job(conn, job["id"]))
    return jobs


class DemoWorker(QueueWorker):
    """The real worker, minus the two jobs the demo shows as live.

    The stock worker requeues the seeded running job on start and then drains
    both live jobs, so seconds later the queued/running screens are empty —
    the very views the demo exists to review. Claiming skips the seeded refs
    and their states go back after recovery has run over them, while a real
    "Örnek fiş" upload still runs through the same queue.
    """

    def start(self) -> None:
        super().start()
        self._restate_live_jobs()

    def _restate_live_jobs(self) -> None:
        """Undo recover()'s requeue of the running one; it never ran."""
        conn = self._db()
        for job in db.list_jobs(conn, limit=1000):
            name = str(job["client_ref"] or "").removeprefix("demo-")
            wanted = LIVE_STATES.get(name)
            if wanted and job["status"] != wanted:
                db.set_status(conn, job["id"], wanted)

    def _claim(self, conn):
        marks = ", ".join("?" * len(LIVE_REFS))
        row = conn.execute(
            "SELECT id FROM jobs WHERE status = 'queued'"
            f" AND (client_ref IS NULL OR client_ref NOT IN ({marks}))"
            " ORDER BY created_at, rowid LIMIT 1",
            tuple(LIVE_REFS),
        ).fetchone()
        return db.set_status(conn, row["id"], "running") if row else None


def _model_runner(models):
    """The real pipeline pointed at the stub servers; the queue worker and
    the admin quality-rerun route share this one runner."""
    ocr = OcrClient(base_url=models.ocr.base_url)
    structurer = Structurer(base_url=models.structurer.base_url)

    def runner(image_bytes, *, quality_mode=False, worker=""):
        return pipeline.run(
            image_bytes,
            quality_mode=quality_mode,
            worker=worker,
            ocr=ocr,
            structurer=structurer,
        )

    return runner


def _start_worker(db_path: pathlib.Path, runner) -> QueueWorker:
    """The real queue worker running the real pipeline against the stubs."""
    worker = DemoWorker(db_path=db_path, runner=runner, poll_interval=0.05)
    worker.start()
    return worker


def _add_demo_routes(app: FastAPI, api_key: str) -> None:
    """The PWA's demo handshake: its key, the sample list, the sample bytes.

    Outside /v1 and /api on purpose — the PWA must read the config before it
    has a key, and the demo key is public by design.
    """
    names = fixture_names()

    @app.get("/demo/config.json")
    def demo_config() -> dict:
        return {"api_key": api_key, "samples": names}

    @app.get("/demo/samples/{name}")
    def demo_sample(name: str):
        if name not in names:  # a closed set, so no path can be reached
            raise HTTPException(404, "unknown sample")
        return Response(_fixture_image(name).read_bytes(), media_type="image/png")


def _serve(app, port: int):
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 30.0
    while not server.started:
        if server.should_exit or time.monotonic() > deadline:
            raise DemoError("app did not come up")
        time.sleep(0.02)
    return server


def _url(server) -> str:
    host, port, *_ = server.servers[0].sockets[0].getsockname()
    return f"http://{host}:{port}"


def _boot(workdir: pathlib.Path, port: int):
    """Everything up: data dir, seeded db, stubs, app, worker."""
    os.environ["DATA_DIR"] = str(workdir)  # uploaded images land here, not in ./data
    db_path = workdir / "demo.db"
    conn = db.connect(db_path)
    try:
        key_id, api_key = auth.create_key(conn, WORKER)
        seed_jobs(conn, key_id=key_id, images_dir=config.images_dir())
    finally:
        conn.close()
    models = start_fake_models()
    runner = _model_runner(models)
    app = create_app(db_path=db_path, runner=runner)
    _add_demo_routes(app, api_key)
    server = _serve(app, port)
    worker = _start_worker(db_path, runner)
    return server, worker, models, api_key


def _check(base_url: str, api_key: str) -> None:
    with httpx.Client(
        base_url=base_url, timeout=30.0, follow_redirects=True
    ) as client:
        resp = client.get("/app")
        if resp.status_code != 200:
            raise DemoError(f"GET /app -> HTTP {resp.status_code}")
        # ASSUMPTION: the admin UI is M3; until it lands its mount answers
        # 404, so the check only requires the app to answer for /admin.
        resp = client.get("/admin")
        if resp.status_code not in (200, 404):
            raise DemoError(f"GET /admin -> HTTP {resp.status_code}")
        resp = client.get("/api/me/jobs", headers={"X-API-Key": api_key})
        if resp.status_code != 200:
            raise DemoError(f"GET /api/me/jobs -> HTTP {resp.status_code}")
        if not resp.json()["jobs"]:
            raise DemoError("the seeded demo key sees no jobs")


def _review(base_url: str, api_key: str) -> None:
    _log("PWA", f"{base_url}/app — demo key pre-filled, Örnek fiş ready")
    _log("admin", f"{base_url}/admin")
    _log("api key", api_key)
    print("Ctrl+C to stop", flush=True)
    while True:
        time.sleep(3600)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Demo server: fake model stubs + seeded jobs on :8090."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="boot on an ephemeral port, probe /app /admin /api/me/jobs, exit 0",
    )
    parser.add_argument("--port", type=int, default=config.app_port())
    args = parser.parse_args(argv)
    started = time.perf_counter()
    # ignore_errors: the worker's recovery connection can outlive stop() on
    # Windows, and a demo must not fail over a leftover temp directory.
    with tempfile.TemporaryDirectory(
        prefix="ocr-demo-", ignore_cleanup_errors=True
    ) as workdir:
        try:
            # ASSUMPTION: --check boots on an ephemeral port so the gate can
            # run while a demo is already serving on 8090.
            server, worker, models, api_key = _boot(
                pathlib.Path(workdir), 0 if args.check else args.port
            )
        except Exception as exc:
            _log("DEMO FAILED", str(exc))
            return 1
        code = 0
        try:
            if args.check:
                try:
                    _check(_url(server), api_key)
                except Exception as exc:
                    _log("DEMO CHECK FAILED", str(exc))
                    code = 1
                else:
                    _log(
                        "DEMO CHECK OK",
                        f"booted and probed in {time.perf_counter() - started:.1f}s",
                    )
            else:
                _review(_url(server), api_key)
        except KeyboardInterrupt:
            pass
        finally:
            worker.stop()
            models.shutdown()
        return code


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        # the banner carries Turkish; a cp1252 console would kill the print
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
