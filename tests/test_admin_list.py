"""T35 — the admin's submissions table, fed the real demo seed.

The corpus is scripts.serve_demo.seed_jobs: one job per committed fixture,
spread over every queue state and verdict, so every filter is checked against
receipts that genuinely differ from each other rather than against rows this
test invented.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import create_app
from scripts import serve_demo

ANAHTAR = "yonetici-anahtari-4b8d"
SUTUNLAR = {
    "job_id",
    "kisa_id",
    "worker",
    "status",
    "tarih",
    "firma",
    "toplam",
    "verdict",
    "kalite_mode",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A demo-seeded database, an admin session and the rows that went in."""
    auth._sessions.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, _ = auth.create_key(conn, serve_demo.WORKER)
    jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn, jobs
    conn.close()
    auth._sessions.clear()


def liste(client, **params) -> dict:
    resp = client.get("/admin/api/jobs", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def iso(satir: dict) -> str:
    """The row's dd.MM.yyyy back to an ISO day, for window arithmetic."""
    gun, ay, yil = satir["tarih"].split(".")
    return f"{yil}-{ay}-{gun}"


def idler(satirlar) -> set[str]:
    return {satir["job_id"] for satir in satirlar}


# --- the rows themselves ---


def test_every_seeded_job_is_listed_once(env):
    client, _, jobs = env
    body = liste(client, limit=200)
    assert body["total"] == len(jobs)
    assert len(body["jobs"]) == len(jobs)
    assert idler(body["jobs"]) == {job["id"] for job in jobs}


def test_a_row_carries_exactly_the_table_columns(env):
    client, _, jobs = env
    satirlar = liste(client, limit=200)["jobs"]
    assert all(set(satir) == SUTUNLAR for satir in satirlar)
    ok = next(satir for satir in satirlar if satir["verdict"] in ("ok", "mismatch"))
    assert ok["kisa_id"] == ok["job_id"][:8]
    assert ok["worker"] == serve_demo.WORKER
    assert ok["firma"] and isinstance(ok["toplam"], float)
    assert ok["kalite_mode"] is False
    okunamayan = [satir for satir in satirlar if satir["verdict"] == "unreadable"]
    assert okunamayan
    assert all(s["toplam"] is None and s["firma"] == "" for s in okunamayan)


def test_a_job_that_never_ran_has_no_amount_but_still_a_day(env):
    client, _, _ = env
    satirlar = liste(client, limit=200)["jobs"]
    bekleyen = [s for s in satirlar if s["status"] in ("queued", "running", "failed")]
    assert bekleyen
    for satir in bekleyen:
        assert satir["toplam"] is None  # never 0,00: nothing was read
        assert satir["verdict"] is None and satir["firma"] == ""
        assert iso(satir)  # the submission day stands in for the receipt's


def test_the_quality_mode_column_follows_the_run_not_the_fixture(env):
    client, conn, jobs = env
    hedef = next(job for job in jobs if job["status"] == "done")
    db.update_job(conn, hedef["id"], mode="quality", meta_json={"quality_mode": True})
    satirlar = {s["job_id"]: s for s in liste(client, limit=200)["jobs"]}
    assert satirlar[hedef["id"]]["kalite_mode"] is True
    assert sum(1 for s in satirlar.values() if s["kalite_mode"]) == 1


# --- filters ---


def test_status_filter_keeps_only_that_state(env):
    client, _, jobs = env
    durumlar = sorted({job["status"] for job in jobs})
    assert durumlar == ["done", "failed", "queued", "running"]  # the seed's spread
    for durum in durumlar:
        body = liste(client, status=durum, limit=200)
        assert body["total"] == sum(1 for job in jobs if job["status"] == durum) > 0
        assert {satir["status"] for satir in body["jobs"]} == {durum}


def test_worker_filter_uses_the_names_the_panel_offers(env):
    client, conn, _ = env
    assert liste(client)["workers"] == [serve_demo.WORKER]
    other_id, _ = auth.create_key(conn, "mehmet")
    db.create_job(conn, key_id=other_id, worker="mehmet")
    body = liste(client, worker="mehmet")
    assert body["total"] == 1 and body["jobs"][0]["worker"] == "mehmet"
    assert body["workers"] == ["demo", "mehmet"]  # the dropdown's own options


def test_a_worker_with_no_jobs_is_an_empty_list_not_an_error(env):
    client, _, _ = env
    body = liste(client, worker="kimsenin-adi-yok")
    assert body["jobs"] == [] and body["total"] == 0


def test_the_date_window_closes_around_the_day_the_row_shows(env):
    client, _, _ = env
    butun = liste(client, limit=200)["jobs"]
    gunler = sorted({iso(satir) for satir in butun})
    assert len(gunler) > 1  # receipt days and submission days differ
    for bas, son in ((gunler[-1], ""), ("", gunler[0])):
        beklenen = [
            satir
            for satir in butun
            if (not bas or iso(satir) >= bas) and (not son or iso(satir) <= son)
        ]
        body = liste(client, date_from=bas, date_to=son, limit=200)
        assert 0 < body["total"] == len(beklenen) < len(butun)
        assert idler(body["jobs"]) == idler(beklenen)


def test_a_window_after_every_receipt_is_empty(env):
    client, _, _ = env
    yarin = (date.today() + timedelta(days=1)).isoformat()
    assert liste(client, date_from=yarin)["total"] == 0


def test_a_date_the_browser_never_sends_is_the_usual_validation_envelope(env):
    client, _, _ = env
    resp = client.get("/admin/api/jobs", params={"date_from": "28.10.2026"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# --- free text ---


def test_search_finds_a_receipt_by_its_header(env):
    client, _, _ = env
    butun = liste(client, limit=200)["jobs"]
    market = [satir for satir in butun if satir["firma"].startswith("BILGIN")]
    assert market
    assert idler(liste(client, q="bilgin")["jobs"]) == idler(market)
    assert idler(liste(client, q="Bilgin Marketler")["jobs"]) == idler(market)
    assert idler(liste(client, q="1234567890")["jobs"]) == idler(market)  # vergi_no


def test_search_finds_a_product_the_table_never_shows(env):
    client, _, _ = env
    butun = liste(client, limit=200)["jobs"]
    market = idler(s for s in butun if s["firma"].startswith("BILGIN"))
    bulunan = idler(liste(client, q="zeytinyağı")["jobs"])
    assert bulunan == market  # "Zeytinyağı 1L" is only ever an item line
    # a phone keyboard types plain ASCII: no ş, no ğ, no dot on the i
    assert idler(liste(client, q="zeytinyagi")["jobs"]) == bulunan
    assert idler(liste(client, q="CAY 1KG")["jobs"]) == bulunan


def test_every_search_word_has_to_appear(env):
    client, _, _ = env
    assert liste(client, q="akpet")["total"] > 0
    assert liste(client, q="zeytinyagi")["total"] > 0
    assert liste(client, q="akpet zeytinyagi")["total"] == 0  # two receipts
    assert liste(client, q="smdr-yok-boyle-bir-fis")["total"] == 0


# --- sorting and paging ---


def test_sorting_orders_the_column_and_sinks_the_rows_that_have_no_value(env):
    client, _, _ = env
    for direction in ("asc", "desc"):
        satirlar = liste(client, sort="toplam", dir=direction, limit=200)["jobs"]
        degerler = [satir["toplam"] for satir in satirlar]
        sayilar = [t for t in degerler if t is not None]
        assert sayilar == sorted(sayilar, reverse=direction == "desc")
        assert degerler[len(sayilar) :] == [None] * (len(degerler) - len(sayilar))
    firmalar = [
        satir["firma"] for satir in liste(client, sort="firma", dir="asc", limit=200)["jobs"]
    ]
    assert firmalar == sorted(firmalar)


def test_pages_repeat_and_skip_nothing(env):
    client, _, jobs = env
    butun = [satir["job_id"] for satir in liste(client, limit=200)["jobs"]]
    sayfa, offset, parcalar = 3, 0, []
    while True:
        vucut = liste(client, limit=sayfa, offset=offset)
        assert vucut["total"] == len(jobs)  # the whole filter, not the page
        parcalar += [satir["job_id"] for satir in vucut["jobs"]]
        if len(vucut["jobs"]) < sayfa:
            break
        offset += sayfa
    assert parcalar == butun


def test_an_oversized_page_still_answers_with_what_there_is(env):
    client, _, jobs = env
    body = liste(client, limit=5000, offset=-10)
    assert body["total"] == len(jobs) and len(body["jobs"]) == len(jobs)


# --- the page that draws it ---


def test_the_page_holds_the_list_controls(env):
    client, _, _ = env
    html = client.get("/admin/").text
    for kontrol in (
        "fis-filtreler",
        "fis-ara",
        "fis-durum",
        "fis-calisan",
        "fis-baslangic",
        "fis-bitis",
        "fis-temizle",
        "fis-tablo",
        "fis-bos",
        "fis-hata",
        "fis-sayfalama",
        "fis-onceki",
        "fis-sonraki",
    ):
        assert f'id="{kontrol}"' in html
    assert "Anahtarlar" in html and "Durum" in html  # T34's shell still intact


def test_the_list_module_calls_the_admin_api(env):
    client, _, _ = env
    js = client.get("/admin/list.js")
    assert js.status_code == 200
    assert 'API = "/admin/api"' in js.text
    assert "${API}/jobs?" in js.text
    for param in (
        "status",
        "worker",
        "date_from",
        "date_to",
        "q",
        "sort",
        "dir",
        "limit",
        "offset",
    ):
        assert param in js.text
