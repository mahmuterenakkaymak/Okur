"""T89: scripts/small_brain_gate.py — brief 9 gates 1 and 3, in both directions.

The gate scores the live small brain, which no test can ship. What a test can
ship is a fake brain on an ephemeral port that answers the *recorded* stage-1
text the gate really sent with that fixture's committed ground truth: the arms,
the flag in front of each request, the table, the two scores and the exit code
are all the real ones over a real socket.

And a gate that cannot fail is not a gate, so the rigs matter: an answer broken
in one arm alone, a miss on the wrong fixture, a brain that never answers —
each has to leave a nonzero exit behind. ``--if-installed`` is pinned both
ways, because .hybrid/checks.json runs that form on clones with no 2.1 GB model
and it must SKIP there, not fail.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import config

GATE = config.ROOT / "scripts" / "small_brain_gate.py"
FIXTURE_DIR = config.ROOT / "fixtures"
STAGE1 = json.loads((config.ROOT / "spike" / "bench_paddle.json").read_text(encoding="utf-8"))
RECORDED = {row["fixture"]: row["raw"] for row in STAGE1}
ALLOWED_MISS = "fis_benzin_foto"
MUSH = "Fişi okuyamadım, lütfen tekrar çekin."
# What the child must not inherit from this shell: the gate's arms set the image
# flag themselves, and its brain is the stub, not this machine's :8100.
CLEAR_PREFIXES = ("SMALL_BRAIN_", "OCR_", "STRUCTURER_", "STRATA_", "UNSLOTH_", "DATA_DIR")


def ground_truth(fixture: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture}.json").read_text(encoding="utf-8"))


def fixture_for(text: str) -> str | None:
    """Which fixture this request is about, from the text the gate sent."""
    return next((name for name, raw in RECORDED.items() if raw and raw in text), None)


def _last_message(body: dict) -> tuple[str, bool]:
    """(joined text, photo attached) of the gate's request."""
    parts = body["messages"][0]["content"]
    if isinstance(parts, str):
        return parts, False
    texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
    has_image = any(part.get("type") == "image_url" for part in parts)
    return "\n".join(texts), has_image


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
            text, has_image = _last_message(body)
        except (ValueError, KeyError, IndexError, TypeError):
            text, has_image = "", False
        self.server.brain.reply(self, text, has_image)

    def log_message(self, *args):
        pass


class Brain:
    """A fake small brain on an ephemeral port.

    ``bad`` are the fixtures answered with prose instead of JSON (schema miss),
    ``off`` the fixtures misread into a schema-valid result the validator
    rejects, ``fixed`` the fixtures read correctly no matter what. By default
    only ``fis_benzin_foto`` is misread — the brief's 5/6 on a healthy brain.
    ``only_without_image`` aims ``bad`` at the text-only arm alone: the rig that
    shows the two arms are scored apart.
    """

    def __init__(self) -> None:
        self.bad: set[str] = set()
        self.off: set[str] = set()
        self.fixed: set[str] = set()
        self.only_without_image = False
        self.requests: list[tuple[str | None, bool]] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.brain = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port, *_ = self._httpd.server_address
        return f"http://{host}:{port}"

    def content(self, fixture: str | None, has_image: bool) -> str:
        if fixture is None:  # the gate sent something that is not our corpus
            return MUSH
        if fixture in self.bad and not (self.only_without_image and has_image):
            return MUSH
        truth = ground_truth(fixture)
        if fixture in self.off or (fixture == ALLOWED_MISS and fixture not in self.fixed):
            truth["totals"]["toplam"] += 250.0
        return json.dumps(truth, ensure_ascii=False)

    def reply(self, handler: BaseHTTPRequestHandler, text: str, has_image: bool) -> None:
        fixture = fixture_for(text)
        self.requests.append((fixture, has_image))
        payload = json.dumps(
            {
                "id": "chatcmpl-brain",
                "object": "chat.completion",
                "created": 0,
                "model": "Qwen3-VL-4B-Instruct",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": self.content(fixture, has_image)},
                    "finish_reason": "stop",
                }],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def brain():
    server = Brain()
    yield server
    server.shutdown()


