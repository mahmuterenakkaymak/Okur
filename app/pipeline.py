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

    try:
        seen = ocr.transcribe(image_bytes, quality_mode=quality_mode)
    except OcrError as exc:
        return _bundle(worker, 0, started, quality_mode, f"stage 1: {exc}")
    ocr_ms = _ms(seen.get("ms"))

    # ASSUMPTION: stage 2 reports unusable output with its own UnreadableError;
    # any other stage-2 failure (dead server, timeout) means the same thing
    # here — no result — so both take the unreadable path with the reason kept.
    try:
        structured = structurer.structure(str(seen.get("text") or ""), image_bytes)
    except Exception as exc:
        return _bundle(worker, ocr_ms, started, quality_mode, f"stage 2: {exc}")

    # Parsing through the contract is what keeps arithmetic out of the model's
    # hands: it keeps only result fields, so a smuggled validation block or
    # verdict in the model payload never reaches the job.
    result = contract.Result.parse(structured if isinstance(structured, dict) else {})
    return _bundle(worker, ocr_ms, started, quality_mode, "", result)


def _default_structurer(quality_mode: bool) -> Any:
    # ASSUMPTION: stage 2 owns quality-mode routing (its structure() takes only
    # the OCR text and image), so the mode is a construction concern. Imported
    # lazily so injected clients never depend on that module.
    from app.structurer import Structurer

    return Structurer(quality_mode=quality_mode)


def _bundle(
    worker: str,
    ocr_ms: int,
    started: float,
    quality_mode: bool,
    error: str,
    result: contract.Result | None = None,
) -> dict[str, Any]:
    result = contract.Result() if result is None else result
    meta = contract.JobMeta(
        worker=worker,
        ocr_ms=ocr_ms,
        total_ms=int((time.perf_counter() - started) * 1000),
        model=config.unsloth_model() if quality_mode else config.strata_model(),
        quality_mode=quality_mode,
    )
    return {
        "result": result.model_dump(),
        "validation": validator.validate(result),
        "meta": meta.model_dump(),
        "error": error,
    }


def _ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
