"""T41 — quality-mode rerun: one POST, and the receipt is read all over again.

A rerun is not a note next to the job, it replaces it: the same stored image
goes through the pipeline with quality_mode true (stage 2 on Unsloth :8888),
and the result, the validation recomputed over the new numbers and the meta
block (model, quality_mode, timings) land on the two stored columns every
surface reads. So the check is that after one POST the integrator's GET, the
admin detail, the worker's result view, both lists and the export row all
tell the new story — and that a rerun whose model server failed leaves the
job exactly as it was, because a sick Unsloth must not cost the reviewer the
receipt they already have.
"""
from __future__ import annotations

import csv
import io
import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import auth, config, contract, db, exports, validator
from app.contract import JobEnvelope
from app.main import create_app
from scripts import serve_demo

ANAHTAR = "yonetici-anahtari-9f2d"

# A whole readable result for the failed-job recovery: 45,00 at %20 is 9,00
# KDV and 54,00 on the till, so the validator runs over it clean.
SONUC = {
    "header": {"isim": "REFALENTİM MARKET"},
    "meta": {"tarih": "28.10.2026", "saat": "14:32", "no": "42"},
    "items": [{"ad": "Süt yarım yağ 1L", "miktar": 1, "birim_fiyat": 45.0, "toplam": 45.0}],
    "totals": {"ara_toplam": 45.0, "iskonto": 0, "kdv": 9.0, "kdv_orani": 0.2, "toplam": 54.0},
    "para_birimi": "TRY",
}


