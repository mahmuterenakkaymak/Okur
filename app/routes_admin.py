"""/admin/api/*: the admin panel's own door.

The admin UI is a static shell, so it authenticates with a session cookie
instead of a worker key (PLAN.md decision 6): login compares ADMIN_TOKEN in
constant time and mints a random session id, which the browser stores in an
httpOnly cookie the page can never read. main's guard checks that cookie for
every /admin/api path, so an admin route added later is protected the moment
it is registered.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import auth, config, contract, db, exports, numbers, validator
from app.routes_jobs import _Status, _bad_field, _clean_iso, _envelope
from app.routes_worker import _image_path

router = APIRouter(prefix="/admin/api", tags=["admin"])

# The two routes that answer before a session exists; everything else under
# /admin/api is the guard's job.
PUBLIC_PATHS = frozenset({"/admin/api/login", "/admin/api/logout"})

# The table's sortable columns and the exact keys a row answers with, so an
# internal helper key can never reach the browser by accident.
_Sort = Literal["worker", "tarih", "firma", "toplam", "verdict", "kalite_mode"]
_Yon = Literal["asc", "desc"]
_Bicim = Literal["json", "csv", "xlsx"]

# What each export format lands on the wire as, so the browser saves a file
# of the type it says rather than a spreadsheet named .csv.
_TUR = {
    "json": "application/json",
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_SUTUNLAR = (
    "job_id",
    "kisa_id",
    "worker",
    "status",
    "tarih",
    "firma",
    "toplam",
    "verdict",
    "kalite_mode",
)


class LoginBody(BaseModel):
    token: str = ""


class CorrectionBody(BaseModel):
    """One entry per corrected field: {"items[0].toplam": "12,50"}."""

    fields: dict[str, Any] = {}


@router.post("/login")
def login(body: LoginBody):
    """Exchange the admin token for a session cookie."""
    if not auth.admin_configured():
        raise HTTPException(503, "ADMIN_TOKEN is not set on the server")
    if not auth.admin_token_ok(body.token):
        raise HTTPException(401, "invalid admin token")
    response = _session_response(True)
    _issue_cookie(response, auth.start_session())
    return response


@router.post("/logout")
def logout(request: Request):
    """Drop the session server-side and expire the cookie; always succeeds."""
    auth.end_session(request.cookies.get(auth.ADMIN_COOKIE, ""))
    response = _session_response(False)
    response.delete_cookie(auth.ADMIN_COOKIE, path="/admin")
    return response


@router.get("/session")
def session():
    """Who am I? The guard has already refused a caller without a session."""
    return _session_response(True)


@router.get("/jobs")
def list_jobs(
    request: Request,
    status: _Status | None = Query(None),
    worker: str | None = Query(None),
    date_from: str = Query(""),
    date_to: str = Query(""),
    q: str = Query(""),
    sort: _Sort = Query("tarih"),
    dir: _Yon = Query("desc"),
    limit: int = Query(25),
    offset: int = Query(0),
):
    """Every submission, one row each, narrowed and ordered on the server.

    Status and worker ride the indexed SQL columns; the date window, the
    free-text search and the sort run over the rows themselves, because the
    day a row shows is the receipt's own when it has one and the search has to
    fold Turkish letters SQLite's LIKE cannot.
    """
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    bas, son = _pencere_gunu(date_from, "date_from"), _pencere_gunu(date_to, "date_to")
    terimler = _terimler(q)
    conn = _connect(request)
    try:
        # limit=-1 is SQLite for "no limit": paging needs the whole filtered
        # set, so the page is the last thing cut.
        satirlar = [
            _satir(row)
            for row in db.list_jobs(conn, status=status, worker=worker, limit=-1)
        ]
        calisanlar = [
            row["worker"]
            for row in conn.execute(
                "SELECT worker FROM jobs WHERE worker <> ''"
                " GROUP BY worker ORDER BY worker"
            )
        ]
    finally:
        conn.close()
    eslesen = [
        satir
        for satir in satirlar
        if _pencerede(satir, bas, son) and _icerir(satir, terimler)
    ]
    sirali = _sirala(eslesen, sort, dir == "desc")
    return {
        "jobs": [
            {sutun: satir[sutun] for sutun in _SUTUNLAR}
            for satir in sirali[offset : offset + limit]
        ],
        "total": len(eslesen),
        "workers": calisanlar,
    }


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    """One job as the contract v1 envelope, plus where its image lives.

    The detail is the same body GET /v1/jobs/{id} answers with, so the
    reviewer and the integrator never read two versions of one receipt.
    """
    conn = _connect(request)
    try:
        return _detay(_job(conn, job_id))
    finally:
        conn.close()


@router.patch("/jobs/{job_id}")
def correct_job(request: Request, job_id: str, body: CorrectionBody):
    """Field-level corrections: one write, and every view follows.

    A correction rewrites the two columns the job is made of — result_json and
    a validation block recomputed over the corrected data — and every surface
    reads those columns: GET /v1/jobs/{id}, this panel's detail, the worker
    PWA's result view, both list views and the export rows (T38) derive from
    exactly these keys. So one PATCH here is what makes the receipt correct
    everywhere, and the verdict on screen is always the verdict of the numbers
    on screen — the model never gets to keep a wrong total.

    ASSUMPTION: the task names the resource (PATCH /v1/jobs/{id}); the door is
    the admin one, because /v1 is key-authed and frozen for integrators while
    PLAN.md puts corrections behind the admin session in routes_admin.
    """
    if not body.fields:
        raise _bad_field(("body", "fields"), "expected at least one field")
    conn = _connect(request)
    try:
        row = _job(conn, job_id)
        if not row["result_json"]:
            # ASSUMPTION: a job the pipeline has not read has no fields to
            # correct, so 409 — the row exists, it simply is not ready yet.
            raise HTTPException(409, "job has no result to correct yet")
        sonuc, kayitlar = _duzelt(_json(row, "result_json"), body.fields)
        guncel = db.update_job(
            conn,
            job_id,
            result_json=sonuc,
            validation_json=validator.validate(sonuc),
        )
        for alan, eski, yeni in kayitlar:
            db.add_correction(
                conn,
                job_id,
                field=alan,
                old_value=eski,
                new_value=yeni,
                who=WHO,
            )
        return _detay(guncel)
    finally:
        conn.close()


@router.get("/jobs/{job_id}/image")
def get_image(request: Request, job_id: str):
    """The stored receipt, behind the same session as the rest of /admin/api."""
    conn = _connect(request)
    try:
        data = _image_path(_job(conn, job_id)).read_bytes()
    finally:
        conn.close()
    return Response(content=data, media_type="image/jpeg")


@router.get("/export")
def export_jobs(
    request: Request,
    format: _Bicim = Query("csv"),
    ids: str = Query(""),
    worker: str = Query(""),
    since: str = Query(""),
):
    """Every submission the caller names, as JSON, CSV or XLSX.

    The three formats are one query apart: the rows come from the same two
    stored columns the panels show (contract 8), so a receipt corrected here
    exports corrected. ids is a comma-separated selection — the panel's
    checkboxes — while worker and since narrow the whole set; with none of the
    three the export is everything.

    ASSUMPTION: the task names GET /v1/export; the door is the admin one,
    because /v1 is key-authed and per-integrator while an export spans every
    worker's receipts — the same reading as T37's corrections.
    """
    conn = _connect(request)
    try:
        isler = exports.select(
            conn,
            ids=[parca.strip() for parca in ids.split(",") if parca.strip()],
            worker=worker.strip(),
            since=_clean_iso(since, ("query", "since")),
        )
    finally:
        conn.close()
    if format == "json":
        govde: str | bytes = json.dumps(exports.to_json(isler), ensure_ascii=False)
    else:
        satirlar = [exports.row(job) for job in isler]
        govde = (
            exports.to_csv(satirlar)
            if format == "csv"
            else exports.to_xlsx(satirlar)
        )
    response = Response(content=govde, media_type=_TUR[format])
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{exports.filename(format)}"'
    )
    return response


def _connect(request: Request):
    """One connection per request, same rule as main._connect."""
    return db.connect(request.app.state.db_path)


def _job(conn, job_id: str) -> dict:
    row = db.get_job(conn, job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    return row


def _detay(row: dict) -> dict:
    """Queue row -> contract envelope, plus where this job's image lives."""
    envelope = _envelope(row)
    envelope["image_url"] = (
        f"/admin/api/jobs/{row['id']}/image" if row["image_path"] else None
    )
    return envelope


