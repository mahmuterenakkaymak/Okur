"""Brief section 9 gates 1 and 3: the small brain over the six repo fixtures.

One command scores the installed stage-2 brain the way the brief does. Each
fixture's *recorded* stage-1 text (spike/bench_paddle.json, what PaddleOCR-VL
really read) goes into the real ``Structurer``, the brain's answer through the
real contract and the real validator — once with the receipt in the request
(``--with-image``, gate 1) and once text only (``--no-image``, gate 3, which is
what decides the future t4b demotion). Both arms must read schema-valid 6/6 and
validator-ok 5/6 with ``fis_benzin_foto`` the only miss: the bake-off's parity
line, and the one receipt whose own printed totals are shuffled.

    .venv/Scripts/python scripts/small_brain_gate.py                 # both arms
    .venv/Scripts/python scripts/small_brain_gate.py --with-image
    .venv/Scripts/python scripts/small_brain_gate.py --if-installed

``--if-installed`` is the form .hybrid/checks.json runs: a clone without the
2.1 GB model prints SKIP and exits 0 (PLAN run-2 R10), so the gate sits in the
smoke list next to the checks that always run. The brain's address is config's,
so ``SMALL_BRAIN_BASE_URL`` points the gate at any port — no flag of its own,
and one resolver for the backend (PLAN run-2 R1).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # direct `python scripts/small_brain_gate.py`
    sys.path.insert(0, str(ROOT))

from app import config, validator  # noqa: E402
from app.structurer import Structurer, StructurerError, UnreadableError  # noqa: E402

STAGE1_LOG = config.ROOT / "spike" / "bench_paddle.json"
FIXTURE_DIR = config.ROOT / "fixtures"
INSTALLER = "scripts\\install_small_brain.ps1"
# Brief 9.1 / 9.3, verbatim: 6/6 schema-valid, 5/6 validator-ok, and the only
# miss is the photographed fuel receipt.
NEED_SCHEMA = 6
NEED_VALID = 5
ALLOWED_MISS = "fis_benzin_foto"
WITH_IMAGE = "with-image"
NO_IMAGE = "no-image"
ARMS = (WITH_IMAGE, NO_IMAGE)
DETAIL_W = 60


class GateError(RuntimeError):
    """The corpus or its recording is missing; its message is the report."""


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


def stage1_texts() -> dict[str, str]:
    """fixture -> the stage-1 text the spike actually recorded for it."""
    try:
        rows = json.loads(STAGE1_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{_name(STAGE1_LOG)} unreadable: {exc}") from exc
    return {str(row.get("fixture")): str(row.get("raw") or "") for row in rows}


def fixture_names() -> list[str]:
    """The committed fixture corpus, in table order."""
    names = sorted(path.stem for path in FIXTURE_DIR.glob("*.png"))
    if not names:
        raise GateError(f"no fixture images in {_name(FIXTURE_DIR)}")
    return names


def _ask(arm: str, brain: Structurer, fixture: str, texts: dict[str, str]) -> dict:
    """One fixture through one arm: the row is printed here, as it happens."""
    text = texts.get(fixture)
    if not text:
        raise GateError(f"{fixture} has no recorded stage-1 text in {_name(STAGE1_LOG)}")
    image = (FIXTURE_DIR / f"{fixture}.png").read_bytes()
    try:
        answer = brain.structure(text, image)
    except UnreadableError as exc:
        return _row(arm, fixture, False, "unreadable", _brief(exc))
    except StructurerError as exc:
        return _row(arm, fixture, False, "error", _brief(exc))
    check = validator.validate(answer)
    fields = list(check["fields"])
    verdict = str(check["verdict"])
    detail = ", ".join(fields) if fields else f"{answer['ms']} ms"
    return _row(arm, fixture, True, verdict, detail)


def _row(arm: str, fixture: str, schema_ok: bool, verdict: str, detail: str) -> dict:
    _log(f"{arm:<10} {fixture:<20} {'yes' if schema_ok else 'no':<6} {verdict:<11} {detail}")
    return {"arm": arm, "fixture": fixture, "schema": schema_ok, "verdict": verdict}


def run_arm(arm: str, names: list[str], texts: dict[str, str]) -> list[dict]:
    """One arm over the whole corpus, the flag set for the client it builds."""
    previous = os.environ.get("STRUCTURER_INCLUDE_IMAGE")
    os.environ["STRUCTURER_INCLUDE_IMAGE"] = "1" if arm == WITH_IMAGE else "0"
    try:
        # Built inside the window: STRUCTURER_INCLUDE_IMAGE is read per client,
        # which is what lets both arms run in one process before the cutover.
        brain = Structurer(backend="small")
        return [_ask(arm, brain, name, texts) for name in names]
    finally:
        if previous is None:
            os.environ.pop("STRUCTURER_INCLUDE_IMAGE", None)
        else:
            os.environ["STRUCTURER_INCLUDE_IMAGE"] = previous


def _gate_line(arm: str, label: str, got: str, want: str, ok: bool, note: str) -> bool:
    _log(
        f"{arm:<10} {label:<13} {got:<6} need {want:<12} "
        f"{'PASS' if ok else 'FAIL'}  {'' if ok else note}".rstrip()
    )
    return ok


def summarize(arm: str, rows: list[dict]) -> bool:
    """The two gates of one arm, scored over the rows it printed."""
    total = len(rows)
    schema = sum(1 for row in rows if row["schema"])
    ok = sum(1 for row in rows if row["verdict"] == "ok")
    unreadable = [row["fixture"] for row in rows if not row["schema"]]
    misses = [row["fixture"] for row in rows if row["verdict"] != "ok"]
    # A miss anywhere but fis_benzin_foto is a regression even at 5/6: the brief
    # names the one fixture the small brain is allowed to misread.
    checks = [
        (
            "schema-valid",
            f"{schema}/{total}",
            f"{NEED_SCHEMA}/{NEED_SCHEMA}",
            schema >= NEED_SCHEMA,
            unreadable,
        ),
        (
            "validator-ok",
            f"{ok}/{total}",
            f"{NEED_VALID}/{NEED_SCHEMA}",
            ok >= NEED_VALID and not [name for name in misses if name != ALLOWED_MISS],
            misses,
        ),
    ]
    passed = True
    for label, got, want, check, named in checks:
        if not named:
            note = "see the rows above"
        else:
            note = "misses: " + ", ".join(named[:3]) + (", …" if len(named) > 3 else "")
        passed &= _gate_line(arm, label, got, want, check, note)
    return passed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Brief section 9 gates 1 and 3: the six fixtures through the "
        "live small brain, with and without the receipt image."
    )
    parser.add_argument(
        "--with-image", action="store_true", help=f"run gate 1 only ({WITH_IMAGE})"
    )
    parser.add_argument(
        "--no-image", action="store_true", help=f"run gate 3 only ({NO_IMAGE})"
    )
    parser.add_argument(
        "--if-installed",
        action="store_true",
        help="print SKIP and exit 0 when the small brain's files are not installed",
    )
    args = parser.parse_args(argv)
    arms = [arm for arm, on in zip(ARMS, (args.with_image, args.no_image)) if on] or list(ARMS)
    if args.if_installed and not config.small_brain_ready():
        _log(
            f"SKIP — small brain not installed ({_name(config.small_brain_dir())} has no "
            f"model files); kurmak için {INSTALLER}"
        )
        return 0
    started = time.perf_counter()
    _log(
        f"small brain gate — {config.small_brain_base_url()} "
        f"({config.small_brain_model()}), {len(arms)} arm(s): {', '.join(arms)}"
    )
    try:
        names, texts = fixture_names(), stage1_texts()
        _log(f"{'arm':<10} {'fixture':<20} {'schema':<6} {'verdict':<11} detail")
        passed = [summarize(arm, run_arm(arm, names, texts)) for arm in arms]
    except GateError as exc:
        _log(f"SMALL BRAIN GATE FAILED — {exc}")
        return 1
    except Exception as exc:  # a gate reports, it does not dump a traceback
        _log(f"SMALL BRAIN GATE FAILED — {type(exc).__name__}: {_brief(exc)}")
        return 1
    elapsed = time.perf_counter() - started
    failed = [arm for arm, ok in zip(arms, passed) if not ok]
    if failed:
        _log(f"SMALL BRAIN GATE FAILED — {', '.join(failed)} regressed in {elapsed:.0f}s")
        return 1
    _log(f"SMALL BRAIN GATE OK — {', '.join(arms)} in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        # the rows and reasons carry Turkish; a cp1252 console would kill the print
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
