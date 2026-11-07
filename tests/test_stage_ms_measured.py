"""T99: a stage that ran never stores 0 ms.

stage_ms's 0 is contract 13's "this stage never ran", and the admin detail reads
it out loud: "Doğrulama —" under a receipt it had just validated, "Yapılandırma —"
under a stage 2 that spent the whole timeout dying. Both are producer bugs, not
display bugs — a sub-millisecond validator truncated to an int is 0, and a stage
2 that raises leaves no self-report behind — so both are fixed where the numbers
are written: the pipeline times a stage 2 that raises on its own clock, and times
the validator itself. The success path keeps the structurer's own ms and total_ms
stays the whole run.
"""
from __future__ import annotations

import io
import json
import pathlib
import time

from PIL import Image

from app import auth, db, pipeline
from app.ocr_client import OcrError
from app.queue_worker import QueueWorker
from app.structurer import StructurerError, UnreadableError

ROOT = pathlib.Path(__file__).resolve().parents[1]
# A real fixture, so the "did the validator get a millisecond" question is asked
# of the work it actually does on a receipt rather than of an empty result.
FIXTURE = json.loads((ROOT / "fixtures" / "fis_benzin_clean.json").read_text("utf-8"))


def jpeg(width: int = 60, height: int = 40) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


IMAGE = jpeg()
WAIT = 0.06  # a stage-2 outage worth reading on a screen: 60 ms, reported ≥ 50


class FakeOcr:
    def __init__(self, ms: int = 900, error: Exception | None = None):
        self.ms, self.error = ms, error

    def transcribe(self, image_bytes, *, quality_mode=False):
        if self.error:
            raise self.error
        return {"text": "Kurşunsuz 95 53,19", "ms": self.ms}


class FakeStructurer:
    """The real stage 2's manners: it reports its own ms, or it raises."""

    def __init__(self, ms: int | None = 2500, sleep: float = 0.0, error: Exception | None = None):
        self.ms, self.sleep, self.error = ms, sleep, error

    def structure(self, ocr_text, image_bytes):
        if self.sleep:
            time.sleep(self.sleep)
        if self.error:
            raise self.error
        return {**FIXTURE, "ms": self.ms}


def run(image_bytes=IMAGE, *, ocr=None, structurer=None, **kwargs):
    return pipeline.run(
        image_bytes,
        ocr=ocr or FakeOcr(),
        structurer=structurer or FakeStructurer(),
        **kwargs,
    )


# --- stage 2: an outage is a stage that ran ----------------------------------


def test_a_stage_two_outage_reports_the_wait_it_cost():
    bundle = run(structurer=FakeStructurer(
        sleep=WAIT, error=StructurerError("structuring timed out after 120s")
    ))
    stages = bundle["meta"]["stage_ms"]

    assert bundle["error"].startswith("stage 2:")
    assert stages["structure"] >= 50  # the timeout it waited out, not "never ran"
    assert bundle["meta"]["total_ms"] >= 50  # total_ms is still the whole run


def test_an_unreadable_verdict_reports_the_wait_it_cost():
    bundle = run(structurer=FakeStructurer(sleep=WAIT, error=UnreadableError("no JSON")))
    stages = bundle["meta"]["stage_ms"]

    # The job finishes done, so this is exactly the row ops review reads: it has
    # to say how long stage 2 took to give up.
    assert bundle["error"] == ""
    assert bundle["validation"]["verdict"] == "unreadable"
    assert stages["ocr"] == 900
    assert stages["structure"] >= 50
    assert stages["validate"] >= 1


# --- stage 3: the validator's own clock, never the contract's 0 --------------


def test_the_validator_of_a_read_receipt_is_never_zero():
    bundle = run(structurer=FakeStructurer(ms=2500))
    stages = bundle["meta"]["stage_ms"]

    assert bundle["validation"]["verdict"] == "ok"
    assert isinstance(stages["validate"], int) and stages["validate"] >= 1
    assert stages["ocr"] == 900


def test_the_success_path_keeps_the_structurers_own_report():
    bundle = run(structurer=FakeStructurer(ms=5, sleep=WAIT))

    # The structurer's clock saw the network the pipeline's never saw.
    assert bundle["meta"]["stage_ms"]["structure"] == 5
    assert bundle["meta"]["total_ms"] >= 50


def test_a_stage_that_never_ran_is_still_the_contracts_zero():
    bundle = run(ocr=FakeOcr(error=OcrError("ocr server unreachable")))

    # Nothing past stage 1 ran, so those two stay the contract's 0: the fix is
    # for stages that ran, not a blanket "always at least one". Stage 1 ran, and
    # tests/test_stage_ms_stage1.py pins the wait it reports.
    assert bundle["error"].startswith("stage 1:")
    stages = bundle["meta"]["stage_ms"]
    assert stages["structure"] == 0
    assert stages["validate"] == 0


# --- so the stored row and the screen underneath it say the same thing -------


def test_a_done_job_stores_a_validator_millisecond(tmp_path):
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, _ = auth.create_key(conn, "ayse")
    image = tmp_path / "fis.jpg"
    image.write_bytes(IMAGE)
    job_id = db.create_job(conn, key_id=key_id, worker="ayse", image_path=str(image))["id"]

    QueueWorker(path, runner=run, poll_interval=0.01).run_once()

    meta = json.loads(db.get_job(conn, job_id)["meta_json"])
    assert db.get_job(conn, job_id)["status"] == "done"
    assert meta["stage_ms"]["validate"] >= 1
    assert meta["stage_ms"] == {"ocr": 900, "structure": 2500, "validate": meta["stage_ms"]["validate"]}
    conn.close()
