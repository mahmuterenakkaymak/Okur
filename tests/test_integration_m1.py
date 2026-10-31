"""M1 integration: one real fixture image through the real app, auth, queue, pipeline and validator.

The only fakes in the loop are the two model HTTP responses, and they are faked
at the httpx transport (PLAN.md decision 3): the fixture PNG is uploaded for
real, the auth middleware checks a real registered key, a real worker thread
drains the real SQLite queue, and the validator recomputes the arithmetic. The
canned outputs are the committed fixture ground truth, so the ok verdict and
the tampered-KDV mismatch are both decided by the app, not by the test.
"""
from __future__ import annotations

import base64
import copy
import json
import time

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import auth, config, contract, db, pipeline
from app.main import create_app
from app.ocr_client import OcrClient
from app.queue_worker import QueueWorker
from scripts.fake_models import FixtureBook, default_dirs

FIXTURE = "fis_market_clean"
FIXTURE_JSON = config.ROOT / "fixtures" / f"{FIXTURE}.json"
FIXTURE_PNG = config.ROOT / "fixtures" / f"{FIXTURE}.png"
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
TAMPERED_KDV = 999.99
POLL_TIMEOUT_S = 20.0

BOOK = FixtureBook(default_dirs())


# --- model stubs: canned fixture outputs at the HTTP transport ---


def data_url(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode()


def completion(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def parts(request: httpx.Request) -> list:
    """Content parts of the chat request each stub answers."""
    return json.loads(request.content)["messages"][-1]["content"]


def ocr_transport():
    """Stage 1: the fixture whose PNG arrived, as Paddle table text."""
    def handle(request):
        url = next(p["image_url"]["url"] for p in parts(request) if "image_url" in p)
        fixture = BOOK.for_image_bytes(base64.b64decode(url.rsplit(",", 1)[-1]))
        return httpx.Response(200, json=completion(fixture.text))
    return httpx.MockTransport(handle)


def structurer_transport(tamper=None):
    """Stage 2: the fixture stage 1 just read, as contract JSON, tampered on request."""
    def handle(request):
        text = "\n".join(p.get("text", "") for p in parts(request) if "text" in p)
        result = copy.deepcopy(BOOK.for_text(text).result)
        if tamper:
            tamper(result)
        return httpx.Response(200, json=completion(json.dumps(result, ensure_ascii=False)))
    return httpx.MockTransport(handle)


class HttpStructurer:
    """Stage 2 as a real OpenAI-compatible POST over a stubbed transport.

    ASSUMPTION: app/structurer.py belongs to T11; pipeline.run accepts any
    object with structure(), so the integration holds that seam open with a
    transport-level stand-in and needs no change when the real client lands.
    """

    def __init__(self, transport):
        self._client = httpx.Client(transport=transport, base_url="http://strata")

    def structure(self, ocr_text, image_bytes):
        started = time.perf_counter()
        resp = self._client.post("/v1/chat/completions", json={"messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": ocr_text},
                {"type": "image_url", "image_url": {"url": data_url(image_bytes)}},
            ],
        }]})
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return {
            **json.loads(content),
            "ms": int((time.perf_counter() - started) * 1000),
        }


# --- harness ---


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real app on a temp database with one registered worker key."""
    auth._buckets.clear()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    _, plaintext = auth.create_key(conn, "ayse")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    yield client, plaintext, path
    conn.close()
    auth._buckets.clear()


def start_worker(path, tamper=None):
    """Real queue worker thread running the real pipeline."""
    ocr = OcrClient(transport=ocr_transport())
    structurer = HttpStructurer(structurer_transport(tamper))

    def runner(image_bytes, *, quality_mode=False, worker=""):
        return pipeline.run(
            image_bytes,
            quality_mode=quality_mode,
            worker=worker,
            ocr=ocr,
            structurer=structurer,
        )

    worker = QueueWorker(db_path=path, runner=runner, poll_interval=0.02)
    worker.start()
    return worker


def submit(client, plaintext, image):
    return client.post(
        "/v1/jobs",
        headers={"X-API-Key": plaintext},
        files={"image": ("fis.png", image, "image/png")},
        data={"client_ref": "fis-001"},
    )


def poll(client, plaintext, job_id, timeout=POLL_TIMEOUT_S):
    """Poll until the worker finishes; every envelope seen is contract v1."""
    deadline = time.monotonic() + timeout
    while True:
        resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        body = resp.json()
        jsonschema.validate(body, SCHEMA)
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job stuck in {body['status']}"
        time.sleep(0.02)


def tamper_kdv(result):
    result["totals"]["kdv"] = TAMPERED_KDV


# --- the whole M1 loop ---


def test_fixture_image_travels_the_whole_pipeline(env):
    client, plaintext, path = env
    accepted = submit(client, plaintext, FIXTURE_PNG.read_bytes())
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"

    worker = start_worker(path)
    try:
        body = poll(client, plaintext, accepted.json()["job_id"])
    finally:
        worker.stop()

    truth = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    assert body["status"] == "done", body
    assert body["client_ref"] == "fis-001"
    assert body["validation"]["verdict"] == "ok"
    assert body["validation"]["fields"] == []
    assert body["result"]["items"] == truth["items"]
    assert body["result"]["totals"] == truth["totals"]
    assert body["meta"]["worker"] == "ayse"
    assert body["meta"]["model"] == config.strata_model()
    assert body["meta"]["quality_mode"] is False
    assert body["meta"]["received_at"]
    assert body["meta"]["total_ms"] >= 0


def test_tampered_kdv_from_the_model_yields_mismatch_naming_the_field(env):
    client, plaintext, path = env
    job_id = submit(client, plaintext, FIXTURE_PNG.read_bytes()).json()["job_id"]

    worker = start_worker(path, tamper=tamper_kdv)
    try:
        body = poll(client, plaintext, job_id)
    finally:
        worker.stop()

    assert body["status"] == "done", body
    assert body["validation"]["verdict"] == "mismatch"
    assert body["validation"]["fields"] == ["totals.kdv"]
    assert body["validation"]["actual"]["kdv"] == TAMPERED_KDV
    assert body["validation"]["expected"]["kdv"] == 198.82
    # the printed value survives in the result for the discrepancy panel
    assert body["result"]["totals"]["kdv"] == TAMPERED_KDV
