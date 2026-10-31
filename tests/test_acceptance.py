"""T48: the acceptance harness is a gate, so both directions of its exit code count.

One test runs the accept command itself (--demo: real app, real auth, real
queue, stubbed models) and the rest pin the teeth of the individual checks,
because a gate that cannot fail is not a gate.
"""
from __future__ import annotations

import io
import subprocess
import sys

import httpx
import pytest
from openpyxl import load_workbook

from app import config, exports, validator
from scripts import acceptance

DEAD_URL = "http://127.0.0.1:1"


def _instance() -> acceptance.Instance:
    """An instance handle for the checks that never reach the network here."""
    return acceptance.Instance(DEAD_URL, "ocrk_" + "0" * 40)


def _envelope() -> dict:
    return {
        "job_id": "job-1",
        "status": "done",
        "client_ref": None,
        "result": None,
        "validation": None,
        "meta": {"worker": "eren"},
    }


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200, json=payload, request=httpx.Request("GET", f"{DEAD_URL}/v1/jobs/job-1")
    )


def _export_row(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "worker": "eren",
        "client_ref": "",
        "tarih": "28.10.2026",
        "saat": "14:32",
        "firma": "BİLGİN MARKET",
        "vergi_no": "1234567890",
        "ara_toplam": 1046.4,
        "iskonto": 52.32,
        "kdv": 198.82,
        "toplam": 1192.9,
        "para_birimi": "TRY",
        "verdict": "ok",
        "items_json": "[]",
        "kalite_mode": False,
        "gonderim_zamani": "2026-10-28 14:32:00",
    }


# --- the accept command itself ---


def test_acceptance_passes_against_a_booted_demo():
    run = subprocess.run(
        [sys.executable, str(config.ROOT / "scripts" / "acceptance.py"), "--demo"],
        cwd=config.ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "7/7 checks passed" in run.stdout
    # the KDV row has to name the field it caught, not just report a pass
    assert "totals.kdv" in run.stdout


def test_main_exits_nonzero_when_a_check_fails(monkeypatch, capsys):
    def boom(_inst):
        raise acceptance.CheckError("the app said no")

    monkeypatch.setattr(acceptance, "CHECKS", (("verdict ok", boom),))
    monkeypatch.setattr(
        acceptance, "_boot_demo", lambda: (_instance(), lambda: None)
    )
    assert acceptance.main(["--demo"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "the app said no" in out


def test_main_reports_an_unreachable_instance_without_a_traceback(monkeypatch, capsys):
    def no_boot():
        raise acceptance.CheckError("app did not come up")

    monkeypatch.setattr(acceptance, "_boot_demo", no_boot)
    assert acceptance.main(["--demo"]) == 1
    assert "instance up" in capsys.readouterr().out


# --- the checks have teeth ---


def test_an_envelope_outside_contract_v1_fails():
    body = _envelope()
    body["status"] = "sleeping"  # a status the frozen contract never had
    with pytest.raises(acceptance.CheckError, match="contract v1"):
        _instance().envelope(_response(body))


def test_verdict_check_fails_when_the_validator_disagrees(monkeypatch):
    inst = _instance()
    monkeypatch.setattr(
        inst,
        "job_to_done",
        lambda ref: {"job_id": "job-1", "validation": {"verdict": "mismatch", "fields": ["totals.kdv"]}},
    )
    with pytest.raises(acceptance.CheckError, match="mismatch"):
        acceptance.check_verdict_ok(inst)


def test_verdict_check_fails_on_amounts_outside_ground_truth(monkeypatch):
    inst = _instance()
    body = {
        "job_id": "job-1",
        "validation": {"verdict": "ok", "fields": []},
        "result": {"items": acceptance.TRUTH["items"], "totals": {"toplam": 1.0}},
    }
    monkeypatch.setattr(inst, "job_to_done", lambda ref: body)
    with pytest.raises(acceptance.CheckError, match="ground truth"):
        acceptance.check_verdict_ok(inst)


def test_validator_edge_suite_passes_as_written():
    assert "6 cases" in acceptance.check_validator_edges(None)


def test_validator_edge_suite_fails_when_the_validator_stops_recomputing(monkeypatch):
    monkeypatch.setattr(validator, "validate", lambda result: {"verdict": "ok", "fields": []})
    with pytest.raises(acceptance.CheckError, match="iskonto"):
        acceptance.check_validator_edges(None)


# --- the export readers read what the app writes ---


def test_export_readers_see_the_rows_the_app_writes():
    rows = [_export_row("job-1"), _export_row("job-2")]
    assert [r["job_id"] for r in acceptance._csv_rows(exports.to_csv(rows))] == [
        "job-1",
        "job-2",
    ]
    cells = acceptance._xlsx_rows(
        load_workbook(io.BytesIO(exports.to_xlsx(rows))).active
    )
    assert [c["job_id"] for c in cells] == ["job-1", "job-2"]
    assert cells[0]["kdv"] == 198.82  # numeric cells, not Excel text


def test_parity_fails_when_a_selected_row_is_missing_from_the_file():
    with pytest.raises(acceptance.CheckError, match="csv has 1 rows"):
        acceptance._exact([{"job_id": "job-1"}], {"job-1": {}, "job-2": {}}, "csv")
