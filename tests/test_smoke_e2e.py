"""The smoke is a gate, so both directions of its exit code are the contract.

One test runs the accept command itself as a subprocess — real app, real
sockets, real queue — and the rest pin the checks it fails on, because a gate
that cannot fail is not a gate.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys

import httpx
import pytest

from app import auth, config
from scripts import smoke_e2e as smoke

FIXTURE_JSON = config.ROOT / "fixtures" / f"{smoke.FIXTURE}.json"


@pytest.fixture(autouse=True)
def small_backend(monkeypatch):
    """The backend this file describes: stage 2 on the small brain.

    The smoke compares meta.model against whatever backend config resolves, so
    the envelope names the model that backend runs. tests/test_cutover_backend.py
    puts the Strata rollback through the same smoke.
    """
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")


def _envelope() -> dict:
    """A done envelope the smoke has to accept, built from ground truth."""
    truth = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    return {
        "job_id": "job-1",
        "status": "done",
        "client_ref": smoke.CLIENT_REF,
        "result": copy.deepcopy(truth),
        "validation": {
            "verdict": "ok",
            "expected": truth["totals"],
            "actual": truth["totals"],
            "fields": [],
        },
        "meta": {
            "worker": smoke.WORKER,
            "captured_at": None,
            "received_at": "2026-10-31T09:00:00.000Z",
            "ocr_ms": 10,
            "total_ms": 20,
            "model": config.stage2_model(False),
            "quality_mode": False,
        },
    }


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200, json=payload, request=httpx.Request("GET", "http://smoke/v1/jobs/job-1")
    )


def _no_app(self, *args, **kwargs):
    raise smoke.SmokeError("app did not come up")


def _run_smoke() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(config.ROOT / "scripts" / "smoke_e2e.py")],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_smoke_passes_over_real_http():
    run = _run_smoke()
    assert run.returncode == 0, run.stdout + run.stderr
    assert "SMOKE OK" in run.stdout


def test_the_strata_rollback_passes_the_same_smoke(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    run = _run_smoke()
    assert run.returncode == 0, run.stdout + run.stderr
    assert "SMOKE OK" in run.stdout


def test_smoke_exits_nonzero_when_a_stage_breaks(monkeypatch, tmp_path):
    # main() repoints DATA_DIR at its own workspace and registers a key;
    # monkeypatch puts both back so the run leaves no trace on the suite.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth, "_buckets", {})
    monkeypatch.setattr(smoke._App, "start", _no_app)
    assert smoke.main() == 1


def test_a_clean_envelope_is_accepted():
    smoke._check(_envelope())


def test_amounts_disagreeing_with_ground_truth_fail():
    body = _envelope()
    body["result"]["totals"]["toplam"] += 1.0
    with pytest.raises(smoke.SmokeError, match="totals"):
        smoke._check(body)


def test_a_mismatch_verdict_fails():
    body = _envelope()
    body["validation"] = {
        "verdict": "mismatch",
        "expected": {},
        "actual": {},
        "fields": ["totals.kdv"],
    }
    with pytest.raises(smoke.SmokeError, match="mismatch"):
        smoke._check(body)


def test_an_envelope_outside_contract_v1_fails():
    body = _envelope()
    body["status"] = "sleeping"  # a status the frozen contract never had
    with pytest.raises(smoke.SmokeError, match="contract v1"):
        smoke._validated(_response(body))
