import contextlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.queue_worker import QueueWorker, recover

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"


def bundle(error=""):
    return {
        "result": {"items": [{"ad": "Çay", "toplam": 12.5}]},
        "validation": {"verdict": "ok", "fields": []},
        "meta": {"model": "test-model", "ocr_ms": 10, "total_ms": 20},
        "error": error,
    }


def ok_runner(image_bytes, *, quality_mode=False, worker=""):
    return bundle()


def ago(minutes: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wait_until(fn, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def env(tmp_path):
    image = tmp_path / "fis.jpg"
    image.write_bytes(IMAGE)
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    yield path, conn, str(image)
    conn.close()


def submit(conn, image_path, **kwargs):
    return db.create_job(conn, image_path=image_path, **kwargs)


@contextlib.contextmanager
def running(worker):
    worker.start()
    try:
        yield worker
    finally:
        worker.stop()


# --- one job through the state machine ---


def test_run_once_processes_oldest_queued_job(env):
    path, conn, image = env
    first = submit(conn, image, worker="ayse")
    second = submit(conn, image)
    assert QueueWorker(path, runner=ok_runner, poll_interval=0.01).run_once() is True
    assert db.get_job(conn, first["id"])["status"] == "done"
    assert db.get_job(conn, second["id"])["status"] == "queued"


def test_job_is_running_while_the_runner_sees_it(env):
    path, conn, image = env
    job = submit(conn, image)
    seen = {}

    def runner(image_bytes, *, quality_mode=False, worker=""):
        seen["status"] = db.get_job(conn, job["id"])["status"]
        seen["image"] = image_bytes
        return bundle()

    assert QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    assert seen["status"] == "running"
    assert seen["image"] == IMAGE


def test_done_stamps_finished_and_stores_the_bundle(env):
    path, conn, image = env
    job = submit(conn, image)
    QueueWorker(path, runner=ok_runner, poll_interval=0.01).run_once()
    done = db.get_job(conn, job["id"])
    assert done["status"] == "done"
    assert done["started_at"] and done["finished_at"]
    assert done["error"] == ""
    assert json.loads(done["result_json"])["items"][0]["ad"] == "Çay"
    assert json.loads(done["validation_json"])["verdict"] == "ok"


def test_meta_keeps_pipeline_fields_and_gains_received_at(env):
    path, conn, image = env
    job = submit(conn, image)
    QueueWorker(path, runner=ok_runner, poll_interval=0.01).run_once()
    meta = json.loads(db.get_job(conn, job["id"])["meta_json"])
    assert meta["model"] == "test-model"
    assert meta["ocr_ms"] == 10
    assert meta["received_at"] == job["created_at"]


def test_runner_gets_quality_mode_and_worker(env):
    path, conn, image = env
    job = submit(conn, image, worker="ayse", mode="quality")
    calls = []

    def runner(image_bytes, *, quality_mode=False, worker=""):
        calls.append({"quality_mode": quality_mode, "worker": worker})
        return bundle()

    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    assert calls == [{"quality_mode": True, "worker": "ayse"}]


def test_fast_mode_is_the_default_for_the_runner(env):
    path, conn, image = env
    submit(conn, image)
    calls = []

    def runner(image_bytes, *, quality_mode=False, worker=""):
        calls.append(quality_mode)
        return bundle()

    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    assert calls == [False]


# --- failures ---


def test_bundle_error_fails_the_job_and_keeps_result_null(env):
    path, conn, image = env
    job = submit(conn, image)
    runner = lambda img, **kw: bundle(error="stage 1: OCR server returned HTTP 503")
    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    failed = db.get_job(conn, job["id"])
    assert failed["status"] == "failed"
    assert "503" in failed["error"]
    assert failed["result_json"] is None


def test_runner_exception_fails_job_but_the_worker_survives(env):
    path, conn, image = env
    first = submit(conn, image)
    second = submit(conn, image)
    calls = []

    def runner(image_bytes, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("model exploded")
        return bundle()

    worker = QueueWorker(path, runner=runner, poll_interval=0.01)
    worker.run_once()
    assert db.get_job(conn, first["id"])["status"] == "failed"
    assert "model exploded" in db.get_job(conn, first["id"])["error"]
    worker.run_once()
    assert db.get_job(conn, second["id"])["status"] == "done"


def test_missing_image_file_fails_the_job(env):
    path, conn, _ = env
    job = submit(conn, str(path.parent / "nope.jpg"))
    QueueWorker(path, runner=ok_runner, poll_interval=0.01).run_once()
    failed = db.get_job(conn, job["id"])
    assert failed["status"] == "failed"
    assert failed["error"].startswith("image:")


# --- burst absorption and the thread ---


def test_burst_of_jobs_is_absorbed(env):
    path, conn, image = env
    calls = []

    def runner(image_bytes, **kw):
        time.sleep(0.005)
        calls.append(image_bytes)
        return bundle()

    worker = QueueWorker(path, runner=runner, poll_interval=0.01)
    with running(worker):
        ids = [submit(conn, image)["id"] for _ in range(8)]
        # a job that lands mid-burst is absorbed too
        ids.append(submit(conn, image)["id"])
        assert wait_until(
            lambda: all(
                db.get_job(conn, jid)["status"] == "done" for jid in ids
            )
        ), "burst did not drain"
    assert len(calls) == 9


def test_start_processes_queued_jobs_and_stop_ends_the_thread(env):
    path, conn, image = env
    job = submit(conn, image)
    worker = QueueWorker(path, runner=ok_runner, poll_interval=0.01)
    with running(worker):
        assert wait_until(
            lambda: db.get_job(conn, job["id"])["status"] == "done"
        ), "queued job never ran"
    assert worker._thread is None
    late = submit(conn, image)
    time.sleep(0.05)
    assert db.get_job(conn, late["id"])["status"] == "queued"


def test_stop_waits_for_the_job_in_flight(env):
    path, conn, image = env
    job = submit(conn, image)
    started = threading.Event()
    gate = threading.Event()

    def runner(image_bytes, **kw):
        started.set()
        gate.wait(5)
        return bundle()

    worker = QueueWorker(path, runner=runner, poll_interval=0.01)
    worker.start()
    try:
        assert started.wait(5)
        threading.Timer(0.05, gate.set).start()
        worker.stop(timeout=5)
        assert db.get_job(conn, job["id"])["status"] == "done"
    finally:
        gate.set()


# --- restart recovery ---


def test_recover_requeues_recently_running_jobs(env):
    path, conn, image = env
    job = submit(conn, image)
    db.set_status(conn, job["id"], "running")
    assert recover(conn, stale_minutes=10) == {"requeued": 1, "failed": 0}
    assert db.get_job(conn, job["id"])["status"] == "queued"


def test_recover_fails_stale_running_jobs(env):
    path, conn, image = env
    job = submit(conn, image)
    db.set_status(conn, job["id"], "running")
    db.update_job(conn, job["id"], started_at=ago(30))
    assert recover(conn, stale_minutes=10) == {"requeued": 0, "failed": 1}
    failed = db.get_job(conn, job["id"])
    assert failed["status"] == "failed"
    assert "stale" in failed["error"]


def test_recover_leaves_other_statuses_alone(env):
    path, conn, image = env
    queued = submit(conn, image)
    done = submit(conn, image)
    db.set_status(conn, done["id"], "running")
    db.set_status(conn, done["id"], "done")
    assert recover(conn, stale_minutes=10) == {"requeued": 0, "failed": 0}
    assert db.get_job(conn, queued["id"])["status"] == "queued"
    assert db.get_job(conn, done["id"])["status"] == "done"


def test_start_recovers_the_crash_then_processes(env):
    path, conn, image = env
    crashed = submit(conn, image)
    db.set_status(conn, crashed["id"], "running")
    fresh = submit(conn, image)
    worker = QueueWorker(path, runner=ok_runner, poll_interval=0.01)
    with running(worker):
        assert wait_until(
            lambda: db.get_job(conn, crashed["id"])["status"] == "done"
            and db.get_job(conn, fresh["id"])["status"] == "done"
        ), "recovered job never ran"
