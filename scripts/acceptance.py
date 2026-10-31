"""Brief section 9's automatable acceptance checks, run against a live instance.

--demo boots the demo stack (real app, real auth, real queue, fake model stubs)
on an ephemeral port; without it the same checks run against an instance that
is already up, whose worker key comes from --api-key or OCR_ACCEPTANCE_KEY (only
a demo instance still hands one out over /demo/config.json). Each check prints
one row of a table as it finishes and the run exits 1 when any row is FAIL, so
the operator, run.py and CI gate on one command.

    .venv/Scripts/python scripts/acceptance.py --demo
    .venv/Scripts/python scripts/acceptance.py --base-url http://127.0.0.1:8090 --api-key ocrk_…
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import jsonschema
from openpyxl import load_workbook

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # direct `python scripts/acceptance.py`
    sys.path.insert(0, str(ROOT))

from app import config, contract, validator  # noqa: E402
from scripts import serve_demo  # noqa: E402

FIXTURE = "fis_market_clean"
TAMPERED_KDV = 999.99
DEMO_ADMIN_TOKEN = "acceptance-admin"
POLL_TIMEOUT_S = 60.0
AMOUNTS = ("ara_toplam", "iskonto", "kdv", "toplam")
# fresh refs per run, so a rerun against a live instance is not its own retry
RUN = uuid.uuid4().hex[:8]
SCHEMA = json.loads(contract.SCHEMA_PATH.read_text(encoding="utf-8"))
TRUTH = json.loads(
    (config.ROOT / "fixtures" / f"{FIXTURE}.json").read_text(encoding="utf-8")
)


class CheckError(RuntimeError):
    """What a check expected and did not get; its message is the row's detail."""


# --- the instance under test -------------------------------------------------


class Instance:
    """A running app plus the two identities the checks knock on its doors with."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.api = httpx.Client(base_url=base_url, timeout=30.0)
        self._admin: httpx.Client | None = None

    def close(self) -> None:
        self.api.close()
        if self._admin is not None:
            self._admin.close()

    def admin(self) -> httpx.Client:
        """The admin session, logged in on first use (corrections, exports, keys)."""
        if self._admin is None:
            client = httpx.Client(base_url=self.base_url, timeout=30.0)
            resp = client.post("/admin/api/login", json={"token": config.admin_token()})
            if resp.status_code != 200:
                client.close()
                raise CheckError(
                    f"admin login -> HTTP {resp.status_code}: {_reason(resp)}; "
                    "the instance needs ADMIN_TOKEN"
                )
            self._admin = client
        return self._admin

    def get(self, path: str, **params: Any) -> httpx.Response:
        return self.api.get(path, headers={"X-API-Key": self.api_key}, **params)

    def submit(self, client_ref: str) -> httpx.Response:
        png = config.ROOT / "fixtures" / f"{FIXTURE}.png"
        return self.api.post(
            "/v1/jobs",
            headers={"X-API-Key": self.api_key},
            files={"image": (png.name, png.read_bytes(), "image/png")},
            data={"client_ref": client_ref},
        )

    def envelope(self, resp: httpx.Response) -> dict:
        """A response body that has to be contract v1."""
        body = _body(resp)
        try:
            jsonschema.validate(body, SCHEMA)
        except jsonschema.ValidationError as exc:
            raise CheckError(
                f"HTTP {resp.status_code} body breaks contract v1: {exc.message}"
            ) from exc
        return body

    def job_to_done(self, client_ref: str) -> dict:
        """A fresh fixture job, every envelope on the way contract v1."""
        body = self.envelope(self.submit(client_ref))
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while body["status"] not in ("done", "failed"):
            if time.monotonic() > deadline:
                raise CheckError(
                    f"job stuck in {body['status']} after {POLL_TIMEOUT_S:.0f}s"
                )
            time.sleep(0.1)
            body = self.envelope(self.get(f"/v1/jobs/{body['job_id']}"))
        if body["status"] != "done":
            raise CheckError(f"job {body['job_id'][:8]} failed in the queue")
        return body


# --- the checks (brief section 9, the automatable ones) ----------------------


def check_contract(inst: Instance) -> str:
    """9.2: a valid key's upload is a 202 and its envelopes are contract v1."""
    accepted = inst.envelope(inst.submit(f"{RUN}-contract"))
    if accepted["status"] != "queued":
        raise CheckError(f"a fresh job is {accepted['status']}, expected queued")
    inst.envelope(inst.get(f"/v1/jobs/{accepted['job_id']}"))
    return "POST 202 and GET envelopes validate against contract_v1.schema.json"


