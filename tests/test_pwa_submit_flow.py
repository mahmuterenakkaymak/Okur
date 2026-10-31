"""T26 — the served submit-flow page wires every module and DOM hook."""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MODULES = ("app.js", "api.js", "capture.js", "crop.js", "status.js")

# every hook app.js must reach for capture -> crop -> upload -> status -> result
HOOKS = (
    "api-anahtari",
    "anahtar-ipucu",
    "adim-cekim",
    "adim-kirp",
    "adim-durum",
    "adim-sonuc",
    "cekim-alani",
    "kirp-alani",
    "cekime-don",
    "hata-mesaji",
    "durum-etiket",
    "durum-ipucu",
    "durum-ilerleme",
    "gecen-sure",
    "verdict-tasi",
    "sonuc-uyari",
    "sonuc-firma",
    "sonuc-meta",
    "urun-govde",
    "t-ara-toplam",
    "t-iskonto",
    "t-kdv",
    "t-kdv-orani",
    "t-toplam",
    "t-para-birimi",
    "ham-json",
    "ham-json-dugme",
    "yeni-fis",
)


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "ocr.db")
    return TestClient(app, raise_server_exceptions=False)


def page(client):
    return client.get("/app/").text


def app_js(client):
    return client.get("/app/app.js").text


# --- modules ---


@pytest.mark.parametrize("asset", MODULES)
def test_flow_module_is_served(client, asset):
    resp = client.get(f"/app/{asset}")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_page_loads_the_flow_entrypoint(client):
    assert '<script type="module" src="app.js">' in page(client)


def test_app_wires_every_flow_module(client):
    src = app_js(client)
    for name in ("api.js", "capture.js", "crop.js", "status.js"):
        assert f'from "./{name}"' in src, name
    for entry in ("createCapture", "createCropper", "submitJob", "pollJob", "statusOf"):
        assert entry in src, entry


# --- DOM hooks ---


def test_page_defines_every_hook_app_js_reaches_for(client):
    html, src = page(client), app_js(client)
    hooks = set(re.findall(r'getElementById\("([^"]+)"\)', src))
    assert set(HOOKS) <= hooks, "app.js must reach every flow hook"
    for hook in sorted(hooks):
        assert f'id="{hook}"' in html, f"index.html is missing #{hook}"


def test_flow_starts_at_capture_with_later_steps_hidden(client):
    html = page(client)
    assert 'id="adim-cekim">' in html
    for step in ("adim-kirp", "adim-durum", "adim-sonuc"):
        assert f'id="{step}" hidden' in html


# --- result view ---


def test_result_view_has_items_table_and_turkish_totals(client):
    html = page(client)
    assert 'id="urun-tablosu"' in html
    for baslik in ("Ürün", "Miktar", "Birim fiyat", "Tutar"):
        assert baslik in html
    for etiket in ("Ara toplam", "İskonto", "KDV", "Toplam", "Para birimi"):
        assert etiket in html


def test_raw_json_toggle_is_on_the_result_card(client):
    html = page(client)
    assert 'id="ham-json-dugme"' in html and 'id="ham-json"' in html
    assert "Ham JSON" in html


def test_verdict_chip_and_unreadable_warning_copy(client):
    html, src = page(client), app_js(client)
    assert 'id="verdict-tasi"' in html
    assert 'id="sonuc-uyari"' in html
    assert "Okunamayan bölümler" in src
    assert "Uyuşmayan alanlar" in src
