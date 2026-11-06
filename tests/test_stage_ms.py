"""stage_ms: the pipeline times it, the queue merges it, GET still reports it.

The run's one additive /v1 field, so both halves matter: an old row (or a junk
one) reads as three zeros instead of breaking a view, and a finished job keeps
its breakdown through the worker's meta merge — the same rule T52 wrote for
captured_at, one level deeper. Only the two model servers are stubbed, so the
meta under test is exactly the one production writes.
"""
from __future__ import annotations

import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, contract, db, pipeline
from app.main import create_app
from app.ocr_client import OcrError
from app.queue_worker import QueueWorker
from app.structurer import UnreadableError
from scripts import serve_demo

STAMP = "2026-10-30T14:03:00Z"
RESULT = {
    "header": {"isim": "Test Market", "vergi_dairesi": "Kadıköy"},
    "items": [{"ad": "Çay", "miktar": 1.0, "birim_fiyat": 12.5, "toplam": 12.5}],
    "totals": {"ara_toplam": 12.5, "iskonto": 0.0, "kdv": 2.08, "toplam": 12.5},
}
OLD_META = {
    "worker": "ayse",
    "captured_at": STAMP,
    "received_at": "2026-10-30T14:04:00Z",
    "ocr_ms": 900,
    "total_ms": 31600,
    "model": "strata-30b",
    "quality_mode": False,
}


def jpeg(width: int = 60, height: int = 40) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


IMAGE = jpeg()


class FakeOcr:
    def __init__(self, ms=7, error: bool = False):
        self.ms, self.error = ms, error

    def transcribe(self, image_bytes, *, quality_mode=False):
        if self.error:
            raise OcrError("ocr server unreachable")
        return {"text": "Çay 12,50", "ms": self.ms}


class FakeStructurer:
    """Reports its own ms the way the real structurer does."""

    def __init__(self, ms=5, sleep=0.0, error: Exception | None = None):
        self.ms, self.sleep, self.error = ms, sleep, error

    def structure(self, ocr_text, image_bytes):
        started = time.perf_counter()
        if self.sleep:
            time.sleep(self.sleep)
        if self.error:
            raise self.error
        reported = self.ms
        if reported is None:  # honest self-report, like the real client
            reported = int((time.perf_counter() - started) * 1000)
        return {**RESULT, "ms": reported}


def make_runner(ocr=None, structurer=None, tune=None):
    def runner(image_bytes, *, quality_mode=False, worker=""):
        bundle = pipeline.run(
            image_bytes,
            quality_mode=quality_mode,
            worker=worker,
            ocr=ocr or FakeOcr(),
            structurer=structurer or FakeStructurer(),
        )
        if tune is not None:
            tune(bundle)
        return bundle

    return runner


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


def process(path, runner=None):
    QueueWorker(path, runner=runner or make_runner(), poll_interval=0.01).run_once()


def submit(client, plaintext):
    resp = client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.jpg", IMAGE, "image/jpeg")},
        data={"captured_at": STAMP},
    )
    return resp.json()["job_id"]


def meta_of(client, plaintext, job_id):
    resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200
    return resp.json()["meta"]


# --- the contract field -----------------------------------------------------


def test_missing_stage_ms_reads_three_zeros():
    assert contract.JobMeta.parse(OLD_META).model_dump()["stage_ms"] == {
        "ocr": 0,
        "structure": 0,
        "validate": 0,
    }


def test_junk_stage_values_read_zero():
    stages = contract.JobMeta.parse(
        {"stage_ms": {"ocr": "yok", "structure": None, "validate": -5, "ek": 1}}
    ).stage_ms
    assert stages.model_dump() == {"ocr": 0, "structure": 0, "validate": 0}


@pytest.mark.parametrize("junk", ["yok", 5, ["ocr"], True])
def test_a_junk_stage_block_reads_zeros(junk):
    meta = contract.JobEnvelope.parse({"meta": {"stage_ms": junk}}).meta
    assert meta.stage_ms.model_dump() == {"ocr": 0, "structure": 0, "validate": 0}


def test_printed_numbers_become_ints():
    stages = contract.JobMeta.parse({"stage_ms": {"ocr": "1.046", "structure": 30.9}})
    assert stages.stage_ms.model_dump() == {"ocr": 1046, "structure": 30, "validate": 0}


def test_no_existing_meta_field_changed_shape():
    meta = contract.JobMeta.parse(OLD_META).model_dump()
    assert {key: value for key, value in meta.items() if key != "stage_ms"} == OLD_META


# --- the pipeline times all three stages ------------------------------------


def test_the_pipeline_reports_the_three_stages():
    bundle = pipeline.run(
        IMAGE, ocr=FakeOcr(ms=900), structurer=FakeStructurer(ms=30600)
    )
    stages = bundle["meta"]["stage_ms"]
    assert stages["ocr"] == 900
    assert stages["structure"] == 30600
    assert isinstance(stages["validate"], int) and stages["validate"] >= 0


