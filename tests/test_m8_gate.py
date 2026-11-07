"""M8 gate: the box nobody configures, measured on the wire.

M8 flipped stage 2 to the small brain: ``config.DEFAULT_STRUCTURER_BACKEND`` is
``"small"``, Strata became the rollback and every part that had assumed a GPU
box had to follow in the same breath. Each M8 task owned one file — the smoke,
the demo, the stub, the phone, the docs, the two §9 gates — so this file walks
the seams none of them could see from inside, with no ``STRUCTURER_BACKEND`` in
the env at all:

  * a receipt posted to a default box is structured by the brain and not by a
    Strata that is not installed — the leg on the closed port is never asked,
    and the model the integrator, the phone and the admin detail name is the one
    config resolves, inside an envelope that validated against the committed
    schema on every poll;
  * one env value puts Strata back and the same receipt still reaches verdict ok;
  * the stub, the Durum probe and both §9 gates read the backend from config:
    the stub answers as ``config.stage2_model(False)``, the stage-2 chip is
    green with nothing on :8080, and a quiet box gets a SKIP from the gates
    instead of a screenful of "unreachable" rows and exit 1 (PLAN run-2 R10);
  * and the numbers the cutover published agree: the phone's stale threshold
    outlasts the latency budget OPERATIONS tells integrators to budget, so a
    normal 45 s CPU receipt never reads as a stuck job.

Real app, real auth, real SQLite queue, real worker thread, real sockets on
ephemeral ports. The model servers are the project's own stubs, so answers stay
canned and a job that reaches a leg with nothing listening fails instead of
lying. The project's env is cleared first (T74's rule): the gate measures the
code's defaults, never this shell.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import socket
import time
from types import SimpleNamespace

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import auth, config, contract, db, status
from app.main import create_app
from app.queue_worker import QueueWorker
from scripts import live_ocr_gate, small_brain_gate
from scripts.fake_models import FakeModelServer, FixtureBook

ROOT = config.ROOT
OPERATIONS = ROOT / "OPERATIONS.md"
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
RECEIPT = "fis_market_clean"
# Only config knows these ids; a hardcoded one in an assertion would keep
# passing while the code moved away from it.
BRAIN_ID = "Qwen3-VL-Brain-m8"
STRATA_ID = "strata-m8"
ADMIN_TOKEN = "m8-yonetici"
YOK_VRAM = {"used_mb": None, "total_mb": None, "ok": False}
# PLAN.md contract 8, verbatim: the cutover is not allowed to grow these.
SUTUNLAR = [
    "job_id", "worker", "client_ref", "tarih", "saat", "firma", "vergi_no",
    "ara_toplam", "iskonto", "kdv", "toplam", "para_birimi", "verdict",
    "items_json", "kalite_mode", "gonderim_zamani",
]
ENV_PREFIXES = (
    "APP_", "OCR_", "STRATA_", "UNSLOTH_", "SMALL_BRAIN_", "STRUCTURER_",
    "PROBE_", "STARTUP_", "ADMIN_", "RATE_", "DATA_DIR", "DB_PATH",
    "MAX_UPLOAD", "IMAGE_", "THUMB_", "JPEG_", "LLAMA_", "STALE_",
)
POLL_TIMEOUT_S = 20.0


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in [n for n in os.environ if n.startswith(ENV_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SMALL_BRAIN_MODEL", BRAIN_ID)
    monkeypatch.setenv("STRATA_MODEL", STRATA_ID)
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(status, "vram_info", lambda: YOK_VRAM)


def closed_port() -> int:
    """A port nothing listens on — a job that wandered there failed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def make_box(monkeypatch, tmp_path):
    """A running stack whose two stage-2 legs are one stub and a closed port.

    ``backend`` is what STRUCTURER_BACKEND is set to; ``None`` leaves the name
    out of the env, which is the box M8 shipped. Only the leg the config names
    answers, so a done job can only have been structured there.
    """
    workers: list[QueueWorker] = []
    stops: list = []

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for suffix in (".json", ".png"):
        shutil.copy(config.ROOT / "fixtures" / f"{RECEIPT}{suffix}", fixtures)
    image = (fixtures / f"{RECEIPT}.png").read_bytes()
    book = FixtureBook([fixtures])

    def make(*, backend: str | None):
        auth._buckets.clear()
        auth._sessions.clear()
        ocr = FakeModelServer("ocr", book)
        stage2 = FakeModelServer("structurer", book)
        stops.extend([ocr, stage2])

        monkeypatch.setenv("OCR_HOST", str(httpx.URL(ocr.base_url).host))
        monkeypatch.setenv("OCR_PORT", str(ocr.port))
        monkeypatch.setenv(
            "SMALL_BRAIN_BASE_URL",
            stage2.base_url if backend != "strata"
            else f"http://127.0.0.1:{closed_port()}",
        )
        monkeypatch.setenv("STRATA_HOST", "127.0.0.1")
        monkeypatch.setenv(
            "STRATA_PORT", str(stage2.port if backend == "strata" else closed_port())
        )
        if backend is None:
            monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
        else:
            monkeypatch.setenv("STRUCTURER_BACKEND", backend)

        path = tmp_path / "ocr.db"
        conn = db.connect(path)
        _, plaintext = auth.create_key(conn, "ayse")
        conn.close()
        client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
        assert client.post(
            "/admin/api/login", json={"token": ADMIN_TOKEN}
        ).status_code == 200
        worker = QueueWorker(db_path=path, poll_interval=0.02)
        worker.start()
        workers.append(worker)
        return SimpleNamespace(client=client, key=plaintext, image=image, stub=stage2)

    yield make
    for worker in workers:
        worker.stop()
    for stop in stops:
        stop.shutdown()
    auth._buckets.clear()
    auth._sessions.clear()