def check_verdict_ok(inst: Instance) -> str:
    """9.2: the fixture comes back verdict ok with the ground-truth amounts."""
    body = inst.job_to_done(f"{RUN}-verdict")
    block = body["validation"] or {}
    if block.get("verdict") != "ok" or block.get("fields"):
        raise CheckError(f"verdict {block.get('verdict')!r} on {block.get('fields')}")
    result = body["result"] or {}
    if result.get("items") != TRUTH["items"] or result.get("totals") != TRUTH["totals"]:
        raise CheckError("items or totals differ from the fixture ground truth")
    return f"{FIXTURE} -> ok, fields [], amounts match ground truth"


def check_tampered_kdv(inst: Instance) -> str:
    """9.3: a wrong KDV ends up as mismatch naming the field it got wrong."""
    job_id = inst.job_to_done(f"{RUN}-kdv")["job_id"]
    resp = inst.admin().patch(
        f"/admin/api/jobs/{job_id}", json={"fields": {"totals.kdv": TAMPERED_KDV}}
    )
    if resp.status_code != 200:
        raise CheckError(f"PATCH totals.kdv -> HTTP {resp.status_code}: {_reason(resp)}")
    block = inst.envelope(inst.get(f"/v1/jobs/{job_id}"))["validation"] or {}
    if block.get("verdict") != "mismatch" or block.get("fields") != ["totals.kdv"]:
        raise CheckError(f"verdict {block.get('verdict')!r} fields {block.get('fields')}")
    expected, actual = block["expected"]["kdv"], block["actual"]["kdv"]
    if expected != TRUTH["totals"]["kdv"] or actual != TAMPERED_KDV:
        raise CheckError(f"expected {expected} actual {actual}")
    return f"mismatch names totals.kdv; recomputed {expected:.2f} vs printed {actual:.2f}"


def check_auth(inst: Instance) -> str:
    """9.4: no key or an unknown key is 401, an exhausted bucket is 429."""
    _expect(inst.api.get("/v1/jobs"), 401, "anonymous GET")
    _expect(
        inst.api.get("/v1/jobs", headers={"X-API-Key": "ocrk_" + "0" * 40}),
        401,
        "unknown key",
    )
    key_id, plaintext = _issue_key(inst)
    ceiling = 3 * config.rate_capacity() + 10
    for hits in range(1, ceiling + 1):
        resp = inst.api.get("/v1/jobs", headers={"X-API-Key": plaintext})
        if resp.status_code == 429:
            break
        _expect(resp, 200, f"hit {hits} on a fresh key")
    else:
        raise CheckError(
            f"no 429 within {ceiling} calls (capacity {config.rate_capacity()})"
        )
    retry_after = resp.headers.get("Retry-After", "")
    if not retry_after:
        raise CheckError("429 without a Retry-After header")
    inst.admin().post(f"/admin/api/keys/{key_id}/revoke")  # leave no live credential
    return f"401 anonymous + unknown, 429 after {hits} calls (Retry-After {retry_after}s)"


def check_idempotent(inst: Instance) -> str:
    """9.5: one client_ref is one job, and the retry names the existing id."""
    ref = f"{RUN}-ref"
    first = inst.submit(ref)
    _expect(first, 202, "first POST")
    job_id = inst.envelope(first)["job_id"]
    again = inst.submit(ref)
    _expect(again, 200, "retried POST")
    retried = inst.envelope(again)["job_id"]
    if retried != job_id:
        raise CheckError(f"the retry queued {retried[:8]} instead of {job_id[:8]}")
    rows = _body(inst.get("/v1/jobs", params={"mine": "true"}))
    same = [row for row in rows if row["client_ref"] == ref]
    if len(same) != 1:
        raise CheckError(f"{len(same)} jobs carry client_ref {ref!r}")
    return f"retry -> 200 with job {job_id[:8]}; exactly one job on the ref"


def check_export_parity(inst: Instance) -> str:
    """9.8: the selected ids are exactly the rows, amounts carried as numbers."""
    wanted = {}
    for index in (1, 2):
        body = inst.job_to_done(f"{RUN}-export-{index}")
        wanted[body["job_id"]] = body["result"]["totals"]
    admin = inst.admin()
    rows = _csv_rows(
        _ok(
            admin.get("/admin/api/export", params={"ids": ",".join(wanted), "format": "csv"}),
            "GET export?format=csv",
        ).content
    )
    _exact(rows, wanted, "csv")
    for row in rows:
        for field in AMOUNTS:
            printed = wanted[row["job_id"]][field]
            if abs(float(row[field]) - printed) > 0.005:
                raise CheckError(f"csv {field} {row[field]} != envelope {printed}")
    cells = _xlsx_rows(
        load_workbook(
            io.BytesIO(
                _ok(
                    admin.get(
                        "/admin/api/export",
                        params={"ids": ",".join(wanted), "format": "xlsx"},
                    ),
                    "GET export?format=xlsx",
                ).content
            )
        ).active
    )
    _exact(cells, wanted, "xlsx")
    for cell in cells:
        for field in AMOUNTS:
            if not isinstance(cell[field], (int, float)):
                raise CheckError(
                    f"xlsx {field} is {type(cell[field]).__name__}, not a number"
                )
    return f"csv + xlsx: exactly the {len(wanted)} selected ids, amounts numeric"


