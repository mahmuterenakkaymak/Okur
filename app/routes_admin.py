"""/admin/api/*: the admin panel's own door.

The admin UI is a static shell, so it authenticates with a session cookie
instead of a worker key (PLAN.md decision 6): login compares ADMIN_TOKEN in
constant time and mints a random session id, which the browser stores in an
httpOnly cookie the page can never read. main's guard checks that cookie for
every /admin/api path, so an admin route added later is protected the moment
it is registered.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import auth, config

router = APIRouter(prefix="/admin/api", tags=["admin"])

# The two routes that answer before a session exists; everything else under
# /admin/api is the guard's job.
PUBLIC_PATHS = frozenset({"/admin/api/login", "/admin/api/logout"})


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
