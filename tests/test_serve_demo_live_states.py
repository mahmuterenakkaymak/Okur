"""The seeded live states must outlive the boot that seeds them.

QueueWorker.start() requeues the seeded running job and the loop then drains
both live jobs, so seconds after boot the queued/running screens — the whole
reason the demo seeds them — are empty. The check boots the real stack and
pushes one real upload through it: claiming is oldest-first, so an upload
that reaches done proves the worker has been through everything seeded
before it, the live jobs included.
"""
from __future__ import annotations

import time

import httpx

from app import config, db
from scripts import serve_demo

UPLOAD_REF = "live-check"
DONE_TIMEOUT_S = 60.0


def _statuses(db_path):
    conn = db.connect(db_path)
    try:
        return {
            job["client_ref"]: job["status"]
            for job in db.list_jobs(conn, limit=1000)
        }
    finally:
        conn.close()


def _upload(base_url: str, api_key: str) -> str:
    """One real fixture into the live queue — the settle signal."""
    png = config.ROOT / "fixtures" / "fis_market_clean.png"
    resp = httpx.post(
        f"{base_url}/v1/jobs",
        headers={"X-API-Key": api_key},
        files={"image": (png.name, png.read_bytes(), "image/png")},
        data={"client_ref": UPLOAD_REF},
        timeout=30.0,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["job_id"]


def _await_done(base_url: str, api_key: str, job_id: str) -> None:
    deadline = time.monotonic() + DONE_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = httpx.get(
            f"{base_url}/v1/jobs/{job_id}",
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )
        assert resp.status_code == 200, resp.text
        status = resp.json()["status"]
        assert status != "failed", "the demo worker failed the upload"
        if status == "done":
            return
        time.sleep(0.05)
    raise AssertionError(f"upload still not done after {DONE_TIMEOUT_S:.0f}s")


def test_queued_and_running_jobs_survive_the_worker(tmp_path, monkeypatch):
    # _boot points DATA_DIR at its workdir; monkeypatch puts it back after
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    server, worker, models, api_key = serve_demo._boot(tmp_path, 0)
    try:
        base_url = serve_demo._url(server)
        _await_done(base_url, api_key, _upload(base_url, api_key))
        statuses = _statuses(tmp_path / "demo.db")
        expected = {
            f"demo-{name}": state for name, state in serve_demo.LIVE_STATES.items()
        }
        assert {ref: statuses[ref] for ref in expected} == expected
        assert {"queued", "running"} <= set(statuses.values())
    finally:
        worker.stop()
        models.shutdown()
