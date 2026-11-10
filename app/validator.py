"""Deterministic arithmetic: the LLM never owns a number.

validate() recomputes line totals, ara toplam, KDV and genel toplam from
items[] and compares each printed value with the recomputed one at 0.01
tolerance, so a misread digit surfaces as a mismatch naming the offending field
(items[2].toplam, totals.kdv) instead of a silently wrong total.

A single-rate receipt is tried on both KDV bases — KDV harici (tax added to the
item sum) and KDV dahildir (tax inside it) — and the closer one names the
fields. A mixed-rate receipt (kdv_orani 0) is checked through its printed
per-rate lines (totals.kdv_satirlari): each line's tax is recomputed from its
matrah, the lines must add up to the printed KDV and tie back to the item sum.

What cannot be recomputed is never passed off as checked: a receipt-level
iskonto, a mixed-rate KDV without its per-rate lines, a per-rate line with no
matrah — those paths land in ``unverified``, so an ``ok`` verdict only ever
vouches for numbers the code actually recomputed. A result whose items carry no
number at all is ``unreadable``, never a vacuous ``ok`` over zeros.

Pure function: no I/O, no mutation of the input.
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
    actual = contract.TotalsBlock(
        ara_toplam=printed.ara_toplam,
        iskonto=printed.iskonto,
        kdv=printed.kdv,
        toplam=printed.toplam,
    )

    if not parsed.items or not _has_numbers(parsed):
        # No items, or items that are only names: nothing numeric was read, so
        # an ok over zero totals would vouch for a receipt nobody read.
        return contract.Validation(
            verdict="unreadable",
            expected=contract.TotalsBlock(),
            actual=actual,
            fields=[],
        ).model_dump()

    fields: list[str] = []
    unverified: list[str] = []

    gross = 0.0
    for index, item in enumerate(parsed.items):
        line = item.miktar * item.birim_fiyat
        gross += round(line, 2)  # receipts sum printed line totals, not raw products
        if not _close(item.toplam, line):
            fields.append(f"items[{index}].toplam")

    # A negative iskonto is the printed "52,32-" form, so its magnitude reduces
    # the base. Nothing on the receipt carries it, so it cannot be recomputed:
    # it is a chain input and the reviewer is told so.
    iskonto = abs(printed.iskonto)
    if iskonto > 0:
        unverified.append("totals.iskonto")
    matrah = gross - iskonto

    line_kdv = _check_kdv_lines(printed.kdv_satirlari, matrah, fields, unverified)

    if printed.kdv_orani > 0:
        bases = _single_rate_bases(gross, matrah, printed.kdv_orani)
    else:
        if line_kdv is None:
            # ASSUMPTION: a mixed-rate receipt read without its per-rate lines
            # has no way to recompute its tax, so the printed kdv is trusted as
            # a chain input — and named as such, never vouched for.
            unverified.append("totals.kdv")
            kdv = printed.kdv
        else:
            kdv = line_kdv
        bases = _mixed_rate_bases(gross, matrah, kdv)

    base = min(bases, key=lambda b: _distance(b, printed))

    for name in ("ara_toplam", "kdv", "toplam"):
        if not _is_printed(printed, name):
            # ASSUMPTION: many Turkish receipts print no ARA TOPLAM (and some
            # no TOPKDV); a 0.0 there is "not on the receipt", not a misread.
            # The genel toplam still ties the chain, so nothing escapes.
            continue
        if not _close(getattr(printed, name), getattr(base, name)):
            fields.append(f"totals.{name}")

    return contract.Validation(
        verdict="ok" if not fields else "mismatch",
        expected=contract.TotalsBlock(
            ara_toplam=round(base.ara_toplam, 2),
            iskonto=iskonto,
            kdv=round(base.kdv, 2),
            toplam=round(base.toplam, 2),
        ),
        actual=actual,
        fields=fields,
        unverified=unverified,
    ).model_dump()


def _has_numbers(parsed: contract.Result) -> bool:
    """True when the model read at least one amount, on an item or the totals."""
    for item in parsed.items:
        if item.miktar or item.birim_fiyat or item.toplam:
            return True
    t = parsed.totals
    return any((t.ara_toplam, t.iskonto, t.kdv, t.toplam, t.kdv_satirlari))


def _is_printed(printed: contract.Totals, name: str) -> bool:
    """genel toplam is always required; ara toplam and kdv may be absent (0.0)."""
    return name == "toplam" or getattr(printed, name) != 0


def _check_kdv_lines(
    lines: list[contract.KdvSatiri],
    matrah: float,
    fields: list[str],
    unverified: list[str],
) -> float | None:
    """Recompute each per-rate line; the summed tax, or None with no lines.

    A line's matrah may be printed net of the tax (kdv = matrah x oran) or
    gross with it (kdv = matrah x oran / (1 + oran)); either reproduces it.
    The lines must also tie back to the items: their matrah adds up to the
    discounted item sum (gross bases, or net bases on a KDV harici receipt),
    or matrah + kdv does (net bases on a KDV dahildir receipt).
    """
    if not lines:
        return None
    all_based = True
    for index, line in enumerate(lines):
        path = f"totals.kdv_satirlari[{index}].kdv"
        if line.oran <= 0 or line.matrah == 0:
            all_based = False
            unverified.append(path)
            continue
        on_net = round(line.matrah * line.oran, 2)
        on_gross = round(line.matrah * line.oran / (1.0 + line.oran), 2)
        if not (_close(line.kdv, on_net) or _close(line.kdv, on_gross)):
            fields.append(path)
    kdv_sum = sum(line.kdv for line in lines)
    if all_based:
        bases_sum = sum(line.matrah for line in lines)
        # Each line is rounded on its own, so the tie allows a kurus per line.
        slack = TOLERANCE * len(lines)
        if not (
            _close(bases_sum, matrah, slack) or _close(bases_sum + kdv_sum, matrah, slack)
        ):
            fields.append("totals.kdv_satirlari")
    return kdv_sum


def _single_rate_bases(gross: float, matrah: float, rate: float) -> list[_Base]:
    """Expected blocks per KDV base, exclusive first so it wins a tie."""
    exclusive = round(matrah * rate, 2)
    # ASSUMPTION: a KDV dahildir receipt prints VAT-inclusive line prices, so
    # the item sum is the gross total and the tax comes back out of it; its ara
    # toplam is printed both as that gross and as the net under the tax.
    inclusive = round(matrah * rate / (1.0 + rate), 2)
    return [
        _Base(gross, exclusive, matrah + exclusive),
        _Base(gross, inclusive, matrah),
        _Base(matrah - inclusive, inclusive, matrah),
    ]


def _mixed_rate_bases(gross: float, matrah: float, kdv: float) -> list[_Base]:
    """The same three shapes with the tax given rather than derived.

    Turkish retail receipts are KDV dahildir — the genel toplam is the item sum
    and TOPKDV sits inside it — so the inclusive shapes are the common case;
    the exclusive one stays first so it wins a tie.
    """
    return [
        _Base(gross, kdv, matrah + kdv),
        _Base(gross, kdv, matrah),
        _Base(matrah - kdv, kdv, matrah),
    ]


def _distance(base: _Base, printed: contract.Totals) -> float:
    """How far a base sits from the printed totals; 0 means it reproduces them."""
    return sum(
        abs(getattr(printed, name) - getattr(base, name))
        for name in base._fields
        if _is_printed(printed, name)
    )


def _close(actual: float, expected: float, tolerance: float = TOLERANCE) -> bool:
    return abs(actual - expected) <= tolerance + _EPS
