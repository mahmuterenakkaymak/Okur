"""T36 — the admin's job detail: the door it comes through.

The panel draws the stored photograph, the contract v1 body and the validation
block, so what is checked here is that one GET hands it all three — the same
envelope an integrator reads, the image bytes off the disk, and the states a
receipt that never made it through the pipeline arrives in. The corpus is the
demo seed again, so every case is a real fixture rather than a row invented
for the test.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.contract import JobEnvelope
from app.main import create_app
from scripts import serve_demo

ANAHTAR = "yonetici-anahtari-4b8d"
DETAY_ALANLARI = set(JobEnvelope.model_fields) | {"image_url"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A demo-seeded database, an admin session and the seeded jobs by ref."""
    auth._sessions.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, _ = auth.create_key(conn, serve_demo.WORKER)
    jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn, {job["client_ref"]: job for job in jobs}
    conn.close()
    auth._sessions.clear()


def detay(client, job_id: str) -> dict:
    resp = client.get(f"/admin/api/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def kayitli_sonuc(conn, job_id: str) -> dict:
    return json.loads(db.get_job(conn, job_id)["result_json"])


# --- the body the panel draws ---


def test_the_detail_is_the_contract_envelope_plus_where_the_image_lives(env):
    client, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    govde = detay(client, job["id"])
    JobEnvelope.model_validate(govde)  # parses as contract v1, untouched
    assert set(govde) == DETAY_ALANLARI
    assert govde["job_id"] == job["id"] and govde["status"] == "done"
    assert govde["result"]["header"]["isim"].startswith("BILGIN")
    assert govde["result"]["items"][0]["ad"] == "Tam buğday ekmeği"
    assert govde["validation"]["verdict"] == "ok"
    assert govde["meta"]["worker"] == serve_demo.WORKER
    assert govde["image_url"] == f"/admin/api/jobs/{job['id']}/image"


def test_the_stored_image_is_the_one_the_worker_uploaded(env):
    client, _, jobs = env
    job = jobs["demo-fis_restoran_clean"]
    yanit = client.get(detay(client, job["id"])["image_url"])
    assert yanit.status_code == 200
    assert yanit.headers["content-type"] == "image/jpeg"
    assert yanit.content == pathlib.Path(job["image_path"]).read_bytes()


def test_the_detail_reads_the_row_again_so_a_written_result_shows_up(env):
    client, conn, jobs = env
    job = jobs["demo-fis_benzin_foto"]
    sonuc = kayitli_sonuc(conn, job["id"])
    sonuc["okunamayan"] = ["KDV oranı satırı", "fiş numarası"]
    db.update_job(conn, job["id"], result_json=sonuc)
    assert detay(client, job["id"])["result"]["okunamayan"] == [
        "KDV oranı satırı",
        "fiş numarası",
    ]


def test_the_mismatched_receipt_carries_the_block_the_panel_compares(env):
    client, _, jobs = env
    govde = detay(client, jobs["demo-fis_market_foto"]["id"])
    blok = govde["validation"]
    assert blok["verdict"] == "mismatch" and blok["fields"] == ["totals.toplam"]
    assert blok["expected"]["toplam"] != blok["actual"]["toplam"]
    assert set(blok["expected"]) == {"ara_toplam", "iskonto", "kdv", "toplam"}


def test_an_unreadable_receipt_arrives_empty_rather_than_zero_rich(env):
    client, _, jobs = env
    govde = detay(client, jobs["demo-el_yazisi_liste"]["id"])
    assert govde["validation"]["verdict"] == "unreadable"
    assert govde["result"]["items"] == [] and govde["result"]["okunamayan"] == []


# --- the states a receipt arrives in ---


def test_a_job_that_never_ran_has_no_result_but_still_an_image(env):
    client, _, jobs = env
    job = jobs["demo-fis_benzin_clean"]  # the seeded queued one
    assert job["status"] == "queued"
    govde = detay(client, job["id"])
    assert govde["result"] is None and govde["validation"] is None
    assert govde["meta"]["worker"] == serve_demo.WORKER
    assert client.get(govde["image_url"]).status_code == 200


def test_a_job_with_no_image_on_disk_says_so_instead_of_breaking(env):
    client, conn, _ = env
    key_id, _ = auth.create_key(conn, "kadsiz")
    job = db.create_job(conn, key_id=key_id, worker="kadsiz")
    assert detay(client, job["id"])["image_url"] is None
    assert client.get(f"/admin/api/jobs/{job['id']}/image").status_code == 404


def test_an_unknown_job_is_404_on_both_doors(env):
    client, _, _ = env
    assert client.get("/admin/api/jobs/olmayan-bir-fis").status_code == 404
    assert client.get("/admin/api/jobs/olmayan-bir-fis/image").status_code == 404


def test_neither_the_detail_nor_the_image_open_without_a_session(env):
    client, _, jobs = env
    job = jobs["demo-fis_market_clean"]
    client.cookies.clear()
    for yol in (
        f"/admin/api/jobs/{job['id']}",
        f"/admin/api/jobs/{job['id']}/image",
    ):
        yanit = client.get(yol)
        assert yanit.status_code == 401
        assert yanit.json()["error"]["code"] == "unauthorized"


# --- the page that draws it ---


def test_the_page_holds_the_detail_controls(env):
    client, _, _ = env
    html = client.get("/admin/").text
    for kontrol in (
        "fis-detay",
        "detay-baslik",
        "detay-ozet",
        "detay-dogrulama",
        "detay-kapat",
        "detay-hata",
        "detay-tekrar",
        "detay-bekleniyor",
        "detay-icerik",
        "detay-panel",
        "detay-gorsel",
        "detay-resim",
        "detay-urun-govde",
        "detay-toplamlar",
        "detay-karsilastirma-kutusu",
        "detay-okunamayan-liste",
        "detay-json-dugme",
        "detay-json",
    ):
        assert f'id="{kontrol}"' in html
    for metin in ("Ürünler", "Toplamlar", "Beklenen", "Okunamayan", "Ham JSON"):
        assert metin in html


def test_the_detail_module_calls_the_admin_api(env):
    client, _, _ = env
    js = client.get("/admin/detail.js")
    assert js.status_code == 200
    assert 'API = "/admin/api"' in js.text
    assert "${API}/jobs/" in js.text
    for alan in ("ad", "miktar", "birim_fiyat", "toplam", "kdv_orani", "okunamayan"):
        assert alan in js.text


def test_a_list_row_opens_the_detail(env):
    client, _, _ = env
    assert "tr.dataset.job" in client.get("/admin/list.js").text
    assert "acis: detay.ac" in client.get("/admin/admin.js").text