def install_dir(tmp_path: Path, *, ready: bool) -> Path:
    """A fake %LOCALAPPDATA%\\ocr-small-brain: config decides which files count."""
    root = tmp_path / "ocr-small-brain"
    if ready:
        files = [
            Path("llama") / "llama-server.exe",
            Path("models") / config.DEFAULT_SMALL_BRAIN_MODEL_FILE,
            Path("models") / config.DEFAULT_SMALL_BRAIN_MMPROJ_FILE,
        ]
        for rel in files:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
    return root


def run_gate(
    brain_url: str, *args: str, brain_dir: Path | None = None
) -> subprocess.CompletedProcess:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(CLEAR_PREFIXES)
    }
    env["SMALL_BRAIN_BASE_URL"] = brain_url
    env["PYTHONIOENCODING"] = "utf-8"
    if brain_dir is not None:
        env["OCR_SMALL_BRAIN_DIR"] = str(brain_dir)
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=config.ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def row_of(out: str, arm: str, fixture: str) -> tuple[str, str, str]:
    """(schema, verdict, detail) of one printed table row."""
    found = re.search(rf"^{arm}\s+{fixture}\s+(\S+)\s+(\S+)\s*(.*)$", out, re.M)
    assert found, f"no {arm} row for {fixture} in:\n{out}"
    return found.group(1), found.group(2), found.group(3).strip()


def score_of(out: str, arm: str, label: str) -> tuple[str, str, str, str]:
    """(got, need, verdict, note) of one printed gate line."""
    found = re.search(
        rf"^{arm}\s+{label}\s+(\S+)\s+need\s+(\S+)\s+(\S+)\s*(.*)$", out, re.M
    )
    assert found, f"no {arm} {label} line in:\n{out}"
    return found.group(1), found.group(2), found.group(3), found.group(4).strip()


# --- the healthy corpus ------------------------------------------------------


def test_both_arms_pass_the_brief_line(brain, tmp_path):
    run = run_gate(brain.base_url, brain_dir=install_dir(tmp_path, ready=True))
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "SMALL BRAIN GATE OK" in out
    assert "FAIL" not in out
    # Each arm on the brief's line: 6/6 schema-valid, 5/6 validator-ok.
    for arm in ("with-image", "no-image"):
        assert score_of(out, arm, "schema-valid")[:3] == ("6/6", "6/6", "PASS")
        assert score_of(out, arm, "validator-ok")[:3] == ("5/6", "5/6", "PASS")
        # Six rows, all schema-valid; only fis_benzin_foto fails the validator.
        for fixture in RECORDED:
            schema, verdict, _ = row_of(out, arm, fixture)
            expected = "mismatch" if fixture == ALLOWED_MISS else "ok"
            assert (schema, verdict) == ("yes", expected), f"{arm} {fixture}"
        assert score_of(out, arm, "validator-ok")[1] == "5/6"


def test_the_arms_differ_on_the_wire(brain, tmp_path):
    """The --no-image arm measured text-only: the photo is really not attached."""
    run_gate(brain.base_url, brain_dir=install_dir(tmp_path, ready=True))
    with_image = [name for name, has_image in brain.requests if has_image]
    without_image = [name for name, has_image in brain.requests if not has_image]
    assert len(brain.requests) == len(RECORDED) * 2
    assert sorted(set(with_image)) == sorted(RECORDED)
    assert sorted(set(without_image)) == sorted(RECORDED)
    assert all(name in RECORDED for name, _ in brain.requests), "a fixture was invented"


def test_one_arm_alone_scores_only_itself(brain, tmp_path):
    run = run_gate(brain.base_url, "--no-image", brain_dir=install_dir(tmp_path, ready=True))
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert score_of(out, "no-image", "validator-ok")[:3] == ("5/6", "5/6", "PASS")
    assert "with-image" not in out
    assert len(brain.requests) == len(RECORDED)
    assert all(not has_image for _, has_image in brain.requests)


# --- the rigs: a gate must be able to fail -----------------------------------


