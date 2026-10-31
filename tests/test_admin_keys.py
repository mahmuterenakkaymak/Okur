"""T39 — key management over the admin API.

The three endpoints (create with a worker label, list without secrets,
revoke) plus the one promise the whole design rests on: the plaintext key
crosses the wire exactly once, and a revoked key stops working on the very
next PWA call.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import create_app

ANAHTAR = "yonetici-anahtari-e7a1"
ALANLAR = {"id", "worker", "created_at", "revoked"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A signed-in admin client over a fresh database."""
    auth._sessions.clear()
    auth._buckets.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def olustur(client, worker: str) -> dict:
    resp = client.post("/admin/api/keys", json={"worker": worker})
    assert resp.status_code == 200, resp.text
    return resp.json()


def liste(client) -> list[dict]:
    resp = client.get("/admin/api/keys")
    assert resp.status_code == 200, resp.text
    return resp.json()["keys"]


def iptal(client, key_id: int):
    return client.post(f"/admin/api/keys/{key_id}/revoke")


# --- create ---


def test_creating_a_key_answers_with_the_plaintext_once(env):
    client, _ = env
    vucut = olustur(client, "ayşe")
    assert vucut["worker"] == "ayşe"
    assert vucut["key"].startswith("ocrk_") and len(vucut["key"]) == 45
    assert vucut["key_id"] == liste(client)[0]["id"]


def test_a_fresh_key_works_on_the_pwa_path_immediately(env):
    client, _ = env
    duz = olustur(client, "ayşe")["key"]
    resp = client.get("/api/me/jobs", headers={"X-API-Key": duz})
    assert resp.status_code == 200
    assert resp.json() == {"jobs": [], "total": 0}


def test_a_worker_label_of_nothing_is_a_validation_envelope(env):
    client, _ = env
    for bos in ("", "   "):
        resp = client.post("/admin/api/keys", json={"worker": bos})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"
    assert liste(client) == []


# --- list ---


def test_the_list_holds_identities_and_never_a_secret(env):
    client, _ = env
    duz = olustur(client, "ayşe")["key"]
    olustur(client, "fatma")
    satirlar = liste(client)
    assert [s["worker"] for s in satirlar] == ["ayşe", "fatma"]
    assert all(set(s) == ALANLAR for s in satirlar)
    assert all(s["revoked"] is False and s["created_at"] for s in satirlar)
    govde = client.get("/admin/api/keys").text
    assert duz not in govde and auth.hash_key(duz) not in govde


# --- revoke ---


def test_revoking_flips_the_row_and_keeps_the_history(env):
    client, _ = env
    key_id = olustur(client, "ayşe")["key_id"]
    assert iptal(client, key_id).status_code == 200
    (satir,) = liste(client)
    assert satir["id"] == key_id and satir["revoked"] is True


def test_a_revoked_key_is_401_on_the_very_next_pwa_call(env):
    client, _ = env
    duz = olustur(client, "ayşe")["key"]
    assert client.get("/api/me/jobs", headers={"X-API-Key": duz}).status_code == 200
    assert iptal(client, olustur(client, "fatma")["key_id"]).status_code == 200
    # the other worker keeps working: revocation is per key, not global
    assert client.get("/api/me/jobs", headers={"X-API-Key": duz}).status_code == 200
    assert iptal(client, liste(client)[0]["id"]).status_code == 200
    resp = client.get("/api/me/jobs", headers={"X-API-Key": duz})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_revoking_twice_or_an_unknown_id_is_409(env):
    client, _ = env
    key_id = olustur(client, "ayşe")["key_id"]
    assert iptal(client, key_id).status_code == 200
    assert iptal(client, key_id).status_code == 409
    assert iptal(client, 9999).status_code == 409


# --- the guard covers the new routes the moment they exist ---


def test_the_key_endpoints_refuse_a_caller_without_a_session(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "ocr.db"))
    assert client.get("/admin/api/keys").status_code == 401
    assert client.post("/admin/api/keys", json={"worker": "ayşe"}).status_code == 401
    assert client.post("/admin/api/keys/1/revoke").status_code == 401


# --- the page that draws it ---


def test_the_page_holds_the_key_controls(env):
    client, _ = env
    html = client.get("/admin/").text
    for kontrol in (
        "anahtar-ekle",
        "anahtar-tablo",
        "anahtar-bos",
        "anahtar-hata",
        "anahtar-olustur-formu",
        "anahtar-calisan",
        "anahtar-duz",
        "anahtar-kopyala",
    ):
        assert f'id="{kontrol}"' in html


def test_the_keys_module_calls_the_admin_api(env):
    client, _ = env
    js = client.get("/admin/keys.js")
    assert js.status_code == 200
    assert 'API = "/admin/api"' in js.text
    for yol in ("/keys", "/revoke"):
        assert yol in js.text
    assert "clipboard" in js.text  # the copy button's one job
