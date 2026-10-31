"""T38 — exports: one row per submission, three formats, one story.

The corpus is the demo seed again, because an export is only worth testing
against receipts that genuinely differ: an ok one with amounts, a mismatched
one a reviewer can correct, an unreadable one with nothing to total, and jobs
still sitting in the queue. Each format is then read back with its own reader
— csv, openpyxl, json — rather than trusted from the bytes written here.
"""
from __future__ import annotations

import csv
import datetime
import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import auth, db, exports
from app.contract import JobEnvelope
from app.main import create_app
from scripts import serve_demo

ANAHTAR = "yonetici-anahtari-9f2e"
BOM = b"\xef\xbb\xbf"
# PLAN.md contract 8, in the order its columns are listed.
SUTUNLAR = (
    "job_id", "worker", "client_ref", "tarih", "saat", "firma", "vergi_no",
    "ara_toplam", "iskonto", "kdv", "toplam", "para_birimi", "verdict",
    "items_json", "kalite_mode", "gonderim_zamani",
)
BICIMLER = ("json", "csv", "xlsx")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A demo-seeded database, an admin session and the worker's own key."""
    auth._sessions.clear()
    auth._buckets.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, api_key = auth.create_key(conn, serve_demo.WORKER)
    jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn, {job["client_ref"]: job for job in jobs}, api_key
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def turce(deger: float) -> str:
    """An amount the way a reviewer types it: 1192.9 -> "1192,90"."""
    return f"{deger:.2f}".replace(".", ",")


def indir(client, **params):
    yanit = client.get("/admin/api/export", params=params)
    assert yanit.status_code == 200, yanit.text
    return yanit


def _sayfa(yanit):
    return load_workbook(io.BytesIO(yanit.content)).active


def csv_satirlari(yanit) -> list[dict]:
    assert yanit.content.startswith(BOM), "Excel reads Turkish only from a BOM"
    alanlar, *setirler = csv.reader(io.StringIO(yanit.content.decode("utf-8-sig")))
    assert tuple(alanlar) == exports.FIELDS
    return [dict(zip(alanlar, setir)) for setir in setirler]


def xlsx_satirlari(yanit) -> list[dict]:
    satirlar = list(_sayfa(yanit).iter_rows(values_only=True))
    assert tuple(satirlar[0]) == exports.FIELDS
    return [dict(zip(satirlar[0], satir)) for satir in satirlar[1:]]


def kimler(client, bicim: str, **params) -> set[str]:
    """The jobs one export covers, whichever format it arrived in."""
    yanit = indir(client, format=bicim, **params)
    if bicim == "json":
        return {sarmal["job_id"] for sarmal in yanit.json()}
    satirlar = csv_satirlari(yanit) if bicim == "csv" else xlsx_satirlari(yanit)
    return {satir["job_id"] for satir in satirlar}


# --- the row itself ---


def test_the_export_row_is_exactly_the_contract_8_columns(env):
    client, _, jobs, _ = env
    hedef = jobs["demo-fis_market_clean"]
    assert exports.FIELDS == SUTUNLAR
    satir = exports.row(hedef)
    assert tuple(satir) == exports.FIELDS
    assert satir["verdict"] == "ok" and satir["kalite_mode"] is False
    assert satir["gonderim_zamani"] == hedef["created_at"]


# --- json: the contract, not a report ---


def test_json_answers_with_contract_v1_envelopes(env):
    client, _, jobs, _ = env
    govde = indir(client, format="json").json()
    assert len(govde) == len(jobs)
    for sarmal in govde:
        JobEnvelope.model_validate(sarmal)
    market = next(s for s in govde if s["job_id"] == jobs["demo-fis_market_clean"]["id"])
    assert market["status"] == "done"
    assert market["client_ref"] == "demo-fis_market_clean"
    assert market["result"]["totals"]["toplam"] == 1192.9
    assert market["validation"]["verdict"] == "ok"
    bekleyen = next(s for s in govde if s["job_id"] == jobs["demo-fis_benzin_clean"]["id"])
    assert bekleyen["status"] == "queued" and bekleyen["result"] is None


# --- csv and xlsx: the flat row, one column per contract key ---


def test_csv_carries_the_contract_header_and_one_row_per_submission(env):
    client, _, jobs, _ = env
    satirlar = csv_satirlari(indir(client))  # csv is the default format
    assert len(satirlar) == len(jobs)
    assert {satir["job_id"] for satir in satirlar} == {job["id"] for job in jobs.values()}


