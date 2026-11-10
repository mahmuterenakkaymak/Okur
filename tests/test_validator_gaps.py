"""The validator vouches only for numbers it recomputed.

Each test pins one gap a review found in the old validator, where a result
reached verdict ``ok`` without the code having checked the number:
names-only items, an invented mixed-rate KDV, an invented iskonto, and the
false alarm on a receipt that prints no ARA TOPLAM.
"""
from app import validator


def item(ad="Ürün", miktar=1.0, birim_fiyat=100.0, toplam=100.0):
    return {"ad": ad, "miktar": miktar, "birim_fiyat": birim_fiyat, "toplam": toplam}


# --- names-only items -------------------------------------------------------

def test_items_with_names_but_no_numbers_are_unreadable_not_ok():
    report = validator.validate({"items": [{"ad": "EKMEK"}, {"ad": "SUT"}]})
    assert report["verdict"] == "unreadable"


def test_names_only_items_with_a_printed_toplam_are_a_mismatch():
    report = validator.validate({"items": [{"ad": "EKMEK"}], "totals": {"toplam": 30.0}})
    assert report["verdict"] == "mismatch"
    assert "totals.toplam" in report["fields"]


# --- mixed-rate KDV ---------------------------------------------------------

def test_mixed_rate_kdv_without_lines_is_named_unverified():
    report = validator.validate({
        "items": [item()],
        "totals": {"ara_toplam": 100, "kdv": 999, "kdv_orani": 0, "toplam": 1099},
    })
    # The arithmetic closes, but nothing recomputed the 999: it must say so.
    assert report["verdict"] == "ok"
    assert "totals.kdv" in report["unverified"]


# A typical KDV dahildir market receipt: bread at %1, detergent at %20, the
# genel toplam is the item sum, TOPKDV sits inside it, matrah printed gross.
DAHIL_MIXED = {
    "items": [
        item("Ekmek", 2, 15.0, 30.0),
        item("Deterjan", 1, 120.0, 120.0),
    ],
    "totals": {
        "kdv": 20.30,
        "kdv_orani": 0,
        "toplam": 150.0,
        "kdv_satirlari": [
            {"oran": "%1", "matrah": 30.0, "kdv": 0.30},
            {"oran": "%20", "matrah": 120.0, "kdv": 20.0},
        ],
    },
}


def test_mixed_rate_kdv_dahil_receipt_with_lines_is_ok_and_verified():
    report = validator.validate(DAHIL_MIXED)
    assert report["verdict"] == "ok", report["fields"]
    assert report["unverified"] == []
    assert report["expected"]["kdv"] == 20.30
    assert report["expected"]["toplam"] == 150.0


def test_mixed_rate_kdv_dahil_without_lines_no_longer_flags_toplam():
    data = {"items": DAHIL_MIXED["items"],
            "totals": {"kdv": 20.30, "kdv_orani": 0, "toplam": 150.0}}
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    assert report["unverified"] == ["totals.kdv"]


def test_a_wrong_per_rate_kdv_is_named():
    data = {"items": DAHIL_MIXED["items"],
            "totals": {**DAHIL_MIXED["totals"], "kdv": 25.30,
                       "kdv_satirlari": [{"oran": 0.01, "matrah": 30.0, "kdv": 0.30},
                                         {"oran": 0.20, "matrah": 120.0, "kdv": 25.0}]}}
    report = validator.validate(data)
    assert report["verdict"] == "mismatch"
    assert report["fields"] == ["totals.kdv_satirlari[1].kdv"]


def test_lines_that_do_not_add_up_to_the_printed_kdv_name_totals_kdv():
    data = {"items": DAHIL_MIXED["items"], "totals": {**DAHIL_MIXED["totals"], "kdv": 30.0}}
    report = validator.validate(data)
    assert report["fields"] == ["totals.kdv"]


def test_lines_whose_matrah_does_not_tie_to_the_items_are_named():
    lines = [{"oran": 0.01, "matrah": 300.0, "kdv": 3.0},
             {"oran": 0.20, "matrah": 120.0, "kdv": 20.0}]
    data = {"items": DAHIL_MIXED["items"],
            "totals": {"kdv": 23.0, "kdv_orani": 0, "toplam": 150.0, "kdv_satirlari": lines}}
    report = validator.validate(data)
    assert "totals.kdv_satirlari" in report["fields"]


def test_net_matrah_on_a_kdv_haric_mixed_receipt_is_ok():
    data = {
        "items": [item("A", 1, 100.0, 100.0), item("B", 1, 50.0, 50.0)],
        "totals": {"ara_toplam": 150.0, "kdv": 21.0, "kdv_orani": 0, "toplam": 171.0,
                   "kdv_satirlari": [{"oran": 0.10, "matrah": 60.0, "kdv": 6.0},
                                     {"oran": 0.20, "matrah": 90.0, "kdv": 15.0}]},
    }
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    assert report["unverified"] == []


def test_a_per_rate_line_with_no_matrah_is_unverified_not_checked():
    data = {"items": DAHIL_MIXED["items"],
            "totals": {"kdv": 20.30, "kdv_orani": 0, "toplam": 150.0,
                       "kdv_satirlari": [{"oran": 0.01, "kdv": 0.30},
                                         {"oran": 0.20, "matrah": 120.0, "kdv": 20.0}]}}
    report = validator.validate(data)
    assert report["verdict"] == "ok", report["fields"]
    assert report["unverified"] == ["totals.kdv_satirlari[0].kdv"]


# --- iskonto ----------------------------------------------------------------

def test_a_receipt_level_iskonto_is_named_unverified():
    report = validator.validate({
        "items": [item()],
        "totals": {"ara_toplam": 100, "iskonto": 50, "kdv": 10, "kdv_orani": 0.2, "toplam": 60},
    })
    assert report["verdict"] == "ok"
    assert report["unverified"] == ["totals.iskonto"]


def test_no_iskonto_leaves_nothing_unverified_on_a_single_rate_receipt():
    report = validator.validate({
        "items": [item()],
        "totals": {"ara_toplam": 100, "kdv": 20, "kdv_orani": 0.2, "toplam": 120},
    })
    assert report["verdict"] == "ok"
    assert report["unverified"] == []


# --- ara toplam not printed ------------------------------------------------

def test_an_unprinted_ara_toplam_is_not_a_false_alarm():
    report = validator.validate({
        "items": [item()],
        "totals": {"kdv": 20, "kdv_orani": 0.2, "toplam": 120},
    })
    assert report["verdict"] == "ok", report["fields"]


def test_an_unprinted_ara_toplam_still_catches_a_wrong_toplam():
    report = validator.validate({
        "items": [item()],
        "totals": {"kdv": 20, "kdv_orani": 0.2, "toplam": 130},
    })
    assert report["fields"] == ["totals.toplam"]
