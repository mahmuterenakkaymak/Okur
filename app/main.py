"""HTTP shell: app factory, /v1 auth + rate limit, JSON error envelope, static mounts.

One factory assembles everything (run.py, smokes and tests all call
create_app), so the middleware order — auth before routing, the envelope
around everything — is never reassembled by hand. /v1 and /api/me are the
authenticated surfaces, and auth.authorize already folds key verification and
the per-key token bucket into one verdict, so a single middleware maps
401/429/200 onto responses and hands the key row to routes through
request.state. Every failure the app can produce (missing route, bad request,
crash, auth) leaves as the same JSON envelope, so integrators parse one shape.
"""
from __future__ import annotations

import http
import math
import os
import sqlite3
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import auth, config, contract, db, routes_jobs, routes_worker

STATIC_DIR = config.ROOT / "static"


def create_app(db_path: str | os.PathLike[str] | None = None) -> FastAPI:
    """The whole HTTP app; db_path defaults to config.db_path()."""
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
    app.include_router(routes_jobs.router)
    app.include_router(routes_worker.router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        # ASSUMPTION: the launcher probes /health (unauthenticated liveness);
        # the deep model/queue probe is the /v1/status route (status.py).
        return {"status": "ok"}

    _add_error_envelope(app)
    _add_auth_middleware(app)
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
        return _error(500, "internal_error", "unexpected server error")


def _code_for(status_code: int) -> str:
    try:
        return http.HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "error"


def _mount_static(app: FastAPI) -> None:
    # The PWA and admin bundles arrive in M2/M3; the directories are created
    # on first boot so a fresh clone still starts.
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
