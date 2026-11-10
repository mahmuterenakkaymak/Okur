"""M7 gate: the toggle, the timings and the Durum chip, measured on the wire.

M7 gave a CPU-only box three knobs. ``STRUCTURER_INCLUDE_IMAGE=0`` tells *the
small brain* to read text only; every job now carries ``meta.stage_ms``; and
the status page probes the stage-2 brain that is configured instead of a Strata
that is not there. Each M7 task owned one module and saw the other side only in
a stub, so this file walks the seams nobody stood on:

  * what the flag decides is visible in the request the app really puts on the
    wire to the brain — and the legs the flag does not speak to (Strata, and
    quality mode's Unsloth) still receive the receipt;
  * the three numbers one real run measured are the three the integrator, the
    worker's phone and the admin detail show, and they stayed out of the
    export's columns;
  * the admin page's hand-written keys (its stage labels, its service chips)
    are still the keys the backend writes, the one place stage_ms and contract
    9 cross from Python into JS;
  * the status door answers for the configured brain over HTTP, and a Strata
    box is not rescued by a brain that happens to be up;
  * and the demo admin token the quick start promises is the one the demo pins.

Real app, real auth, real SQLite queue, real worker thread, real sockets on
ephemeral ports. The model servers are the project's own stubs with a tap in
front of them, so the answers stay canned and the requests stay readable; the
stub's book holds exactly one receipt, so a done job is always that receipt
read back. The project's env is cleared first (T74's rule): the gate measures
the code's defaults, never this shell.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

from app import auth, config, contract, db, status, structurer
from app.main import create_app
from app.queue_worker import QueueWorker
from scripts import serve_demo
from scripts.fake_models import FakeModelServer, FixtureBook

ROOT = config.ROOT
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
RECEIPT = "fis_market_clean"
# Only config knows these ids; a hardcoded one in an assertion would pass while
# the code moved away from it.
STRATA_ID = "strata-m7"
BRAIN_ID = "Qwen3-VL-Brain-m7"
UNSLOTH_ID = "unsloth-m7"
ADMIN_TOKEN = "m7-yonetici"
YOK_VRAM = {"used_mb": None, "total_mb": None, "ok": False}
# PLAN.md contract 8, verbatim: the two spreadsheet formats' headers.
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
    monkeypatch.setattr(status, "vram_info", lambda: YOK_VRAM)


def closed_port() -> int:
    """A port nothing listens on — a job or probe that wandered there failed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _TapHandler(BaseHTTPRequestHandler):
    """Record one request body, hand it to the stub, relay the answer back."""

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.bodies.append(json.loads(raw or b"{}"))
        self._relay(raw)

    def do_GET(self):
        self._relay(b"")

    def _relay(self, body: bytes) -> None:
        if self.server.delay_ms:
            time.sleep(self.server.delay_ms / 1000)
        with httpx.Client(timeout=30) as client:
            cevap = client.request(
                self.command, f"{self.server.upstream}{self.path}", content=body
            )
        self.send_response(cevap.status_code)
        self.send_header(
            "Content-Type", cevap.headers.get("content-type", "application/json")
        )
        self.send_header("Content-Length", str(len(cevap.content)))
        self.end_headers()
        self.wfile.write(cevap.content)

    def log_message(self, *args):
        pass


