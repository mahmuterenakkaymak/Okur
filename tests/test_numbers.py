import pytest

from app import numbers

THIN = chr(0x2009)
NNBSP = chr(0x202F)
NBSP = chr(0x00A0)
ZWSP = chr(0x200B)
FULLWIDTH = "".join(chr(c) for c in (0xFF11, 0xFF0E, 0xFF10, 0xFF14, 0xFF16, 0xFF0C, 0xFF14, 0xFF10))


def test_turkish_decimal_comma_and_thousands_dot():
    assert numbers.parse_number("1.046,40") == 1046.40
    assert numbers.parse_number("1046,40") == 1046.40
    assert numbers.parse_number("1046.40") == 1046.40
    assert numbers.parse_number("12,5") == 12.5
    assert numbers.parse_number("0,5") == 0.5
    assert numbers.parse_number("1.046") == 1046.0
    assert numbers.parse_number("1.400") == 1400.0
    assert numbers.parse_number("1.046.400") == 1046400.0


def test_thin_nbsp_and_zero_width_spaces():
    assert numbers.parse_number(f"1{THIN}046,40") == 1046.40
    assert numbers.parse_number(f"1{NNBSP}046,40") == 1046.40
    assert numbers.parse_number(f"1{NBSP}046,40") == 1046.40
    assert numbers.parse_number("1 046,40") == 1046.40
    assert numbers.parse_number(f"1.046{ZWSP},40") == 1046.40
    assert numbers.parse_number("  1.046,40  ") == 1046.40


def test_currency_prefix_and_suffix():
    amounts = ("1.046,40 TL", "TL 1.046,40", "₺1.046,40", "1.046,40₺", "1.046,40 tl", "1.046,40 TRY")
    for text in amounts:
        assert numbers.parse_number(text) == 1046.40


def test_discount_and_negative_amounts():
    assert numbers.parse_number("-52,32") == -52.32
    assert numbers.parse_number("149,00-") == -149.0
    assert numbers.parse_number("+15,00") == 15.0


def test_ocr_slips_still_read():
    assert numbers.parse_number("1.046.40") == 1046.40
    assert numbers.parse_number("1,046,40") == 1046.40
    assert numbers.parse_number("1.046,40.") == 1046.40
    assert numbers.parse_number("1.046,") == 1046.0
    assert numbers.parse_number(FULLWIDTH) == 1046.40


@pytest.mark.parametrize("value", [1046.4, 2, -3.5, 0])
def test_plain_numbers_pass_through(value):
    assert numbers.parse_number(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "   ", "abc", "12,5 kg", "MAGAZA", "1.2.3", "1,5,5", "20%", "--", "١٢٣"],
)
def test_not_a_number_is_none(value):
    assert numbers.parse_number(value) is None


@pytest.mark.parametrize("value", [None, [], {}, True, False, float("nan"), float("inf")])
def test_other_types_are_none(value):
    assert numbers.parse_number(value) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("%8", 0.08),
        ("8%", 0.08),
        ("8,%", 0.08),
        ("% 8", 0.08),
        ("KDV %20", 0.2),
        ("%20X", 0.2),
        ("KDV %20X", 0.2),
        ("%10", 0.1),
        ("%1", 0.01),
        ("20", 0.2),
        ("0,2", 0.2),
    ],
)
def test_percent_forms(text, expected):
    assert numbers.parse_percent(text) == expected


def test_percent_numbers_and_junk():
    assert numbers.parse_percent(20) == 0.2
    assert numbers.parse_percent(0.2) == 0.2
    assert numbers.parse_percent("KDV") is None
    assert numbers.parse_percent("%") is None
    assert numbers.parse_percent("") is None
    assert numbers.parse_percent(None) is None
    assert numbers.parse_percent(True) is None
