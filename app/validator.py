"""Deterministic arithmetic: the LLM never owns a number.

validate() recomputes line totals, ara toplam, single-rate KDV and genel
toplam from items[] and compares each printed value with the recomputed one
at 0.01 tolerance, so a misread digit surfaces as a mismatch naming the
offending field (items[2].toplam, totals.kdv) instead of a silently wrong
total. Pure function: no I/O, no mutation of the input.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app import contract

TOLERANCE = 0.01
_EPS = 1e-9  # keeps a printed 0.01 kurus drift inside tolerance despite float noise


def validate(result: Mapping[str, Any] | contract.Result) -> dict[str, Any]:
    """Validation block (contract shape 3) for a result dict or model."""
    parsed = result if isinstance(result, contract.Result) else contract.Result.parse(result)
    printed = parsed.totals

    fields: list[str] = []
    ara_toplam = 0.0
    for index, item in enumerate(parsed.items):
        line = item.miktar * item.birim_fiyat
        ara_toplam += round(line, 2)  # receipts sum printed line totals, not raw products
        if not _close(item.toplam, line):
            fields.append(f"items[{index}].toplam")

    # ASSUMPTION: iskonto is a receipt-level discount no item carries, so it is
    # trusted as a chain input and never flagged on its own.
    matrah = ara_toplam - printed.iskonto
    kdv = round(matrah * printed.kdv_orani, 2)
    toplam = matrah + kdv

    for name, expected in (
        ("ara_toplam", ara_toplam),
        ("kdv", kdv),
        ("toplam", toplam),
    ):
        if not _close(getattr(printed, name), expected):
            fields.append(f"totals.{name}")

    return contract.Validation(
        verdict="ok" if not fields else "mismatch",
        expected=contract.TotalsBlock(
            ara_toplam=round(ara_toplam, 2),
            iskonto=printed.iskonto,
            kdv=kdv,
            toplam=round(toplam, 2),
        ),
        actual=contract.TotalsBlock(
            ara_toplam=printed.ara_toplam,
            iskonto=printed.iskonto,
            kdv=printed.kdv,
            toplam=printed.toplam,
        ),
        fields=fields,
    ).model_dump()


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= TOLERANCE + _EPS
