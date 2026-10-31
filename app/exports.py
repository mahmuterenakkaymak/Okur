"""Export rows (PLAN.md contract 8) as JSON, CSV and XLSX.

One flat row per job, built from the two stored columns every view already
reads, so a correction lands in all three formats at once. CSV and XLSX take
their columns from exactly the row's keys; JSON answers with the contract v1
envelopes instead, because an integrator imports receipts, not a report.
Amounts travel as floats end to end — XLSX cells are real numbers, CSV keeps
the contract's dot decimals — so no format rounds, re-reads or re-prints one.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
from collections.abc import Iterable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app import db
from app.routes_jobs import _envelope

# PLAN.md contract 8, in column order: the two spreadsheet formats' headers
# are these keys verbatim, so a saved file re-imports as the contract it came
# from and an internal helper key can never reach a customer's workbook.
FIELDS = (
    "job_id", "worker", "client_ref", "tarih", "saat", "firma", "vergi_no",
    "ara_toplam", "iskonto", "kdv", "toplam", "para_birimi", "verdict",
    "items_json", "kalite_mode", "gonderim_zamani",
)
AMOUNTS = frozenset({"ara_toplam", "iskonto", "kdv", "toplam"})
_WIDTHS = {"job_id": 38, "client_ref": 22, "firma": 34, "items_json": 60, "gonderim_zamani": 25}


def select(
    conn,
    *,
    ids: Sequence[str] = (),
    worker: str = "",
    since: str | None = None,
) -> list[dict]:
    """The queue rows an export covers, newest first.

    ids is a caller's own selection (the panel's checkboxes); an id with no
    job behind it is simply not in the file.
    """
    jobs = db.list_jobs(conn, worker=worker or None, since=since, limit=-1)
    if ids:
        wanted = set(ids)
        jobs = [job for job in jobs if job["id"] in wanted]
    return jobs


def row(job: dict) -> dict:
    """Queue row -> the flat export row, one key per contract-8 column."""
    result = _json(job, "result_json")
    verdict = _json(job, "validation_json").get("verdict") or ""
    header = result.get("header") or {}
    receipt = result.get("meta") or {}
    # ASSUMPTION: a receipt nothing was read off has no amounts to report —
    # the same rule the admin list applies — so its four amount cells stay
    # empty instead of the 0,00 an accountant would sum into a real total.
    totals = (result.get("totals") or {}) if verdict in ("ok", "mismatch") else {}
    return {
        "job_id": job["id"],
        "worker": job["worker"],
        "client_ref": job["client_ref"] or "",
        "tarih": receipt.get("tarih") or "",
        "saat": receipt.get("saat") or "",
        "firma": header.get("isim") or "",
        "vergi_no": header.get("vergi_no") or "",
        "ara_toplam": totals.get("ara_toplam"),
        "iskonto": totals.get("iskonto"),
        "kdv": totals.get("kdv"),
        "toplam": totals.get("toplam"),
        "para_birimi": result.get("para_birimi") or "",
        "verdict": verdict,
        "items_json": json.dumps(result.get("items") or [], ensure_ascii=False),
        "kalite_mode": bool(_json(job, "meta_json").get("quality_mode", job["mode"] == "quality")),
        "gonderim_zamani": job["created_at"],
    }


def to_json(jobs: Iterable[dict]) -> list[dict]:
    """Contract v1 job envelopes, whole receipts and all."""
    return [_envelope(job) for job in jobs]


def to_csv(rows: Iterable[dict]) -> bytes:
    """UTF-8 with a byte-order mark: the only way Excel reads Turkish right."""
    alan = io.StringIO()
    yazici = csv.writer(alan)  # CRLF, the line ending Excel expects
    yazici.writerow(FIELDS)
    for satir in rows:
        yazici.writerow([_csv_value(satir[field]) for field in FIELDS])
    return alan.getvalue().encode("utf-8-sig")


def to_xlsx(rows: Iterable[dict]) -> bytes:
    """One sheet: bold frozen header, amounts as numbers, widths that read."""
    workbook = Workbook()
    sayfa = workbook.active
    sayfa.title = "Fişler"
    sayfa.append(list(FIELDS))
    for hucre in sayfa[1]:
        hucre.font = Font(bold=True)
    for satir in rows:
        sayfa.append([satir[field] for field in FIELDS])
    for sira, field in enumerate(FIELDS, start=1):
        sutun = get_column_letter(sira)
        sayfa.column_dimensions[sutun].width = _WIDTHS.get(field, 14)
        if field in AMOUNTS:
            for satir_no in range(2, sayfa.max_row + 1):
                sayfa[f"{sutun}{satir_no}"].number_format = "0.00"
    sayfa.freeze_panes = "A2"
    dosya = io.BytesIO()
    workbook.save(dosya)
    return dosya.getvalue()


def filename(format: str) -> str:
    """Download name for one format; ASCII, so no browser mangles it."""
    return f"ihracat-{datetime.date.today():%Y-%m-%d}.{format}"


def _csv_value(deger: object) -> object:
    if deger is None:
        return ""
    return str(deger).lower() if isinstance(deger, bool) else deger


def _json(job: dict, field: str) -> dict:
    """A stored JSON column as a dict; absent — a job that never ran — is empty."""
    return json.loads(job[field]) if job[field] else {}