def poll(client, key: str, job_id: str) -> dict:
    """Poll to a terminal status; every envelope seen is contract v1."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": key})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        jsonschema.validate(body, SCHEMA)
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job {job_id} stuck in {body['status']}"
        # slower than the key's refill, so waiting never spends the rate limit.
        time.sleep(0.25)


def submit(box, ref: str = "m8-gate") -> tuple[str, dict]:
    """One receipt to a terminal status through the real queue."""
    accepted = box.client.post(
        "/v1/jobs",
        headers={"X-API-Key": box.key},
        files={"image": (f"{RECEIPT}.png", box.image, "image/png")},
        data={"client_ref": ref},
    )
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    return job_id, poll(box.client, box.key, job_id)


def run(gate, *argv: str) -> tuple[int, str]:
    """(exit code, printed report) of one gate run in this process."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return gate.main(list(argv)), out.getvalue()


def quiet_env(monkeypatch, tmp_path) -> None:
    """The box of PLAN run-2 R10: nothing installed, nothing running."""
    monkeypatch.setenv("OCR_HOST", "127.0.0.1")
    monkeypatch.setenv("OCR_PORT", str(closed_port()))
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{closed_port()}")
    monkeypatch.setenv("STRATA_PORT", str(closed_port()))
    # The model files present but the brain not started: the case that used to
    # score twelve "unreachable" rows instead of skipping.
    monkeypatch.setenv("OCR_SMALL_BRAIN_DIR", str(tmp_path / "small-brain"))
    for path in (
        config.small_brain_server_path(),
        config.small_brain_model_path(),
        config.small_brain_mmproj_path(),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00")


# --- the default is small, everywhere it is read once ------------------------


def test_the_box_nobody_configured_is_a_small_brain_box():
    assert config.structurer_backend() == config.DEFAULT_STRUCTURER_BACKEND == "small"
    # The Durum probe and the shipped client follow the same single source.
    assert status.stage2_base_url() == config.small_brain_base_url()
    assert config.stage2_model(False) == config.small_brain_model()


def test_the_stub_answers_as_the_model_the_default_backend_picks():
    """scripts/fake_models.py reports the resolved id, so the smoke's meta.model
    check means "the backend config chose", whichever that is."""
    book = FixtureBook([ROOT / "fixtures"])
    stub = FakeModelServer("structurer", book)
    try:
        models = httpx.get(f"{stub.base_url}/v1/models", timeout=10).json()
        assert models["data"][0]["id"] == config.stage2_model(False) == BRAIN_ID
    finally:
        stub.shutdown()


# --- one receipt, both backends, on real sockets ----------------------------


def test_a_default_box_structures_on_the_brain_and_never_asks_strata(make_box):
    box = make_box(backend=None)

    _, envelope = submit(box)

    assert envelope["status"] == "done", envelope
    assert envelope["validation"]["verdict"] == "ok"
    # The Strata leg was a closed port: a job that had used it failed instead.
    assert envelope["meta"]["model"] == BRAIN_ID == config.stage2_model(False)
    assert envelope["meta"]["quality_mode"] is False


def test_the_strata_rollback_is_one_env_value_away(make_box):
    """The documented rollback still runs a receipt end to end with no brain."""
    box = make_box(backend="strata")

    _, envelope = submit(box)

    assert envelope["status"] == "done", envelope
    assert envelope["validation"]["verdict"] == "ok"
    assert envelope["meta"]["model"] == STRATA_ID == config.stage2_model(False)


def test_the_default_job_reads_the_same_on_every_screen(make_box):
    box = make_box(backend=None)
    job_id, envelope = submit(box)
    stages = envelope["meta"]["stage_ms"]

    telefon = box.client.get(f"/api/me/jobs/{job_id}", headers={"X-API-Key": box.key})
    assert telefon.status_code == 200, telefon.text
    yonetici = box.client.get(f"/admin/api/jobs/{job_id}")
    assert yonetici.status_code == 200, yonetici.text
    for body in (telefon.json(), yonetici.json()):
        assert body["meta"]["model"] == envelope["meta"]["model"]
        assert body["meta"]["stage_ms"] == stages
    # Contract 13: a 0 reads as "this stage never ran"; all three ran.
    assert all(value > 0 for value in stages.values()), stages


def test_the_cutover_grew_no_export_column(make_box):
    """Contract 8 is the spreadsheet's header; the new backend added no field."""
    box = make_box(backend=None)
    submit(box)

    csv = box.client.get("/admin/api/export?format=csv").content.decode("utf-8-sig")

    assert csv.splitlines()[0].split(",") == SUTUNLAR
    assert ",ok," in csv


def test_the_durum_chip_is_green_with_no_strata_on_the_box(make_box):
    box = make_box(backend=None)

    govde = box.client.get("/admin/api/status").json()

    assert list(govde) == ["ocr", "strata", "unsloth", "vram", "queue"]
    assert govde["ocr"]["ok"] is True
    assert govde["strata"]["ok"] is True  # contract 9's key, the small brain
    assert govde["vram"] == YOK_VRAM


# --- the §9 gates skip a quiet box instead of failing the smoke list ---------


def test_both_gates_skip_a_box_with_nothing_running(monkeypatch, tmp_path):
    """The form .hybrid/checks.json runs: one SKIP line, exit 0, no fixture sent."""
    quiet_env(monkeypatch, tmp_path)

    kod, ilk = run(small_brain_gate, "--if-installed")
    assert kod == 0, ilk
    assert ilk.strip().startswith("SKIP — "), ilk
    assert len(ilk.strip().splitlines()) == 1, ilk
    assert config.small_brain_base_url() in ilk

    kod, ikinci = run(live_ocr_gate, "--if-installed")
    assert kod == 0, ikinci
    assert ikinci.strip().startswith("SKIP — "), ikinci
    assert len(ikinci.strip().splitlines()) == 1, ikinci
    assert f"{config.ocr_base_url()}{live_ocr_gate.HEALTH_PATH}" in ikinci


def test_the_gates_probe_the_stage2_the_cutover_made_default(monkeypatch, tmp_path):
    """Each gate names the server it is about to measure; both name the brain."""
    quiet_env(monkeypatch, tmp_path)

    assert config.structurer_backend() == "small"
    assert config.small_brain_base_url() in small_brain_gate.skip_reason()
    sebep = live_ocr_gate.server_skip()
    assert f"stage 2 ({config.structurer_backend()})" in sebep, sebep
    assert status.stage2_base_url() in sebep, sebep


# --- the latency the docs publish is the latency the phone allows for --------


def test_the_phone_outlasts_the_latency_budget_the_docs_publish():
    js = (ROOT / "static" / "app" / "status.js").read_text(encoding="utf-8")
    sabit = dict(re.findall(r"export const ([A-Z_]+) = (\d+);", js))
    bayat_ms = int(sabit["STALE_AFTER_MS"])
    okuma_ms = int(sabit["OCR_BUDGET_MS"])
    butce_ms = 1000 * int(re.search(r"budget (\d+) s", OPERATIONS.read_text("utf-8")).group(1))

    # A receipt of the length the docs publish is never a stuck job...
    assert bayat_ms > butce_ms
    # ...and neither is one waiting behind a short queue: the stall the threshold
    # has to catch is the queue's, so it outlasts several receipts.
    assert bayat_ms >= 3 * butce_ms
    # The Yapılandırılıyor hint takes over well inside the documented wait.
    assert okuma_ms < butce_ms