class Wire:
    """A tap in front of one model server.

    ``delay_ms`` holds every chat request before answering, so a stage timing
    that claims that wait cannot be lying, and ``bodies`` is what the app
    actually put on the wire — the half of the include_image claim no in-process
    stub can show.
    """

    def __init__(self, upstream: str, delay_ms: int = 0):
        self.bodies: list[dict] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _TapHandler)
        self._httpd.bodies = self.bodies
        self._httpd.upstream = upstream
        self._httpd.delay_ms = delay_ms
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def parts(self) -> list[str]:
        """Content-part types of the last stage-2 request this leg saw."""
        assert self.bodies, "the app never called this server"
        content = self.bodies[-1]["messages"][0]["content"]
        return [part["type"] for part in content]

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def make_box(monkeypatch, tmp_path):
    """A box: which stage-2 backend is configured, what the flag says, what is up.

    Each leg gets its own tap and its own stub, or a port nothing listens on,
    so a job can only succeed on the leg the config names — and the request the
    winning leg received is the request under test.
    """
    workers: list[QueueWorker] = []
    stops: list = []

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for suffix in (".json", ".png"):
        shutil.copy(config.ROOT / "fixtures" / f"{RECEIPT}{suffix}", fixtures)
    book = FixtureBook([fixtures])
    image = (fixtures / f"{RECEIPT}.png").read_bytes()

    def make(
        *,
        backend: str,
        include_image: str | None = None,
        brain_live: bool = True,
        strata_live: bool = True,
        delay_ms: int = 0,
        quality_delay_ms: int = 0,
    ):
        auth._buckets.clear()
        auth._sessions.clear()

        ocr = FakeModelServer("ocr", book)
        brain_stub = FakeModelServer("structurer", book)
        quality_stub = FakeModelServer("structurer", book)
        stops.extend([ocr, brain_stub, quality_stub])
        brain = Wire(brain_stub.base_url, delay_ms=delay_ms)
        quality = Wire(quality_stub.base_url, delay_ms=quality_delay_ms)
        stops.extend([brain, quality])
        strata_wire: Wire | None = None
        if strata_live:
            strata_stub = FakeModelServer("structurer", book)
            strata_wire = Wire(strata_stub.base_url)
            stops.extend([strata_stub, strata_wire])

        monkeypatch.setenv("OCR_HOST", str(httpx.URL(ocr.base_url).host))
        monkeypatch.setenv("OCR_PORT", str(ocr.port))
        monkeypatch.setenv("STRATA_MODEL", STRATA_ID)
        monkeypatch.setenv("SMALL_BRAIN_MODEL", BRAIN_ID)
        monkeypatch.setenv("UNSLOTH_MODEL", UNSLOTH_ID)
        monkeypatch.setenv("STRUCTURER_BACKEND", backend)
        monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
        if include_image is None:
            monkeypatch.delenv("STRUCTURER_INCLUDE_IMAGE", raising=False)
        else:
            monkeypatch.setenv("STRUCTURER_INCLUDE_IMAGE", include_image)
        monkeypatch.setenv(
            "SMALL_BRAIN_BASE_URL",
            brain.base_url if brain_live else f"http://127.0.0.1:{closed_port()}",
        )
        monkeypatch.setenv("STRATA_HOST", "127.0.0.1")
        monkeypatch.setenv(
            "STRATA_PORT", str(strata_wire.port if strata_wire else closed_port())
        )
        monkeypatch.setenv("UNSLOTH_HOST", str(httpx.URL(quality.base_url).host))
        monkeypatch.setenv("UNSLOTH_PORT", str(quality.port))

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
        return SimpleNamespace(
            client=client, key=plaintext, image=image,
            brain=brain, strata=strata_wire, quality=quality,
        )

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
        # slower than the key's refill, so waiting for a job never spends the
        # rate limit the rest of this test needs.
        time.sleep(0.25)


def submit(box, ref: str = "m7-gate") -> tuple[str, dict]:
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


# --- the include_image toggle, on the wire the app writes --------------------


def test_a_text_only_small_brain_still_brings_the_receipt_home(make_box):
    box = make_box(backend="small", include_image="0", delay_ms=25)

    _, envelope = submit(box)

    assert envelope["status"] == "done", envelope
    assert envelope["validation"]["verdict"] == "ok"
    assert envelope["meta"]["model"] == BRAIN_ID
    body = box.brain.bodies[-1]
    assert [part["type"] for part in body["messages"][0]["content"]] == ["text"]
    assert body["messages"][0]["content"][0]["text"].startswith(structurer.PROMPT)
    # The flag drops one part; the rest of the request is today's request.
    assert body["model"] == BRAIN_ID
    assert body["max_tokens"] == structurer.MAX_TOKENS
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    # And the breakdown the screens will show is this run's own wait.
    stages = envelope["meta"]["stage_ms"]
    assert stages["structure"] >= 25
    assert envelope["meta"]["ocr_ms"] == stages["ocr"]
    assert envelope["meta"]["total_ms"] >= stages["structure"]


def test_the_untouched_default_still_hands_the_brain_the_receipt(make_box):
    box = make_box(backend="small")

    _, envelope = submit(box)

    assert envelope["status"] == "done", envelope
    assert config.structurer_include_image() is True
    assert box.brain.parts() == ["text", "image_url"]


def test_the_flag_never_silences_strata(make_box):
    """STRUCTURER_INCLUDE_IMAGE=0 speaks to the small brain; Strata is deaf."""
    box = make_box(backend="strata", include_image="0")

    _, envelope = submit(box)

    assert envelope["status"] == "done", envelope
    assert envelope["meta"]["model"] == STRATA_ID
    assert box.strata.parts() == ["text", "image_url"]
    assert box.brain.bodies == []


