"""HTTP shell: app factory, auth + rate limit, JSON error envelope, static mounts.

One factory assembles everything (run.py, smokes and tests all call
create_app), so the middleware order — auth before routing, the envelope
around everything — is never reassembled by hand. /v1 and /api/me are the
authenticated surfaces, and auth.authorize already folds key verification and
the per-key token bucket into one verdict, so a single middleware maps
401/429/200 onto responses and hands the key row to routes through
request.state. /admin/api is the other authenticated surface: an admin session
cookie instead of a worker key. Every failure the app can produce (missing
route, bad request, crash, auth) leaves as the same JSON envelope, so
integrators parse one shape.

T46 adds the three outermost layers, in this order from the inside out: the
upload cap (refuse before the body is buffered), the security headers (they
have to cover the auth rejections too) and the request log (one line per
request, whatever it cost or returned).
"""
from __future__ import annotations

import http
import logging
import math
import mimetypes
import os
import re
import sqlite3
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, config, contract, db, routes_admin, routes_jobs, routes_worker

STATIC_DIR = config.ROOT / "static"

REQUEST_LOG = logging.getLogger("app.request")
_JOB_IN_PATH = re.compile(r"/jobs/([^/]+)")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# script/style stay 'unsafe-inline' because the PWA shell carries an inline
# bootstrap block and inline widths (static/app/index.html); everything else
# is same-origin only, which is what stops injected OCR text from executing.
CSP = (
    "default-src 'self'; "
    "img-src 'self' blob: data:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
# swagger-ui arrives from a CDN, so /docs is the one document CSP skips.
CSP_EXEMPT = ("/docs", "/redoc")


def create_app(
    db_path: str | os.PathLike[str] | None = None,
    runner: Any | None = None,
) -> FastAPI:
    """The whole HTTP app; db_path defaults to config.db_path().

    runner is the pipeline seam the quality rerun route calls — QueueWorker's
    shape (image bytes + quality_mode/worker -> bundle); None is pipeline.run.
    """
    app = FastAPI(
        title="OCR API — contract v1",
        version="v1",
        description=(
            "Field-capture receipt OCR. Send `X-API-Key` with every /v1 "
            "call; job envelopes follow contract v1 (JobEnvelope below, "
            "CONTRACT.md for integrators)."
        ),
    )
    app.state.db_path = db_path
    app.state.pipeline_runner = runner
    app.include_router(routes_jobs.router)
    app.include_router(routes_worker.router)
    app.include_router(routes_admin.router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        # ASSUMPTION: the launcher probes /health (unauthenticated liveness);
        # the deep model/queue probe is the /v1/status route (status.py).
        return {"status": "ok"}

    _add_error_envelope(app)
    _add_auth_middleware(app)
    _add_admin_guard(app)
    _add_upload_cap(app)
    _add_security_headers(app)
    _add_request_logging(app)
    _mount_static(app)
    _describe_contract(app)
    return app


def _connect(app: FastAPI) -> sqlite3.Connection:
    """One connection per request: sqlite forbids sharing across threads,
    and opening is cheap at this scale."""
    return db.connect(app.state.db_path)


def _add_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        if not request.url.path.startswith(("/v1", "/api")):
            return await call_next(request)
        conn = _connect(app)
        try:
            status, row, retry_after = auth.authorize(
                conn, request.headers.get("X-API-Key", "")
            )
        finally:
            conn.close()
        if status == 401:
            return _error(401, "unauthorized", "missing or invalid API key")
        if status == 429:
            response = _error(429, "rate_limited", "too many requests, slow down")
            response.headers["Retry-After"] = str(math.ceil(retry_after))
            return response
        request.state.key = row
        return await call_next(request)


def _add_admin_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def admin_session(request: Request, call_next):
        # By prefix, so every /admin/api route is protected the moment it is
        # registered; the static shell under /admin stays public (no data).
        path = request.url.path
        if not path.startswith("/admin/api/") or path in routes_admin.PUBLIC_PATHS:
            return await call_next(request)
        if auth.session_ok(request.cookies.get(auth.ADMIN_COOKIE, "")):
            return await call_next(request)
        return _error(401, "unauthorized", "admin session required")


def _add_upload_cap(app: FastAPI) -> None:
    @app.middleware("http")
    async def upload_cap(request: Request, call_next):
        # The declared length refuses an oversize upload before a single byte
        # is buffered; routes_jobs repeats the check on the bytes it actually
        # read, because a chunked upload carries no Content-Length at all.
        declared = request.headers.get("content-length", "")
        limit = config.max_upload_mb() * 1024 * 1024
        if declared.isdigit() and int(declared) > limit:
            return _error(413, "payload_too_large", routes_jobs.too_large_message())
        return await call_next(request)


def _add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.url.path not in CSP_EXEMPT:
            response.headers["Content-Security-Policy"] = CSP
        return response


def _add_request_logging(app: FastAPI) -> None:
    _configure_request_log()

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # a crash that outlives every handler still gets its line
            _log_request(request, started, 500)
            raise
        _log_request(request, started, response.status_code)
        return response


def _configure_request_log() -> None:
    """uvicorn leaves the root logger alone, so the request line asks for it.

    basicConfig only attaches a stream when none exists (pytest already has
    one), and run.py appends this process's stderr to data/logs/app.log.
    """
    logging.basicConfig(format="%(asctime)s %(message)s")
    REQUEST_LOG.setLevel(logging.INFO)


def _log_request(request: Request, started: float, status: int) -> None:
    key = getattr(request.state, "key", None) or {}
    REQUEST_LOG.info(
        "%s %s %d %dms job=%s worker=%s",
        request.method,
        request.url.path,
        status,
        round((time.perf_counter() - started) * 1000),
        _job_id(request),
        key.get("worker", "-"),
    )


def _job_id(request: Request) -> str:
    """The id this request is about: the route's own when it created one,
    otherwise the one in the path."""
    job_id = getattr(request.state, "job_id", None)
    if job_id:
        return str(job_id)
    match = _JOB_IN_PATH.search(request.url.path)
    return match.group(1) if match else "-"


def _error(
    status_code: int, code: str, message: str, details: list | None = None
) -> JSONResponse:
    # ASSUMPTION: PLAN.md freezes the success envelope but not the failure
    # shape; {"error": {code, message, details?}} is this API's one shape.
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def _add_error_envelope(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, _code_for(exc.status_code), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"]),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return _error(
            422, "validation_error", "request did not match the schema", details
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # T46: the traceback belongs to the log, never to the response — it
        # would hand a caller our internals with every crash.
        REQUEST_LOG.exception(
            "%s %s failed: %s", request.method, request.url.path, exc
        )
        return _error(500, "internal_error", "unexpected server error")


def _code_for(status_code: int) -> str:
    # 413's phrase is "Content Too Long" on 3.12 and "Request Entity Too
    # Large" on 3.11, so the integrator-facing code is pinned instead.
    if status_code == 413:
        return "payload_too_large"
    try:
        return http.HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "error"


def _mount_static(app: FastAPI) -> None:
    # The PWA and admin bundles arrive in M2/M3; the directories are created
    # on first boot so a fresh clone still starts.
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    for name in ("app", "admin"):
        directory = STATIC_DIR / name
        directory.mkdir(parents=True, exist_ok=True)
        app.mount(f"/{name}", StaticFiles(directory=directory, html=True), name=name)


def _describe_contract(app: FastAPI) -> None:
    # The routes answer with contract dicts, so the frozen envelope and the
    # X-API-Key scheme go straight into the OpenAPI document for /docs.
    spec = app.openapi()
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    schemas["JobEnvelope"] = contract.JobEnvelope.model_json_schema()
    spec["components"]["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
    spec["security"] = [{"ApiKeyAuth": []}]
    spec["paths"]["/health"]["get"]["security"] = []
