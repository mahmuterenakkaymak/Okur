"""Deterministic arithmetic: the LLM never owns a number.

validate() recomputes line totals, ara toplam, single- and mixed-rate KDV and
genel toplam from items[] and compares each printed value with the recomputed
one at 0.01 tolerance, so a misread digit surfaces as a mismatch naming the
offending field (items[2].toplam, totals.kdv) instead of a silently wrong
total. A single-rate receipt is tried on both KDV bases — KDV harici (tax added
to the item sum) and KDV dahildir (tax inside it) — and the closer one names the
fields. Pure function: no I/O, no mutation of the input.
"""
from __future__ import annotations

from collections import namedtuple
from collections.abc import Mapping
from typing import Any

from app import contract

TOLERANCE = 0.01
_EPS = 1e-9  # keeps a printed 0.01 kurus drift inside tolerance despite float noise

_Base = namedtuple("_Base", "ara_toplam kdv toplam")


def validate(result: Mapping[str, Any] | contract.Result) -> dict[str, Any]:
    """Validation block (contract shape 3) for a result dict or model."""
    parsed = result if isinstance(result, contract.Result) else contract.Result.parse(result)
    printed = parsed.totals

    if not parsed.items:
        # ASSUMPTION: no items means nothing was read, so the verdict is
        # unreadable rather than a vacuous ok over zero totals.
        return contract.Validation(
            verdict="unreadable",
            expected=contract.TotalsBlock(),
            actual=contract.TotalsBlock(
                ara_toplam=printed.ara_toplam,
                iskonto=printed.iskonto,
                kdv=printed.kdv,
                toplam=printed.toplam,
            ),
            fields=[],
        ).model_dump()

    fields: list[str] = []
    ara_toplam = 0.0
    for index, item in enumerate(parsed.items):
        line = item.miktar * item.birim_fiyat
        ara_toplam += round(line, 2)  # receipts sum printed line totals, not raw products
        if not _close(item.toplam, line):
            fields.append(f"items[{index}].toplam")

    # ASSUMPTION: iskonto is a receipt-level discount no item carries, so it is
    # trusted as a chain input and never flagged on its own; a negative one is
    # the printed "52,32-" form, so its magnitude reduces the base.
    iskonto = abs(printed.iskonto)
    base = min(_bases(ara_toplam, iskonto, printed), key=lambda b: _distance(b, printed))

    for name in ("ara_toplam", "kdv", "toplam"):
        if not _close(getattr(printed, name), getattr(base, name)):
            fields.append(f"totals.{name}")

    return contract.Validation(
        verdict="ok" if not fields else "mismatch",
        expected=contract.TotalsBlock(
            ara_toplam=round(base.ara_toplam, 2),
            iskonto=iskonto,
            kdv=base.kdv,
            toplam=round(base.toplam, 2),
        ),
        actual=contract.TotalsBlock(
            ara_toplam=printed.ara_toplam,
            iskonto=printed.iskonto,
            kdv=printed.kdv,
            toplam=printed.toplam,
        ),
        fields=fields,
    ).model_dump()


def _bases(gross: float, iskonto: float, printed: contract.Totals) -> list[_Base]:
    """Expected blocks per KDV base, exclusive first so it wins a tie."""
    matrah = gross - iskonto
    if printed.kdv_orani <= 0:
        # ASSUMPTION: mixed-rate receipts have no single kdv_orani, so the
        # structurer emits 0 and the printed kdv is trusted as a chain input;
        # the toplam = matrah + kdv line still ties it to the base.
        return [_Base(gross, printed.kdv, matrah + printed.kdv)]

    exclusive = round(matrah * printed.kdv_orani, 2)
    # ASSUMPTION: a KDV dahildir receipt prints VAT-inclusive line prices, so
    # the item sum is the gross total and the tax comes back out of it; its ara
    # toplam is printed both as that gross and as the net under the tax.
    inclusive = round(matrah * printed.kdv_orani / (1.0 + printed.kdv_orani), 2)
    return [
        _Base(gross, exclusive, matrah + exclusive),
        _Base(gross, inclusive, matrah),
        _Base(matrah - inclusive, inclusive, matrah),
    ]


def _distance(base: _Base, printed: contract.Totals) -> float:
    """How far a base sits from the printed totals; 0 means it reproduces them."""
    return sum(abs(getattr(printed, name) - getattr(base, name)) for name in base._fields)


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= TOLERANCE + _EPS
