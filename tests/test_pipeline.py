import copy
import json

import pytest

from app import config, contract, pipeline
from app.ocr_client import OcrError

FIXTURE = config.ROOT / "fixtures" / "fis_market_clean.json"
IMAGE = b"\xff\xd8\xff\xe0fakejpeg"
OCR_TEXT = "<table>BILGIN MARKETLER<ecel>"


class UnreadableError(RuntimeError):
    """Stand-in for stage 2's own signal of unusable model output."""


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeOcr:
    def __init__(self, text=OCR_TEXT, ms=1234, error=None):
        self.text = text
        self.ms = ms
        self.error = error
        self.calls = []

    def transcribe(self, image_bytes, quality_mode=False):
        self.calls.append({"image": image_bytes, "quality_mode": quality_mode})
        if self.error:
            raise self.error
        return {"text": self.text, "ms": self.ms}


class FakeStructurer:
    def __init__(self, result=None, error=None):
        self.result = payload() if result is None else result
        self.error = error
        self.calls = []

    def structure(self, ocr_text, image_bytes):
        self.calls.append({"ocr_text": ocr_text, "image": image_bytes})
        if self.error:
            raise self.error
        out = dict(self.result)
        out["ms"] = 4567
        return out


def run(ocr=None, structurer=None, **kwargs):
    ocr = FakeOcr() if ocr is None else ocr
    structurer = FakeStructurer() if structurer is None else structurer
    return pipeline.run(IMAGE, ocr=ocr, structurer=structurer, **kwargs), ocr, structurer


# --- stage order and wiring ---


def test_runs_stage1_then_stage2_then_stage3():
    order = []

    class Ocr(FakeOcr):
        def transcribe(self, image_bytes, quality_mode=False):
            order.append("ocr")
            return super().transcribe(image_bytes, quality_mode)

    class Structurer(FakeStructurer):
        def structure(self, ocr_text, image_bytes):
            order.append("structure")
            return super().structure(ocr_text, image_bytes)

    bundle, _, _ = run(Ocr(), Structurer())
    assert order == ["ocr", "structure"]
    assert bundle["validation"]["verdict"] == "ok"


def test_structurer_receives_ocr_text_and_image():
    _, _, structurer = run()
    assert structurer.calls == [{"ocr_text": OCR_TEXT, "image": IMAGE}]


def test_bundle_is_a_valid_job_envelope():
    bundle, _, _ = run()
    envelope = contract.JobEnvelope.parse({**bundle, "job_id": "j-1", "status": "done"})
    assert envelope.result.items[0].ad == "Tam buğday ekmeği"
    assert envelope.validation.verdict == "ok"
    assert "error" not in envelope.model_dump()


def test_result_carries_house_defaults_for_absent_fields():
    bundle, _, _ = run(structurer=FakeStructurer(result={"items": [{"ad": "Çay"}]}))
    assert bundle["result"]["header"] == {"isim": "", "vergi_dairesi": "", "vergi_no": ""}
    assert bundle["result"]["para_birimi"] == "TRY"
    assert bundle["result"]["okunamayan"] == []
    assert bundle["result"]["items"][0]["toplam"] == 0.0


# --- timings and meta ---


def test_ocr_ms_comes_from_stage1_and_total_ms_is_measured():
    bundle, _, _ = run()
    assert bundle["meta"]["ocr_ms"] == 1234
    assert isinstance(bundle["meta"]["total_ms"], int)
    assert bundle["meta"]["total_ms"] >= 0


def test_missing_or_rogue_ms_never_breaks_meta():
    bundle, _, _ = run(ocr=FakeOcr(ms=None))
    assert bundle["meta"]["ocr_ms"] == 0


def test_meta_records_strata_model_and_quality_mode_off():
    bundle, ocr, _ = run()
    assert bundle["meta"]["model"] == config.strata_model()
    assert bundle["meta"]["quality_mode"] is False
    assert ocr.calls[0]["quality_mode"] is False


def test_quality_mode_switches_model_name_and_passes_mode_to_stage1():
    bundle, ocr, _ = run(quality_mode=True)
    assert bundle["meta"]["model"] == config.unsloth_model()
    assert bundle["meta"]["quality_mode"] is True
    assert ocr.calls[0]["quality_mode"] is True


def test_worker_label_lands_in_meta():
    bundle, _, _ = run(worker="ayse")
    assert bundle["meta"]["worker"] == "ayse"


# --- arithmetic belongs to the validator ---


def test_ok_receipt_recomputes_the_expected_totals():
    bundle, _, _ = run()
    validation = bundle["validation"]
    assert validation["verdict"] == "ok"
    assert validation["fields"] == []
    assert validation["expected"] == {
        "ara_toplam": 1046.4,
        "iskonto": 52.32,
        "kdv": 198.82,
        "toplam": 1192.9,
    }


