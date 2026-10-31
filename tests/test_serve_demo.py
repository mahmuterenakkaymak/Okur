"""The demo is the review surface, so both of its jobs are pinned.

--check is the gate (real app, real sockets, real queue — the same stack
visual review runs on), and the seed is what makes every screen reviewable:
every queue state, every verdict, images on disk, both fixture dirs.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from fastapi.testclient import TestClient

from app import auth, config, db, validator
from app.main import create_app
from scripts import serve_demo


def _seed(tmp_path):
    """A demo-seeded database the way _boot would make one."""
    conn = db.connect(tmp_path / "demo.db")
    key_id, api_key = auth.create_key(conn, serve_demo.WORKER)
    jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    return conn, api_key, jobs


def test_seed_covers_every_state_and_verdict(tmp_path):
    _, _, jobs = _seed(tmp_path)
    assert {job["status"] for job in jobs} == {"queued", "running", "done", "failed"}
    verdicts = {
        json.loads(job["validation_json"])["verdict"]
        for job in jobs
        if job["validation_json"]
    }
    assert {"ok", "mismatch", "unreadable"} <= verdicts
    names = {job["client_ref"].removeprefix("demo-") for job in jobs}
    assert {"fis_market_clean", "el_yazisi_not"} <= names  # both fixture dirs
    for job in jobs:
        assert pathlib.Path(job["image_path"]).is_file()


def test_done_jobs_revalidate(tmp_path):
    _, _, jobs = _seed(tmp_path)
    for job in jobs:
        if job["status"] != "done":
            continue
        result = json.loads(job["result_json"])
        assert validator.validate(result) == json.loads(job["validation_json"])


def test_mismatch_job_names_its_offending_fields(tmp_path):
    _, _, jobs = _seed(tmp_path)
    mismatched = [
        json.loads(job["validation_json"])
        for job in jobs
        if job["validation_json"]
        and json.loads(job["validation_json"])["verdict"] == "mismatch"
    ]
    assert mismatched and all(block["fields"] for block in mismatched)


def test_demo_routes_serve_config_and_samples(tmp_path):
    app = create_app(db_path=tmp_path / "demo.db")
    serve_demo._add_demo_routes(app, "ocrk_demo")
    client = TestClient(app)

    conf = client.get("/demo/config.json").json()
    assert conf["api_key"] == "ocrk_demo"
    assert "fis_market_clean" in conf["samples"]

    resp = client.get("/demo/samples/fis_market_clean")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

    assert client.get("/demo/samples/olmayan-fis").status_code == 404


def test_check_boots_probes_and_exits_zero():
    run = subprocess.run(
        [sys.executable, str(config.ROOT / "scripts" / "serve_demo.py"), "--check"],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "DEMO CHECK OK" in run.stdout


def test_check_reports_failure_when_boot_breaks(monkeypatch, capsys):
    def no_boot(*args, **kwargs):
        raise serve_demo.DemoError("app did not come up")

    monkeypatch.setattr(serve_demo, "_boot", no_boot)
    assert serve_demo.main(["--check"]) == 1
    assert "app did not come up" in capsys.readouterr().out