def check_validator_edges(_inst: Instance) -> str:
    """9.10: discount, mixed KDV rates and the currency forms a receipt prints."""
    for name, result, verdict, fields in EDGE_CASES:
        report = validator.validate(result)
        if report["verdict"] != verdict or report["fields"] != fields:
            raise CheckError(
                f"{name}: {report['verdict']} {report['fields']}, "
                f"expected {verdict} {fields}"
            )
    return f"{len(EDGE_CASES)} cases: iskonto, mixed KDV rates, TL and ₺, unreadable"


_DISCOUNT = {
    "items": [{"ad": "Süt 1L", "miktar": 2, "birim_fiyat": 50.0, "toplam": 100.0}],
    "totals": {
        "ara_toplam": 100.0,
        "iskonto": 10.0,
        "kdv": 18.0,
        "kdv_orani": 0.2,
        "toplam": 108.0,
    },
}
# Ekmek is KDV %10 and şarap %20, so the receipt has no single kdv_orani and the
# printed kdv (3,00 + 40,00) is the chain input the validator ties toplam to.
_MIXED_RATES = {
    "items": [
        {"ad": "Ekmek", "miktar": 2, "birim_fiyat": 15.0, "toplam": 30.0},
        {"ad": "Şarap", "miktar": 1, "birim_fiyat": 200.0, "toplam": 200.0},
    ],
    "totals": {
        "ara_toplam": 230.0,
        "iskonto": 0.0,
        "kdv": 43.0,
        "kdv_orani": 0.0,
        "toplam": 273.0,
    },
}
_CURRENCY = {
    "items": [
        {
            "ad": "Zeytinyağı 1L",
            "miktar": "2",
            "birim_fiyat": "523,20 TL",
            "toplam": "1.046,40 TL",
        }
    ],
    "totals": {
        "ara_toplam": "1.046,40 TL",
        "iskonto": "₺52,32",
        "kdv": "198,82 TL",
        "kdv_orani": "%20",
        "toplam": "1.192,90 TL",
    },
}


def _variant(base: dict, *, line: tuple[int, float] | None = None, **totals: float) -> dict:
    """A copy of a receipt with one line's printed total and/or totals changed."""
    items = [dict(row) for row in base["items"]]
    if line is not None:
        items[line[0]]["toplam"] = line[1]
    return {"items": items, "totals": {**base["totals"], **totals}}


EDGE_CASES = (
    ("iskonto indirimi", _DISCOUNT, "ok", []),
    ("iskonto toplama yansımamış", _variant(_DISCOUNT, toplam=118.0), "mismatch", ["totals.toplam"]),
    ("çok oranlı fiş", _MIXED_RATES, "ok", []),
    # the printed line total disagrees with miktar x birim_fiyat; the validator
    # recomputes ara_toplam from the products, so the totals still tie
    (
        "çok oranlı, satır toplamı yanlış",
        _variant(_MIXED_RATES, line=(1, 210.0)),
        "mismatch",
        ["items[1].toplam"],
    ),
    ("TL ve ₺ biçimleri", _CURRENCY, "ok", []),
    ("boş fiş", {"items": [], "totals": {}}, "unreadable", []),
)

CHECKS = (
    ("contract v1 schema", check_contract),
    ("verdict ok", check_verdict_ok),
    ("tampered KDV mismatch", check_tampered_kdv),
    ("401 + 429", check_auth),
    ("idempotent client_ref", check_idempotent),
    ("export row parity", check_export_parity),
    ("validator edge suite", check_validator_edges),
)
WIDTH = max(len(name) for name, _ in CHECKS)


# --- small helpers ----------------------------------------------------------


def _issue_key(inst: Instance) -> tuple[int, str]:
    """A throwaway key for the rate-limit run, minted through the admin door."""
    resp = inst.admin().post("/admin/api/keys", json={"worker": "acceptance"})
    if resp.status_code != 200:
        raise CheckError(f"POST /admin/api/keys -> HTTP {resp.status_code}: {_reason(resp)}")
    return resp.json()["key_id"], resp.json()["key"]


def _expect(resp: httpx.Response, status: int, what: str) -> None:
    if resp.status_code != status:
        raise CheckError(
            f"{what} -> HTTP {resp.status_code}, expected {status}: {_reason(resp)}"
        )