def test_model_totals_are_only_the_actual_side_never_the_verdict():
    tampered = payload()
    tampered["totals"]["kdv"] = 999.99
    bundle, _, _ = run(structurer=FakeStructurer(result=tampered))
    validation = bundle["validation"]
    assert validation["verdict"] == "mismatch"
    assert "totals.kdv" in validation["fields"]
    assert validation["actual"]["kdv"] == 999.99
    assert validation["expected"]["kdv"] == 198.82
    # the printed value survives in the result for the discrepancy panel
    assert bundle["result"]["totals"]["kdv"] == 999.99


def test_model_cannot_smuggle_a_verdict_or_validation_block():
    smuggled = payload()
    smuggled["validation"] = {"verdict": "ok", "fields": []}
    smuggled["verdict"] = "ok"
    smuggled["totals"]["toplam"] = 1.0
    bundle, _, _ = run(structurer=FakeStructurer(result=smuggled))
    assert "validation" not in bundle["result"]
    assert "verdict" not in bundle["result"]
    assert bundle["validation"]["verdict"] == "mismatch"
    assert "totals.toplam" in bundle["validation"]["fields"]


def test_printed_amounts_are_normalized_to_floats():
    printed = payload()
    printed["totals"]["ara_toplam"] = "1.046,40"
    printed["totals"]["kdv_orani"] = "%20"
    bundle, _, _ = run(structurer=FakeStructurer(result=printed))
    assert bundle["result"]["totals"]["ara_toplam"] == 1046.4
    assert bundle["validation"]["verdict"] == "ok"


# --- short circuit to unreadable ---


def test_stage1_failure_short_circuits_before_stage2():
    ocr = FakeOcr(error=OcrError("OCR server returned HTTP 503"))
    structurer = FakeStructurer()
    bundle, _, _ = run(ocr=ocr, structurer=structurer)
    assert structurer.calls == []
    assert bundle["validation"]["verdict"] == "unreadable"
    assert bundle["error"].startswith("stage 1:")
    assert "503" in bundle["error"]


def test_stage1_failure_still_returns_a_whole_partial_result():
    bundle, _, _ = run(ocr=FakeOcr(error=OcrError("timeout")))
    assert bundle["result"]["items"] == []
    assert bundle["result"]["header"] == {"isim": "", "vergi_dairesi": "", "vergi_no": ""}
    assert bundle["result"]["totals"] == {
        "ara_toplam": 0.0,
        "iskonto": 0.0,
        "kdv": 0.0,
        "kdv_orani": 0.0,
        "toplam": 0.0,
    }
    assert bundle["result"]["para_birimi"] == "TRY"
    assert bundle["meta"]["ocr_ms"] == 0
    assert bundle["meta"]["total_ms"] >= 0
    assert bundle["meta"]["model"] == config.strata_model()


def test_stage2_unreadable_keeps_ocr_ms_and_reports_unreadable():
    structurer = FakeStructurer(error=UnreadableError("model output not JSON"))
    bundle, _, _ = run(structurer=structurer)
    assert bundle["validation"]["verdict"] == "unreadable"
    assert bundle["meta"]["ocr_ms"] == 1234
    assert bundle["error"].startswith("stage 2:")
    assert "not JSON" in bundle["error"]


@pytest.mark.parametrize(
    "error",
    [UnreadableError("no json"), TimeoutError("strata slow"), ConnectionError("refused")],
)
def test_any_stage2_failure_becomes_unreadable_not_a_crash(error):
    bundle, _, _ = run(structurer=FakeStructurer(error=error))
    assert bundle["validation"]["verdict"] == "unreadable"
    assert bundle["validation"]["fields"] == []


def test_stage2_result_without_items_is_unreadable_not_ok():
    empty = copy.deepcopy(payload())
    empty["items"] = []
    bundle, _, _ = run(structurer=FakeStructurer(result=empty))
    assert bundle["validation"]["verdict"] == "unreadable"
    assert bundle["error"] == ""


def test_unreadable_path_keeps_quality_mode_in_meta():
    bundle, _, _ = run(quality_mode=True, ocr=FakeOcr(error=OcrError("down")))
    assert bundle["meta"]["quality_mode"] is True
    assert bundle["meta"]["model"] == config.unsloth_model()


# --- meta.model names the brain that actually ran (config.stage2_model) ---


def test_meta_names_strata_while_the_default_backend_is_strata(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    bundle, _, _ = run()
    assert bundle["meta"]["model"] == config.strata_model()


def test_meta_names_the_small_brain_on_the_small_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("SMALL_BRAIN_MODEL", "Qwen3-VL-4B-Instruct")
    bundle, _, _ = run()
    assert bundle["meta"]["model"] == config.small_brain_model() == "Qwen3-VL-4B-Instruct"
    assert bundle["meta"]["model"] != config.strata_model()


def test_quality_mode_names_unsloth_even_on_the_small_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    bundle, _, _ = run(quality_mode=True)
    assert bundle["meta"]["model"] == config.unsloth_model()
    assert bundle["meta"]["model"] != config.small_brain_model()