def test_a_quality_rerun_takes_the_receipt_and_retimes_itself(make_box):
    """Quality mode outranks both the flag and the backend, and re-times itself."""
    box = make_box(
        backend="small", include_image="0", delay_ms=25, quality_delay_ms=60
    )
    job_id, envelope = submit(box)
    assert box.brain.parts() == ["text"]
    assert envelope["meta"]["quality_mode"] is False

    yanit = box.client.post(f"/admin/api/jobs/{job_id}/rerun")

    assert yanit.status_code == 200, yanit.text
    guncel = yanit.json()
    assert guncel["meta"]["quality_mode"] is True
    assert guncel["meta"]["model"] == UNSLOTH_ID
    assert box.quality.parts() == ["text", "image_url"]
    assert guncel["meta"]["stage_ms"]["structure"] >= 60  # the rerun's own wait
    # The integrator's door reads the same rerun, not the first read.
    assert poll(box.client, box.key, job_id)["meta"]["model"] == UNSLOTH_ID


# --- stage_ms: one run, every screen, and nowhere else ----------------------


def test_one_run_reports_the_same_stage_times_on_every_screen(make_box):
    box = make_box(backend="small", delay_ms=25)
    job_id, envelope = submit(box)

    stages = envelope["meta"]["stage_ms"]
    assert sorted(stages) == ["ocr", "structure", "validate"]
    telefon = box.client.get(f"/api/me/jobs/{job_id}", headers={"X-API-Key": box.key})
    assert telefon.status_code == 200, telefon.text
    assert telefon.json()["meta"]["stage_ms"] == stages
    yonetici = box.client.get(f"/admin/api/jobs/{job_id}")
    assert yonetici.status_code == 200, yonetici.text
    assert yonetici.json()["meta"]["stage_ms"] == stages
    assert all(isinstance(value, int) and value >= 0 for value in stages.values())


def test_the_stage_times_stayed_out_of_the_export_columns(make_box):
    """stage_ms is /v1's only additive field: contract 8's columns did not grow."""
    box = make_box(backend="small")
    submit(box)

    csv = box.client.get("/admin/api/export?format=csv").content.decode("utf-8-sig")
    assert csv.splitlines()[0].split(",") == SUTUNLAR


def test_the_admin_detail_reads_the_stage_keys_the_contract_writes():
    """stage_ms crosses into JS by hand-written key names in static/admin."""
    js = (ROOT / "static" / "admin" / "detail.js").read_text(encoding="utf-8")
    block = re.search(r"const ASAMALAR = \[(.*?)\];", js, re.S)
    assert block, "the admin detail's stage list disappeared"
    assert re.findall(r'alan:\s*"([a-z_]+)"', block.group(1)) == list(
        contract.StageMs.model_fields
    )


def test_the_status_page_chips_are_the_status_payload_keys(make_box):
    """Contract 9 froze the payload's key names; the Durum page reads them by hand."""
    box = make_box(backend="small")
    govde = box.client.get("/admin/api/status").json()

    js = (ROOT / "static" / "admin" / "status.js").read_text(encoding="utf-8")
    block = re.search(r"const SERVISLER = \[(.*?)\];", js, re.S)
    assert block, "the status page's service list disappeared"
    chips = re.findall(r'anahtar:\s*"([a-z_]+)"', block.group(1))
    assert chips == ["ocr", "strata", "unsloth"]
    assert set(chips) <= set(govde)


# --- the Durum page reads the brain this box actually runs -------------------


def test_the_durum_page_is_green_for_the_brain_that_is_configured(make_box):
    """A CPU-only box has no Strata; its stage-2 chip must still go green."""
    box = make_box(backend="small", strata_live=False)

    govde = box.client.get("/admin/api/status").json()

    assert list(govde) == ["ocr", "strata", "unsloth", "vram", "queue"]
    assert govde["ocr"]["ok"] is True
    assert govde["strata"]["ok"] is True  # contract 9's key, the small brain
    assert govde["vram"] == YOK_VRAM
    assert govde["queue"] == {"queued": 0, "running": 0, "failed": 0}


def test_a_strata_box_is_not_rescued_by_a_brain_that_happens_to_be_up(make_box):
    """The probe follows the config, not whichever server a machine has open."""
    box = make_box(backend="strata", strata_live=False)

    govde = box.client.get("/admin/api/status").json()

    assert govde["strata"]["ok"] is False
    assert govde["strata"]["latency_ms"] is None


# --- and the two tokens the quick start depends on ---------------------------


def demo_tokens(name: str) -> set[str]:
    """Every ADMIN_TOKEN a doc promises in the same breath as the demo."""
    metin = (ROOT / name).read_text(encoding="utf-8")
    return {
        token
        for blok in re.split(r"\n\s*\n", metin)
        if "demo" in blok.lower()
        for token in re.findall(r"ADMIN_TOKEN=([A-Za-z0-9_-]+)", blok)
    }


def test_the_demo_admin_token_the_docs_promise_is_the_one_the_demo_pins():
    promised = set()
    for name in ("README.md", "docs/REFERENCE.md", "HIZLI-BASLANGIC.md", "OPERATIONS.md"):
        promised |= demo_tokens(name)
    assert promised == {serve_demo.ADMIN_TOKEN}
