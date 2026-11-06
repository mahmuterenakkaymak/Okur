"""A stage's failure line is one bounded line (T96).

The queue row's error column rides to two screens: the admin detail's chip and,
since T79, the worker's own detail route, where the PWA paints it into the
failed-state line. So a pydantic ValidationError that dumps the model's whole
payload, or an OcrError carrying WinError text, has to arrive as the same one
short line pipeline's REASON_MAX_CHARS promises — on stage 1 as well as stage 2.
"""
from __future__ import annotations

from pydantic import ValidationError

from app import contract, pipeline
from app.ocr_client import OcrError
from app.structurer import NOT_INSTALLED, StructurerError

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"


class SahteOcr:
    """Stage 1 as a stub; the failure under test is someone else's."""

    def __init__(self, exc=None):
        self.exc = exc

    def transcribe(self, image_bytes, quality_mode=False):
        if self.exc:
            raise self.exc
        return {"text": "<fcel>BILGIN MARKETLER<nl>", "ms": 1200}


class SahteStructurer:
    def __init__(self, exc):
        self.exc = exc

    def structure(self, ocr_text, image_bytes):
        raise self.exc


def hat(stage: int, exc: BaseException) -> str:
    bundle = pipeline.run(
        IMAGE,
        ocr=SahteOcr(exc if stage == 1 else None),
        structurer=SahteStructurer(exc if stage == 2 else None),
        worker="ayse",
    )
    return bundle["error"]


def model_gerisi() -> ValidationError:
    """What stage 2 raises when the model answers with a payload of plain lines."""
    payload = {"items": [f"okunamayan_{i}" for i in range(60)]}
    try:
        contract.Result.model_validate(payload)
    except ValidationError as exc:
        assert len(str(exc)) > pipeline.REASON_MAX_CHARS * 3, "a payload worth truncating"
        return exc
    raise AssertionError("the model's payload was expected to fail the contract")


# --- both stages, same bound ---


def test_a_stage_1_outage_line_is_one_short_line():
    exc = OcrError("[WinError 1225] Uzak bilgisayar sunucuya yanıt vermiyor\n" + "ayrıntı " * 200)
    line = hat(1, exc)
    assert line.startswith("stage 1: ")
    assert len(line) <= pipeline.REASON_MAX_CHARS
    assert "\n" not in line


def test_a_stage_2_crash_line_is_one_short_line():
    line = hat(2, model_gerisi())
    assert line.startswith("stage 2: ")
    assert len(line) <= pipeline.REASON_MAX_CHARS
    assert line.endswith("…"), "a cut line says so"
    assert "\n" not in line


def test_a_short_reason_is_handed_over_whole():
    exc = StructurerError("structuring server unreachable: [WinError 10061] connection refused")
    assert hat(2, exc) == f"stage 2: {exc}"


def test_the_installer_sentence_still_rides_the_row():
    """The one sentence the worker acts on must survive the bound intact."""
    assert hat(2, StructurerError(NOT_INSTALLED)) == f"stage 2: {NOT_INSTALLED}"