# ASSUMPTION: one shared ADMIN_TOKEN signs every correction, so the audit
# column records the operator as "admin" — there is no per-person identity.
WHO = "admin"


def _metin(deger: object) -> str | None:
    return deger.strip() if isinstance(deger, str) else None


# The correctable fields and how each one is read, in the validator's own
# dotted-path vocabulary (items[2].toplam, totals.kdv) — so a correction names
# a field exactly the way the discrepancy panel reports one, and a printed
# "1.046,40" lands on the same float the pipeline stored.
_OKULAR = {
    "items": {
        "ad": (_metin, "text"),
        "miktar": (numbers.parse_number, "number"),
        "birim_fiyat": (numbers.parse_number, "number"),
        "toplam": (numbers.parse_number, "number"),
    },
    "totals": {
        "ara_toplam": (numbers.parse_number, "number"),
        "iskonto": (numbers.parse_number, "number"),
        "kdv": (numbers.parse_number, "number"),
        "kdv_orani": (numbers.parse_percent, "number"),
        "toplam": (numbers.parse_number, "number"),
    },
}


def _uyari(yol: str, mesaj: str) -> RequestValidationError:
    return _bad_field(("body", "fields", yol), mesaj)


# One section and one field: anything else hanging off the path is a typo, not
# a field a reviewer corrects.
_YOL = re.compile(r"(?:items\[(\d+)\]|totals)\.(\w+)")


