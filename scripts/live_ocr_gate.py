"""Brief section 9 gate 2: the three real receipts, live, against the baseline.

``fixtures_real/`` holds the real receipts — two printed, one handwritten — and it
is gitignored (KVKK), so the gate is driven by what the recorded Strata run left
behind: ``scripts/live_ocr_baseline.json``, read out of ``spike/live_real.json``
under today's validator. Each receipt then goes through the shipped pipeline —
stage 1 OCR, the configured stage-2 brain, the real validator — over the sockets
config points at, and brief 9.2 decides the two scores: ``gercek_market_1`` and
``gercek_bim_2`` must reach verdict ``ok``, ``gercek_elyazisi_3_kirp`` must be no
worse than its recorded verdict.

    .venv/Scripts/python scripts/live_ocr_gate.py                  # score it
    .venv/Scripts/python scripts/live_ocr_gate.py --if-installed   # the smoke-list form
    .venv/Scripts/python scripts/live_ocr_gate.py --check          # baseline + inventory
    .venv/Scripts/python scripts/live_ocr_gate.py --record         # re-record the baseline

``--if-installed`` is the form .hybrid/checks.json runs: without the receipts or
the small brain it prints SKIP and exits 0 (PLAN run-2 R10/R11), so the gate sits
in the smoke list next to the checks that always run. Both model servers are
config's — ``OCR_HOST``/``OCR_PORT`` and ``SMALL_BRAIN_BASE_URL`` move them — so
the gate has no address flag of its own (PLAN run-2 R1).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # direct `python scripts/live_ocr_gate.py`
    sys.path.insert(0, str(ROOT))

from app import config, pipeline, validator  # noqa: E402

RECEIPT_DIR = config.ROOT / "fixtures_real"
BASELINE_PATH = config.ROOT / "scripts" / "live_ocr_baseline.json"
LIVE_RUN = config.ROOT / "spike" / "live_real.json"
INSTALLER = "scripts\\install_small_brain.ps1"
WORKER = "live-ocr-gate"
# Brief 9.2, verbatim: these two reach verdict ok — gercek_bim_2 included, which
# the Strata baseline recorded as a mismatch, so the bar there is an improvement.
MUST_BE_OK = ("gercek_market_1", "gercek_bim_2")
# The handwriting is graded against its own recorded verdict, not against ok.
HANDWRITING = "gercek_elyazisi_3_kirp"
FIXTURES = (*MUST_BE_OK, HANDWRITING)
OK = "ok"
ERROR = "error"  # a stage died: no verdict was measured, so nothing can pass on it
# "no worse than the baseline" read as an ordering of the three verdicts.
RANK = {"unreadable": 0, "mismatch": 1, OK: 2}
DETAIL_W = 60


class GateError(RuntimeError):
    """The baseline or the corpus is unusable; its message is the report."""


def _log(line: str) -> None:
    print(line, flush=True)


def _brief(text: str) -> str:
    """One line of model/server chatter, short enough to keep the table a table."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= DETAIL_W else flat[: DETAIL_W - 1] + "…"


def _name(path: pathlib.Path) -> str:
    """Repo-relative path: the report reads the same on every machine."""
    try:
        return str(path.relative_to(config.ROOT))
    except ValueError:
        return str(path)


def _ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _image_path(name: str) -> pathlib.Path:
    return RECEIPT_DIR / f"{name}.png"


# --- the baseline file -------------------------------------------------------


def read_baseline(path: pathlib.Path | None = None) -> dict[str, dict]:
    """The recorded baseline as {receipt: {verdict, total_ms}}, or GateError."""
    path = BASELINE_PATH if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{_name(path)} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise GateError(f"{_name(path)} is not a JSON object")
    unknown = sorted(str(name) for name in data if name not in FIXTURES)
    if unknown:
        raise GateError(f"{_name(path)} names no gate receipt: {', '.join(unknown)}")
    rows: dict[str, dict] = {}
    for fixture, entry in data.items():
        if not isinstance(entry, dict):
            raise GateError(f"{_name(path)}: {fixture} is not an object")
        verdict = str(entry.get("verdict") or "")
        if verdict not in RANK:
            raise GateError(
                f"{_name(path)}: {fixture} verdict {verdict!r} is not one of "
                f"{', '.join(sorted(RANK))}"
            )
        rows[str(fixture)] = {"verdict": verdict, "total_ms": _ms(entry.get("total_ms"))}
    missing = [name for name in FIXTURES if name not in rows]
    if missing:
        raise GateError(f"{_name(path)} has no baseline for: {', '.join(missing)}")
    return rows