def kalite_bundle(sonuc: dict, *, ocr_ms: int = 2100, total_ms: int = 8400) -> dict:
    """What the pipeline hands back for a quality-mode run of a good read."""
    return {
        "result": sonuc,
        "validation": validator.validate(sonuc),
        "meta": contract.JobMeta(
            worker=serve_demo.WORKER,
            ocr_ms=ocr_ms,
            total_ms=total_ms,
            model=config.unsloth_model(),
            quality_mode=True,
        ).model_dump(),
        "error": "",
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Demo-seeded db, an admin session, and a pipeline the test controls."""
    auth._sessions.clear()
    auth._buckets.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, api_key = auth.create_key(conn, serve_demo.WORKER)
    jobs = serve_demo.seed_jobs(conn, key_id=key_id, images_dir=tmp_path / "images")
    calls: list[dict] = []
    state: dict = {"bundle": kalite_bundle(SONUC)}

    def runner(image_bytes, *, quality_mode=False, worker=""):
        calls.append(
            {"image": image_bytes, "quality_mode": quality_mode, "worker": worker}
        )
        return state["bundle"]

    client = TestClient(
        create_app(db_path=path, runner=runner), raise_server_exceptions=False
    )
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn, api_key, {job["client_ref"]: job for job in jobs}, calls, state
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def yeni_sonuc(conn, job_id: str, **toplam) -> dict:
    """The job's stored result with a few totals moved — the quality model's
    second read of the same receipt, seen from the runner's side."""
    sonuc = json.loads(db.get_job(conn, job_id)["result_json"])
    sonuc["totals"].update(toplam)
    return sonuc


def rerun(client, job_id: str):
    return client.post(f"/admin/api/jobs/{job_id}/rerun")


# --- the surfaces a rerun has to refresh ---


def v1(client, api_key: str, job_id: str) -> dict:
    yanit = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": api_key})
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def detay(client, job_id: str) -> dict:
    yanit = client.get(f"/admin/api/jobs/{job_id}")
    assert yanit.status_code == 200, yanit.text
    return yanit.json()


def calisan_detay(client, api_key: str, job_id: str) -> dict:
    yanit = client.get(f"/api/me/jobs/{job_id}", headers={"X-API-Key": api_key})
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
    """(toplam, verdict) as each of the five surfaces reports this job."""
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


# --- one rerun, every view follows ---


def test_quality_rerun_replaces_the_result_and_every_view_follows(env):
    client, conn, api_key, jobs, calls, state = env
    job = jobs["demo-fis_market_foto"]  # mismatch: the 5 TL hidden discount
    once = detay(client, job["id"])
    assert once["validation"]["verdict"] == "mismatch"
    assert once["meta"]["quality_mode"] is False
    dogru = once["validation"]["expected"]["toplam"]
    state["bundle"] = kalite_bundle(yeni_sonuc(conn, job["id"], toplam=dogru))

    yanit = rerun(client, job["id"])

    assert yanit.status_code == 200, yanit.text
    govde = yanit.json()
    JobEnvelope.model_validate(govde)
    assert govde["result"]["totals"]["toplam"] == dogru
    assert govde["validation"]["verdict"] == "ok"
    assert govde["meta"]["quality_mode"] is True
    assert govde["meta"]["model"] == config.unsloth_model()
    assert govde["meta"]["ocr_ms"] == 2100 and govde["meta"]["total_ms"] == 8400
    assert bes_yuzey(client, api_key, job["id"]) == [(dogru, "ok")] * 5
    assert yonetici_satiri(client, job["id"])["kalite_mode"] is True
    assert db.get_job(conn, job["id"])["mode"] == "quality"
    # the runner ran quality over the stored image, as the queue would
    assert calls == [
        {
            "image": pathlib.Path(job["image_path"]).read_bytes(),
            "quality_mode": True,
            "worker": serve_demo.WORKER,
        }
    ]


def test_the_verdict_after_a_rerun_is_the_verdict_of_the_new_numbers(env):
    client, conn, api_key, jobs, _, state = env
    job = jobs["demo-fis_restoran_clean"]
    assert detay(client, job["id"])["validation"]["verdict"] == "ok"
    state["bundle"] = kalite_bundle(yeni_sonuc(conn, job["id"], kdv=100.0))

    govde = rerun(client, job["id"]).json()

    blok = govde["validation"]
    assert blok["verdict"] == "mismatch"
    assert "totals.kdv" in blok["fields"]
    assert blok["actual"]["kdv"] == 100.0
    assert calisan_satiri(client, api_key, job["id"])["verdict"] == "mismatch"


def test_the_rerun_keeps_who_the_job_belongs_to_and_shows_quality_in_exports(env):
    client, conn, _, jobs, _, state = env
    job = jobs["demo-fis_market_clean"]
    kayit = db.get_job(conn, job["id"])
    db.update_job(
        conn,
        job["id"],
        meta_json={
            **json.loads(kayit["meta_json"]),
            "captured_at": "2026-10-28T10:04:00Z",
        },
    )
    state["bundle"] = kalite_bundle(yeni_sonuc(conn, job["id"]))

    meta = rerun(client, job["id"]).json()["meta"]

    assert meta["captured_at"] == "2026-10-28T10:04:00Z"
    assert meta["worker"] == serve_demo.WORKER
    assert meta["received_at"] == kayit["created_at"]
    assert meta["model"] == config.unsloth_model()

    dis = exports.row(db.get_job(conn, job["id"]))
    assert dis["kalite_mode"] is True
    assert dis["verdict"] == "ok"
    govde = client.get(
        "/admin/api/export", params={"format": "json", "ids": job["id"]}
    ).json()
    assert govde[0]["meta"]["quality_mode"] is True
    metin = client.get(
        "/admin/api/export", params={"format": "csv", "ids": job["id"]}
    ).content.decode("utf-8-sig")
    satirlar = list(csv.reader(io.StringIO(metin)))
    assert satirlar[1][exports.FIELDS.index("kalite_mode")] == "true"
    xlsx = client.get("/admin/api/export", params={"format": "xlsx", "ids": job["id"]})
    assert xlsx.status_code == 200
    sayfa = load_workbook(io.BytesIO(xlsx.content)).active
    assert sayfa.cell(2, exports.FIELDS.index("kalite_mode") + 1).value is True


def test_a_failed_job_comes_back_done_through_quality_mode(env):
    client, conn, _, jobs, _, state = env
    job = jobs["demo-fis_kotu_cekim"]
    assert job["status"] == "failed"
    state["bundle"] = kalite_bundle(SONUC)

    govde = rerun(client, job["id"]).json()

    assert govde["status"] == "done"
    assert govde["validation"]["verdict"] == "ok"
    row = db.get_job(conn, job["id"])
    assert row["error"] == "" and row["mode"] == "quality"


# --- what a rerun is not ---


def test_a_failed_rerun_leaves_the_job_exactly_as_it_was(env):
    client, conn, _, jobs, _, state = env
    job = jobs["demo-fis_market_clean"]
    once = db.get_job(conn, job["id"])
    state["bundle"] = {
        "result": None,
        "validation": None,
        "meta": {},
        "error": "stage 1: OCR server unreachable",
    }

    yanit = rerun(client, job["id"])

    assert yanit.status_code == 502, yanit.text
    assert "OCR server unreachable" in yanit.json()["error"]["message"]
    simdi = db.get_job(conn, job["id"])
    for alan in ("result_json", "validation_json", "meta_json", "status", "mode", "error"):
        assert simdi[alan] == once[alan], alan


def test_a_job_still_in_the_queue_has_nothing_to_rerun(env):
    client, _, _, jobs, calls, _ = env
    assert rerun(client, jobs["demo-fis_benzin_clean"]["id"]).status_code == 409
    assert rerun(client, jobs["demo-fis_restoran_foto"]["id"]).status_code == 409
    assert rerun(client, "olmayan-bir-fis").status_code == 404
    assert calls == []


def test_the_rerun_door_is_the_admin_session_not_a_worker_key(env):
    client, _, api_key, jobs, _, _ = env
    job = jobs["demo-fis_market_clean"]
    client.cookies.clear()
    yanit = rerun(client, job["id"])
    assert yanit.status_code == 401
    assert yanit.json()["error"]["code"] == "unauthorized"
    # and the frozen /v1 surface has no rerun resource for a key to reach
    yanit = client.post(f"/v1/jobs/{job['id']}/rerun", headers={"X-API-Key": api_key})
    assert yanit.status_code == 404


# --- the reviewer's own door ---


def test_the_detail_page_hands_the_reviewer_a_confirmation_and_a_diff(env):
    client = env[0]
    html = client.get("/admin/").text
    for kontrol in (
        "detay-yeniden",
        "detay-yeniden-onay",
        "detay-yeniden-onayla",
        "detay-yeniden-vazgec",
        "detay-fark",
        "detay-fark-icerik",
    ):
        assert f'id="{kontrol}"' in html
    assert "Kalite modunda yeniden işle" in html

    js = client.get("/admin/detail.js").text
    assert 'method: "POST"' in js
    assert "/rerun" in js
    assert "kaliteFarki" in js
    assert '"Önce"' in js and '"Sonra"' in js
    css = client.get("/admin/style.css").text
    assert ".fark" in css and ".yeniden-onay" in css
