"""T59: every endpoint CONTRACT.md names is a route the app actually registers.

The table used to advertise PATCH /v1/jobs/{id}, POST /v1/jobs/{id}/rerun,
GET /v1/export and GET /v1/status; all four ship under /admin/api on the admin
session (PLAN.md decision 6), so the doc is checked against the live route
table instead of trusted.
"""
import re

from app.main import create_app
from scripts import gen_contract_doc

_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")
# ASSUMPTION: a table row is where the doc advertises a door; prose that names an
# absent /v1 route (the versioning note) is documentation, not an endpoint.
_ROW = re.compile(rf"^\| ({'|'.join(_METHODS)}) \| `(/[^`]*)` \|")
_PARAM = re.compile(r"\{[^{}]+\}")

# The doors this task moved: the doc names the shipped admin ones, never /v1.
_ADMIN_DOORS = {
    ("PATCH", "/admin/api/jobs/{id}"),
    ("POST", "/admin/api/jobs/{id}/rerun"),
    ("GET", "/admin/api/export"),
    ("GET", "/admin/api/status"),
}


def _doc_rows() -> list[tuple[str, str]]:
    text = gen_contract_doc.DOC_PATH.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        found = _ROW.match(line)
        if found:
            rows.append((found[1], found[2]))
    return rows


def _app_routes() -> set[tuple[str, str]]:
    # The doc writes {id} where the route names {job_id}, so compare shapes
    # rather than parameter names. openapi() is the route table the app
    # publishes; create_app keeps included routers nested, so app.routes is
    # not flat.
    return {
        (method, _PARAM.sub("{}", path))
        for path, ops in create_app().openapi()["paths"].items()
        for method in _METHODS
        if method.lower() in ops
    }


def test_doc_endpoint_table_is_readable():
    rows = _doc_rows()
    assert rows, "no endpoint row parsed out of CONTRACT.md"
    assert set(rows) >= _ADMIN_DOORS


def test_every_doc_endpoint_is_registered():
    routes = _app_routes()
    missing = [
        f"{method} {path}"
        for method, path in _doc_rows()
        if (method, _PARAM.sub("{}", path)) not in routes
    ]
    assert not missing, "CONTRACT.md advertises unregistered endpoints"
