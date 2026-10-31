import hmac

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import create_app

ANAHTAR = "gz-anahtari-9f2c"
KORUNAN = "/admin/api/session"  # any /admin/api path: the guard works by prefix


@pytest.fixture
def client(tmp_path, monkeypatch):
    auth._buckets.clear()
    auth._sessions.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    app = create_app(db_path=tmp_path / "ocr.db")
    yield TestClient(app, raise_server_exceptions=False)
    auth._sessions.clear()
    auth._buckets.clear()


def giris(client, token=ANAHTAR):
    return client.post("/admin/api/login", json={"token": token})


# --- the guard ---


def test_admin_api_without_a_session_is_401_envelope(client):
    resp = client.get(KORUNAN)
    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "unauthorized", "message": "admin session required"}
    }


def test_unknown_admin_api_path_is_401_before_routing(client):
    # The guard runs by prefix, so a route a later task adds cannot be
    # registered unauthenticated by accident.
    assert client.get("/admin/api/henuz-yok").status_code == 401


def test_worker_api_key_does_not_unlock_the_admin_api(client, tmp_path):
    conn = db.connect(tmp_path / "ocr.db")  # the fixture's own database
    try:
        _, plaintext = auth.create_key(conn, "ayse")
    finally:
        conn.close()
    resp = client.get(KORUNAN, headers={"X-API-Key": plaintext})
    assert resp.status_code == 401


def test_admin_shell_page_is_public(client):
    # The shell carries no data; it loads so the login form can appear.
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


# --- login ---


def test_login_issues_an_httponly_session_cookie(client):
    resp = giris(client)
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True}
    cookie = resp.headers["set-cookie"]
    assert f"{auth.ADMIN_COOKIE}=" in cookie
    for attribute in ("HttpOnly", "SameSite=lax", "Path=/admin", "Max-Age="):
        assert attribute in cookie


def test_session_cookie_unlocks_the_admin_api(client):
    assert giris(client).status_code == 200
    resp = client.get(KORUNAN)
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True}


def test_cookie_holds_a_session_id_not_the_admin_token(client):
    giris(client)
    session_id = client.cookies.get(auth.ADMIN_COOKIE)
    assert session_id and session_id != ANAHTAR
    assert len(session_id) >= 32


def test_wrong_token_is_401_and_sets_no_cookie(client):
    resp = giris(client, "yanlis-anahtar")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert "set-cookie" not in resp.headers


def test_empty_token_is_401(client):
    assert client.post("/admin/api/login", json={"token": ""}).status_code == 401


def test_non_ascii_token_is_401_not_500(client):
    # hmac.compare_digest rejects non-ASCII str: a pasted token must not
    # reach it unencoded.
    assert giris(client, "🔑-anahtar").status_code == 401


def test_login_compares_the_token_in_constant_time(client, monkeypatch):
    cagrilan = []
    gercek = hmac.compare_digest

    def casus(a, b):
        cagrilan.append((a, b))
        return gercek(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", casus)
    assert giris(client).status_code == 200
    assert cagrilan and all(
        isinstance(part, bytes) for cift in cagrilan for part in cift
    )


def test_login_is_refused_when_the_server_has_no_admin_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "")
    client = TestClient(create_app(db_path=tmp_path / "ocr.db"))
    resp = giris(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "service_unavailable"
    assert "set-cookie" not in resp.headers


# --- expiry and logout ---


def test_session_expires_with_admin_session_hours(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_HOURS", "0")
    assert giris(client).status_code == 200
    assert client.get(KORUNAN).status_code == 401


def test_logout_ends_the_session(client):
    giris(client)
    assert client.get(KORUNAN).status_code == 200
    assert client.post("/admin/api/logout").status_code == 200
    assert client.get(KORUNAN).status_code == 401


def test_logout_without_a_session_is_not_an_error(client):
    assert client.post("/admin/api/logout").status_code == 200


def test_each_login_gets_its_own_session(client):
    giris(client)
    ilk = client.cookies.get(auth.ADMIN_COOKIE)
    giris(client)
    assert client.cookies.get(auth.ADMIN_COOKIE) != ilk
    # the first browser is still signed in: logging in does not evict anyone
    assert auth.session_ok(ilk)


# --- shell page ---


def test_shell_has_turkish_nav(client):
    html = client.get("/admin/").text
    assert 'lang="tr"' in html
    for metin in ("Fişler", "Anahtarlar", "Durum", "Giriş yap", "Çıkış"):
        assert metin in html


def test_shell_assets_resolve(client):
    css = client.get("/admin/style.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    js = client.get("/admin/admin.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert 'API = "/admin/api"' in js.text
    for yol in ("/login", "/logout", "/session"):
        assert f"${{API}}{yol}" in js.text
