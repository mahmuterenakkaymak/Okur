"""Stage 1 → 2 → 3 orchestration: one image in, a contract-valid bundle out.

Only this module knows the order: OCR text feeds the structurer, the
structurer's result feeds the deterministic validator, and every amount the
job reports is one the validator recomputed from items[] — the model's own
totals survive only as the "actual" side of the comparison. A receipt that
cannot be read short-circuits to an empty result, which the validator reports
as unreadable, so a job never carries a hole where a view or export expects a
whole object.
"""
from __future__ import annotations

import math
import time
from typing import Any

from app import config, contract, validator
from app.ocr_client import OcrClient, OcrError
from app.structurer import UnreadableError

# The reason shows up inline in the PWA's warning line and as a chip in the
# admin detail, so a model's whole complaint never runs past either.
REASON_MAX_CHARS = 160


def run(
    image_bytes: bytes,
    *,
    quality_mode: bool = False,
    worker: str = "",
    ocr: Any | None = None,
    structurer: Any | None = None,
) -> dict[str, Any]:
    """Run the three stages over one image.

    Returns ``{"result", "validation", "meta", "error"}`` — the three contract
    blocks plus a one-line reason, empty on the normal path, for the queue
    row's error column. Never raises for a bad photo or a sick model server.
    """
    ocr = OcrClient() if ocr is None else ocr
    structurer = _default_structurer(quality_mode) if structurer is None else structurer
    started = time.perf_counter()
    # meta.stage_ms: a stage that answered reports its own ms; a stage that died
    # and the validator that always runs are timed on this module's clock (below),
    # because the contract reads a 0 as "this stage never ran". total_ms stays
    # the whole-run number either way.
    stages = {"ocr": 0, "structure": 0, "validate": 0}
    # meta.ocr_ms stays the client's own report — one a stage that never answered
    # does not have — while the breakdown asks a different question: did it run?
    ocr_ms = 0
    stage_started = time.perf_counter()
    try:
        seen = ocr.transcribe(image_bytes, quality_mode=quality_mode)
    except OcrError as exc:
        # A stage 1 that raised has no self-report, and its wait is the whole
        # OCR_TIMEOUT_S: timing it here is what stops "Okuma —" — contract 13's
        # "this stage never ran" — from painting the failed row an operator opens
        # to find out what died as a job that never started.
        stages["ocr"] = _wait_ms(stage_started)
        return _bundle(
            worker, stages, started, quality_mode, _line(1, exc), ocr_ms=ocr_ms
        )
    stages["ocr"] = ocr_ms = _ms(seen.get("ms"))

    # ASSUMPTION: UnreadableError is the model's own verdict on the receipt, so
    # the job completes done with that verdict and the reason in okunamayan;
    # any other stage-2 failure (dead server, timeout) is an outage, so it stays
    # a failed job with the reason in the error column.
    # A stage 2 that raises leaves nothing behind to report its own ms, so its
    # wait is timed here: the row ops review is the unreadable or timed-out
    # receipt, and "Yapılandırma —" on a stage that ate the whole timeout is a
    # lie about a stage that ran for 31 seconds.
    stage_started = time.perf_counter()
    try:
        structured = structurer.structure(str(seen.get("text") or ""), image_bytes)
    except UnreadableError as exc:
        stages["structure"] = _wait_ms(stage_started)
        return _bundle(
            worker,
            stages,
            started,
            quality_mode,
            "",
            contract.Result(okunamayan=[_reason(exc)]),
            ocr_ms=ocr_ms,
        )
    except Exception as exc:
        stages["structure"] = _wait_ms(stage_started)
        return _bundle(
            worker, stages, started, quality_mode, _line(2, exc), ocr_ms=ocr_ms
        )
    # An answered stage 2 keeps its own report — the HTTP call is the stage, and
    # that clock saw the network the pipeline's never saw.
    stages["structure"] = _ms(
        structured.get("ms") if isinstance(structured, dict) else None
    )

    # Parsing through the contract is what keeps arithmetic out of the model's
    # hands: it keeps only result fields, so a smuggled validation block or
    # verdict in the model payload never reaches the job.
    result = contract.Result.parse(structured if isinstance(structured, dict) else {})
    return _bundle(worker, stages, started, quality_mode, "", result, ocr_ms=ocr_ms)


def _default_structurer(quality_mode: bool) -> Any:
    # ASSUMPTION: stage 2 owns quality-mode routing (its structure() takes only
    # the OCR text and image), so the mode is a construction concern. Imported
    # lazily so injected clients never depend on that module.
    from app.structurer import Structurer

    return Structurer(quality_mode=quality_mode)


def _bundle(
    worker: str,
    stages: dict[str, int],
    started: float,
    quality_mode: bool,
    error: str,
    result: contract.Result | None = None,
    ocr_ms: int = 0,
) -> dict[str, Any]:
    result = contract.Result() if result is None else result
    clock = time.perf_counter()
    validation = validator.validate(result)
    # Stage 3 is timed here because it is the one stage no one else times, and
    # its work is sub-millisecond: truncated to an int it was always 0, which is
    # contract 13's "never ran" — on the one stage every receipt goes through.
    # ASSUMPTION: a run that died in stage 1 or 2 validated nothing but an empty
    # result, so it keeps reporting no stage 3 and its breakdown names the stage
    # that actually died.
    if not error:
        stages["validate"] = _wait_ms(clock)
    meta = contract.JobMeta(
        worker=worker,
        ocr_ms=ocr_ms,
        total_ms=int((time.perf_counter() - started) * 1000),
        model=config.stage2_model(quality_mode),
        quality_mode=quality_mode,
        stage_ms=stages,
    )
    return {
        "result": result.model_dump(),
        "validation": validation,
        "meta": meta.model_dump(),
        "error": error,
    }


def _line(stage: int, exc: BaseException) -> str:
    """One stage's failure line for the queue row's error column.

    Bounded like every other reason: the worker's detail route hands this
    column straight to the phone, so a pydantic dump of the model's whole
    payload or a WinError's text never runs past the warning line.
    """
    return _reason(f"stage {stage}: {exc}")


def _reason(exc: BaseException | str) -> str:
    """One short line for a screen from a model's or a stage's complaint."""
    text = " ".join(str(exc).split())
    return text if len(text) <= REASON_MAX_CHARS else text[: REASON_MAX_CHARS - 1].rstrip() + "…"


def _wait_ms(started: float) -> int:
    """Whole milliseconds this clock waited since ``started``, never 0.

    Rounded up rather than truncated: a stage that ran is never the contract's
    0, however short the wait was.
    """
    return max(1, math.ceil((time.perf_counter() - started) * 1000))


def _ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
