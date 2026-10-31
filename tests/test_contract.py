import pytest
from pydantic import ValidationError

from app import contract

MARKET = {
    "header": {
        "isim": "BILGIN MARKETLER ANONIM SIRKETI",
        "vergi_dairesi": "KIZILAY",
        "vergi_no": "1234567890",
    },
    "meta": {"tarih": "28.10.2026", "saat": "14:32", "no": "A2-998877", "tip": "gider"},
    "items": [
        {"ad": "Tam buğday ekmeği", "miktar": 2, "birim_fiyat": 15.0, "toplam": 30.0},
        {"ad": "Süt %3,5 yağ 1L", "miktar": 3, "birim_fiyat": 42.5, "toplam": 127.5},
    ],
    "totals": {
        "ara_toplam": 1046.4,
        "iskonto": 52.32,
        "kdv": 198.82,
        "kdv_orani": 0.2,
        "toplam": 1192.9,
    },
    "para_birimi": "TRY",
}


def test_empty_dict_gets_house_defaults():
    result = contract.Result.parse({})
    assert result.header.isim == ""
    assert result.header.vergi_no == ""
    assert result.meta.tarih == ""
    assert result.meta.tip == ""
    assert result.items == []
    assert result.totals.ara_toplam == 0.0
    assert result.totals.iskonto == 0.0
    assert result.totals.kdv == 0.0
    assert result.totals.kdv_orani == 0.0
    assert result.totals.toplam == 0.0
    assert result.para_birimi == "TRY"
    assert result.okunamayan == []


def test_none_is_the_same_as_missing():
    result = contract.Result.parse(
        {"header": None, "meta": None, "items": None, "totals": None, "para_birimi": None, "okunamayan": None}
    )
    assert result.header.isim == ""
    assert result.meta.saat == ""
    assert result.items == []
    assert result.totals.toplam == 0.0
    assert result.para_birimi == "TRY"
    assert result.okunamayan == []


def test_fixture_shape_parses_whole():
    result = contract.Result.parse(MARKET)
    assert result.header.isim == "BILGIN MARKETLER ANONIM SIRKETI"
    assert result.meta.no == "A2-998877"
    assert len(result.items) == 2
    assert result.items[1].miktar == 3.0
    assert result.items[1].birim_fiyat == 42.5
    assert result.totals.ara_toplam == 1046.4
    assert result.totals.kdv_orani == 0.2
    assert result.okunamayan == []


def test_partial_item_fills_number_defaults():
    item = contract.Item.parse({"ad": "Süt"})
    assert item.miktar == 0.0
    assert item.birim_fiyat == 0.0
    assert item.toplam == 0.0


def test_turkish_amount_forms_reach_floats():
    totals = contract.Totals.parse(
        {"ara_toplam": "1.046,40", "iskonto": "52,32-", "kdv": "198.82 TL", "kdv_orani": "KDV %20X", "toplam": "1.192,90"}
    )
    assert totals.ara_toplam == 1046.40
    assert totals.iskonto == -52.32
    assert totals.kdv == 198.82
    assert totals.kdv_orani == 0.2
    assert totals.toplam == 1192.90


def test_unreadable_amount_is_zero_never_none_or_nan():
    item = contract.Item.parse({"ad": "Zeytinyağı", "miktar": "bir", "birim_fiyat": "", "toplam": None})
    assert item.miktar == 0.0
    assert item.birim_fiyat == 0.0
    assert item.toplam == 0.0


def test_numeric_text_fields_become_strings():
    header = contract.Header.parse({"isim": None, "vergi_no": 1234567890})
    assert header.isim == ""
    assert header.vergi_no == "1234567890"


def test_okunamayan_keeps_text():
    result = contract.Result.parse({"okunamayan": ["KDV ?", None, 20]})
    assert result.okunamayan == ["KDV ?", "", "20"]


def test_wrong_shape_still_raises():
    with pytest.raises(ValidationError):
        contract.Result.parse({"items": "ad, miktar"})
    with pytest.raises(ValidationError):
        contract.Result.parse({"totals": 5})


def test_validation_defaults_and_forms():
    validation = contract.Validation.parse({"verdict": "MISMATCH", "fields": ["items[2].toplam", "totals.kdv"]})
    assert validation.verdict == "mismatch"
    assert validation.fields == ["items[2].toplam", "totals.kdv"]
    assert validation.expected.toplam == 0.0
    assert validation.actual.kdv == 0.0


def test_validation_without_verdict_is_not_ok():
    assert contract.Validation.parse({}).verdict == "unreadable"


def test_unknown_verdict_raises():
    with pytest.raises(ValidationError):
        contract.Validation.parse({"verdict": "tamam"})


def test_envelope_defaults():
    job = contract.JobEnvelope.parse({})
    assert job.job_id == ""
    assert job.status == "queued"
    assert job.client_ref is None
    assert job.result is None
    assert job.validation is None
    assert job.meta.worker == ""
    assert job.meta.captured_at is None
    assert job.meta.received_at == ""
    assert job.meta.ocr_ms == 0
    assert job.meta.total_ms == 0
    assert job.meta.model == ""
    assert job.meta.quality_mode is False


def test_envelope_carries_result_and_validation():
    job = contract.JobEnvelope.parse(
        {
            "job_id": "6f6a1c2e-0000-4000-8000-000000000001",
            "status": "DONE",
            "client_ref": "fis-0042",
            "result": MARKET,
            "validation": {"verdict": "ok", "expected": {"toplam": 1192.9}, "actual": {"toplam": "1.192,90"}},
            "meta": {"worker": "kasa-3", "received_at": "2026-10-31T09:15:00", "ocr_ms": 2400, "model": "strata"},
        }
    )
    assert job.status == "done"
    assert job.client_ref == "fis-0042"
    assert job.result.totals.ara_toplam == 1046.4
    assert job.validation.verdict == "ok"
    assert job.validation.expected.toplam == 1192.9
    assert job.validation.actual.toplam == 1192.9
    assert job.validation.fields == []
    assert job.meta.worker == "kasa-3"
    assert job.meta.ocr_ms == 2400
    assert job.meta.total_ms == 0
    assert job.meta.quality_mode is False


def test_envelope_null_result_stays_null_until_done():
    job = contract.JobEnvelope.parse({"job_id": "x", "status": "running", "result": None, "validation": None})
    assert job.result is None
    assert job.validation is None


def test_quality_mode_flag():
    assert contract.JobMeta.parse({"quality_mode": "true"}).quality_mode is True
    assert contract.JobMeta.parse({"quality_mode": None}).quality_mode is False


def test_dump_reparses_unchanged():
    job = contract.JobEnvelope.parse(
        {"job_id": "x", "status": "done", "result": MARKET, "validation": {"verdict": "ok"}, "meta": {"ocr_ms": 1}}
    )
    dumped = job.model_dump(mode="json")
    assert contract.JobEnvelope.parse(dumped) == job
    assert dumped["result"]["para_birimi"] == "TRY"
    assert dumped["client_ref"] is None
