"""/admin/api/*: the admin panel's own door.

The admin UI is a static shell, so it authenticates with a session cookie
instead of a worker key (PLAN.md decision 6): login compares ADMIN_TOKEN in
constant time and mints a random session id, which the browser stores in an
httpOnly cookie the page can never read. main's guard checks that cookie for
every /admin/api path, so an admin route added later is protected the moment
it is registered.
"""
from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import auth, config, db
from app.routes_jobs import _Status, _bad_field, _envelope
from app.routes_worker import _image_path

router = APIRouter(prefix="/admin/api", tags=["admin"])

# The two routes that answer before a session exists; everything else under
# /admin/api is the guard's job.
PUBLIC_PATHS = frozenset({"/admin/api/login", "/admin/api/logout"})

# The table's sortable columns and the exact keys a row answers with, so an
# internal helper key can never reach the browser by accident.
_Sort = Literal["worker", "tarih", "firma", "toplam", "verdict", "kalite_mode"]
_Yon = Literal["asc", "desc"]
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
        row = _job(conn, job_id)
        envelope = _envelope(row)
        envelope["image_url"] = (
            f"/admin/api/jobs/{row['id']}/image" if row["image_path"] else None
        )
        return envelope
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


def _connect(request: Request):
    """One connection per request, same rule as main._connect."""
    return db.connect(request.app.state.db_path)


def _job(conn, job_id: str) -> dict:
    row = db.get_job(conn, job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    return row


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