def test_total_ms_stays_the_whole_run():
    bundle = pipeline.run(
        IMAGE, ocr=FakeOcr(ms=1), structurer=FakeStructurer(ms=None, sleep=0.05)
    )
    stages = bundle["meta"]["stage_ms"]
    assert stages["structure"] >= 40  # the structurer's own reported ms
    assert bundle["meta"]["total_ms"] >= stages["structure"]
    assert bundle["meta"]["ocr_ms"] == 1  # the old field still reports stage 1


def test_a_stage_that_never_ran_reads_zero():
    bundle = pipeline.run(IMAGE, ocr=FakeOcr(error=True), structurer=FakeStructurer())
    assert bundle["error"].startswith("stage 1:")
    assert bundle["meta"]["stage_ms"] == {"ocr": 0, "structure": 0, "validate": 0}


def test_a_stage_two_outage_reports_the_measured_wait():
    bundle = pipeline.run(
        IMAGE,
        ocr=FakeOcr(ms=900),
        structurer=FakeStructurer(sleep=0.06, error=RuntimeError("down")),
    )
    # Stage 2 died without answering, so it has no ms to report and the pipeline
    # times the wait it actually waited: a 0 here reads as "never ran".
    stages = bundle["meta"]["stage_ms"]
    assert stages["ocr"] == 900
    assert stages["structure"] >= 50
    assert stages["validate"] == 0  # a run that died in stage 2 validated nothing
    assert bundle["meta"]["total_ms"] >= stages["structure"] - 1


def test_the_unreadable_path_reports_what_it_measured():
    bundle = pipeline.run(
        IMAGE,
        ocr=FakeOcr(ms=900),
        structurer=FakeStructurer(error=UnreadableError("no JSON")),
    )
    assert bundle["error"] == ""
    assert bundle["meta"]["stage_ms"]["ocr"] == 900
    assert bundle["meta"]["stage_ms"]["validate"] >= 0


# --- the queue keeps it, so a GET after done still reports it ----------------


def test_a_get_after_done_reports_stage_ms(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)

    process(path)

    stages = meta_of(client, plaintext, job_id)["stage_ms"]
    assert stages["ocr"] == 7
    assert stages["structure"] == 5
    assert isinstance(stages["validate"], int) and stages["validate"] >= 0
    assert meta_of(client, plaintext, job_id)["captured_at"] == STAMP


def test_the_list_view_reports_it_too(env):
    client, _, path, plaintext = env
    submit(client, plaintext)

    process(path)

    bodies = client.get("/v1/jobs", headers={"X-API-Key": plaintext}).json()
    assert bodies[0]["meta"]["stage_ms"]["structure"] == 5


def test_a_stored_stage_the_runner_did_not_report_survives_the_merge(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)
    db.update_job(
        conn,
        job_id,
        meta_json={"captured_at": STAMP, "stage_ms": {"ocr": 900, "structure": 30600}},
    )

    def partial(bundle):  # a runner that only timed the validator
        bundle["meta"]["stage_ms"] = {"validate": 1}

    process(path, make_runner(tune=partial))

    assert meta_of(client, plaintext, job_id)["stage_ms"] == {
        "ocr": 900,
        "structure": 30600,
        "validate": 1,
    }


def test_a_row_written_before_stage_ms_reports_zeros(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)
    db.update_job(conn, job_id, meta_json=dict(OLD_META))
    db.set_status(conn, job_id, "done", result_json=RESULT, validation_json={})

    assert meta_of(client, plaintext, job_id)["stage_ms"] == {
        "ocr": 0,
        "structure": 0,
        "validate": 0,
    }


def test_a_junk_stored_block_never_breaks_the_worker_or_the_get(env):
    client, conn, path, plaintext = env
    job_id = submit(client, plaintext)
    db.update_job(conn, job_id, meta_json={"stage_ms": "yok"})

    process(path)

    assert meta_of(client, plaintext, job_id)["stage_ms"]["structure"] == 5


# --- the demo screens show numbers ------------------------------------------


def test_every_seeded_run_carries_stage_times(tmp_path):
    conn = db.connect(tmp_path / "demo.db")
    try:
        key_id, _ = auth.create_key(conn, serve_demo.WORKER)
        jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "img")
    finally:
        conn.close()
    done = [job for job in jobs if job["status"] == "done"]
    assert done
    for job in done:
        meta = json.loads(job["meta_json"])
        stages = meta["stage_ms"]
        assert set(stages) == {"ocr", "structure", "validate"}
        assert all(isinstance(value, int) and value > 0 for value in stages.values())
        assert sum(stages.values()) <= meta["total_ms"]
        assert stages["ocr"] == meta["ocr_ms"]