def record_baseline(path: pathlib.Path | None = None, source: pathlib.Path | None = None) -> dict:
    """Re-record the baseline from the spike's live run, under today's validator."""
    path = BASELINE_PATH if path is None else path
    source = LIVE_RUN if source is None else source
    try:
        run = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{_name(source)} unreadable: {exc}") from exc
    if not isinstance(run, dict):
        raise GateError(f"{_name(source)} is not a JSON object")
    rows: dict[str, dict] = {}
    for name in FIXTURES:
        envelope = run.get(f"{name}.png")
        result = envelope.get("result") if isinstance(envelope, dict) else None
        if not isinstance(result, dict):
            raise GateError(f"{_name(source)} has no result for {name}.png")
        # ASSUMPTION: PLAN run-2 records {verdict, total_ms} per receipt — the
        # verdict is what the gate compares, total_ms is context for the table.
        rows[name] = {
            "verdict": str(validator.validate(result)["verdict"]),
            "total_ms": _ms((envelope.get("meta") or {}).get("total_ms")),
        }
    path.write_text(
        json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for name in FIXTURES:
        _log(
            f"{name:<22} recorded {rows[name]['verdict']:<11} "
            f"{rows[name]['total_ms']:>8} ms"
        )
    _log(f"BASELINE RECORDED — {_name(path)} from {_name(source)}")
    return rows


def check_baseline(baseline: dict[str, dict], path: pathlib.Path) -> int:
    """What the baseline promises and what this machine holds, one row each."""
    _log(f"{'receipt':<22} {'gate':<11} {'baseline':<11} {'total_ms':>8}  dosya")
    for name in FIXTURES:
        role = "verdict-ok" if name in MUST_BE_OK else "no-worse"
        _log(
            f"{name:<22} {role:<11} {baseline[name]['verdict']:<11} "
            f"{baseline[name]['total_ms']:>8}  {'var' if _image_path(name).is_file() else 'yok'}"
        )
    _log(f"BASELINE OK — {len(FIXTURES)} receipts in {_name(path)}")
    return 0


# --- the live run ------------------------------------------------------------


def skip_reason(if_installed: bool) -> str | None:
    """Why this box cannot run the gate, in the one line that skips instead of fails."""
    missing = [name for name in FIXTURES if not _image_path(name).is_file()]
    if missing:
        return (
            f"no real receipts in {_name(RECEIPT_DIR)} ({', '.join(missing)}); "
            "fixtures_real/ gitignored — özel fişler depoda değil"
        )
    if if_installed and config.structurer_backend() == "small" and not config.small_brain_ready():
        return (
            f"small brain not installed ({_name(config.small_brain_dir())} has no "
            f"model files); kurmak için {INSTALLER}"
        )
    return None


def _row(name: str, verdict: str, baseline: str, detail: str) -> dict:
    _log(f"{name:<22} {verdict:<11} {baseline:<11} {_brief(detail)}")
    return {"fixture": name, "verdict": verdict, "baseline": baseline}


def run_receipt(name: str, baseline: dict[str, dict]) -> dict:
    """One real receipt through the shipped pipeline, printed as it finishes."""
    outcome = pipeline.run(_image_path(name).read_bytes(), worker=WORKER)
    recorded = baseline[name]["verdict"]
    error = str(outcome.get("error") or "")
    if error:
        return _row(name, ERROR, recorded, error)
    check = outcome["validation"]
    verdict, fields = str(check["verdict"]), list(check["fields"])
    total_ms = _ms((outcome.get("meta") or {}).get("total_ms"))
    return _row(name, verdict, recorded, ", ".join(fields) if fields else f"{total_ms} ms")


def _gate_line(
    name: str, label: str, got: str, want: str, ok: bool, note: str
) -> bool:
    _log(
        f"{name:<22} {label:<11} {got:<11} need {want:<13} "
        f"{'PASS' if ok else 'FAIL'}  {'' if ok else note}".rstrip()
    )
    return ok


def score(rows: list[dict]) -> bool:
    """Brief 9.2 over the rows it just printed."""
    passed = True
    for row in rows:
        name, verdict, recorded = row["fixture"], row["verdict"], row["baseline"]
        note = "" if verdict != ERROR else "no verdict — the row above says why"
        if name in MUST_BE_OK:
            passed &= _gate_line(name, "verdict-ok", verdict, OK, verdict == OK, note)
        else:
            # ASSUMPTION: brief 9.2 grades the handwriting "no worse than the
            # recorded Strata baseline", so the bar is the baseline's own verdict
            # under today's validator, ordered ok > mismatch > unreadable.
            ok = verdict != ERROR and RANK[verdict] >= RANK[recorded]
            passed &= _gate_line(name, "no-worse", verdict, f">={recorded}", ok, note)
    return passed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Brief section 9 gate 2: the real receipts in fixtures_real/ "
        "through the live OCR and stage 2, against scripts/live_ocr_baseline.json."
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help=f"re-record the baseline from {_name(LIVE_RUN)} and exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the baseline file and the receipt inventory, run nothing",
    )
    parser.add_argument(
        "--if-installed",
        action="store_true",
        help="print SKIP and exit 0 when the small brain's files are not installed",
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if args.record:
            record_baseline()
            return 0
        baseline = read_baseline()
        if args.check:
            return check_baseline(baseline, BASELINE_PATH)
        skip = skip_reason(args.if_installed)
        if skip:
            _log(f"SKIP — {skip}")
            return 0
        _log(
            f"live OCR gate — {config.ocr_base_url()} → stage 2 "
            f"{config.structurer_backend()} ({config.stage2_model(False)}), "
            f"{_name(BASELINE_PATH)}"
        )
        _log(f"{'receipt':<22} {'verdict':<11} {'baseline':<11} detail")
        passed = score([run_receipt(name, baseline) for name in FIXTURES])
    except GateError as exc:
        _log(f"LIVE OCR GATE FAILED — {exc}")
        return 1
    except Exception as exc:  # a gate reports, it does not dump a traceback
        _log(f"LIVE OCR GATE FAILED — {type(exc).__name__}: {_brief(exc)}")
        return 1
    elapsed = time.perf_counter() - started
    if not passed:
        _log(f"LIVE OCR GATE FAILED — brief 9.2 regressed vs baseline in {elapsed:.0f}s")
        return 1
    _log(f"LIVE OCR GATE OK — {len(FIXTURES)} receipts in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        # the rows and reasons carry Turkish; a cp1252 console would kill the print
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
