"""T108: a failed job keeps its meta — the timings an operator opens it for.

The row a stage-1 death lands on is exactly the row the admin detail opens to
find out what died, and it was the one row in the system that answered "Aşama
süreleri —" for a run that spent the whole OCR_TIMEOUT_S: the worker merged the
bundle's meta and then handed the failure branch only the error string, so
meta_json stayed NULL and stage_ms, total_ms and model read the contract's
zeros and "". Only stage 1 is faked (pipeline.run's own seam), so the meta under
test is the one production writes, and the row, GET /v1/jobs/{id} and the admin
detail are the real chain PLAN contract 13 names.
"""
from __future__ import annotations

import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, config, db, pipeline
from app.main import create_app
from app.ocr_client import OcrError
from app.queue_worker import QueueWorker

STAMP = "2026-10-30T14:03:00Z"
ANAHTAR = "yonetici-anahtari-4b8d"
WAIT = 0.06  # a stage 1 worth reading on a screen: 60 ms, reported >= 50


def jpeg(width: int = 60, height: int = 40) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


IMAGE = jpeg()


class DeadOcr:
    """Stage 1 that burns the clock and raises: the cold-load timeout in mini."""

    def transcribe(self, image_bytes, *, quality_mode=False):
        time.sleep(WAIT)
        raise OcrError("ocr server unreachable")


class NeverReachedStructurer:
    def structure(self, ocr_text, image_bytes):  # pragma: no cover - stage 1 died
        raise AssertionError("stage 2 must not run after a stage-1 death")


def runner(image_bytes, *, quality_mode=False, worker=""):
    return pipeline.run(
        image_bytes,
        quality_mode=quality_mode,
        worker=worker,
        ocr=DeadOcr(),
        structurer=NeverReachedStructurer(),
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    auth._buckets.clear()
    auth._sessions.clear()
    # the backend this file describes: meta.model is the Strata id it asserts
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, plaintext = auth.create_key(conn, "ayse")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn, path, plaintext
    conn.close()
    auth._buckets.clear()
    auth._sessions.clear()


def submit(client, plaintext):
    return client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.jpg", IMAGE, "image/jpeg")},
        data={"captured_at": STAMP},
    ).json()["job_id"]


def process(path):
    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()


def body_of(client, plaintext, job_id):
    resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200
    return resp.json()


def row_meta(conn, job_id):
    return json.loads(db.get_job(conn, job_id)["meta_json"])


# --- the row itself ---------------------------------------------------------


def test_a_stage_one_death_stores_its_timings_on_the_row(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)

    process(path)

    row = db.get_job(conn, job_id)
    assert row["status"] == "failed"
    assert row["error"].startswith("stage 1:")
    meta = json.loads(row["meta_json"])
    stages = meta["stage_ms"]
    assert stages["ocr"] >= 50  # the wait it actually waited, not 0
    assert stages["structure"] == 0  # nothing past stage 1 ran
    assert stages["validate"] == 0
    assert meta["total_ms"] >= stages["ocr"] - 1  # total truncates, the wait rounds up
    assert meta["model"] == config.strata_model()
    assert meta["worker"] == "ayse"


# --- and every door that reads the row --------------------------------------


def test_get_reports_the_failed_run_instead_of_zeros(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)

    process(path)

    body = body_of(client, plaintext, job_id)
    assert body["status"] == "failed"
    assert body["meta"]["stage_ms"] == row_meta(conn, job_id)["stage_ms"]
    assert body["meta"]["stage_ms"]["ocr"] >= 50
    assert body["meta"]["total_ms"] > 0
    assert body["meta"]["model"] == config.strata_model()


def test_the_admin_detail_reports_the_same_numbers(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)

    process(path)

    resp = client.get(f"/admin/api/jobs/{job_id}")
    assert resp.status_code == 200
    detay = resp.json()
    assert detay["status"] == "failed"
    assert detay["meta"] == body_of(client, plaintext, job_id)["meta"]
    assert detay["meta"]["stage_ms"]["ocr"] >= 50


def test_the_list_view_reports_them_too(env):
    client, _, path, plaintext = env
    submit(client, plaintext)

    process(path)

    bodies = client.get("/v1/jobs", headers={"X-API-Key": plaintext}).json()
    assert [body["status"] for body in bodies] == ["failed"]
    assert bodies[0]["meta"]["stage_ms"]["ocr"] >= 50


# --- the merge keeps what the route stored ----------------------------------


def test_captured_at_and_received_at_survive_the_failure_merge(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)
    received = db.get_job(conn, job_id)["created_at"]

    process(path)

    meta = body_of(client, plaintext, job_id)["meta"]
    assert meta["captured_at"] == STAMP
    assert meta["received_at"] == received


def test_result_and_validation_stay_null_on_a_failed_job(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)

    process(path)

    row = db.get_job(conn, job_id)
    assert not row["result_json"] and not row["validation_json"]
    body = body_of(client, plaintext, job_id)
    assert body["result"] is None
    assert body["validation"] is None
