"""T37 — field-level corrections: one write, and every surface follows.

A correction is not a note pinned next to a job, it rewrites the job. So the
check is that after a single PATCH the integrator's GET /v1/jobs/{id}, the
admin's detail, the worker's own result view and both list views all tell one
story, and that the row the three export formats are built from (PLAN.md
contract 8) tells it too. The validator runs over the corrected data, so the
verdict on screen always belongs to the numbers on screen — the model never
gets to keep a total a reviewer has already fixed.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.contract import JobEnvelope
from app.main import create_app
from scripts import serve_demo

ANAHTAR = "yonetici-anahtari-7c3a"
ZAMAN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# PLAN.md contract 8: the flat row every export format's columns derive from.
DISA_AKTARIM_ALANLARI = {
    "job_id",
    "worker",
    "client_ref",
    "tarih",
    "saat",
    "firma",
    "vergi_no",
    "ara_toplam",
    "iskonto",
    "kdv",
    "toplam",
    "para_birimi",
    "verdict",
    "items_json",
    "kalite_mode",
    "gonderim_zamani",
}


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
    yield client, conn, api_key, {job["client_ref"]: job for job in jobs}
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def turce(deger: float) -> str:
    """An amount the way a reviewer types it: 1192.9 -> "1192,90"."""
    return f"{deger:.2f}".replace(".", ",")


def duzelt(client, job_id: str, fields: dict):
    return client.patch(f"/admin/api/jobs/{job_id}", json={"fields": fields})


def kayitli_sonuc(conn, job_id: str) -> dict:
    return json.loads(db.get_job(conn, job_id)["result_json"])


def duzeltme_kayitlari(conn, job_id: str) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM corrections WHERE job_id = ? ORDER BY id", (job_id,)
        )
    ]


# --- the five surfaces a corrected field shows up on ---


def v1(client, api_key: str, job_id: str) -> dict:
    yanit = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": api_key})
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def detay(client, job_id: str) -> dict:
    yanit = client.get(f"/admin/api/jobs/{job_id}")
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def calisan_detay(client, api_key: str, job_id: str) -> dict:
    yanit = client.get(
        f"/api/me/jobs/{job_id}", headers={"X-API-Key": api_key}
    )
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def yonetici_satiri(client, job_id: str) -> dict:
    yanit = client.get("/admin/api/jobs", params={"limit": 200})
    assert yanit.status_code == 200, yanit.text
    return next(s for s in yanit.json()["jobs"] if s["job_id"] == job_id)


def calisan_satiri(client, api_key: str, job_id: str) -> dict:
    yanit = client.get(
        "/api/me/jobs", params={"limit": 200}, headers={"X-API-Key": api_key}
    )
    assert yanit.status_code == 200, yanit.text
    return next(s for s in yanit.json()["jobs"] if s["job_id"] == job_id)


def bes_yuzey(client, api_key: str, job_id: str) -> list[tuple]:
    """(toplam, verdict) as each of the five surfaces reports this job.

    The three detail bodies answer with the contract envelope, the two list
    views with the flat row their own screen is built from; all five read the
    same two stored columns, so all five owe the same pair.
    """
    govde = [
        v1(client, api_key, job_id),
        detay(client, job_id),
        calisan_detay(client, api_key, job_id),
    ]
    satirlar = [
        yonetici_satiri(client, job_id),
        calisan_satiri(client, api_key, job_id),
    ]
    return [
        *(
            (round(d["result"]["totals"]["toplam"], 2), d["validation"]["verdict"])
            for d in govde
        ),
        *[(round(s["toplam"], 2), s["verdict"]) for s in satirlar],
    ]


def disa_aktarim_satiri(conn, job_id: str) -> dict:
    """The export row (contract 8) off the stored columns, as T38 will build it.

    JSON, CSV and XLSX all derive their columns from exactly these keys, so
    this is where a correction reaches every format at once.
    """
    row = db.get_job(conn, job_id)
    result = json.loads(row["result_json"])
    meta = json.loads(row["meta_json"])
    totals, header, receipt = result["totals"], result["header"], result["meta"]
    return {
        "job_id": row["id"],
        "worker": row["worker"],
        "client_ref": row["client_ref"],
        "tarih": receipt["tarih"],
        "saat": receipt["saat"],
        "firma": header["isim"],
        "vergi_no": header["vergi_no"],
        **{alan: totals[alan] for alan in ("ara_toplam", "iskonto", "kdv", "toplam")},
        "para_birimi": result["para_birimi"],
        "verdict": json.loads(row["validation_json"])["verdict"],
        "items_json": json.dumps(result["items"], ensure_ascii=False),
        "kalite_mode": bool(meta.get("quality_mode", row["mode"] == "quality")),
        "gonderim_zamani": row["created_at"],
    }


# --- one PATCH, five agreeing surfaces ---


def test_one_correction_lands_on_all_five_surfaces_at_once(env):
    client, _, api_key, jobs = env
    job = jobs["demo-fis_market_foto"]
    once = detay(client, job["id"])
    assert once["validation"]["verdict"] == "mismatch"
    assert once["validation"]["fields"] == ["totals.toplam"]
    dogru = once["validation"]["expected"]["toplam"]  # the 5 TL the model missed

    guncel = duzelt(client, job["id"], {"totals.toplam": turce(dogru)}).json()

    assert guncel["result"]["totals"]["toplam"] == dogru
    assert guncel["validation"]["verdict"] == "ok"
    assert guncel["validation"]["fields"] == []
    assert bes_yuzey(client, api_key, job["id"]) == [(dogru, "ok")] * 5


def test_the_corrected_envelope_is_still_contract_v1_on_every_door(env):
    client, _, api_key, jobs = env
    job = jobs["demo-fis_market_clean"]
    duzelt(client, job["id"], {"totals.iskonto": "52,32"}).close()
    for govde in (
        v1(client, api_key, job["id"]),
        detay(client, job["id"]),
        calisan_detay(client, api_key, job["id"]),
    ):
        JobEnvelope.model_validate(govde)


def test_the_verdict_after_a_correction_is_the_verdict_of_the_new_numbers(env):
    client, _, api_key, jobs = env
    job = jobs["demo-fis_restoran_clean"]
    assert detay(client, job["id"])["validation"]["verdict"] == "ok"

    guncel = duzelt(client, job["id"], {"totals.kdv": "100"}).json()

    blok = guncel["validation"]
    assert blok["verdict"] == "mismatch"
    assert "totals.kdv" in blok["fields"]
    assert blok["actual"]["kdv"] == 100.0  # what the reviewer typed
    assert blok["expected"]["kdv"] == 111.0  # what 1110,00 at %10 is
    assert yonetici_satiri(client, job["id"])["verdict"] == "mismatch"
    assert calisan_satiri(client, api_key, job["id"])["verdict"] == "mismatch"


def test_a_correction_touches_only_the_field_it_names(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_restoran_clean"]
    once = kayitli_sonuc(conn, job["id"])
    before = db.get_job(conn, job["id"])

    duzelt(client, job["id"], {"items[0].ad": "Adana kebap porsiyon"}).close()

    guncel = kayitli_sonuc(conn, job["id"])
    assert guncel["items"][0]["ad"] == "Adana kebap porsiyon"
    assert guncel["items"][0] != once["items"][0]
    for alan in ("header", "meta", "totals", "para_birimi", "okunamayan"):
        assert guncel[alan] == once[alan], alan
    assert guncel["items"][1:] == once["items"][1:]
    simdi = db.get_job(conn, job["id"])
    for alan in ("status", "worker", "client_ref", "mode", "image_path", "created_at"):
        assert simdi[alan] == before[alan], alan
    assert json.loads(simdi["meta_json"]) == json.loads(before["meta_json"])


def test_the_corrected_product_name_is_what_the_list_searches_on(env):
    client, _, _, jobs = env
    job = jobs["demo-fis_restoran_clean"]
    duzelt(client, job["id"], {"items[0].ad": "Karışık turşu 500g"}).close()

    def bulunan(q):
        yanit = client.get("/admin/api/jobs", params={"q": q, "limit": 200})
        return [s["job_id"] for s in yanit.json()["jobs"]]

    assert job["id"] in bulunan("turşu")
    assert job["id"] not in bulunan("kebir")


def test_the_export_row_every_format_is_built_from_carries_the_correction(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_foto"]
    once = disa_aktarim_satiri(conn, job["id"])
    assert once["verdict"] == "mismatch"

    dogru = detay(client, job["id"])["validation"]["expected"]["toplam"]
    duzelt(
        client, job["id"], {"totals.toplam": turce(dogru), "items[1].ad": "Süt yarım yağ 1L"}
    ).close()

    simdi = disa_aktarim_satiri(conn, job["id"])
    assert set(simdi) == DISA_AKTARIM_ALANLARI
    assert simdi["verdict"] == "ok"
    assert simdi["toplam"] == dogru
    assert simdi["ara_toplam"] == once["ara_toplam"]
    assert simdi["firma"] == "BILGIN MARKETLER ANONIM SIRKETI"
    assert simdi["tarih"] == "28.10.2026" and simdi["saat"] == "14:32"
    assert "Süt yarım yağ 1L" in simdi["items_json"]
    assert json.loads(simdi["items_json"])[1]["toplam"] == 127.5


# --- the audit trail ---


def test_every_field_that_moved_is_recorded_with_who_and_when(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    alanlar = {"items[0].miktar": "3", "totals.iskonto": "52,32"}  # one is a no-op
    duzelt(client, job["id"], alanlar).close()

    kayitlar = duzeltme_kayitlari(conn, job["id"])
    assert len(kayitlar) == 1, "a field left as it was writes no row"
    kayit = kayitlar[0]
    assert kayit["job_id"] == job["id"]
    assert kayit["field"] == "items[0].miktar"
    assert (kayit["old_value"], kayit["new_value"]) == ("2.0", "3.0")
    assert kayit["who"] == "admin"
    assert ZAMAN.match(kayit["created_at"])


def test_corrections_accumulate_so_the_history_reads_oldest_first(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    duzelt(client, job["id"], {"totals.iskonto": "0"}).close()
    duzelt(client, job["id"], {"totals.iskonto": "25"}).close()

    kayitlar = duzeltme_kayitlari(conn, job["id"])
    assert [k["field"] for k in kayitlar] == ["totals.iskonto", "totals.iskonto"]
    assert [(k["old_value"], k["new_value"]) for k in kayitlar] == [
        ("52.32", "0.0"),
        ("0.0", "25.0"),
    ]


# --- what a PATCH is not ---


def test_a_field_that_cannot_be_read_leaves_the_job_exactly_as_it_was(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    once = db.get_job(conn, job["id"])

    yanit = duzelt(
        client, job["id"], {"totals.kdv": "yüzde yirmi", "items[0].ad": "Yeni ad"}
    )

    assert yanit.status_code == 422, yanit.text
    assert yanit.json()["error"]["details"][0]["field"] == "body.fields.totals.kdv"
    simdi = db.get_job(conn, job["id"])
    assert simdi["result_json"] == once["result_json"]
    assert simdi["validation_json"] == once["validation_json"]
    assert duzeltme_kayitlari(conn, job["id"]) == []


@pytest.mark.parametrize(
    "yol",
    [
        "header.isim",  # not a field the reviewer corrects here
        "meta.tarih",
        "okunamayan",
        "totals",  # a section is not a field
        "items[0]",
        "totals.kdv_orani.fazla",
        "items[-1].toplam",
        "items[9].toplam",  # a row this receipt does not have
    ],
)
def test_only_a_field_the_panel_edits_can_be_corrected(env, yol):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    yanit = duzelt(client, job["id"], {yol: "1"})
    assert yanit.status_code == 422, yanit.text
    assert kayitli_sonuc(conn, job["id"])["totals"]["kdv"] == 198.82


def test_an_empty_body_is_not_a_correction(env):
    client, conn, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    assert duzelt(client, job["id"], {}).status_code == 422
    assert duzeltme_kayitlari(conn, job["id"]) == []


def test_a_job_the_pipeline_has_not_read_has_nothing_to_correct(env):
    client, _, _, jobs = env
    job = jobs["demo-fis_benzin_clean"]  # the seeded queued one
    assert job["status"] == "queued"
    assert duzelt(client, job["id"], {"totals.toplam": "1"}).status_code == 409
    assert duzelt(client, "olmayan-bir-fis", {"totals.toplam": "1"}).status_code == 404


def test_the_correction_door_is_the_admin_session_not_a_worker_key(env):
    client, _, api_key, jobs = env
    job = jobs["demo-fis_market_clean"]
    client.cookies.clear()
    yanit = duzelt(client, job["id"], {"totals.toplam": "1"})
    assert yanit.status_code == 401
    assert yanit.json()["error"]["code"] == "unauthorized"
    # and the frozen /v1 surface stays read-only for a key that tries it
    yanit = client.patch(
        f"/v1/jobs/{job['id']}",
        json={"fields": {"totals.toplam": "1"}},
        headers={"X-API-Key": api_key},
    )
    assert yanit.status_code == 405


# --- the reviewer's own door ---


def test_the_detail_page_hands_the_reviewer_a_save(env):
    client, _, _, _ = env
    html = client.get("/admin/").text
    for kontrol in ("detay-kaydet", "detay-kaydet-durum"):
        assert f'id="{kontrol}"' in html
    assert "Kaydet" in html

    js = client.get("/admin/detail.js").text
    assert 'method: "PATCH"' in js
    assert "${API}/jobs/" in js
    assert "fields:" in js
    assert "onDuzeltme" in js
    assert "items[${index}]." in js and "totals.${kolon.alan}" in js
    assert "onDuzeltme:" in client.get("/admin/admin.js").text
    assert ".gecersiz" in client.get("/admin/style.css").text
