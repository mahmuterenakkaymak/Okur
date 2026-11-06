"""/api/me/*: the worker PWA's own views.

Everything here is key-scoped: a worker sees only the jobs submitted with
their own key, and another worker's job does not exist (404, never a 403
that would confirm it does). The list is the contract's lite view — enough
for the PWA history feed — while the detail reuses the full v1 envelope
from routes_jobs, so the PWA parses exactly what integrators parse.
Images are private (KVKK): the bytes leave only through these routes,
behind the same X-API-Key middleware as /v1, thumbnails generated once and
cached under data/thumbs/.
"""
from __future__ import annotations

import io
import json
import pathlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from PIL import Image

from app import config, db
from app.routes_jobs import _envelope

router = APIRouter(prefix="/api/me", tags=["worker"])


@router.get("/jobs")
def list_jobs(request: Request, limit: int = 100, offset: int = 0):
    """Newest first, paged for the PWA history's infinite scroll."""
    key = request.state.key
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conn = _connect(request)
    try:
        rows = db.list_jobs(conn, key_id=key["id"], limit=limit, offset=offset)
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE key_id = ?", (key["id"],)
        ).fetchone()[0]
        return {"jobs": [_lite(row) for row in rows], "total": total}
    finally:
        conn.close()


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    conn = _connect(request)
    try:
        row = _own_job(conn, request.state.key, job_id)
        envelope = _envelope(row)
        envelope["image_url"] = (
            f"/api/me/jobs/{row['id']}/image" if row["image_path"] else None
        )
        # A job that died says why on the worker's failure line; a job with
        # nothing to explain keeps the contract envelope's own keys.
        if row["error"]:
            envelope["error"] = row["error"]
        return envelope
    finally:
        conn.close()


@router.get("/jobs/{job_id}/thumbnail")
def get_thumbnail(request: Request, job_id: str):
    conn = _connect(request)
    try:
        row = _own_job(conn, request.state.key, job_id)
        data = _thumbnail(_image_path(row))
    finally:
        conn.close()
    return Response(content=data, media_type="image/jpeg")


@router.get("/jobs/{job_id}/image")
def get_image(request: Request, job_id: str):
    conn = _connect(request)
    try:
        row = _own_job(conn, request.state.key, job_id)
        path = _image_path(row)
        data = path.read_bytes()
    finally:
        conn.close()
    return Response(content=data, media_type="image/jpeg")


def _connect(request: Request):
    """One connection per request, same rule as main._connect."""
    return db.connect(request.app.state.db_path)


def _own_job(conn, key: dict, job_id: str) -> dict:
    """The row when it belongs to the caller's key; anything else is 404."""
    row = db.get_job(conn, job_id)
    if row is None or row["key_id"] != key["id"]:
        raise HTTPException(404, "job not found")
    return row


def _image_path(row: dict) -> pathlib.Path:
    path = pathlib.Path(row["image_path"])
    if not row["image_path"] or not path.is_file():
        raise HTTPException(404, "image not found")
    return path


def _lite(row: dict) -> dict:
    """Queue row -> lite list item (PLAN.md contract 10).

    verdict/toplam are null until the job is done, and received_at falls
    back to created_at exactly like the full envelope, so a queued job
    still renders.
    """
    meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
    result = json.loads(row["result_json"]) if row["result_json"] else None
    validation = (
        json.loads(row["validation_json"]) if row["validation_json"] else None
    )
    totals = (result or {}).get("totals") or {}
    return {
        "job_id": row["id"],
        "status": row["status"],
        "client_ref": row["client_ref"],
        "received_at": meta.get("received_at") or row["created_at"],
        "thumbnail_url": (
            f"/api/me/jobs/{row['id']}/thumbnail" if row["image_path"] else None
        ),
        "verdict": (validation or {}).get("verdict"),
        "toplam": totals.get("toplam"),
    }


def _thumbnail(path: pathlib.Path) -> bytes:
    """Pillow-resized JPEG, cached per job; undecodable sources pass through."""
    cache = config.data_dir() / "thumbs" / path.name
    if cache.is_file():
        return cache.read_bytes()
    try:
        img = Image.open(path)
        edge = config.thumb_max_edge()
        img.thumbnail((edge, edge))
    except OSError:
        return path.read_bytes()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=config.jpeg_quality())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(buf.getvalue())
    return buf.getvalue()
