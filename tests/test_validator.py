"""T05: the validator recomputes receipt arithmetic and names offending fields."""
import copy
import json

import pytest

from app import config, contract, validator

ROOT = config.ROOT
FIXTURES = sorted((ROOT / "fixtures").glob("*.json"))


@pytest.fixture()
def market() -> dict:
    path = ROOT / "fixtures" / "fis_market_clean.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_ground_truth_fixtures_validate_ok(fixture):
    report = validator.validate(json.loads(fixture.read_text(encoding="utf-8")))
    assert report["verdict"] == "ok", report["fields"]
    assert report["fields"] == []


def test_ok_report_carries_expected_and_actual_blocks(market):
    report = validator.validate(market)
    assert report["verdict"] == "ok"
    assert report["expected"] == {
        "ara_toplam": 1046.4,
        "iskonto": 52.32,
        "kdv": 198.82,
        "toplam": 1192.9,
    }
    assert report["actual"] == report["expected"]


def test_tampered_line_total_names_the_item(market):
    market["items"][2]["toplam"] = 385.0
    report = validator.validate(market)
    assert report["verdict"] == "mismatch"
    assert report["fields"] == ["items[2].toplam"]
    # ara toplam is recomputed from miktar x birim_fiyat, so it stays clean.
    assert report["expected"]["ara_toplam"] == 1046.4


def test_tampered_kdv_names_totals_kdv(market):
    market["totals"]["kdv"] = 250.0
    report = validator.validate(market)
    assert report["fields"] == ["totals.kdv"]
    assert report["expected"]["kdv"] == 198.82
    assert report["actual"]["kdv"] == 250.0


def test_tampered_grand_total_names_totals_toplam(market):
    market["totals"]["toplam"] = 1200.0
    report = validator.validate(market)
    assert report["fields"] == ["totals.toplam"]
    assert report["expected"]["toplam"] == 1192.9
    assert report["actual"]["toplam"] == 1200.0


def test_tampered_ara_toplam_names_only_totals_ara_toplam(market):
    market["totals"]["ara_toplam"] = 1146.4
    report = validator.validate(market)
    assert report["fields"] == ["totals.ara_toplam"]


def test_kurus_drift_within_tolerance_stays_ok(market):
    market["items"][0]["toplam"] = 30.01
    market["totals"]["kdv"] = 198.81
    assert validator.validate(market)["verdict"] == "ok"


def test_drift_beyond_tolerance_is_mismatch(market):
    market["items"][0]["toplam"] = 30.02
    report = validator.validate(market)
    assert report["fields"] == ["items[0].toplam"]


def test_accepts_contract_model(market):
    assert validator.validate(contract.Result.parse(market)) == validator.validate(market)


def test_missing_totals_fall_back_to_house_defaults():
    partial = {"items": [{"ad": "Su", "miktar": 2, "birim_fiyat": 15.0, "toplam": 30.0}]}
    report = validator.validate(partial)
    assert report["verdict"] == "mismatch"
    assert report["fields"] == ["totals.ara_toplam", "totals.toplam"]


def test_input_is_not_mutated(market):
    before = copy.deepcopy(market)
    validator.validate(market)
    assert market == before


def test_report_is_json_serializable(market):
    json.dumps(validator.validate(market))