def test_a_receipt_lands_in_csv_exactly_as_the_contract_row_reads_it(env):
    client, _, jobs, _ = env
    hedef = jobs["demo-fis_market_clean"]
    satir = next(s for s in csv_satirlari(indir(client)) if s["job_id"] == hedef["id"])
    assert satir["worker"] == serve_demo.WORKER
    assert satir["client_ref"] == hedef["client_ref"]
    assert satir["firma"] == "BILGIN MARKETLER ANONIM SIRKETI"
    assert satir["vergi_no"] == "1234567890"
    assert satir["tarih"] == "28.10.2026" and satir["saat"] == "14:32"
    assert satir["ara_toplam"] == "1046.4" and satir["iskonto"] == "52.32"
    assert satir["kdv"] == "198.82" and satir["toplam"] == "1192.9"
    assert satir["para_birimi"] == "TRY" and satir["verdict"] == "ok"
    assert satir["kalite_mode"] == "false"
    assert satir["gonderim_zamani"] == hedef["created_at"]
    assert json.loads(satir["items_json"])[2] == {
        "ad": "Zeytinyağı 1L", "miktar": 1.0, "birim_fiyat": 285.0, "toplam": 285.0
    }


def test_xlsx_writes_amounts_as_real_numbers_under_a_bold_header(env):
    client, _, jobs, _ = env
    yanit = indir(client, format="xlsx")
    assert "spreadsheetml.sheet" in yanit.headers["content-type"]
    sayfa = _sayfa(yanit)
    assert sayfa.freeze_panes == "A2"
    assert all(hucre.font.bold for hucre in sayfa[1])
    hedef = next(
        sira
        for sira, hucre in enumerate(sayfa["A"], start=1)
        if hucre.value == jobs["demo-fis_market_clean"]["id"]
    )
    for sira, alan in enumerate(exports.FIELDS, start=1):
        hucre = sayfa.cell(row=hedef, column=sira)
        if alan in exports.AMOUNTS:
            assert isinstance(hucre.value, float), alan
            assert hucre.number_format == "0.00", alan
        else:
            assert not isinstance(hucre.value, float), alan
    assert sayfa.cell(row=hedef, column=exports.FIELDS.index("toplam") + 1).value == 1192.9


def test_turkish_survives_both_spreadsheet_formats(env):
    client, _, jobs, _ = env
    hedef = jobs["demo-fis_market_clean"]["id"]
    assert "Zeytinyağı 1L".encode("utf-8") in indir(client, format="csv").content
    satir = next(
        s for s in xlsx_satirlari(indir(client, format="xlsx")) if s["job_id"] == hedef
    )
    assert satir["firma"] == "BILGIN MARKETLER ANONIM SIRKETI"
    assert "Zeytinyağı 1L" in satir["items_json"]


def test_a_receipt_with_nothing_read_off_exports_no_amounts(env):
    client, _, jobs, _ = env
    xlsx = {satir["job_id"]: satir for satir in xlsx_satirlari(indir(client, format="xlsx"))}
    csvv = {satir["job_id"]: satir for satir in csv_satirlari(indir(client, format="csv"))}
    for ref in ("demo-el_yazisi_liste", "demo-fis_benzin_clean", "demo-fis_kotu_cekim"):
        hedef = jobs[ref]["id"]
        assert all(xlsx[hedef][alan] is None for alan in exports.AMOUNTS), ref
        assert all(csvv[hedef][alan] == "" for alan in exports.AMOUNTS), ref
        assert not xlsx[hedef]["firma"] and not csvv[hedef]["firma"], ref


def test_the_quality_mode_flag_reaches_all_three_formats(env):
    client, conn, jobs, _ = env
    hedef = jobs["demo-fis_market_clean"]
    db.update_job(conn, hedef["id"], mode="quality", meta_json={"quality_mode": True})
    assert next(
        s for s in csv_satirlari(indir(client, format="csv")) if s["job_id"] == hedef["id"]
    )["kalite_mode"] == "true"
    assert next(
        s for s in xlsx_satirlari(indir(client, format="xlsx")) if s["job_id"] == hedef["id"]
    )["kalite_mode"] is True
    sarmal = next(
        s for s in indir(client, format="json").json() if s["job_id"] == hedef["id"]
    )
    assert sarmal["meta"]["quality_mode"] is True
    assert all(
        satir["kalite_mode"] == "false"
        for satir in csv_satirlari(indir(client, format="csv"))
        if satir["job_id"] != hedef["id"]
    )


# --- one correction, three agreeing formats ---


