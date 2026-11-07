"""T107: a stage 1 that died still reports the wait it cost.

stage_ms's 0 is contract 13's "this stage never ran", and the admin detail reads
it straight out: a job whose OCR spent the whole OCR_TIMEOUT_S dying stored
{ocr: 0, structure: 0, validate: 0}, so the failed row an operator opens to find
out what died was painted "Okuma — · Yapılandırma — · Doğrulama —" — a job that
never started. T99 fixed this for stage 2 by timing the raise on the pipeline's
own clock; this is the same fix for stage 1. A stage that answered keeps its own
self-report, and nothing past stage 1 ran, so those two stay 0.
"""
from __future__ import annotations

import io
import time

from PIL import Image

from app import pipeline
from app.ocr_client import OcrError

IMAGE = io.BytesIO()
Image.new("RGB", (60, 40), (200, 30, 30)).save(IMAGE, "JPEG", quality=90)
IMAGE = IMAGE.getvalue()
WAIT = 0.06  # the cold model load OPERATIONS puts near 90 s, shrunk to 60 ms


class FakeOcr:
    """The real client's manners: it reports its own ms, or it raises after waiting."""

    def __init__(self, ms: int | None = 900, sleep: float = 0.0, error: Exception | None = None):
        self.ms, self.sleep, self.error = ms, sleep, error

    def transcribe(self, image_bytes, *, quality_mode=False):
        if self.sleep:
            time.sleep(self.sleep)
        if self.error:
            raise self.error
        return {"text": "Kurşunsuz 95 53,19", "ms": self.ms}


class FakeStructurer:
    def structure(self, ocr_text, image_bytes):
        raise AssertionError("a job that failed in stage 1 never reaches stage 2")


def run(ocr, **kwargs):
    return pipeline.run(IMAGE, ocr=ocr, structurer=FakeStructurer(), **kwargs)


# --- a stage 1 that raised is a stage that ran ------------------------------


def test_a_stage_one_outage_reports_the_wait_it_cost():
    bundle = run(FakeOcr(sleep=WAIT, error=OcrError("ocr request timed out after 120s")))
    stages = bundle["meta"]["stage_ms"]

    assert bundle["error"].startswith("stage 1:")
    # The timeout it waited out — never the contract's "this stage never ran".
    assert stages["ocr"] >= 50
    assert bundle["meta"]["total_ms"] >= stages["ocr"] - 1  # total_ms covers the wait


def test_a_short_stage_one_failure_is_still_not_zero():
    # The measured wait is rounded up, not truncated: a 50 ms failing read left
    # ocr 0 against total_ms 50, which is the same lie at a smaller scale.
    bundle = run(FakeOcr(sleep=0.0, error=OcrError("ocr server unreachable")))

    assert bundle["meta"]["stage_ms"]["ocr"] >= 1


def test_nothing_past_stage_one_started():
    bundle = run(FakeOcr(sleep=WAIT, error=OcrError("OCR server returned HTTP 503")))
    stages = bundle["meta"]["stage_ms"]

    # The breakdown names the stage that died: structure and validate stay 0.
    assert stages["structure"] == 0
    assert stages["validate"] == 0


def test_ocr_ms_stays_the_clients_own_report():
    # meta.ocr_ms is what the OCR client said about itself, and a client that
    # never answered said nothing; the "did stage 1 run" number is stage_ms.ocr.
    failed = run(FakeOcr(sleep=WAIT, error=OcrError("ocr server unreachable")))
    read = run(FakeOcr(ms=1234, sleep=WAIT))

    assert failed["meta"]["ocr_ms"] == 0
    assert failed["meta"]["stage_ms"]["ocr"] >= 50
    assert read["meta"]["ocr_ms"] == 1234


def test_the_success_path_keeps_the_ocr_clients_own_ms():
    bundle = run(FakeOcr(ms=900, sleep=WAIT))

    # The client's clock saw the network the pipeline's never saw.
    assert bundle["meta"]["stage_ms"]["ocr"] == 900
    assert bundle["meta"]["total_ms"] >= 50
