"""M5 integration: the small backend from a real socket into the real app.

STRUCTURER_BACKEND=small and SMALL_BRAIN_BASE_URL are the only things pointed at
the stub servers; everything between the two model roles is the shipped code
over real sockets — auth middleware, SQLite queue, worker thread, pipeline and
validator — and stage 2 runs through app.structurer.Structurer's own defaults.
Nothing hand-rolls a structurer here, so a pipeline that re-hardcodes the Strata
id or a structurer that ignores the backend fails this test.
"""
from __future__ import annotations

import json
import socket
import time

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import auth, config, contract, db
from app.main import create_app
from app.queue_worker import QueueWorker
from scripts.fake_models import start_fake_models

FIXTURE = "fis_market_clean"
FIXTURE_JSON = config.ROOT / "fixtures" / f"{FIXTURE}.json"
FIXTURE_PNG = config.ROOT / "fixtures" / f"{FIXTURE}.png"
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
# An id only the small brain has: whatever else ran, the job will say so.
SMALL_BRAIN_ID = "Qwen3-VL-4B-Small-Test"
POLL_TIMEOUT_S = 20.0


def closed_port() -> int:
    """A port nothing listens on — a job that wandered off to Strata fails."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real app, queue and worker; both model roles on real HTTP sockets."""
    auth._buckets.clear()
    models = start_fake_models()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OCR_HOST", str(httpx.URL(models.ocr.base_url).host))
    monkeypatch.setenv("OCR_PORT", str(models.ocr.port))
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", models.structurer.base_url)
    monkeypatch.setenv("SMALL_BRAIN_MODEL", SMALL_BRAIN_ID)
    monkeypatch.setenv("STRATA_HOST", "127.0.0.1")
    monkeypatch.setenv("STRATA_PORT", str(closed_port()))

    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, plaintext = auth.create_key(conn, "ayse")
    conn.close()
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    worker = QueueWorker(db_path=path, poll_interval=0.02)
    worker.start()
    yield client, plaintext
    worker.stop()
    models.shutdown()
    auth._buckets.clear()


def poll(client, plaintext, job_id):
    """Poll to a terminal status; every envelope seen is contract v1."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        body = resp.json()
        jsonschema.validate(body, SCHEMA)
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job stuck in {body['status']}"
        time.sleep(0.05)


def test_small_backend_runs_a_job_end_to_end(env):
    client, plaintext = env
    accepted = client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": (FIXTURE_PNG.name, FIXTURE_PNG.read_bytes(), "image/png")},
        data={"client_ref": "small-001"},
    )
    assert accepted.status_code == 202
    body = poll(client, plaintext, accepted.json()["job_id"])

    truth = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    assert body["status"] == "done", body
    assert body["meta"]["model"] == SMALL_BRAIN_ID
    assert body["meta"]["quality_mode"] is False
    assert body["meta"]["worker"] == "ayse"
    assert body["validation"]["verdict"] == "ok"
    assert body["validation"]["fields"] == []
    assert body["result"]["totals"] == truth["totals"]


def test_stub_reports_the_resolved_stage2_model(monkeypatch):
    """The structurer role answers as the backend config picked, not as Strata."""
    models = start_fake_models()
    try:
        monkeypatch.setenv("STRUCTURER_BACKEND", "small")
        monkeypatch.setenv("SMALL_BRAIN_MODEL", SMALL_BRAIN_ID)
        listed = httpx.get(f"{models.structurer.base_url}/v1/models", timeout=10).json()
        assert listed["data"][0]["id"] == SMALL_BRAIN_ID
    finally:
        models.shutdown()