def _ok(resp: httpx.Response, what: str) -> httpx.Response:
    if resp.status_code >= 300:  # 202 (an accepted upload) and 200 both answer fine
        raise CheckError(f"{what} -> HTTP {resp.status_code}: {_reason(resp)}")
    return resp


def _body(resp: httpx.Response) -> Any:
    return _ok(resp, f"{resp.request.method} {resp.request.url.path}").json()


def _reason(resp: httpx.Response) -> str:
    """The server's own failure text, so a FAIL row says what the app said."""
    try:
        return str(resp.json()["error"]["message"])[:120]
    except (ValueError, KeyError, TypeError):
        return resp.text[:120]


def _csv_rows(payload: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))


def _xlsx_rows(sheet) -> list[dict]:
    rows = list(sheet.iter_rows(values_only=True))
    head = [str(cell) for cell in rows[0]]
    return [dict(zip(head, row)) for row in rows[1:]]


def _exact(rows: list[dict], wanted: dict[str, dict], fmt: str) -> None:
    if len(rows) != len(wanted) or {row["job_id"] for row in rows} != set(wanted):
        raise CheckError(
            f"{fmt} has {len(rows)} rows, expected exactly the {len(wanted)} selected ids"
        )


# --- the run ----------------------------------------------------------------


def _boot_demo() -> tuple[Instance, Callable[[], None]]:
    """The demo stack on an ephemeral port: real app and queue, stubbed models."""
    workdir = tempfile.TemporaryDirectory(
        prefix="ocr-acceptance-", ignore_cleanup_errors=True
    )
    # Corrections and exports are checked through the admin door, so a demo
    # nobody configured still has to have one.
    os.environ.setdefault("ADMIN_TOKEN", DEMO_ADMIN_TOKEN)
    server, worker, models, api_key = serve_demo._boot(pathlib.Path(workdir.name), 0)

    def teardown() -> None:
        worker.stop()
        models.shutdown()
        workdir.cleanup()

    return Instance(serve_demo._url(server), api_key), teardown


def _live(base_url: str, api_key: str) -> Instance:
    """An instance that is already up, keyed the way the operator keyed it.

    A real deployment has no /demo/config.json — only serve_demo serves one —
    so --api-key/OCR_ACCEPTANCE_KEY is the way in and the demo endpoint is the
    fallback that keeps a bare --base-url working against a demo stack.
    """
    if api_key:
        return Instance(base_url, api_key)
    try:
        resp = httpx.get(f"{base_url}/demo/config.json", timeout=10.0)
        resp.raise_for_status()
        return Instance(base_url, resp.json()["api_key"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise CheckError(
            f"{base_url} has no /demo/config.json to read a key from and no "
            f"--api-key (or OCR_ACCEPTANCE_KEY) was given: {exc}"
        )


def _attempt(check, inst: Instance) -> tuple[bool, str]:
    try:
        return True, check(inst)
    except (CheckError, httpx.HTTPError) as exc:
        return False, str(exc)


def _row(rows: list, name: str, ok: bool, detail: str) -> None:
    rows.append((name, ok, detail))
    print(f"{name.ljust(WIDTH)}  {'PASS' if ok else 'FAIL'}  {detail}", flush=True)


def _summary(rows: list, started: float) -> int:
    failed = [name for name, ok, _ in rows if not ok]
    print("-" * (WIDTH + 8), flush=True)
    print(
        f"{len(rows) - len(failed)}/{len(rows)} checks passed in {time.monotonic() - started:.1f}s"
        + (f" — failed: {', '.join(failed)}" if failed else ""),
        flush=True,
    )
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Brief section 9 acceptance checks against a running instance."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="boot the demo stack (fake model stubs) on an ephemeral port and check it",
    )
    parser.add_argument(
        "--base-url",
        default=config.app_base_url(),
        help="an instance that is already up (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=config.env_str("OCR_ACCEPTANCE_KEY"),
        help="worker key for --base-url (default: $OCR_ACCEPTANCE_KEY, else the demo handshake)",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    target = "a booted demo instance" if args.demo else args.base_url
    print(f"acceptance — brief 9 checks against {target}", flush=True)
    print(f"{'check'.ljust(WIDTH)}  result  detail", flush=True)
    rows: list[tuple[str, bool, str]] = []
    try:
        inst, teardown = (
            _boot_demo() if args.demo else (_live(args.base_url, args.api_key), None)
        )
    except Exception as exc:  # nothing to check until the app answers
        _row(rows, "instance up", False, str(exc))
        return _summary(rows, started)
    try:
        for name, check in CHECKS:
            _row(rows, name, *_attempt(check, inst))
    finally:
        inst.close()
        if teardown is not None:
            teardown()
    return _summary(rows, started)


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        # the rows carry Turkish; a cp1252 console would kill the print
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
