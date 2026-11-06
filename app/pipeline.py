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
    # meta.stage_ms: stage 1 and 2 report their own ms, stage 3 gets this
    # module's clock (below), and total_ms stays the whole-run number.
    stages = {"ocr": 0, "structure": 0, "validate": 0}

    try:
        seen = ocr.transcribe(image_bytes, quality_mode=quality_mode)
    except OcrError as exc:
        return _bundle(worker, stages, started, quality_mode, _line(1, exc))
    stages["ocr"] = _ms(seen.get("ms"))

    # ASSUMPTION: UnreadableError is the model's own verdict on the receipt, so
    # the job completes done with that verdict and the reason in okunamayan;
    # any other stage-2 failure (dead server, timeout) is an outage, so it stays
    # a failed job with the reason in the error column.
    try:
        structured = structurer.structure(str(seen.get("text") or ""), image_bytes)
    except UnreadableError as exc:
        return _bundle(
            worker,
            stages,
            started,
            quality_mode,
            "",
            contract.Result(okunamayan=[_reason(exc)]),
        )
    except Exception as exc:
        return _bundle(worker, stages, started, quality_mode, _line(2, exc))
    # Stage 2 times itself — the HTTP call is the stage — and a stage that died
    # on the way reported no ms, so it reads 0 rather than the whole run.
    stages["structure"] = _ms(
        structured.get("ms") if isinstance(structured, dict) else None
    )

    # Parsing through the contract is what keeps arithmetic out of the model's
    # hands: it keeps only result fields, so a smuggled validation block or
    # verdict in the model payload never reaches the job.
    result = contract.Result.parse(structured if isinstance(structured, dict) else {})
    return _bundle(worker, stages, started, quality_mode, "", result)


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
) -> dict[str, Any]:
    result = contract.Result() if result is None else result
    clock = time.perf_counter()
    validation = validator.validate(result)
    # Stage 3 is the validator's own clock: microseconds of arithmetic, but it
    # is the one stage nobody else times, so the breakdown stays honest.
    stages["validate"] = _ms((time.perf_counter() - clock) * 1000)
    meta = contract.JobMeta(
        worker=worker,
        ocr_ms=stages["ocr"],
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


def _ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
