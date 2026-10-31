"""A receipt the model could not structure is a verdict, not an outage.

Stage 2's UnreadableError used to be folded into the bundle's error, and the
queue worker fails any job whose error is non-empty — so the unreadable verdict,
the PWA's one-tap re-shoot and the integrator's reason all died before the row
was written. These tests follow one unreadable receipt from stage 2 to the job.
"""
import functools
import json

import pytest

from app import config, contract, db, pipeline
from app.queue_worker import QueueWorker
from app.structurer import StructurerError, UnreadableError

IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<table>BILGIN MARKETLER<ecel>"
REASON = "model output has none of the contract fields"


class FakeOcr:
    def transcribe(self, image_bytes, quality_mode=False):
        return {"text": OCR_TEXT, "ms": 1234}


class RaisingStructurer:
    def __init__(self, error):
        self.error = error

    def structure(self, ocr_text, image_bytes):
        raise self.error


def run(error=None, **kwargs):
    return pipeline.run(
        IMAGE,
        ocr=FakeOcr(),
        structurer=RaisingStructurer(UnreadableError(REASON) if error is None else error),
        **kwargs,
    )


# --- the pipeline: unreadable is a verdict, an outage is a failure ---


def test_unreadable_output_leaves_the_error_column_empty():
    bundle = run()
    assert bundle["error"] == ""
    assert bundle["validation"]["verdict"] == "unreadable"
    assert bundle["validation"]["fields"] == []


def test_unreadable_reason_rides_in_okunamayan():
    assert run()["result"]["okunamayan"] == [REASON]


def test_unreadable_result_is_still_a_whole_contract_object():
    bundle = run()
    envelope = contract.JobEnvelope.parse({**bundle, "job_id": "j-1", "status": "done"})
    assert envelope.result.items == []
    assert envelope.result.totals.toplam == 0.0
    assert envelope.validation.verdict == "unreadable"


def test_unreadable_keeps_ocr_ms_and_the_mode_it_ran_in():
    bundle = run(quality_mode=True)
    assert bundle["meta"]["ocr_ms"] == 1234
    assert bundle["meta"]["quality_mode"] is True
    assert bundle["meta"]["model"] == config.unsloth_model()


def test_a_long_multiline_reason_collapses_to_one_short_line():
    noisy = UnreadableError("model output is not contract-valid: " + "items\n 0 toplam\n" * 40)
    (reason,) = run(error=noisy)["result"]["okunamayan"]
    assert reason.startswith("model output is not contract-valid:")
    assert "\n" not in reason and "  " not in reason
    assert len(reason) <= pipeline.REASON_MAX_CHARS
    assert reason.endswith("…")


@pytest.mark.parametrize(
    "error",
    [
        StructurerError("structuring server returned HTTP 502"),
        TimeoutError("strata slow"),
        ConnectionError("connection refused"),
    ],
)
def test_every_other_stage2_failure_stays_a_reasoned_failure(error):
    bundle = run(error=error)
    assert bundle["error"].startswith("stage 2:")
    assert str(error) in bundle["error"]
    assert bundle["result"]["okunamayan"] == []


# --- the queue: the verdict reaches the job row ---


@pytest.fixture
def env(tmp_path):
    image = tmp_path / "fis.jpg"
    image.write_bytes(IMAGE)
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    yield path, conn, str(image)
    conn.close()


def process(env, error):
    path, conn, image = env
    job = db.create_job(conn, image_path=image, worker="ayse")
    runner = functools.partial(
        pipeline.run, ocr=FakeOcr(), structurer=RaisingStructurer(error)
    )
    QueueWorker(path, runner=runner, poll_interval=0.01).run_once()
    return db.get_job(conn, job["id"])


def test_unreadable_job_finishes_done_with_its_verdict(env):
    job = process(env, UnreadableError(REASON))
    assert job["status"] == "done"
    assert job["error"] == ""
    assert json.loads(job["validation_json"])["verdict"] == "unreadable"
    assert json.loads(job["result_json"])["okunamayan"] == [REASON]


def test_stage2_outage_job_still_fails(env):
    job = process(env, StructurerError("structuring server unreachable"))
    assert job["status"] == "failed"
    assert "unreachable" in job["error"]
    assert job["result_json"] is None
