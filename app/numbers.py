"""Turkish receipt numbers to floats: one parser for the structurer and validator.

Receipts print "1.046,40", "1.046,40 TL", "%20" or "8,%" and OCR slips blur
them ("1.046.40", "%20X"). The last separator is the decimal one and earlier
dots group thousands, so every form lands on the same float -- or None, never a
silent 0.0 that the validator would then trust.
"""
from __future__ import annotations

import math
import re
import unicodedata

# Zero-width marks survive OCR between digits; NFKC folds thin/nbsp to spaces.
_ZERO_WIDTH = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))
_GROUPED_RE = re.compile(r"\d{1,3}(?:\.\d{3})+", re.ASCII)  # 1.046 / 1.046.400
_INT_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d+", re.ASCII)  # 1.046 / 1,046 / 1046
_FRAC_RE = re.compile(r"\d*", re.ASCII)
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d*)?", re.ASCII)
_CURRENCY = ("tl", "try", "₺")


def parse_number(value: object) -> float | None:
    """Amount or quantity as a float; None when the value is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None

    text = _clean(value)
    # "-52,32" and the printed-discount "149,00-" both mean negative.
    negative = "-" in text
    number = _parse(text.strip("+-").rstrip(".,"))
    if number is None:
        return None
    return -number if negative else number


# ASSUMPTION: rates return as fractions, since contract totals.kdv_orani stores 0.2, not 20.
def parse_percent(value: object) -> float | None:
    """Rate as a fraction: "%20", "20 %", "20,%", "KDV %20X" -> 0.2.

    A bare number is the contract fraction already (0.2 -> 0.2); above 1 no
    Turkish rate is printed as a fraction, so 20 -> 0.2.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = parse_number(value)
        return None if number is None else _fraction(number)
    if not isinstance(value, str):
        return None

    text = _clean(value).upper()
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    number = parse_number(match.group())
    if number is None:
        return None
    return number / 100.0 if "%" in text else _fraction(number)


def _clean(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_ZERO_WIDTH)
    text = "".join(text.split())  # thin/nbsp spaces became plain ones
    for mark in _CURRENCY:
        if text.lower().startswith(mark):
            text = text[len(mark):]
        elif text.lower().endswith(mark):
            text = text[: -len(mark)]
    return text


def _parse(text: str) -> float | None:
    if "," not in text and _GROUPED_RE.fullmatch(text):
        return _build(text.replace(".", ""), "")
    cut = max(text.rfind("."), text.rfind(","))
    if cut < 0:
        return _build(text, "")
    return _build(text[:cut], text[cut + 1:])


def _build(int_part: str, frac_part: str) -> float | None:
    if not _INT_RE.fullmatch(int_part) or not _FRAC_RE.fullmatch(frac_part):
        return None
    digits = int_part.replace(".", "").replace(",", "")
    return float(f"{digits}.{frac_part}") if frac_part else float(digits)


def _fraction(number: float) -> float:
    return number / 100.0 if number > 1 else number
