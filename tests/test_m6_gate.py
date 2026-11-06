"""M6 gate: the box the installer builds is the box the launcher runs.

M6 gave the small brain a process owner (run.py) and an installer
(scripts\\install_small_brain.ps1 and its manifest). What the milestone touched is
four seams, each between two modules that the M6 tasks only ever saw from one
side, so this file walks the whole of each:

  * the bytes the manifest puts down are the bytes app/config.py calls ready,
    and the command run.py builds points at exactly those files and that port;
  * the install command a red launcher line and a dead job print is a script
    that actually ships;
  * --stop reaps the brain, so nothing is left holding its port;
  * and none of it moved the shipping default: a box with a brain installed
    *and* listening still sends stage 2 to Strata until M8 flips the backend.

Receipts run through the real app, the SQLite queue and a real worker over real
sockets. The project's own env is cleared first (T74's rule) and %LOCALAPPDATA%
is a temp directory: the gate measures what the code defaults to on a clean box,
never this shell or this machine's real install.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient

import run
from app import auth, config, contract, db, structurer
from app.main import create_app
from app.queue_worker import QueueWorker
from scripts.fake_models import start_fake_models

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = json.loads(
    (ROOT / "scripts" / "small_brain_manifest.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
FIXTURE_PNG = config.ROOT / "fixtures" / "fis_market_clean.png"
# Only config knows these ids; a hardcoded one in an assertion would pass while
# the code moved away from it.
STRATA_ID = "strata-m6"
BRAIN_ID = "Qwen3-VL-4B-Brain"
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
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


def closed_port() -> int:
    """A port nothing listens on — a job that wandered there cannot succeed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def install_from_manifest() -> None:
    """Exactly what scripts\\install_small_brain.ps1 leaves behind: every
    manifest row written to its dest under the install dir config resolves."""
    for row in MANIFEST:
        target = config.small_brain_dir().joinpath(*row["dest"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")


def flag_value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


# --- the installer and the launcher are looking at the same box ---------------


def test_the_install_command_the_box_prints_names_a_script_that_ships():
    """The launcher's red line and a dead job both tell the operator to run a
    command; since T80 that command has to be a file that exists."""
    named = {run.INSTALL_SCRIPT, structurer.NOT_INSTALLED.rsplit(" ", 1)[-1]}
    assert len(named) == 1, "the launcher and the job blame different scripts"
    script = ROOT / named.pop().replace("\\", "/")
    assert script.is_file(), script
    assert script.read_text(encoding="utf-8-sig").lstrip().startswith("<#")


def test_a_manifest_box_is_a_ready_box_the_launcher_serves():
    assert config.small_brain_ready() is False
    install_from_manifest()
    assert config.small_brain_ready() is True

    command = run.small_brain_command()
    served = [pathlib.Path(command[0])] + [
        pathlib.Path(flag_value(command, flag)) for flag in ("-m", "--mmproj")
    ]
    assert all(path.is_file() for path in served), served
    installed = {
        str(path.relative_to(config.small_brain_dir())).replace("\\", "/")
        for path in served
    }
    assert installed == {row["dest"] for row in MANIFEST}
    # and it is served on the address the stage-2 client will call
    assert int(flag_value(command, "--port")) == config.small_brain_port() == 8100
    assert flag_value(command, "--host") == urlparse(config.small_brain_base_url()).hostname


def test_a_stop_leaves_nothing_holding_the_brains_port():
    """run.py owns the process, so --stop is what frees 8100."""
    child = subprocess.Popen(
        [
            sys.executable, "-c",
            "import socket, time\n"
            "s = socket.socket()\n"
            "s.bind(('127.0.0.1', 0))\n"
            "s.listen(1)\n"
            "print(s.getsockname()[1], flush=True)\n"
            "time.sleep(120)\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    port = int(child.stdout.readline())
    path = run.pid_path("small-brain")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(child.pid), encoding="utf-8")
    try:
        assert run._port_free("127.0.0.1", port) is False
        assert run.stop() == 0
        assert path.exists() is False
        deadline = time.monotonic() + 5.0
        while not run._port_free("127.0.0.1", port) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert run._port_free("127.0.0.1", port) is True
    finally:
        child.kill()
        child.wait(timeout=10)


# --- whole boxes: real app, queue and worker over real sockets ---------------


@pytest.fixture
def make_box(monkeypatch, tmp_path):
    """Build a box: which stage-2 backend is configured, whether the brain is
    installed, and which of the two stage-2 servers actually answers."""
    workers: list[QueueWorker] = []
    models: list = []

    def make(*, backend: str | None, installed: bool, strata_live: bool, brain_live: bool):
        auth._buckets.clear()
        stubs = start_fake_models()
        models.append(stubs)
        monkeypatch.setenv("OCR_HOST", str(httpx.URL(stubs.ocr.base_url).host))
        monkeypatch.setenv("OCR_PORT", str(stubs.ocr.port))
        monkeypatch.setenv("STRATA_MODEL", STRATA_ID)
        monkeypatch.setenv("SMALL_BRAIN_MODEL", BRAIN_ID)
        if backend is None:
            monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
        else:
            monkeypatch.setenv("STRUCTURER_BACKEND", backend)
        strata_url = (
            stubs.structurer.base_url
            if strata_live
            else f"http://127.0.0.1:{closed_port()}"
        )
        brain_url = (
            stubs.structurer.base_url
            if brain_live
            else f"http://127.0.0.1:{closed_port()}"
        )
        monkeypatch.setenv("STRATA_HOST", str(httpx.URL(strata_url).host))
        monkeypatch.setenv("STRATA_PORT", str(httpx.URL(strata_url).port))
        monkeypatch.setenv("SMALL_BRAIN_BASE_URL", brain_url)
        if installed:
            install_from_manifest()
        assert config.small_brain_ready() is installed

        path = tmp_path / "ocr.db"
        conn = db.connect(path)
        _, plaintext = auth.create_key(conn, "ayse")
        conn.close()
        client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
        worker = QueueWorker(db_path=path, poll_interval=0.02)
        worker.start()
        workers.append(worker)
        return SimpleNamespace(client=client, key=plaintext)

    yield make
    for worker in workers:
        worker.stop()
    for stub in models:
        stub.shutdown()
    auth._buckets.clear()


def submit_and_poll(box) -> tuple[str, dict]:
    """One receipt to a terminal status; the envelope stays contract v1."""
    accepted = box.client.post(
        "/v1/jobs",
        headers={"X-API-Key": box.key},
        files={"image": (FIXTURE_PNG.name, FIXTURE_PNG.read_bytes(), "image/png")},
        data={"client_ref": "m6-gate"},
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = box.client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": box.key})
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "failed"):
            jsonschema.validate(body, SCHEMA)
            return job_id, body
        assert time.monotonic() < deadline, f"job {job_id} stuck in {body['status']}"
        # slower than the key's 5 requests/s refill, so waiting for a job never
        # spends the rate limit this client needs to keep polling.
        time.sleep(0.25)


def test_an_installed_and_listening_brain_does_not_move_the_default(make_box):
    box = make_box(backend=None, installed=True, strata_live=True, brain_live=True)
    assert config.structurer_backend() == "strata"

    _, body = submit_and_poll(box)
    assert body["status"] == "done", body
    assert body["meta"]["model"] == STRATA_ID
    assert body["meta"]["quality_mode"] is False
    assert body["validation"]["verdict"] == "ok"


def test_a_cpu_only_box_with_no_strata_runs_the_receipt_on_the_brain(make_box):
    box = make_box(backend="small", installed=True, strata_live=False, brain_live=True)

    _, body = submit_and_poll(box)
    assert body["status"] == "done", body
    assert body["meta"]["model"] == BRAIN_ID
    assert body["validation"]["verdict"] == "ok"
    assert body["result"]["items"]


def test_a_cpu_only_box_that_never_installed_says_which_script_to_run(make_box):
    box = make_box(backend="small", installed=False, strata_live=False, brain_live=False)

    job_id, body = submit_and_poll(box)
    assert body["status"] == "failed", body
    worker_view = box.client.get(f"/api/me/jobs/{job_id}", headers={"X-API-Key": box.key})
    assert worker_view.status_code == 200
    assert structurer.NOT_INSTALLED in worker_view.json()["error"]
