"""T57 — sorting the tarih column follows the receipt's real day.

The printed dd.MM.yyyy string reads 02.11.2026 above 01.12.2026, so the
order has to come from the row's ISO day, not the text the table shows.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import create_app

ANAHTAR = "yonetici-anahtari-4b8d"
FIS_TARIHLARI = ["01.12.2026", "02.11.2026", "15.11.2026", "30.10.2026", "05.12.2026"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One done job per receipt date, spread over three months."""
    auth._sessions.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, _ = auth.create_key(conn, "demo")
    for sira, tarih in enumerate(FIS_TARIHLARI, start=1):
        job = db.create_job(conn, key_id=key_id, worker="demo")
        db.set_status(
            conn,
            job["id"],
            "done",
            result_json={
                "header": {"isim": f"FISMA {sira}"},
                "meta": {"tarih": tarih, "saat": "12:00", "no": str(sira), "tip": "fiş"},
                "items": [],
                "totals": {"ara_toplam": 10.0, "iskonto": 0.0, "kdv": 2.0, "toplam": 12.0},
                "para_birimi": "TRY",
            },
            validation_json={
                "verdict": "ok",
                "expected": {},
                "actual": {},
                "fields": [],
            },
        )
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client
    conn.close()
    auth._sessions.clear()


def tarihler(client, **params) -> list[str]:
    resp = client.get("/admin/api/jobs", params={"limit": 200, **params})
    assert resp.status_code == 200, resp.text
    return [satir["tarih"] for satir in resp.json()["jobs"]]


def test_desc_newest_receipt_first_across_months(env):
    # the bug: string order put 02.11.2026 above 01.12.2026
    assert tarihler(env, sort="tarih", dir="desc") == [
        "05.12.2026",
        "01.12.2026",
        "15.11.2026",
        "02.11.2026",
        "30.10.2026",
    ]


def test_asc_oldest_receipt_first_across_months(env):
    assert tarihler(env, sort="tarih", dir="asc") == [
        "30.10.2026",
        "02.11.2026",
        "15.11.2026",
        "01.12.2026",
        "05.12.2026",
    ]


def test_tarih_is_the_default_order(env):
    assert tarihler(env) == tarihler(env, sort="tarih", dir="desc")
