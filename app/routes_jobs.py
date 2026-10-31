"""POST/GET /v1/jobs: intake, idempotency and the contract v1 views.

A POST is an enqueue, not a computation: the image lands under
data/images/<job_id>.jpg, the row goes queued and 202 says "accepted" —
the envelope matures as the worker writes and every GET re-reads it.
Idempotency is UNIQUE(key_id, client_ref): a retry carrying a ref this key
already used answers 200 with the existing job instead of queueing a second
OCR run. No route here reshapes anything — every body is one
contract.JobEnvelope, so integrators parse the frozen contract everywhere.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import config, contract, db

Mode = Literal["fast", "quality"]
_Status = Literal["queued", "running", "done", "failed"]

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.post("/jobs", status_code=202)
def create_job(
    request: Request,
    image: UploadFile = File(...),
    mode: Mode = Form(db.DEFAULT_MODE),
    client_ref: str | None = Form(None),
    captured_at: str | None = Form(None),
):
    data = image.file.read()
    if not data:
        raise _bad_field(("body", "image"), "image is empty")
    client_ref = client_ref.strip() if client_ref and client_ref.strip() else None
    captured_at = _clean_iso(captured_at, ("body", "captured_at"))
    key = request.state.key
    conn = _connect(request)
    try:
        existing = db.find_job_by_client_ref(conn, key["id"], client_ref)
        if existing is not None:
            return JSONResponse(status_code=200, content=_envelope(existing))
        try:
            job = db.create_job(
                conn,
                key_id=key["id"],
                worker=key["worker"],
                client_ref=client_ref,
                mode=mode,
            )
        except sqlite3.IntegrityError:
            raced = db.find_job_by_client_ref(conn, key["id"], client_ref)
            if raced is None:
                raise
            return JSONResponse(status_code=200, content=_envelope(raced))
        path = config.images_dir() / f"{job['id']}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        updates = {"image_path": str(path)}
        if captured_at:
            # ASSUMPTION: captured_at is not a queue column, so it rides in
            # meta_json; the worker replaces meta_json on completion (T13),
            # after which the envelope reports it as null.
            updates["meta_json"] = {"captured_at": captured_at}
        return _envelope(db.update_job(conn, job["id"], **updates))
    finally:
        conn.close()


@router.get("/jobs")
def list_jobs(
    request: Request,
    status: _Status | None = Query(None),
    worker: str | None = Query(None),
    since: str | None = Query(None),
    mine: bool = Query(False),
):
    key = request.state.key
    conn = _connect(request)
    try:
        rows = db.list_jobs(
            conn,
            status=status,
            worker=worker,
            key_id=key["id"] if mine else None,
            since=_clean_iso(since, ("query", "since")),
        )
        return [_envelope(row) for row in rows]
    finally:
        conn.close()


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    conn = _connect(request)
    try:
        row = db.get_job(conn, job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        return _envelope(row)
    finally:
        conn.close()


def _connect(request: Request):
    """One connection per request, same rule as main._connect."""
    return db.connect(request.app.state.db_path)


def _envelope(row: dict) -> dict:
    """Queue row -> contract v1 envelope.

    meta falls back to the row's own identity fields, so a job that has not
    been touched by the worker yet still reports worker and received_at.
    """
    meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
    meta.setdefault("worker", row["worker"])
    meta.setdefault("received_at", row["created_at"])
    return contract.JobEnvelope.parse(
        {
            "job_id": row["id"],
            "status": row["status"],
            "client_ref": row["client_ref"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "validation": (
                json.loads(row["validation_json"])
                if row["validation_json"]
                else None
            ),
            "meta": meta,
        }
    ).model_dump()


def _clean_iso(value: str | None, field: tuple[str, ...]) -> str | None:
    if not value or not value.strip():
        return None
    stamp = value.strip()
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        raise _bad_field(field, "is not an ISO-8601 timestamp")
    return stamp


def _bad_field(field: tuple[str, ...], message: str) -> RequestValidationError:
    """Manual 422s leave through the same validation_error envelope."""
    return RequestValidationError(
        [{"loc": field, "msg": message, "type": "value_error"}], body=None
    )
