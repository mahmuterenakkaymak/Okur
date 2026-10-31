"""captured_at through the queue: the route stores it, the worker must not drop it.

There is no captured_at column, so the route parks it in the row's meta_json
and the worker answers for the finished job with the pipeline bundle — a full
JobMeta dump whose own captured_at is null. Only the two model servers are
stubbed here (pipeline.run's own seams), so the meta the worker writes is
exactly the one production produces, and GET is where a null would surface.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, config, db, pipeline
from app.main import create_app
from app.queue_worker import QueueWorker

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
STAMP = "2026-10-30T14:03:00Z"
RESULT = {
    "header": {"isim": "Test Market", "vergi_dairesi": "Kadıköy"},
    "items": [{"ad": "Çay", "miktar": 1.0, "birim_fiyat": 12.5, "toplam": 12.5}],
    "totals": {"ara_toplam": 12.5, "iskonto": 0.0, "kdv": 2.08, "toplam": 12.5},
}


class FakeOcr:
    def transcribe(self, image_bytes, *, quality_mode=False):
        return {"text": "Çay 12,50", "ms": 10}


class FakeStructurer:
    def structure(self, ocr_text, image_bytes):
        return {**RESULT, "ms": 5}


def runner(image_bytes, *, quality_mode=False, worker=""):
    return pipeline.run(
        image_bytes,
        quality_mode=quality_mode,
        worker=worker,
        ocr=FakeOcr(),
        structurer=FakeStructurer(),
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, plaintext = auth.create_key(conn, "ayse")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    yield client, conn, path, plaintext
    conn.close()
    auth._buckets.clear()


def submit(client, plaintext, data=None):
    return client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.jpg", IMAGE, "image/jpeg")},
        data=data or {},
    )


def process(path):
    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()


def meta_of(client, plaintext, job_id):
    resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200
    return resp.json()["meta"]


def test_captured_at_survives_the_worker_into_the_get(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext, {"captured_at": STAMP}).json()["job_id"]
    received = db.get_job(conn, job_id)["created_at"]

    process(path)

    meta = meta_of(client, plaintext, job_id)
    assert meta["captured_at"] == STAMP
    assert meta["received_at"] == received
    assert meta["worker"] == "ayse"
    assert meta["model"] == config.strata_model()
    assert meta["total_ms"] >= 0


def test_the_list_view_reports_it_too(env):
    client, _, path, plaintext = env
    submit(client, plaintext, {"captured_at": STAMP})
    process(path)
    bodies = client.get("/v1/jobs", headers={"X-API-Key": plaintext}).json()
    assert [body["status"] for body in bodies] == ["done"]
    assert [body["meta"]["captured_at"] for body in bodies] == [STAMP]


def test_a_rerun_keeps_captured_at_and_refreshes_the_pipeline_meta(env, monkeypatch):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext, {"captured_at": STAMP}).json()["job_id"]
    process(path)
    monkeypatch.setenv("STRATA_MODEL", "strata-rerun")
    db.set_status(conn, job_id, "queued")

    process(path)

    meta = meta_of(client, plaintext, job_id)
    assert meta["captured_at"] == STAMP
    assert meta["model"] == "strata-rerun"


def test_captured_at_stays_null_when_it_was_never_sent(env):
    client, _, path, plaintext = env
    job_id = submit(client, plaintext).json()["job_id"]

    process(path)

    meta = meta_of(client, plaintext, job_id)
    assert meta["captured_at"] is None
    assert meta["model"] == config.strata_model()
