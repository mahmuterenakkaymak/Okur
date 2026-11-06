"""T90: scripts/live_ocr_gate.py — brief 9 gate 2 over the real receipts.

No test can ship the real receipts (fixtures_real is gitignored), a live
PaddleOCR-VL or a running brain, so the gate runs here against two
OpenAI-compatible stubs on ephemeral ports and fake receipt files whose bytes
name the receipt: stage 1 answers with that name, stage 2 with the result the
test picked for it. Everything between the two sockets — the shipped pipeline,
the contract, the validator, the baseline comparison, the exit code — is real.

And a gate that cannot fail is not a gate, so the rigs matter: a mismatch where
brief 9.2 wants ``ok``, a handwriting that fell below its own recorded verdict
and a stage that never answered must each leave a nonzero behind — while
``--if-installed`` is pinned both ways, because .hybrid/checks.json runs that
form on clones that have neither the receipts nor the 2.1 GB model.

The gate is driven in-process so its receipt dir and baseline file can be temp
paths; the servers move the way they always do, on ``OCR_PORT`` and
``SMALL_BRAIN_BASE_URL``.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import config
from scripts import live_ocr_gate as gate

MUSH = "Fişi okuyamadım, lütfen tekrar çekin."
ANSWERS = ("ok", "mismatch", "unreadable", "mush", "error")
# The bar brief 9.2 draws, spelled out: the two printed receipts must reach ok and
# the handwriting is graded against its own recorded verdict.
BASELINE = {
    "gercek_market_1": "ok",
    "gercek_bim_2": "mismatch",
    "gercek_elyazisi_3_kirp": "unreadable",
}
# A temp baseline nothing can satisfy, for the rigs that only exist to fail: it
# keeps the row under test the only thing that can move the exit code.
IMPOSSIBLE = {name: "ok" for name in gate.FIXTURES}
# What --record writes from spike/live_real.json under today's validator.
COMMITTED_BASELINE = {
    "gercek_market_1": {"verdict": "ok", "total_ms": 17868},
    "gercek_bim_2": {"verdict": "mismatch", "total_ms": 14512},
    "gercek_elyazisi_3_kirp": {"verdict": "unreadable", "total_ms": 7336},
}


def answer(kind: str) -> dict:
    """A contract result whose verdict under the real validator is ``kind``."""
    if kind == "ok":
        totals = {"ara_toplam": 10.0, "iskonto": 0.0, "kdv": 0.0, "kdv_orani": 0.0, "toplam": 10.0}
        items = [{"ad": "URUN", "miktar": 1.0, "birim_fiyat": 10.0, "toplam": 10.0}]
    elif kind == "mismatch":
        totals = {"ara_toplam": 10.0, "iskonto": 0.0, "kdv": 0.0, "kdv_orani": 0.0, "toplam": 999.0}
        items = [{"ad": "URUN", "miktar": 1.0, "birim_fiyat": 10.0, "toplam": 10.0}]
    else:  # nothing read: the validator calls an empty receipt unreadable
        totals = {"ara_toplam": 0.0, "iskonto": 0.0, "kdv": 0.0, "kdv_orani": 0.0, "toplam": 0.0}
        items = []
    return {
        "header": {"isim": "MARKET", "vergi_dairesi": "", "vergi_no": ""},
        "meta": {"tarih": "30.01.2022", "saat": "12:31", "no": "0004", "tip": ""},
        "items": items,
        "totals": totals,
        "para_birimi": "TRY",
        "okunamayan": [],
    }


def _completion(content: str) -> dict:
    return {
        "id": "chatcmpl-live-gate",
        "object": "chat.completion",
        "created": 0,
        "model": "stub",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


def _message(body: dict) -> tuple[str, str]:
    """(joined text, last image data url) of the stub's request."""
    content = (body.get("messages") or [{}])[-1].get("content")
    parts = [content] if isinstance(content, str) else (content or [])
    texts, images = [], []
    for part in parts:
        if part.get("type") == "text":
            texts.append(str(part.get("text", "")))
        elif part.get("type") == "image_url":
            images.append(str((part.get("image_url") or {}).get("url", "")))
    return "\n".join(texts), (images[-1] if images else "")


