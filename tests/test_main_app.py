import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app import auth, db, main
from app.main import create_app


@pytest.fixture
def env(tmp_path):
    auth._buckets.clear()
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    key_id, plaintext = auth.create_key(conn, "ayse")
    app = create_app(db_path=path)
    client = TestClient(app, raise_server_exceptions=False)
    yield app, client, conn, key_id, plaintext
    conn.close()
    auth._buckets.clear()


def key_headers(plaintext):
    return {"X-API-Key": plaintext}


# --- public surface ---


def test_health_is_public(env):
    _, client, *_ = env
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_docs_page_is_public(env):
    _, client, *_ = env
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger-ui" in resp.text


def test_openapi_describes_contract_v1(env):
    _, client, *_ = env
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "v1"
    envelope = spec["components"]["schemas"]["JobEnvelope"]
    assert set(envelope["properties"]) >= {
        "job_id",
        "status",
        "result",
        "validation",
        "meta",
    }
    scheme = spec["components"]["securitySchemes"]["ApiKeyAuth"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}


# --- /v1 auth ---


def test_v1_without_key_is_401_envelope(env):
    _, client, *_ = env
    resp = client.get("/v1/jobs")
    assert resp.status_code == 401
    assert resp.json() == {
        "error": {"code": "unauthorized", "message": "missing or invalid API key"}
    }


def test_unknown_key_is_401(env):
    _, client, *_ = env
    resp = client.get("/v1/jobs", headers=key_headers("ocrk_" + "0" * 40))
    assert resp.status_code == 401


def test_revoked_key_is_401(env):
    _, client, conn, key_id, plaintext = env
    auth.revoke_key(conn, key_id)
    resp = client.get("/v1/jobs", headers=key_headers(plaintext))
    assert resp.status_code == 401


def test_valid_key_reaches_the_router(env):
    _, client, _, _, plaintext = env
    # A valid key clears the middleware and the route answers: 200, not 401.
    resp = client.get("/v1/jobs", headers=key_headers(plaintext))
    assert resp.status_code == 200
    assert resp.json() == []


# --- rate limit ---


def test_rate_limit_returns_429_with_retry_after(env, monkeypatch):
    _, client, _, _, plaintext = env
    monkeypatch.setenv("RATE_LIMIT_CAPACITY", "3")
    monkeypatch.setenv("RATE_LIMIT_REFILL_PER_S", "0.1")
    headers = key_headers(plaintext)
    responses = [client.get("/v1/jobs", headers=headers) for _ in range(4)]
    assert [resp.status_code for resp in responses] == [200, 200, 200, 429]
    resp = responses[3]
    assert resp.json()["error"]["code"] == "rate_limited"
    assert int(resp.headers["Retry-After"]) >= 1


def test_401_does_not_consume_rate_tokens(env, monkeypatch):
    _, client, *_ = env
    monkeypatch.setenv("RATE_LIMIT_CAPACITY", "2")
    monkeypatch.setenv("RATE_LIMIT_REFILL_PER_S", "0.1")
    for _ in range(5):
        assert client.get("/v1/jobs").status_code == 401


# --- error envelope ---


def test_unknown_path_is_404_envelope(env):
    _, client, *_ = env
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "not_found", "message": "Not Found"}
    }


def test_validation_errors_use_the_envelope(env):
    app, client, _, _, plaintext = env

    @app.get("/v1/echo")
    def echo(n: int):
        return {"n": n}

    resp = client.get("/v1/echo?n=abc", headers=key_headers(plaintext))
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "query.n"


def test_unhandled_crash_becomes_500_envelope(env):
    app, client, *_ = env

    @app.get("/boom")
    def boom():
        raise RuntimeError("model exploded")

    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json() == {
        "error": {"code": "internal_error", "message": "unexpected server error"}
    }


# --- static mounts ---


def test_static_mounts_registered(env):
    app, *_ = env
    mounts = {route.path for route in app.routes if isinstance(route, Mount)}
    assert {"/app", "/admin"} <= mounts


def test_pwa_page_is_served_from_static(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "app").mkdir(parents=True)
    (static / "app" / "index.html").write_text("<h1>PWA</h1>", encoding="utf-8")
    monkeypatch.setattr(main, "STATIC_DIR", static)
    client = TestClient(create_app(db_path=tmp_path / "ocr.db"))
    assert client.get("/app/").text == "<h1>PWA</h1>"
    # the admin directory is created on boot, so a fresh clone still starts
    assert client.get("/admin/").status_code == 404
