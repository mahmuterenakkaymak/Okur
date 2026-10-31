"""T06: validator edge cases — mixed KDV rates, currency forms, weight and
zero-quantity lines, signed or missing iskonto, missing totals, empty items."""
import copy
import json

from app import validator


def line_item(ad="Süt %3,5 yağ 1L", miktar=2.0, birim_fiyat=42.5, toplam=85.0):
    return {"ad": ad, "miktar": miktar, "birim_fiyat": birim_fiyat, "toplam": toplam}


# Ekmek is KDV %10 and şarap %20; a mixed receipt has no single kdv_orani, so
# the structurer emits 0 and the printed kdv (3,00 + 40,00) is the chain input.
MIXED_RATE = {
    "items": [
        {"ad": "Ekmek", "miktar": 2, "birim_fiyat": 15.0, "toplam": 30.0},
        {"ad": "Şarap", "miktar": 1, "birim_fiyat": 200.0, "toplam": 200.0},
    ],
    "totals": {
        "ara_toplam": 230.0,
        "iskonto": 0.0,
        "kdv": 43.0,
        "kdv_orani": 0.0,
        "toplam": 273.0,
    },
}


def test_mixed_kdv_rate_receipt_validates_ok():
    report = validator.validate(copy.deepcopy(MIXED_RATE))
    assert report["verdict"] == "ok", report["fields"]
    assert report["fields"] == []


def test_mixed_kdv_rate_tampered_toplam_names_totals_toplam():
    data = copy.deepcopy(MIXED_RATE)
    data["totals"]["toplam"] = 280.0
    report = validator.validate(data)
    assert report["fields"] == ["totals.toplam"]
    assert report["expected"]["toplam"] == 273.0


def test_mixed_kdv_rate_tampered_line_total_names_the_item():
    data = copy.deepcopy(MIXED_RATE)
    data["items"][0]["toplam"] = 35.0
    report = validator.validate(data)
    assert report["fields"] == ["items[0].toplam"]


def test_currency_forms_tl_and_lira_sign():
    data = {
        "items": [
            {"ad": "Zeytinyağı 1L", "miktar": "2", "birim_fiyat": "523,20 TL", "toplam": "1.046,40 TL"}
        ],
        "totals": {
            "ara_toplam": "1.046,40 TL",
            "iskonto": "₺52,32",
            "kdv": "198,82 TL",
            "kdv_orani": "%20",
            "toplam": "₺1.192,90",
        },
    }
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    assert report["expected"] == {
        "ara_toplam": 1046.4,
        "iskonto": 52.32,
        "kdv": 198.82,
        "toplam": 1192.9,
    }


def test_zero_quantity_line_adds_nothing():
    data = {
        "items": [line_item(), line_item(ad="Promosyon", miktar=0, birim_fiyat=25.0, toplam=0.0)],
        "totals": {"ara_toplam": 85.0, "kdv": 17.0, "kdv_orani": 0.2, "toplam": 102.0},
    }
    assert validator.validate(data)["verdict"] == "ok"


def test_zero_quantity_with_nonzero_line_total_names_the_item():
    data = {
        "items": [line_item(), line_item(ad="Promosyon", miktar=0, birim_fiyat=25.0, toplam=25.0)],
        "totals": {"ara_toplam": 85.0, "kdv": 17.0, "kdv_orani": 0.2, "toplam": 102.0},
    }
    report = validator.validate(data)
    assert report["fields"] == ["items[1].toplam"]


def test_kg_line_three_decimal_product_rounds_to_kurus():
    data = {
        "items": [{"ad": "Dana kıyma", "miktar": "1,033", "birim_fiyat": "99,00", "toplam": "102,27"}],
        "totals": {"ara_toplam": "102,27", "kdv": "20,45", "kdv_orani": "%20", "toplam": "122,72"},
    }
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    # ara toplam keeps the printed kurus line total, not the raw 102,267 product.
    assert report["expected"]["ara_toplam"] == 102.27


def test_negative_iskonto_reduces_the_base_by_its_magnitude():
    data = {
        "items": [line_item()],
        "totals": {
            "ara_toplam": "85,00",
            "iskonto": "-17,00",
            "kdv": "13,60",
            "kdv_orani": "%20",
            "toplam": "81,60",
        },
    }
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    assert report["expected"]["iskonto"] == 17.0
    assert report["actual"]["iskonto"] == -17.0


def test_missing_iskonto_defaults_to_zero():
    data = {
        "items": [line_item()],
        "totals": {"ara_toplam": 85.0, "kdv": 17.0, "kdv_orani": 0.2, "toplam": 102.0},
    }
    report = validator.validate(data)
    assert report["verdict"] == "ok"
    assert report["expected"]["iskonto"] == 0.0


def test_missing_totals_block_is_mismatch_not_crash():
    report = validator.validate({"items": [line_item()]})
    assert report["verdict"] == "mismatch"
    assert report["fields"] == ["totals.ara_toplam", "totals.toplam"]


def test_empty_items_is_unreadable_not_vacuous_ok():
    report = validator.validate({"items": [], "totals": {}})
    assert report["verdict"] == "unreadable"
    assert report["fields"] == []
    assert validator.validate({})["verdict"] == "unreadable"
    json.dumps(report)


def test_empty_items_with_printed_totals_stays_unreadable():
    data = {
        "items": [],
        "totals": {"ara_toplam": 100.0, "kdv": 20.0, "kdv_orani": 0.2, "toplam": 120.0},
    }
    report = validator.validate(data)
    assert report["verdict"] == "unreadable"
    assert report["fields"] == []
    assert report["actual"]["toplam"] == 120.0