def _yol(yol: str) -> tuple[str, int | None, str]:
    """'items[2].toplam' -> ("items", 2, "toplam"), 'totals.kdv' -> ("totals", None, "kdv")."""
    adim = _YOL.fullmatch(yol)
    if adim is None:
        raise _uyari(yol, "expected items[N].field or totals.field")
    sira, ad = adim.groups()
    return ("items", int(sira), ad) if sira else ("totals", None, ad)


def _kayit(deger: object) -> str:
    """An old/new value as audit text; absent reads as empty, never as "None"."""
    return "" if deger is None else str(deger)


def _duzelt(
    sonuc: dict, duzeltmeler: dict[str, Any]
) -> tuple[dict, list[tuple[str, str, str]]]:
    """Corrected result + one (field, old, new) row per field that moved.

    Nothing is written from here, and the caller stores only once every field
    has read cleanly, so a body carrying one bad path leaves the job as it was.
    """
    govde = copy.deepcopy(sonuc)
    kayitlar = []
    for yol, deger in duzeltmeler.items():
        bolum, sira, ad = _yol(yol)
        okuyucu = _OKULAR[bolum].get(ad)
        if okuyucu is None:
            raise _uyari(yol, f"not a correctable field: {ad or 'field'}")
        if bolum == "totals":
            hedef = govde.setdefault("totals", {})
        else:
            urunler = govde.setdefault("items", [])
            if sira >= len(urunler):
                raise _uyari(yol, f"this receipt has {len(urunler)} items")
            hedef = urunler[sira]
        yeni = okuyucu[0](deger)
        if yeni is None:
            raise _uyari(yol, f"expected a {okuyucu[1]}")
        eski = hedef.get(ad)
        hedef[ad] = yeni
        if eski != yeni:
            kayitlar.append((yol, _kayit(eski), _kayit(yeni)))
    return contract.Result.parse(govde).model_dump(), kayitlar