def test_a_corrected_receipt_exports_corrected_in_every_format(env):
    client, _, jobs, _ = env
    job = jobs["demo-fis_market_foto"]
    once = client.get(f"/admin/api/jobs/{job['id']}").json()
    assert once["validation"]["verdict"] == "mismatch"
    dogru = once["validation"]["expected"]["toplam"]  # the 5 TL the model missed
    yanit = client.patch(
        f"/admin/api/jobs/{job['id']}",
        json={
            "fields": {
                "totals.toplam": turce(dogru),
                "items[0].ad": "Tam buğday ekmeği 2'li",
            }
        },
    )
    assert yanit.status_code == 200, yanit.text

    sarmal = next(s for s in indir(client, format="json").json() if s["job_id"] == job["id"])
    assert sarmal["validation"]["verdict"] == "ok"
    assert sarmal["result"]["totals"]["toplam"] == dogru

    csv_satiri = next(
        s for s in csv_satirlari(indir(client, format="csv")) if s["job_id"] == job["id"]
    )
    assert float(csv_satiri["toplam"]) == dogru and csv_satiri["verdict"] == "ok"
    assert "Tam buğday ekmeği 2'li" in csv_satiri["items_json"]

    xlsx_satiri = next(
        s for s in xlsx_satirlari(indir(client, format="xlsx")) if s["job_id"] == job["id"]
    )
    assert xlsx_satiri["toplam"] == dogru and xlsx_satiri["verdict"] == "ok"
    assert "Tam buğday ekmeği 2'li" in xlsx_satiri["items_json"]


# --- who gets exported ---


def test_ids_exports_exactly_the_selection(env):
    client, _, jobs, _ = env
    secim = [jobs["demo-fis_market_clean"]["id"], jobs["demo-fis_restoran_clean"]["id"]]
    for bicim in BICIMLER:
        assert kimler(client, bicim, ids=",".join(secim)) == set(secim), bicim
        assert kimler(client, bicim, ids=f"{secim[0]}, olmayan-bir-fis") == {secim[0]}, bicim


def test_worker_and_since_narrow_the_whole_set(env):
    client, conn, jobs, _ = env
    butun = {job["id"] for job in jobs.values()}
    for bicim in BICIMLER:
        assert kimler(client, bicim, worker=serve_demo.WORKER) == butun, bicim
        assert kimler(client, bicim, worker="kimsenin-adi-yok") == set(), bicim
    assert kimler(client, "json", since="2000-01-01T00:00:00.000Z") == butun
    assert kimler(client, "json", since="2999-01-01T00:00:00.000Z") == set()
    esik = db._now()
    yeni = db.create_job(conn, worker=serve_demo.WORKER)
    assert [s["job_id"] for s in indir(client, format="json", since=esik).json()] == [
        yeni["id"]
    ]


def test_an_empty_selection_is_a_header_only_file_not_an_error(env):
    client, _, _, _ = env
    for bicim in BICIMLER:
        assert kimler(client, bicim, ids="olmayan-bir-fis") == set(), bicim
    assert indir(client, format="json", ids="olmayan-bir-fis").json() == []


# --- the door and its refusals ---


def test_each_format_arrives_as_a_named_download(env):
    client, _, _, _ = env
    bugun = datetime.date.today().isoformat()
    for bicim, tip in (
        ("json", "application/json"),
        ("csv", "text/csv"),
        ("xlsx", "spreadsheetml.sheet"),
    ):
        yanit = indir(client, format=bicim)
        assert tip in yanit.headers["content-type"], bicim
        assert yanit.headers["content-disposition"] == (
            f'attachment; filename="ihracat-{bugun}.{bicim}"'
        )


def test_the_export_door_is_the_admin_session(env):
    client, _, jobs, api_key = env
    client.cookies.clear()
    yanit = client.get("/admin/api/export")
    assert yanit.status_code == 401
    assert yanit.json()["error"]["code"] == "unauthorized"
    # ASSUMPTION: /v1 stays per-integrator and read-only, so it has no export.
    yanit = client.get(
        "/v1/export", params={"format": "json"}, headers={"X-API-Key": api_key}
    )
    assert yanit.status_code == 404


def test_a_format_or_a_since_the_browser_never_sends_is_a_validation_error(env):
    client, _, _, _ = env
    for param in ({"format": "pdf"}, {"since": "dün"}):
        yanit = client.get("/admin/api/export", params=param)
        assert yanit.status_code == 422, yanit.text
        assert yanit.json()["error"]["code"] == "validation_error"