def _decode(data_url: str) -> str:
    payload = data_url.rsplit(",", 1)[-1] if "," in data_url else data_url
    try:
        return base64.b64decode(payload, validate=False).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _send(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        self.server.rig.reply(self, self.server.role, body)

    def log_message(self, *args):
        pass


class _Server:
    """One model role on an ephemeral port."""

    def __init__(self, rig: "Rig", role: str) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.rig = rig
        self._httpd.role = role
        self._closed = False
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def base_url(self) -> str:
        host, port, *_ = self._httpd.server_address
        return f"http://{host}:{port}"

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class Rig:
    """The two model stubs; ``answers`` picks each receipt's stage-2 behaviour.

    ``ok``/``mismatch``/``unreadable`` answer with a result whose verdict under
    the real validator is that word, ``mush`` answers with prose — an unreadable
    receipt, still a measured verdict — and ``error`` answers HTTP 500, which the
    pipeline reports as a stage failure with no verdict at all.
    """

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = dict(answers or {})
        self.ocr_seen: list[str] = []
        self.brain_seen: list[str] = []
        self.ocr = _Server(self, "ocr")
        self.brain = _Server(self, "brain")

    def stop_ocr(self) -> None:
        """Kill stage 1 so the gate's next request meets a closed port."""
        self.ocr.shutdown()

    def reply(self, handler: BaseHTTPRequestHandler, role: str, body: dict) -> None:
        text, image = _message(body)
        name = next((n for n in gate.FIXTURES if n in text), "")
        if role == "ocr":
            name = next((n for n in gate.FIXTURES if n in _decode(image)), "")
            self.ocr_seen.append(name)
            _send(handler, 200, _completion(f"<fcel>{name}<nl>"))
            return
        self.brain_seen.append(name)
        kind = self.answers.get(name, "ok")
        if kind not in ANSWERS:
            raise ValueError(f"unknown rig answer: {kind!r}")
        if kind == "error":
            _send(handler, 500, {"error": {"message": "brain down"}})
        elif kind == "mush":
            _send(handler, 200, _completion(MUSH))
        else:
            _send(handler, 200, _completion(json.dumps(answer(kind), ensure_ascii=False)))


def use_baseline(tmp_path: Path, monkeypatch, verdicts: dict[str, str] | None = None, raw: str | None = None) -> Path:
    """A temp scripts/live_ocr_baseline.json the gate is pointed at."""
    path = tmp_path / "baseline" / "live_ocr_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = dict(IMPOSSIBLE if verdicts is None else verdicts)
    path.write_text(
        raw
        if raw is not None
        else json.dumps(
            {name: {"verdict": verdict, "total_ms": 1000} for name, verdict in rows.items()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "BASELINE_PATH", path)
    return path


def brain_installed(tmp_path: Path, monkeypatch, ready: bool) -> None:
    """A fake %LOCALAPPDATA%\\ocr-small-brain: config decides which files count."""
    root = tmp_path / "ocr-small-brain"
    monkeypatch.setenv("OCR_SMALL_BRAIN_DIR", str(root))
    files = [
        Path("llama") / "llama-server.exe",
        Path("models") / config.DEFAULT_SMALL_BRAIN_MODEL_FILE,
        Path("models") / config.DEFAULT_SMALL_BRAIN_MMPROJ_FILE,
    ]
    if not ready:  # the model file a clone does not have
        files.pop(1)
    for rel in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")


def run_gate(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = gate.main(list(argv))
    return code, out.getvalue()


def row_of(out: str, name: str) -> tuple[str, str, str]:
    """(verdict, recorded verdict, detail) of one printed table row."""
    found = re.search(
        rf"^{name}[ ]+(ok|mismatch|unreadable|error)[ ]+(ok|mismatch|unreadable)[ ]*(.*)$",
        out, re.M,
    )
    assert found, f"no {name} row in:\n{out}"
    return found.group(1), found.group(2), found.group(3).strip()


def score_of(out: str, name: str) -> tuple[str, str, str, str, str]:
    """(bar, got, want, PASS/FAIL, note) of one printed gate line."""
    found = re.search(
        rf"^{name}[ ]+(\S+)[ ]+(\S+)[ ]+need[ ]+(\S+)[ ]+(PASS|FAIL)[ ]*(.*)$", out, re.M
    )
    assert found, f"no gate line for {name} in:\n{out}"
    return found.group(1), found.group(2), found.group(3), found.group(4), found.group(5).strip()


# --- rigs --------------------------------------------------------------------


@pytest.fixture
def receipts(tmp_path, monkeypatch) -> Path:
    """A temp fixtures_real/ with the three gate receipts: the bytes name the file."""
    root = tmp_path / "fixtures_real"
    root.mkdir(exist_ok=True)
    for name in gate.FIXTURES:
        (root / f"{name}.png").write_bytes(name.encode("utf-8"))
    monkeypatch.setattr(gate, "RECEIPT_DIR", root)
    return root


@pytest.fixture
def stack(receipts, monkeypatch):
    """Both model roles on real sockets, wired in through config's own env."""
    started: list[Rig] = []

    def start(answers: dict[str, str] | None = None) -> Rig:
        rig = Rig(answers)
        started.append(rig)
        for name, value in (
            ("OCR_HOST", "127.0.0.1"),
            ("OCR_PORT", str(rig.ocr.port)),
            ("STRUCTURER_BACKEND", "small"),
            ("SMALL_BRAIN_BASE_URL", rig.brain.base_url),
            ("OCR_TIMEOUT_S", "15"),
            ("STRUCTURER_TIMEOUT_S", "15"),
        ):
            monkeypatch.setenv(name, value)
        return rig

    yield start
    for rig in started:
        rig.brain.shutdown()
        rig.ocr.shutdown()


# --- the healthy run ---------------------------------------------------------


def test_every_receipt_on_its_own_bar(stack, tmp_path, monkeypatch):
    """market ok + bim ok + the handwriting at its recorded verdict: the gate passes."""
    rig = stack({"gercek_elyazisi_3_kirp": "unreadable"})
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate()
    assert code == 0, out
    assert "LIVE OCR GATE OK" in out
    assert "FAIL" not in out
    assert row_of(out, "gercek_market_1")[:2] == ("ok", "ok")
    assert row_of(out, "gercek_bim_2")[:2] == ("ok", "mismatch")
    assert row_of(out, "gercek_elyazisi_3_kirp")[:2] == ("unreadable", "unreadable")
    # Each bar brief 9.2 draws, printed against what it got.
    assert score_of(out, "gercek_market_1") == ("verdict-ok", "ok", "ok", "PASS", "")
    assert score_of(out, "gercek_bim_2") == ("verdict-ok", "ok", "ok", "PASS", "")
    assert score_of(out, "gercek_elyazisi_3_kirp") == (
        "no-worse", "unreadable", ">=unreadable", "PASS", ""
    )
    # Both legs really ran: every receipt through stage 1 and on into stage 2.
    assert sorted(rig.ocr_seen) == sorted(gate.FIXTURES)
    assert sorted(rig.brain_seen) == sorted(gate.FIXTURES)


def test_a_mismatch_names_its_fields(stack, tmp_path, monkeypatch):
    stack({"gercek_market_1": "mismatch"})
    use_baseline(tmp_path, monkeypatch)
    code, out = run_gate()
    assert code != 0, out
    assert row_of(out, "gercek_market_1") == ("mismatch", "ok", "totals.toplam")


# --- the rigs: a gate must be able to fail -----------------------------------


def test_market_must_reach_ok(stack, tmp_path, monkeypatch):
    """Its own baseline said ok once; falling to mismatch is a regression."""
    stack({"gercek_market_1": "mismatch"})
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate()
    assert code != 0, out
    assert "LIVE OCR GATE FAILED" in out
    assert score_of(out, "gercek_market_1")[3] == "FAIL"
    # The other two bars held: every receipt is scored on its own line.
    assert score_of(out, "gercek_bim_2")[3] == "PASS"
    assert score_of(out, "gercek_elyazisi_3_kirp")[3] == "PASS"


def test_bim_must_be_ok_although_the_baseline_was_mismatch(stack, tmp_path, monkeypatch):
    """Matching the baseline is not enough here: brief 9.2 asks the brain for ok."""
    rig = stack({"gercek_bim_2": "mismatch"})
    use_baseline(tmp_path, monkeypatch, {**IMPOSSIBLE, "gercek_bim_2": "mismatch"})
    code, out = run_gate()
    assert code != 0, out
    assert row_of(out, "gercek_bim_2")[:2] == ("mismatch", "mismatch")
    assert score_of(out, "gercek_bim_2")[:4] == ("verdict-ok", "mismatch", "ok", "FAIL")
    assert rig.brain_seen == list(gate.FIXTURES)


def test_a_recorded_downgrade_exits_nonzero(stack, tmp_path, monkeypatch):
    """The handwriting read ok in the baseline and now reads mismatch: gate fails."""
    stack({"gercek_elyazisi_3_kirp": "mismatch"})
    use_baseline(tmp_path, monkeypatch, {**IMPOSSIBLE, "gercek_elyazisi_3_kirp": "ok"})
    code, out = run_gate()
    assert code != 0, out
    assert "LIVE OCR GATE FAILED" in out
    assert row_of(out, "gercek_elyazisi_3_kirp")[:2] == ("mismatch", "ok")
    assert score_of(out, "gercek_elyazisi_3_kirp") == ("no-worse", "mismatch", ">=ok", "FAIL", "")


def test_the_handwriting_may_stay_or_improve(stack, tmp_path, monkeypatch):
    """The bar is the baseline, so unreadable-while-recorded-unreadable passes."""
    use_baseline(tmp_path, monkeypatch, BASELINE)
    stack({"gercek_elyazisi_3_kirp": "unreadable"})
    code, out = run_gate()
    assert code == 0, out
    assert score_of(out, "gercek_elyazisi_3_kirp") == (
        "no-worse", "unreadable", ">=unreadable", "PASS", ""
    )
    # And the receipt that reads better than its baseline is never punished.
    stack({"gercek_elyazisi_3_kirp": "mismatch"})
    code, out = run_gate()
    assert code == 0, out
    assert score_of(out, "gercek_elyazisi_3_kirp") == (
        "no-worse", "mismatch", ">=unreadable", "PASS", ""
    )


def test_an_unreadable_receipt_is_a_verdict_not_a_failure(stack, tmp_path, monkeypatch):
    """Prose from the brain scores unreadable; a dead stage scores nothing."""
    stack({"gercek_elyazisi_3_kirp": "mush"})
    use_baseline(tmp_path, monkeypatch, {**IMPOSSIBLE, "gercek_elyazisi_3_kirp": "mismatch"})
    code, out = run_gate()
    assert code != 0, out
    verdict, recorded, detail = row_of(out, "gercek_elyazisi_3_kirp")
    assert (verdict, recorded) == ("unreadable", "mismatch")
    assert detail.endswith("ms")
    assert "no verdict" not in out
    assert score_of(out, "gercek_elyazisi_3_kirp")[3] == "FAIL"


def test_a_stage_that_never_answers_is_no_verdict(stack, tmp_path, monkeypatch):
    """The 500 is neither ok nor worse-than-ok: it is a row with no verdict."""
    stack({"gercek_elyazisi_3_kirp": "error"})
    use_baseline(tmp_path, monkeypatch, {**IMPOSSIBLE, "gercek_elyazisi_3_kirp": "mismatch"})
    code, out = run_gate()
    assert code != 0, out
    verdict, recorded, detail = row_of(out, "gercek_elyazisi_3_kirp")
    assert (verdict, recorded) == ("error", "mismatch")
    assert "HTTP 500" in detail
    line = score_of(out, "gercek_elyazisi_3_kirp")
    assert line[:4] == ("no-worse", "error", ">=mismatch", "FAIL")
    assert "no verdict" in line[4]


def test_a_dead_stage_one_fails_the_run(stack, tmp_path, monkeypatch):
    """A closed OCR port is a failure, never the SKIP an absent box gets."""
    rig = stack()
    use_baseline(tmp_path, monkeypatch, BASELINE)
    rig.stop_ocr()
    code, out = run_gate()
    assert code != 0, out
    assert "LIVE OCR GATE FAILED" in out
    assert "SKIP" not in out
    assert row_of(out, "gercek_market_1")[0] == "error"
    assert rig.brain_seen == []


# --- SKIP: no receipts, no brain ---------------------------------------------


def test_no_receipts_means_skip(stack, tmp_path, monkeypatch):
    """fixtures_real is gitignored, so a clean clone skips instead of failing."""
    monkeypatch.setattr(gate, "RECEIPT_DIR", tmp_path / "no-receipts-here")
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate()
    assert code == 0, out
    assert out.startswith("SKIP")
    assert "fixtures_real" in out
    assert "LIVE OCR GATE" not in out


def test_if_installed_skips_without_the_brain(stack, tmp_path, monkeypatch):
    stack()
    use_baseline(tmp_path, monkeypatch, BASELINE)
    brain_installed(tmp_path, monkeypatch, ready=False)
    code, out = run_gate("--if-installed")
    assert code == 0, out
    assert out.startswith("SKIP")
    assert "install_small_brain" in out
    assert "LIVE OCR GATE" not in out


def test_if_installed_scores_when_the_brain_is_installed(stack, tmp_path, monkeypatch):
    rig = stack()
    use_baseline(tmp_path, monkeypatch, BASELINE)
    brain_installed(tmp_path, monkeypatch, ready=True)
    code, out = run_gate("--if-installed")
    assert code == 0, out
    assert "SKIP" not in out
    assert "LIVE OCR GATE OK" in out
    assert sorted(rig.ocr_seen) == sorted(gate.FIXTURES)


def test_if_installed_never_skips_a_box_it_cannot_install(stack, tmp_path, monkeypatch):
    """Strata is not something this script installs: with that backend the run goes on."""
    rig = stack()
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    monkeypatch.setenv("STRATA_HOST", "127.0.0.1")
    monkeypatch.setenv("STRATA_PORT", str(rig.brain.port))
    use_baseline(tmp_path, monkeypatch, BASELINE)
    brain_installed(tmp_path, monkeypatch, ready=False)
    code, out = run_gate("--if-installed")
    assert code == 0, out
    assert "SKIP" not in out
    assert "LIVE OCR GATE OK" in out


# --- --check: the baseline file and the fixture inventory --------------------


def test_check_reads_the_baseline_and_the_inventory(receipts, tmp_path, monkeypatch):
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate("--check")
    assert code == 0, out
    assert "BASELINE OK" in out
    assert "verdict-ok" in out and "no-worse" in out
    # All three receipts are on this box, and the inventory says so.
    assert out.count("var") == len(gate.FIXTURES)


def test_check_survives_a_clean_clone(stack, tmp_path, monkeypatch):
    """--check runs where the receipts are not: the inventory reports ``yok``."""
    monkeypatch.setattr(gate, "RECEIPT_DIR", tmp_path / "no-receipts-here")
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate("--check")
    assert code == 0, out
    assert out.count("yok") == len(gate.FIXTURES)


@pytest.mark.parametrize(
    "raw, problem",
    [
        ("not json at all", "unreadable"),
        ("[]", "not a JSON object"),
        (json.dumps({"gercek_market_1": {"verdict": "maybe", "total_ms": 1}}), "verdict"),
        (json.dumps({"gercek_market_1": {"verdict": "ok", "total_ms": 1}}), "no baseline for"),
        (json.dumps({
            "gercek_market_1": {"verdict": "ok", "total_ms": 1},
            "gercek_bim_2": {"verdict": "ok", "total_ms": 1},
            "gercek_elyazisi_3_kirp": {"verdict": "ok", "total_ms": 1},
            "fis_market_clean": {"verdict": "ok", "total_ms": 1},
        }), "no gate receipt"),
    ],
)
def test_check_rejects_a_broken_baseline(tmp_path, monkeypatch, raw, problem):
    use_baseline(tmp_path, monkeypatch, raw=raw)
    code, out = run_gate("--check")
    assert code != 0, out
    assert "LIVE OCR GATE FAILED" in out
    assert problem in out


def test_check_without_a_baseline_file_is_a_failure(tmp_path, monkeypatch):
    path = use_baseline(tmp_path, monkeypatch, BASELINE)
    path.unlink()
    code, out = run_gate("--check")
    assert code != 0, out
    assert "unreadable" in out


def test_the_committed_baseline_is_valid():
    """scripts/live_ocr_baseline.json ships valid: no temp path, no server."""
    code, out = run_gate("--check")
    assert code == 0, out
    assert "BASELINE OK" in out


def test_the_committed_baseline_is_the_recorded_spike_run():
    """The shipped baseline is what --record writes from spike/live_real.json."""
    committed = json.loads(gate.BASELINE_PATH.read_text(encoding="utf-8"))
    assert committed == COMMITTED_BASELINE


# --- --record ----------------------------------------------------------------


def test_record_rewrites_the_baseline_from_a_live_run(tmp_path, monkeypatch):
    source = tmp_path / "live_real.json"
    source.write_text(
        json.dumps({
            f"{name}.png": {"result": answer("ok"), "meta": {"total_ms": 1234, "model": "strata"}}
            for name in gate.FIXTURES
        }),
        encoding="utf-8",
    )
    path = use_baseline(tmp_path, monkeypatch, BASELINE)
    monkeypatch.setattr(gate, "LIVE_RUN", source)
    code, out = run_gate("--record")
    assert code == 0, out
    assert "BASELINE RECORDED" in out
    assert json.loads(path.read_text(encoding="utf-8")) == {
        name: {"verdict": "ok", "total_ms": 1234} for name in gate.FIXTURES
    }


def test_record_needs_every_receipt(tmp_path, monkeypatch):
    source = tmp_path / "live_real.json"
    source.write_text(
        json.dumps({
            f"{name}.png": {"result": answer("ok"), "meta": {"total_ms": 1}}
            for name in gate.MUST_BE_OK
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "LIVE_RUN", source)
    use_baseline(tmp_path, monkeypatch, BASELINE)
    code, out = run_gate("--record")
    assert code != 0, out
    assert "has no result for gercek_elyazisi_3_kirp.png" in out