def _satir(row: dict) -> dict:
    """Queue row -> table row.

    A job that has not been through the pipeline simply has no firm, total or
    verdict yet, so those read as empty rather than as a zero the admin would
    read as a real amount; the day falls back to the submission date.
    """
    result = _json(row, "result_json")
    meta = _json(row, "meta_json")
    header = result.get("header") or {}
    totals = result.get("totals") or {}
    gun = _iso_gun((result.get("meta") or {}).get("tarih")) or str(row["created_at"])[:10]
    quality = meta.get("quality_mode")
    verdict = _json(row, "validation_json").get("verdict")
    # ASSUMPTION: an unreadable receipt has no amounts to report — its stored
    # result is the contract's empty default, and 0,00 on the list would read
    # as a receipt that totalled nothing.
    return {
        "job_id": row["id"],
        "kisa_id": str(row["id"])[:8],
        "worker": row["worker"],
        "status": row["status"],
        "tarih": f"{gun[8:10]}.{gun[5:7]}.{gun[:4]}",
        "firma": header.get("isim") or "",
        "toplam": totals.get("toplam") if verdict in ("ok", "mismatch") else None,
        "verdict": verdict,
        "kalite_mode": (
            row["mode"] == "quality" if quality is None else bool(quality)
        ),
        "_gun": gun,
        "_arama": _fold(
            " ".join(
                [
                    header.get("isim") or "",
                    header.get("vergi_dairesi") or "",
                    header.get("vergi_no") or "",
                    *(item.get("ad") or "" for item in result.get("items") or []),
                ]
            )
        ),
    }


def _json(row: dict, field: str) -> dict:
    """A stored JSON column as a dict; absent — a job that never ran — is empty."""
    return json.loads(row[field]) if row[field] else {}


def _iso_gun(deger: object) -> str:
    """Receipt date dd.MM.yyyy as an ISO day; anything unreadable is empty."""
    parca = str(deger or "").split(".")
    if len(parca) != 3 or not all(p.isdigit() for p in parca):
        return ""
    gun, ay, yil = (int(p) for p in parca)
    try:
        return date(yil, ay, gun).isoformat()
    except ValueError:
        return ""


def _pencere_gunu(deger: str, alan: str) -> str:
    """One bound of the date window; blank stays open, a typo is a 422."""
    stamp = (deger or "").strip()
    if not stamp:
        return ""
    try:
        return datetime.strptime(stamp, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise _bad_field(("query", alan), "expected a YYYY-MM-DD date")


def _pencerede(satir: dict, bas: str, son: str) -> bool:
    return (not bas or satir["_gun"] >= bas) and (not son or satir["_gun"] <= son)


def _fold(metin: str) -> str:
    """Search key: case- and accent-insensitive, Turkish folded to ASCII so a
    phone keyboard's plain "cay" still finds "Çay 1kg".
    ASSUMPTION: over-matching beats under-matching in a receipt lookup.
    """
    daginik = unicodedata.normalize("NFD", metin.casefold())
    sade = "".join(c for c in daginik if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", sade).replace("ı", "i")


def _terimler(q: str) -> list[str]:
    """Every word has to appear somewhere in the row; their order is free."""
    return [term for term in (_fold(word) for word in q.split()) if term]


def _icerir(satir: dict, terimler: list[str]) -> bool:
    return all(term in satir["_arama"] for term in terimler)


def _sirala(satirlar: list[dict], sort: str, ters: bool) -> list[dict]:
    """Order on one column; a row with nothing in it stays at the bottom
    whichever way the column is read, and the day breaks ties."""
    dolu = [satir for satir in satirlar if satir[sort] is not None]
    bos = [satir for satir in satirlar if satir[sort] is None]
    dolu.sort(key=lambda satir: (satir[sort], satir["_gun"], satir["job_id"]), reverse=ters)
    return dolu + bos


def _session_response(authenticated: bool) -> JSONResponse:
    return JSONResponse({"authenticated": authenticated})


def _issue_cookie(response: JSONResponse, session_id: str) -> None:
    # ASSUMPTION: the panel is same-origin over Tailscale HTTPS (T47), so
    # SameSite=Lax is the CSRF guard and Secure stays off to keep plain-http
    # development on 127.0.0.1 able to set a cookie at all.
    response.set_cookie(
        auth.ADMIN_COOKIE,
        session_id,
        max_age=int(config.admin_session_hours() * 3600),
        path="/admin",
        httponly=True,
        samesite="lax",
    )