def test_a_rigged_bad_arm_exits_nonzero(brain, tmp_path):
    """Only the text-only arm breaks — and that alone fails the run."""
    brain.only_without_image = True
    brain.bad = {"fis_market_clean"}
    run = run_gate(brain.base_url, brain_dir=install_dir(tmp_path, ready=True))
    out = run.stdout + run.stderr
    assert run.returncode != 0, out
    assert "SMALL BRAIN GATE FAILED" in out
    # The rigged arm's row never parsed; the line under it says the arm lost.
    assert row_of(out, "no-image", "fis_market_clean")[:2] == ("no", "unreadable")
    assert score_of(out, "no-image", "schema-valid") == (
        "5/6", "6/6", "FAIL", "misses: fis_market_clean",
    )
    # The healthy arm still reports its own PASS: arms are scored apart.
    assert score_of(out, "with-image", "schema-valid")[:3] == ("6/6", "6/6", "PASS")
    assert score_of(out, "with-image", "validator-ok")[:3] == ("5/6", "5/6", "PASS")


def test_a_miss_on_the_wrong_fixture_exits_nonzero(brain, tmp_path):
    """5/6 is only 5/6 when fis_benzin_foto is the one that missed."""
    brain.fixed = {ALLOWED_MISS}
    brain.off = {"fis_restoran_clean"}
    run = run_gate(brain.base_url, "--with-image", brain_dir=install_dir(tmp_path, ready=True))
    out = run.stdout + run.stderr
    assert run.returncode != 0, out
    assert row_of(out, "with-image", "fis_restoran_clean")[:2] == ("yes", "mismatch")
    assert score_of(out, "with-image", "schema-valid")[:3] == ("6/6", "6/6", "PASS")
    assert score_of(out, "with-image", "validator-ok") == (
        "5/6", "5/6", "FAIL", "misses: fis_restoran_clean",
    )
    assert "SMALL BRAIN GATE FAILED" in out


def test_a_brain_that_never_answers_exits_nonzero(tmp_path):
    run = run_gate(
        f"http://127.0.0.1:{closed_port()}", "--with-image",
        brain_dir=install_dir(tmp_path, ready=True),
    )
    out = run.stdout + run.stderr
    assert run.returncode != 0, out
    assert "SMALL BRAIN GATE FAILED" in out
    assert row_of(out, "with-image", "fis_market_clean")[:2] == ("no", "error")


# --- --if-installed is the form CI runs ---------------------------------------


def test_if_installed_skips_without_the_model(brain, tmp_path):
    run = run_gate(
        brain.base_url, "--if-installed", brain_dir=install_dir(tmp_path, ready=False)
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.startswith("SKIP")
    assert "install_small_brain" in run.stdout
    assert "SMALL BRAIN GATE" not in run.stdout
    assert brain.requests == []


def test_if_installed_skips_a_brain_that_is_not_running(brain, tmp_path):
    """Files installed, llama-server not started: "no brain", not a regression.

    This is every box that is not running ``python run.py`` this second — and
    the smoke list runs unattended, so the gate has to tell a brain that is not
    there from a brain that reads badly (PLAN run-2 R10).
    """
    port = closed_port()
    run = run_gate(
        f"http://127.0.0.1:{port}", "--if-installed",
        brain_dir=install_dir(tmp_path, ready=True),
    )
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert run.stdout.startswith("SKIP")
    assert f"http://127.0.0.1:{port}" in run.stdout
    assert "python run.py" in run.stdout
    assert "SMALL BRAIN GATE" not in out
    assert brain.requests == []


def test_flagless_still_fails_a_brain_that_is_not_running(tmp_path):
    """The flag is the whole difference: flagless is what an operator runs
    knowing the brain is up, so a refused port keeps its rows and its exit 1."""
    port = closed_port()
    run = run_gate(
        f"http://127.0.0.1:{port}", "--with-image",
        brain_dir=install_dir(tmp_path, ready=True),
    )
    out = run.stdout + run.stderr
    assert run.returncode != 0, out
    assert "SKIP" not in out
    assert row_of(out, "with-image", "fis_market_clean")[:2] == ("no", "error")


def test_if_installed_scores_when_the_model_is_there(brain, tmp_path):
    run = run_gate(
        brain.base_url, "--if-installed", brain_dir=install_dir(tmp_path, ready=True)
    )
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "SKIP" not in out
    assert "SMALL BRAIN GATE OK" in out
    assert len(brain.requests) == len(RECORDED) * 2
