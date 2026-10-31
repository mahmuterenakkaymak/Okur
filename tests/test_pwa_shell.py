import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "ocr.db")
    return TestClient(app, raise_server_exceptions=False)


# --- shell page ---


def test_shell_is_reachable_without_a_key(client):
    # /app is outside the auth middleware's /v1 + /api prefixes; the shell
    # must load before the worker has ever entered a key.
    for path in ("/app", "/app/"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")


def test_page_is_turkish(client):
    html = client.get("/app/").text
    assert 'lang="tr"' in html
    for metin in ("Fiş Çek", "Hoş geldin", "Çevrimiçi", "Ana Ekrana Ekle"):
        assert metin in html


def test_page_wires_manifest_icon_and_worker(client):
    html = client.get("/app/").text
    assert '<link rel="manifest" href="manifest.webmanifest">' in html
    assert '<link rel="icon" href="icon.svg" type="image/svg+xml">' in html
    assert "<svg" in html  # inline SVG logo, no binary asset needed
    assert 'navigator.serviceWorker.register("sw.js")' in html


# --- manifest ---


def test_manifest_declares_installable_standalone_app(client):
    resp = client.get("/app/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    mf = resp.json()
    assert mf["name"] and mf["short_name"]
    assert mf["display"] == "standalone"
    assert mf["theme_color"].startswith("#")
    assert mf["lang"] == "tr"
    # relative start_url/scope keep the install scope on /app/
    assert mf["start_url"] == "./" and mf["scope"] == "./"
    assert mf["icons"]


def test_manifest_icons_resolve(client):
    mf = client.get("/app/manifest.webmanifest").json()
    for icon in mf["icons"]:
        assert icon["src"] and icon["sizes"] and icon["type"] == "image/svg+xml"
        assert client.get(f"/app/{icon['src']}").status_code == 200


# --- icon ---


def test_icon_is_valid_svg(client):
    resp = client.get("/app/icon.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(resp.text)
    assert root.tag.endswith("svg")
    assert root.get("viewBox")


# --- service worker ---


def test_sw_precaches_shell_and_leaves_api_alone(client):
    resp = client.get("/app/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    js = resp.text
    assert "caches.open" in js and "skipWaiting" in js and "clients.claim" in js
    for asset in ("index.html", "manifest.webmanifest", "icon.svg"):
        assert asset in js
    # live job data must never be served from the cache
    assert '"/v1"' in js and '"/api"' in js
