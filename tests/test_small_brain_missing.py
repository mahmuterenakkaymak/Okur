"""A job says why the brain is missing (T79).

A CPU-only box with no model files installed has no stage-2 server to answer,
and every receipt then dies the same way. "structuring server unreachable" tells
the operator nothing; "small brain not installed — çalıştırmak için
scripts\\install_small_brain.ps1" tells them to run one command. The sentence is
born in the structurer and rides the job: the queue row's error column, the
admin detail and the worker's failure line — and the worker treats it as the
expected outcome it is, so no traceback reaches its log.
"""
import functools

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, config, db, pipeline
from app.main import create_app
from app.queue_worker import QueueWorker
from app.structurer import NOT_INSTALLED, Structurer

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<fcel>BILGIN MARKETLER<nl>"
ADMIN_TOKEN = "yonetici-anahtari-4b8d"


class FakeOcr:
    def transcribe(self, image_bytes, quality_mode=False):
        return {"text": OCR_TEXT, "ms": 1200}


def refused(request):
    raise httpx.ConnectError("[WinError 10061] connection refused")


def timed_out(request):
    raise httpx.ReadTimeout("no answer in time")


def structurer(handler=refused, **kwargs):
    return Structurer(transport=httpx.MockTransport(handler), **kwargs)


def reason(handler=refused, **kwargs):
    """The one line stage 2 leaves behind when it cannot reach its server."""
    try:
        structurer(handler, **kwargs).structure(OCR_TEXT, IMAGE)
    except Exception as exc:  # StructurerError is the only thing that raises here
        return str(exc)
    raise AssertionError("the request was expected to fail")


# --- stage 2: missing install vs. installed-but-down ---


def test_a_refused_connection_with_no_brain_installed_names_the_installer(
    monkeypatch,
):
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    assert reason(backend="small") == NOT_INSTALLED


def test_the_backend_comes_from_config_not_from_a_caller(
    monkeypatch,
):
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    assert reason() == NOT_INSTALLED


def test_an_installed_brain_that_is_down_stays_plainly_unreachable(monkeypatch):
    monkeypatch.setattr(config, "small_brain_ready", lambda: True)
    mesaj = reason(backend="small")
    assert mesaj.startswith("structuring server unreachable:")
    assert NOT_INSTALLED not in mesaj


def test_strata_is_never_blamed_on_the_missing_brain(monkeypatch):
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    mesaj = reason(backend="strata")
    assert mesaj.startswith("structuring server unreachable:")
    assert "install_small_brain" not in mesaj


def test_quality_mode_runs_unsloth_not_the_brain(monkeypatch):
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    mesaj = reason(backend="small", quality_mode=True)
    assert mesaj.startswith("structuring server unreachable:")
    assert "install_small_brain" not in mesaj


def test_a_timeout_is_an_outage_even_without_an_install(monkeypatch):
    """Only a connection nobody accepts can mean "never installed"."""
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    mesaj = reason(timed_out, backend="small")
    assert mesaj.startswith("structuring server unreachable:")
    assert "install_small_brain" not in mesaj


# --- the pipeline and the queue row ---


def bundle(**kwargs):
    return pipeline.run(
        IMAGE,
        ocr=FakeOcr(),
        structurer=structurer(backend="small"),
        worker="ayse",
        **kwargs,
    )


def test_the_error_column_reads_the_installer_sentence(monkeypatch):
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    assert bundle()["error"] == f"stage 2: {NOT_INSTALLED}"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setattr(config, "small_brain_ready", lambda: False)
    image = tmp_path / "fis.jpg"
    image.write_bytes(IMAGE)
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    yield path, conn, str(image)
    conn.close()


def isle(env):
    """One real job through the real queue worker and the real pipeline."""
    path, conn, image = env
    job = db.create_job(conn, image_path=image, worker="ayse")
    runner = functools.partial(pipeline.run, ocr=FakeOcr(), structurer=structurer())
    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    return db.get_job(conn, job["id"])


def test_the_failed_job_carries_the_sentence_and_no_traceback(env, capsys, caplog):
    job = isle(env)
    assert job["status"] == "failed"
    assert job["error"] == f"stage 2: {NOT_INSTALLED}"
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err + caplog.text


def test_a_brain_that_is_installed_and_down_fails_the_usual_way(env, monkeypatch):
    monkeypatch.setattr(config, "small_brain_ready", lambda: True)
    job = isle(env)
    assert job["status"] == "failed"
    assert job["error"].startswith("stage 2: structuring server unreachable:")


# --- the two screens that show a dead job ---


@pytest.fixture
def api(tmp_path, monkeypatch):
    auth._sessions.clear()
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, plaintext = auth.create_key(conn, "ayse")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ADMIN_TOKEN}).status_code == 200
    yield client, conn, key_id, plaintext
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def kayit(conn, key_id, *, status="failed", error=NOT_INSTALLED):
    job = db.create_job(conn, key_id=key_id, worker="ayse")
    updates = {"error": error}
    if status == "done":
        updates["result_json"] = {"items": [], "totals": {"toplam": 0.0}}
        updates["validation_json"] = {"verdict": "ok", "fields": []}
    return db.set_status(conn, job["id"], status, **updates)


def test_the_admin_detail_shows_why_the_job_died(api):
    client, conn, key_id, _ = api
    job = kayit(conn, key_id)
    govde = client.get(f"/admin/api/jobs/{job['id']}").json()
    assert govde["status"] == "failed"
    assert govde["error"] == NOT_INSTALLED


def test_the_workers_detail_line_carries_the_sentence(api):
    client, conn, key_id, plaintext = api
    job = kayit(conn, key_id)
    yanit = client.get(
        f"/api/me/jobs/{job['id']}", headers={"X-API-Key": plaintext}
    )
    assert yanit.status_code == 200
    assert yanit.json()["error"] == NOT_INSTALLED


def test_a_job_that_died_for_another_reason_shows_that_reason(api):
    client, conn, key_id, _ = api
    job = kayit(conn, key_id, error="stage 1: OCR server unreachable")
    govde = client.get(f"/admin/api/jobs/{job['id']}").json()
    assert govde["error"] == "stage 1: OCR server unreachable"


def test_a_job_with_nothing_to_explain_adds_no_error_key(api):
    client, conn, key_id, plaintext = api
    isilenmis = kayit(conn, key_id, status="done", error="")
    bekleyen = kayit(conn, key_id, status="queued", error="")
    for job in (isilenmis, bekleyen):
        admin = client.get(f"/admin/api/jobs/{job['id']}")
        isci = client.get(f"/api/me/jobs/{job['id']}", headers={"X-API-Key": plaintext})
        assert admin.status_code == 200 and isci.status_code == 200
        assert "error" not in admin.json() and "error" not in isci.json()
