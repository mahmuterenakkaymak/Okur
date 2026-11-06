"""M5 gate: with nothing configured, stage 2 is still Strata — all the way down.

The milestone added a second stage-2 brain without moving anyone's default, so
the exit state of the box is: an empty environment sends a receipt to Strata
:8080, ``meta.model`` names the Strata id, and every small-brain env key sits
inert until the M8 cutover flips ``config.DEFAULT_STRUCTURER_BACKEND``. This
file walks one receipt through that default along real sockets.

The project's own env vars are cleared first (same rule as T74's NO_COLOR
pin): the gate measures what the code defaults to, not what the developer's
shell happens to export.
"""
from __future__ import annotations

import json
import os
import socket
import time

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import auth, config, contract, db
from app.main import create_app
from app.queue_worker import QueueWorker
from app.structurer import Structurer
from scripts.fake_models import start_fake_models

ENV_PREFIXES = (
    "APP_",
    "OCR_",
    "STRATA_",
    "UNSLOTH_",
    "SMALL_BRAIN_",
    "STRUCTURER_",
    "PROBE_",
    "STARTUP_",
    "ADMIN_",
    "RATE_",
    "DATA_DIR",
    "DB_PATH",
    "MAX_UPLOAD",
    "IMAGE_",
    "THUMB_",
    "JPEG_",
    "LLAMA_",
    "STALE_",
)
FIXTURE = "fis_market_clean"
FIXTURE_JSON = config.ROOT / "fixtures" / f"{FIXTURE}.json"
FIXTURE_PNG = config.ROOT / "fixtures" / f"{FIXTURE}.png"
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
STRATA_ID = "strata-m5"  # only config knows it; a hardcoded id would fail here
OCR_TEXT = "<fcel>BILGIN MARKETLER ANONIM SIRKETI<nl>"
IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
POLL_TIMEOUT_S = 20.0


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in [n for n in os.environ if n.startswith(ENV_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)


def closed_port() -> int:
    """A port nothing listens on — a job that wandered to the small brain dies."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def stage2_request():
    """The single outgoing stage-2 request the default client sends, and its body."""
    seen = []

    def handler(request):
        seen.append(request)
        truth = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(truth, ensure_ascii=False)}}]},
        )

    Structurer(transport=httpx.MockTransport(handler)).structure(OCR_TEXT, IMAGE)
    assert len(seen) == 1
    return seen[0], json.loads(seen[0].content)


@pytest.fixture
def default_env(tmp_path, monkeypatch):
    """Real app, queue and worker; stage 2's stub on a real socket, env untouched.

    The only things pointed anywhere are the data dir and the two model-server
    ports. ``STRUCTURER_BACKEND`` is never set, and the small brain's own URL is
    a closed port: whichever brain the job reaches, the envelope will tell.
    """
    auth._buckets.clear()
    models = start_fake_models()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OCR_HOST", str(httpx.URL(models.ocr.base_url).host))
    monkeypatch.setenv("OCR_PORT", str(models.ocr.port))
    monkeypatch.setenv("STRATA_HOST", str(httpx.URL(models.structurer.base_url).host))
    monkeypatch.setenv("STRATA_PORT", str(models.structurer.port))
    monkeypatch.setenv("STRATA_MODEL", STRATA_ID)
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{closed_port()}")
    monkeypatch.setenv("SMALL_BRAIN_MODEL", "Qwen3-VL-4B-Small-Test")

    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, plaintext = auth.create_key(conn, "ayse")
    conn.close()
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    worker = QueueWorker(db_path=path, poll_interval=0.02)
    worker.start()
    yield client, plaintext, models
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


# --- the default, layer by layer ---


def test_no_env_names_a_backend_and_it_is_strata():
    assert config.DEFAULT_STRUCTURER_BACKEND == "strata"
    assert config.structurer_backend() == "strata"


def test_default_client_points_at_strata():
    structurer = Structurer()
    assert structurer.backend == "strata"
    assert structurer.base_url == config.strata_base_url() == "http://127.0.0.1:8080"
    assert structurer.model == config.strata_model()


def test_default_stage2_model_is_the_strata_id():
    assert config.stage2_model(False) == config.strata_model() == "strata"
    assert config.stage2_model(True) == config.unsloth_model()


def test_stage2_env_overrides_still_come_from_config(monkeypatch):
    monkeypatch.setenv("STRATA_MODEL", STRATA_ID)
    assert config.stage2_model(False) == STRATA_ID
    monkeypatch.setenv("STRATA_MODEL", "  " + STRATA_ID + " ")
    assert Structurer().model == STRATA_ID


# --- the small-brain keys must not move the default ---


def test_small_brain_knobs_are_inert_until_the_backend_is_small(monkeypatch):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{closed_port()}")
    monkeypatch.setenv("SMALL_BRAIN_MODEL", "Qwen3-VL-4B-Small-Test")
    monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", "0")  # small backend only (M7)
    request, body = stage2_request()
    assert str(request.url) == f"{config.strata_base_url()}/v1/chat/completions"
    assert body["model"] == config.strata_model()
    assert [part["type"] for part in body["messages"][0]["content"]] == ["text", "image_url"]


@pytest.mark.parametrize("value", ["", "   ", "q8", "small-brain", "strata-80b"])
def test_any_other_backend_value_reads_as_the_default(value, monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", value)
    assert config.structurer_backend() == config.DEFAULT_STRUCTURER_BACKEND


# --- and the default carries a real receipt to done ---


def test_default_runs_a_receipt_to_strata_end_to_end(default_env):
    client, plaintext, models = default_env
    listed = httpx.get(f"{models.structurer.base_url}/v1/models", timeout=10).json()
    assert listed["data"][0]["id"] == STRATA_ID

    accepted = client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": (FIXTURE_PNG.name, FIXTURE_PNG.read_bytes(), "image/png")},
        data={"client_ref": "m5-gate"},
    )
    assert accepted.status_code == 202
    body = poll(client, plaintext, accepted.json()["job_id"])

    truth = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    assert body["status"] == "done", body
    assert body["meta"]["model"] == STRATA_ID
    assert body["meta"]["quality_mode"] is False
    assert body["validation"]["verdict"] == "ok"
    assert body["validation"]["fields"] == []
    assert body["result"]["totals"] == truth["totals"]
